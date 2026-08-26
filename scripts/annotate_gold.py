"""
精标集标注工具（黄金段落）
========================
把 60 题评测集升级为"人工黄金段落精标"。

输入：data/eval/eval_set.json（已有 gold_chunk_ids，chunk 级）
输出：data/eval/gold_set_v2.json（人工标 gold_paragraph：每个问题选
      1-3 个真正能"完整回答该问题"的 chunk，并标 relevance=core/supporting/not）

用法：
  1) 启动：python scripts/annotate_gold.py
     → 浏览器打开 http://127.0.0.1:5000/__annotate  （或调用下面的 CLI 模式）
  2) 对每题：阅读 top 候选 chunks（已按 hybrid 检索排序），给每个标
       core（必选，回答该题的核心段落）
       supporting（支持，可选）
       not（无关）
     并写一段 1-2 句的 "gold_answer"（基于这些 chunk 写出的标准答案）
  3) 进度自动保存到 data/eval/annotation_progress.json，可分多次

这是项目文档 3.3 后续工作中"评测集精标升级"的人工标注入口。
本脚本提供 CLI 版本（无需前端），命令：
  python scripts/annotate_gold.py --cli
  python scripts/annotate_gold.py --export  # 导出已完成题目为 gold_set_v2.json
"""
from __future__ import annotations
import argparse, json, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

EVAL = ROOT / "data" / "eval" / "eval_set.json"
CHUNKS = ROOT / "data" / "index" / "chunks.json"
PROGRESS = ROOT / "data" / "eval" / "annotation_progress.json"
OUT = ROOT / "data" / "eval" / "gold_set_v2.json"


def load_chunks() -> list[dict]:
    return json.loads(CHUNKS.read_text(encoding="utf-8"))


def load_progress() -> dict:
    if PROGRESS.exists():
        return json.loads(PROGRESS.read_text(encoding="utf-8"))
    return {"annotations": {}}


def save_progress(p: dict) -> None:
    PROGRESS.write_text(json.dumps(p, ensure_ascii=False, indent=2),
                        encoding="utf-8")


def get_top_candidates(question: str, village: str | None, k: int = 5) -> list[dict]:
    from agent.retriever_factory import create_retriever
    r = create_retriever()
    res = r.search(question, village=village or None, top_k=k)
    out = []
    for h in res:
        out.append({
            "text": h.get("text", ""),
            "source": h.get("source", "")[-40:],
            "page": h.get("page"),
            "section": h.get("section"),
            "retriever": h.get("retriever"),
            "score": h.get("score"),
        })
    return out


def cli_annotate():
    qs = json.loads(EVAL.read_text(encoding="utf-8"))["questions"]
    progress = load_progress()
    for q in qs:
        qid = q.get("id")
        if str(qid) in progress["annotations"]:
            print(f"[skip] {qid} already annotated")
            continue
        print("\n" + "=" * 60)
        print(f"Q ({qid}): {q['question']}")
        print(f"Village: {q.get('village','')}  | Keywords: {q.get('keywords','')}")
        cands = get_top_candidates(q["question"], q.get("village"))
        for i, c in enumerate(cands, 1):
            print(f"\n--- candidate {i} (page={c['page']}, retriever={c['retriever']}) ---")
            print(c["text"][:300])
        print("\nLabels: 1=core  2=supporting  3=not   (space-separated, e.g. '1 3')")
        labels_raw = input("> labels: ").strip()
        gold_answer = input("> gold_answer (1-2 sentences): ").strip()
        ann = {"qid": qid, "labels": labels_raw, "gold_answer": gold_answer,
               "candidates": cands, "timestamp": int(time.time())}
        progress["annotations"][str(qid)] = ann
        save_progress(progress)
        print(f"[+] saved {qid}")


def export():
    progress = load_progress()
    out = []
    for qid, ann in progress["annotations"].items():
        out.append({
            "qid": qid,
            "gold_answer": ann.get("gold_answer", ""),
            "labels": ann.get("labels", ""),
        })
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[+] exported {len(out)} to {OUT}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cli", action="store_true", help="interactive CLI annotation")
    ap.add_argument("--export", action="store_true", help="export to gold_set_v2.json")
    args = ap.parse_args()
    if args.export:
        export()
    else:
        cli_annotate()


if __name__ == "__main__":
    main()
