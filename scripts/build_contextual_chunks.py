"""
上下文感知检索：为 9,132 chunks 一次性生成 50-100 token 的中文背景前缀
============================================================
做法（参考 Anthropic Contextual Retrieval）：

  为每条 chunk 调用 LLM 生成一段"前缀摘要"——把 chunk 放回原始语境里
  （档案名 / 章节 / 篇目 / 关键人物 / 事件 / 时间），拼接后：

    new_text = prefix + "\n" + original_text

  优点：BM25 检索直接吃到"皎平渡""遵义会议"等专名；稠密向量获得
  语义锚定（"该公司"等代词不再悬空）。Anthropic 报告 BM25 检索失败
  率 -49%，+重排序 -67%。

运行（需 DEEPSEEK_API_KEY）：

    # 全量（9,132 chunks，预计 5-15 分钟）
    python scripts/build_contextual_chunks.py

    # 小样本试跑
    python scripts/build_contextual_chunks.py --limit 50

    # 断点续跑（自动跳过已有 prefix 的 chunk）
    python scripts/build_contextual_chunks.py --resume

输出：
    data/index/chunks_contextual.json   # 9,132 条，text 字段被 prefix+原文本 替换
    data/eval/contextual_chunks_progress.json   # 进度（可删）
"""
from __future__ import annotations
import argparse, json, os, sys, time, hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

IN_CHUNKS  = ROOT / "data" / "index" / "chunks.json"
OUT_CHUNKS = ROOT / "data" / "index" / "chunks_contextual.json"
PROGRESS   = ROOT / "data" / "eval" / "contextual_chunks_progress.json"
BATCH      = 15          # 每轮 LLM 调用处理的 chunk 数
MAX_TOKENS = 1800        # 默认 chat 模型无 reasoning，1800 足够每条 ~90 token × 15 = 1350

SYSTEM = (
    "你是云南红军长征档案智能体的索引员。"
    "任务：为每条 OCR 档案片段写一段 60–120 字的中文检索前缀，"
    "让该片段脱离原文也能被精准检索。"
    "前缀必须优先写明片段内的关键实体与关系："
    "出现了哪些人物及其职务/事迹、哪些部队番号、哪些事件及时间地点、"
    "哪些遗址/渡口/文物；再补充档案名与章节（如有）。"
    "人物职务要写全（如'刘伯承担任渡河司令'），书名文章要写全称"
    "（如陈云《随军西行见闻录》）。不要重复正文原句，不要评论。"
    "严格按 JSON 数组输出，元素顺序与输入一致；不要 Markdown，不要解释。"
)


def make_user_prompt(batch_chunks: list[dict]) -> str:
    items = []
    for i, c in enumerate(batch_chunks):
        text_snip = c.get("text", "")[:400].replace("\n", " ")
        meta = []
        if c.get("source"):
            tail = c["source"][-80:]
            meta.append(f"档案={tail}")
        if c.get("section"):
            meta.append(f"章节={c['section']}")
        if c.get("page") is not None:
            meta.append(f"页码={c['page']}")
        meta_s = " | ".join(meta) if meta else "（无元数据）"
        items.append(f"[{i}] {meta_s}\n正文片段：{text_snip}…")
    return "请为以下每条片段写一个 60–120 字的中文检索前缀（优先写片段内的人物职务、部队番号、事件时间地点、遗址渡口等实体关系，再补档案名与章节）。\n\n" + "\n\n".join(items) + \
        '\n\n严格按 JSON 数组输出：["前缀1","前缀2",...]'


def parse_json_array(content: str) -> list[str]:
    content = content.strip()
    # strip code fences
    if content.startswith("```"):
        content = content.split("\n", 1)[-1]
        if content.endswith("```"):
            content = content.rsplit("\n", 1)[0]
    # find first [ and last ]
    s, e = content.find("["), content.rfind("]")
    if s == -1 or e == -1:
        raise ValueError("no JSON array found")
    arr = json.loads(content[s:e + 1])
    if not isinstance(arr, list):
        raise ValueError("JSON top-level is not array")
    return [str(x) for x in arr]


