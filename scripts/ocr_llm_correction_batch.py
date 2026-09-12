# -*- coding: utf-8 -*-
"""
OCR LLM 批量纠错（可续跑）
=========================
用 DeepSeek 对 chunks.json 的文本做"最小改动"OCR 纠错，产出纠错映射（不改原索引）：
    data/index/ocr_llm_corrections.json   {chunk_idx: corrected_text}
    data/index/_ocr_llm_state.json        断点状态（重复运行自动续跑）

用法：
    # 候选模式：只处理包含已知错字的 chunk（先跑小批验证）
    python scripts/ocr_llm_correction_batch.py --scope candidates --limit 60 --concurrency 6
    # 全量模式：所有 chunk（可中断续跑）
    python scripts/ocr_llm_correction_batch.py --scope all --concurrency 8

纠错后的索引重建（人工核对后）：
    将本文件产出的 corrections 合并进 knowledge.ocr_fixes 或建立新 chunks 后重建索引，
    并按项目流程重新标注 gold_chunk_ids。
"""
from __future__ import annotations

import argparse
import io
import json
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

CHUNKS = ROOT / "data" / "index" / "chunks.json"
OCR_FIXES = ROOT / "src" / "knowledge" / "ocr_fixes.py"
CORRECTIONS = ROOT / "data" / "index" / "ocr_llm_corrections.json"
STATE = ROOT / "data" / "index" / "_ocr_llm_state.json"

PROMPT = """你是一名严谨的党史档案 OCR 校对员。下面是来自红军长征档案 OCR 的文本片段，
其中存在扫描/OCR 引入的错字（形近错字、繁简混用、双字粘连、整词错字等）。

请只做**最小改动**的纠错：
  1) 保持原文用字风格（不翻译、不改写、不删内容）
  2) 仅修正明显是 OCR 错误的字
  3) 专名（人名/地名/部队番号）不确定时保持原样
  4) 如果没有明显错误，原样返回

严格按 JSON 输出（不要 Markdown，不要解释）：
__JSON_EXAMPLE__

原文：
---
__TEXT__
---"""

_lock = threading.Lock()


def load_known_fixes() -> dict[str, str]:
    ns: dict = {}
    exec(OCR_FIXES.read_text(encoding="utf-8"), ns)
    out: dict[str, str] = {}
    for find, repl in ns.get("OCR_FIXES", ()):
        out.setdefault(find, repl)
    return out


def load_state() -> dict:
    if STATE.exists():
        try:
            return json.loads(STATE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"done": [], "failed": [], "changed": 0, "edits": 0}


def save_state(state: dict) -> None:
    STATE.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")


def load_corrections() -> dict:
    if CORRECTIONS.exists():
        try:
            return json.loads(CORRECTIONS.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_corrections(corr: dict) -> None:
    CORRECTIONS.write_text(json.dumps(corr, ensure_ascii=False), encoding="utf-8")


def build_prompt(text: str) -> str:
    """JSON 示例用替换而非 str.format，避免大括号被当作格式占位符。"""
    example = '{"corrected": "<纠错后的完整文本>", "edits": [{"find": "<原文错>", "repl": "<改正>", "reason": "<形近/粘连/其他>"}]}'
    return PROMPT.replace("__JSON_EXAMPLE__", example).replace("__TEXT__", text[:1500])


def call_llm(client, model: str, text: str) -> dict | None:
    try:
        r = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": build_prompt(text)}],
            temperature=0.0,
            max_tokens=4096,
        )
        content = (r.choices[0].message.content or "").strip()
        content = re.sub(r"^```(?:json)?\s*", "", content)
        content = re.sub(r"\s*```$", "", content)
        s, e = content.find("{"), content.rfind("}")
        if s != -1 and e != -1:
            try:
                return json.loads(content[s:e + 1])
            except json.JSONDecodeError:
                # 容错回退：直接提取 corrected 字段（模型偶发输出非法 JSON）
                m = re.search(r'"corrected"\s*:\s*"((?:[^"\\]|\\.)*)"', content)
                if m:
                    try:
                        corrected = json.loads('"' + m.group(1) + '"')
                        return {"corrected": corrected, "edits": [], "recovered": True}
                    except json.JSONDecodeError:
                        pass
    except Exception as exc:  # noqa: BLE001
        print(f"  [warn] llm failed: {type(exc).__name__}: {str(exc)[:80]}")
    return None


def main() -> None:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--scope", choices=["candidates", "all"], default="candidates")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--concurrency", type=int, default=6)
    ap.add_argument("--min-len", type=int, default=50, help="跳过过短 chunk")
    ap.add_argument("--model", default=None,
                    help="默认用 config.MODEL_NAME；机械纠错建议 deepseek-chat（推理模型会先输出思考、更慢更贵）")
    args = ap.parse_args()

    from agent import config
    from openai import OpenAI

    client = OpenAI(api_key=config.DEEPSEEK_API_KEY, base_url=config.BASE_URL)
    model = args.model or config.MODEL_NAME
    chunks = json.loads(CHUNKS.read_text(encoding="utf-8"))
    known = load_known_fixes()
    state = load_state()
    corr = load_corrections()
    done = set(state.get("done", []))

    if args.scope == "candidates":
        todo = [i for i, c in enumerate(chunks)
                if len(c.get("text", "")) >= args.min_len and any(f in c["text"] for f in known)]
    else:
        todo = [i for i, c in enumerate(chunks) if len(c.get("text", "")) >= args.min_len]
    todo = [i for i in todo if i not in done]
    if args.limit:
        todo = todo[: args.limit]
    print(f"[*] chunks={len(chunks)}  scope={args.scope}  todo={len(todo)}  "
          f"concurrency={args.concurrency}  model={model}")

    t0 = time.time()
    processed = changed = failed = 0
    edits_total = 0

    def work(idx: int):
        text = chunks[idx].get("text", "")
        r = call_llm(client, model, text)
        return idx, text, r

    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = {pool.submit(work, i): i for i in todo}
        for fut in as_completed(futures):
            idx, text, r = fut.result()
            processed += 1
            if not r or "corrected" not in r:
                failed += 1
                state["failed"].append(idx)
            else:
                corrected = (r.get("corrected") or "").strip()
                # 变更保护：长度比例异常或空结果则丢弃
                if corrected and 0.9 <= len(corrected) / max(len(text), 1) <= 1.12 and corrected != text:
                    corr[str(idx)] = corrected
                    changed += 1
                    edits_total += len(r.get("edits") or [])
                state["done"].append(idx)
            if processed % 10 == 0:
                with _lock:
                    save_state(state)
                    save_corrections(corr)
                print(f"  [{processed}/{len(todo)}] changed={changed} failed={failed} "
                      f"elapsed={time.time()-t0:.0f}s", flush=True)

    state["changed"] = state.get("changed", 0) + changed
    state["edits"] = state.get("edits", 0) + edits_total
    save_state(state)
    save_corrections(corr)
    print(f"[Done] processed={processed} changed={changed} failed={failed} edits={edits_total}")
    print(f"       corrections -> {CORRECTIONS}")
    print(f"       state       -> {STATE}")


if __name__ == "__main__":
    main()
