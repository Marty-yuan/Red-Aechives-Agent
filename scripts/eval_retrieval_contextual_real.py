# -*- coding: utf-8 -*-
"""
上下文感知检索评测（复刻 run_eval.py 的判定逻辑）
=================================================
对 60 题评测集，用真实的 ArchiveRetriever / HybridArchiveRetriever 检索，
gold 由 anchor / keywords 子串判定（与 run_eval.py 完全一致）。
分别跑：
  --index-dir data/index            (基线，应复现 80.0% / 88.3%)
  --index-dir data/index_contextual (上下文感知检索)
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agent.retriever import ArchiveRetriever
from agent.hybrid_retriever import HybridArchiveRetriever

GOLD_CAP = 20
TOPK = 5


def run_eval(retriever, label, questions):
    chunks = retriever.chunks
    gold_by_q = {}
    for q in questions:
        anchor = q["anchor"]
        gold_by_q[q["id"]] = [i for i, c in enumerate(chunks) if anchor in c["text"]]

    stats = {k: {"hit": 0, "recall_sum": 0.0, "gold_total": 0} for k in (1, 3, 5)}
    mrr_sum = 0.0
    detail = []

    for q in questions:
        qid = q["id"]
        question = q["question"]
        village = q.get("village")
        anchor = q["anchor"]
        kws = q.get("keywords", [])
        gold = gold_by_q[qid]

        results = retriever.search(question, village=village, top_k=TOPK)
        texts = [r["text"] for r in results]

        def is_rel(text):
            if anchor in text:
                return True
            return any(k in text for k in kws)

        rel_flags = [is_rel(t) for t in texts]
        first_rel = next((i + 1 for i, f in enumerate(rel_flags) if f), None)

        for k in (1, 3, 5):
            top = rel_flags[:k]
            stats[k]["hit"] += int(any(top))
            rel_count = sum(top)
            gold_denom = min(max(len(gold), 1), GOLD_CAP)
            stats[k]["recall_sum"] += rel_count / min(gold_denom, k)
            stats[k]["gold_total"] += 1
        if first_rel:
            mrr_sum += 1.0 / first_rel

        detail.append({"id": qid, "hit5": any(rel_flags), "first_rel": first_rel})

    n = len(questions)
    return {
        "label": label, "n": n,
        "hit@1": stats[1]["hit"] / n, "hit@3": stats[3]["hit"] / n,
        "hit@5": stats[5]["hit"] / n, "mrr": mrr_sum / n,
        "fails": [d["id"] for d in detail if not d["hit5"]],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--index-dir", default="data/index_contextual")
    ap.add_argument("--baseline-dir", default="data/index")
    args = ap.parse_args()

    eval_set = json.load(open(ROOT / "data" / "eval" / "eval_set.json", encoding="utf-8"))
    questions = eval_set["questions"]

    print("=== 基线 (data/index) ===")
    base_tf = run_eval(ArchiveRetriever(index_dir=str(ROOT / args.baseline_dir)), "char", questions)
    base_hy = run_eval(HybridArchiveRetriever(index_dir=str(ROOT / args.baseline_dir)), "hybrid", questions)
    for r in (base_tf, base_hy):
        print(f"  {r['label']:<8} hit@1={r['hit@1']*100:5.1f}% hit@3={r['hit@3']*100:5.1f}% "
              f"hit@5={r['hit@5']*100:5.1f}% MRR={r['mrr']:.3f} fails={len(r['fails'])}")

    print(f"\n=== 上下文感知 ({args.index_dir}) ===")
    ctx_tf = run_eval(ArchiveRetriever(index_dir=str(ROOT / args.index_dir)), "char", questions)
    ctx_hy = run_eval(HybridArchiveRetriever(index_dir=str(ROOT / args.index_dir)), "hybrid", questions)
    for r in (ctx_tf, ctx_hy):
        print(f"  {r['label']:<8} hit@1={r['hit@1']*100:5.1f}% hit@3={r['hit@3']*100:5.1f}% "
              f"hit@5={r['hit@5']*100:5.1f}% MRR={r['mrr']:.3f} fails={len(r['fails'])}")

    print("\n=== Δ（上下文 - 基线）===")
    print(f"  char   hit@1: {(ctx_tf['hit@1']-base_tf['hit@1'])*100:+.1f} pt  "
          f"hit@5: {(ctx_tf['hit@5']-base_tf['hit@5'])*100:+.1f} pt")
    print(f"  hybrid hit@1: {(ctx_hy['hit@1']-base_hy['hit@1'])*100:+.1f} pt  "
          f"hit@5: {(ctx_hy['hit@5']-base_hy['hit@5'])*100:+.1f} pt")
    print(f"  基线未命中题: {base_hy['fails']}")
    print(f"  上下文未命中题: {ctx_hy['fails']}")

    out = {
        "baseline_char": base_tf, "baseline_hybrid": base_hy,
        "ctx_char": ctx_tf, "ctx_hybrid": ctx_hy,
    }
    (ROOT / "data" / "eval" / "retrieval_contextual_real.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[+] data/eval/retrieval_contextual_real.json")


if __name__ == "__main__":
    main()