def call_llm(client, model: str, batch: list[dict], retries: int = 2) -> list[str] | None:
    last_err = ""
    for attempt in range(retries + 1):
        try:
            r = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": SYSTEM},
                    {"role": "user", "content": make_user_prompt(batch)},
                ],
                temperature=0.0,
                max_tokens=MAX_TOKENS,
            )
            content = (r.choices[0].message.content or "").strip()
            if not content:
                last_err = "empty content"
                time.sleep(0.5)
                continue
            prefixes = parse_json_array(content)
            if len(prefixes) > len(batch):
                prefixes = prefixes[: len(batch)]  # model returned extra; truncate
            if len(prefixes) != len(batch):
                last_err = f"got {len(prefixes)} pref, want {len(batch)}; raw[:120]={content[:120]!r}"
                time.sleep(0.5)
                continue
            return prefixes
        except Exception as exc:
            last_err = f"{type(exc).__name__}: {str(exc)[:120]}"
            time.sleep(0.5)
    print(f"  [warn] batch failed after {retries+1} tries: {last_err}")
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--batch", type=int, default=BATCH)
    ap.add_argument("--workers", type=int, default=4, help="parallel LLM calls")
    ap.add_argument("--resume", action="store_true", help="skip chunks already done")
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--model", default="deepseek-chat",
                    help="LLM model id (default deepseek-chat, fast; "
                         "config.MODEL_NAME is deepseek-v4-flash reasoning, slow)")
    args = ap.parse_args()

    from agent import config
    from openai import OpenAI
    from concurrent.futures import ThreadPoolExecutor, as_completed

    model = args.model

    chunks = json.loads(IN_CHUNKS.read_text(encoding="utf-8"))
    print(f"[*] loaded {len(chunks)} chunks from {IN_CHUNKS.name}")
    if args.limit:
        chunks = chunks[: args.limit]

    # load progress
    progress: dict[str, str] = {}
    if args.resume and PROGRESS.exists():
        progress = json.loads(PROGRESS.read_text(encoding="utf-8"))
        print(f"    resume: {len(progress)} already done")

    # pre-populate out_results from progress so final assembly is consistent
    out_results: dict[int, list[str]] = {}
    for k, pfx in progress.items():
        idx = int(k)
        if pfx:
            out_results[idx] = [pfx]
        else:
            out_results[idx] = [""]

    # build batch list, skipping those already done if --resume
    work: list[tuple[int, list[dict]]] = []
    i = args.start
    while i < len(chunks):
        batch = chunks[i: i + args.batch]
        if args.resume and all(str(j) in progress for j, _ in enumerate(batch, start=i)):
            i += args.batch
            continue
        work.append((i, batch))
        i += args.batch

    print(f"    batches to process: {len(work)} (batch={args.batch}, workers={args.workers})")
    n_done = n_fail = 0
    t0 = time.time()
    out_results: dict[int, list[str]] = {}

    def call_one(idx_batch):
        idx, batch = idx_batch
        # each worker needs its own client (openai is thread-safe enough)
        c = OpenAI(api_key=config.DEEPSEEK_API_KEY, base_url=config.BASE_URL)
        p = call_llm(c, model, batch)
        return idx, p

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(call_one, ib): ib for ib in work}
        completed = 0
        for fut in as_completed(futs):
            idx, prefixes = fut.result()
            completed += 1
            _, batch = futs[fut]                   # recover batch length
            n_this_batch = len(batch)
            if prefixes is None or len(prefixes) != n_this_batch:
                # batch failed, per-chunk retry
                for j in range(idx, idx + n_this_batch):
                    if j >= len(chunks):
                        break
                    key = str(j)
                    if args.resume and key in progress and progress[key]:
                        out_results[j] = [progress[key]]
                        continue
                    c = OpenAI(api_key=config.DEEPSEEK_API_KEY, base_url=config.BASE_URL)
                    p = call_llm(c, model, [chunks[j]])
                    if p is None or not p[0].strip():
                        out_results[j] = [""]
                        progress[key] = ""
                        n_fail += 1
                    else:
                        out_results[j] = [p[0].strip()]
                        progress[key] = p[0].strip()
                        n_done += 1
            else:
                for j, p in zip(range(idx, idx + n_this_batch), prefixes):
                    if j >= len(chunks):
                        break
                    key = str(j)
                    progress[key] = p.strip()
                    out_results[j] = [p.strip()]
                    n_done += 1
            if completed % 10 == 0 or completed == len(work):
                PROGRESS.write_text(json.dumps(progress, ensure_ascii=False, indent=2),
                                    encoding="utf-8")
                # also write output file incrementally (every 20 batches)
                if completed % 20 == 0 or completed == len(work):
                    _out = []
                    for _j, _c in enumerate(chunks):
                        _pfx = out_results.get(_j, [""])[0]
                        if _pfx:
                            _out.append({**_c, "text": _pfx + "\n" + _c["text"]})
                        else:
                            _out.append(_c)
                    OUT_CHUNKS.write_text(json.dumps(_out, ensure_ascii=False, indent=2),
                                         encoding="utf-8")
                elapsed = time.time() - t0
                rate = (n_done) / max(elapsed, 1)
                eta = (len(chunks) - (idx + n_this_batch)) / max(rate, 0.1) / 60
                print(f"  [{completed}/{len(work)} batches] done={n_done} fail={n_fail} "
                      f"rate={rate:.1f}/s eta={eta:.1f}min")

    # assemble final output preserving order
    out = []
    for j, c in enumerate(chunks):
        pfx = out_results.get(j, [""])[0]
        if pfx:
            out.append({**c, "text": pfx + "\n" + c["text"]})
        else:
            out.append(c)  # keep original if no prefix
    OUT_CHUNKS.write_text(json.dumps(out, ensure_ascii=False, indent=2),
                         encoding="utf-8")
    print(f"\n[+] {OUT_CHUNKS}")
    print(f"    done={n_done}  fail(no-prefix)={n_fail}  total={len(chunks)}")
    print(f"    elapsed={(time.time()-t0)/60:.1f}min")


if __name__ == "__main__":
    main()
