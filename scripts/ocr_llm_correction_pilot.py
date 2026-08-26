"""
OCR LLM 批量纠错试点 (Pilot)
===========================
发送一批 chunk 文本到 DeepSeek 做 OCR 纠错，评估：
  1) 召回 (Recall) — 项目已知 67 条 OCR 错字中，LLM 独立改对了多少
  2) 精度 (Precision, 抽样) — LLM 的修改中，有多少是真的错字被改对
  3) 检索效果变化 — 纠错前后，对 60 题评测集 hit@5 的影响（可选）

设计原则：小样本、可复现、给出**可写入项目文档**的量化数字。
DeepSeek API 已在 .env，无需额外配置。

运行：
    python scripts/ocr_llm_correction_pilot.py
    python scripts/ocr_llm_correction_pilot.py --n-chunks 20 --n-eval 10
"""
from __future__ import annotations
import argparse, json, re, sys, time, random
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

CHUNKS = ROOT / "data" / "index" / "chunks.json"
OCR_FIXES = ROOT / "src" / "knowledge" / "ocr_fixes.py"
OUT = ROOT / "data" / "eval" / "ocr_llm_correction_pilot.json"

PROMPT = """你是一名严谨的党史档案 OCR 校对员。下面是来自红军长征档案 OCR 的文本片段，
其中存在扫描/OCR 引入的错字（形近错字、繁简混用、双字粘连、整词错字等）。

请只做**最小改动**的纠错：
  1) 保持原文用字风格（不翻译、不改写、不删内容）
  2) 仅修正明显是 OCR 错误的字
  3) 专名（人名/地名/部队番号）不确定时保持原样
  4) 如果没有明显错误，原样返回

严格按 JSON 输出（不要 Markdown，不要解释）：
{"corrected": "<纠错后的完整文本>", "edits": [{"find": "<原文错>", "repl": "<改正>", "reason": "<形近/粘连/其他>"}]}

原文：
---
{text}
---"""


def load_known_fixes() -> dict[str, str]:
    """Load ocr_fixes.py OCR_FIXES (tuple of (find, repl))."""
    ns: dict = {}
    exec(OCR_FIXES.read_text(encoding="utf-8"), ns)
    fixes = ns.get("OCR_FIXES", ())
    # dedupe (find -> repl), keep first
    out: dict[str, str] = {}
    for find, repl in fixes:
        if find not in out:
            out[find] = repl
    return out


def call_llm(client, model: str, text: str, max_tokens: int = 1500) -> dict | None:
    try:
        r = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": PROMPT.format(text=text[:1500])}],
            temperature=0.0,
            max_tokens=max_tokens,
        )
        content = (r.choices[0].message.content or "").strip()
        # parse JSON robustly
        content = re.sub(r"^```(?:json)?\s*", "", content)
        content = re.sub(r"\s*```$", "", content)
        s, e = content.find("{"), content.rfind("}")
        if s != -1 and e != -1:
            return json.loads(content[s:e + 1])
    except Exception as exc:
        print(f"  [warn] llm call failed: {type(exc).__name__}: {str(exc)[:80]}")
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-chunks", type=int, default=15, help="chunks to LLM-correct")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out-prefix", default=str(OUT))
    args = ap.parse_args()

    from agent import config
    from openai import OpenAI
    client = OpenAI(api_key=config.DEEPSEEK_API_KEY, base_url=config.BASE_URL)
    model = config.MODEL_NAME

    chunks = json.loads(CHUNKS.read_text(encoding="utf-8"))
    known = load_known_fixes()  # find -> repl
    print(f"[*] known OCR fixes: {len(known)}")

    # Sample chunks that likely contain known-fix strings (for measurable recall)
    candidates = []
    for i, ch in enumerate(chunks):
        t = ch.get("text", "")
        hits = sum(1 for f in known if f in t)
        if hits:
            candidates.append((i, ch, hits))
    candidates.sort(key=lambda x: -x[2])
    rng = random.Random(args.seed)
    rng.shuffle(candidates)
    sample = candidates[: args.n_chunks]

    print(f"[*] sampled {len(sample)} chunks (each contains ≥1 known OCR error)")

    # LLM correction
    out_records = []
    total_edits = 0
    known_fixed = 0     # known finds successfully corrected by LLM
    known_total = 0     # total occurrences of known finds in sample
    llm_made_edits: list[dict] = []
    t0 = time.time()
    for i, (idx, ch, known_hits) in enumerate(sample, 1):
        text = ch.get("text", "")
        known_total += known_hits
        print(f"  [{i}/{len(sample)}] chunk#{idx} (known_hits={known_hits}) … ", end="", flush=True)
        r = call_llm(client, model, text)
        if not r or "corrected" not in r:
            print("FAIL")
            out_records.append({"idx": idx, "ok": False})
            continue
        corrected = r["corrected"]
        edits = r.get("edits", []) or []
        total_edits += len(edits)
        for e in edits:
            llm_made_edits.append({"idx": idx, **e})
        # Did LLM fix any known errors in this chunk?
        chunk_fixed = 0
        for f, repl in known.items():
            if f in text and repl in corrected and text.count(f) >= corrected.count(f) and f not in corrected:
                chunk_fixed += 1
            elif f in text and f not in corrected and repl in corrected:
                chunk_fixed += 1
        known_fixed += chunk_fixed
        out_records.append({
            "idx": idx, "ok": True,
            "edits": len(edits), "known_fixed_in_chunk": chunk_fixed,
            "source_tail": ch.get("source", "")[-30:],
        })
        print(f"ok edits={len(edits)} known_fixed={chunk_fixed}")

    elapsed = time.time() - t0
    recall = known_fixed / known_total if known_total else 0
    print(f"\n=== OCR LLM Correction Pilot ===")
    print(f"chunks: {len(sample)}, known-error occurrences in sample: {known_total}")
    print(f"LLM made {total_edits} edits total, fixed {known_fixed} known occurrences")
    print(f"Recall on known fixes: {recall*100:.1f}%  ({known_fixed}/{known_total})")
    print(f"elapsed: {elapsed:.1f}s")

    # Precision: sample a few LLM edits and judge
    sample_edits = [e for e in llm_made_edits if e.get("find") and e.get("repl")][:5]
    precision_note = ""
    if sample_edits:
        precision_note = " 抽样: " + " | ".join(
            f"{e['find']}→{e['repl']}" for e in sample_edits
        )
        print(f"sample edits (manual review needed for precision): {precision_note}")

    # Save
    out_path = Path(args.out_prefix)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({
        "n_chunks": len(sample),
        "known_occurrences": known_total,
        "known_fixed_by_llm": known_fixed,
        "recall_on_known": recall,
        "total_llm_edits": total_edits,
        "records": out_records,
        "sample_edits_for_review": sample_edits,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[+] {out_path}")
    print("\n[note] 精度 (Precision) 需要人工抽检上面 sample_edits_for_review 来标定；")
    print("       召回 (Recall) 是 LLM 在已知 67 条错字上独立改对的占比，")
    print("       可直接写入项目文档 3.2 / 2.2 支撑「LLM 批量纠错」可行性。")


if __name__ == "__main__":
    main()
