# -*- coding: utf-8 -*-
"""
检索效果评测（TF-IDF / Hybrid 对比）
------------------------------------
用法：
    python scripts/run_eval.py
    python scripts/run_eval.py --mode hybrid
    python scripts/run_eval.py --mode both
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, "src")
from agent.retriever import ArchiveRetriever
from agent.hybrid_retriever import HybridArchiveRetriever

GOLD_CAP = 20
TOPK = 5


def make_retriever(mode: str):
    if mode == "hybrid":
        return HybridArchiveRetriever(), "Hybrid (char TF-IDF + word TF-IDF + RRF)"
    return ArchiveRetriever(), "TF-IDF char 2-4gram"


def run_eval(retriever, label: str, questions: list, chunks: list) -> dict:
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
            hit = int(any(top))
            stats[k]["hit"] += hit
            rel_count = sum(top)
            gold_denom = min(max(len(gold), 1), GOLD_CAP)
            stats[k]["recall_sum"] += rel_count / min(gold_denom, k)
            stats[k]["gold_total"] += 1
        if first_rel:
            mrr_sum += 1.0 / first_rel

        detail.append({
            "id": qid,
            "question": question,
            "village": village,
            "anchor": anchor,
            "gold_size": len(gold),
            "hit5": any(rel_flags),
            "first_rel": first_rel,
            "top_texts": [t[:40].replace("\n", " ") for t in texts[:3]],
        })

    n = len(questions)
    return {
        "label": label,
        "n": n,
        "hit": {str(k): stats[k]["hit"] for k in (1, 3, 5)},
        "hit_rate": {str(k): round(stats[k]["hit"] / n, 4) for k in (1, 3, 5)},
        "recall": {str(k): round(stats[k]["recall_sum"] / stats[k]["gold_total"], 4) for k in (1, 3, 5)},
        "mrr": round(mrr_sum / n, 4),
        "details": detail,
    }


def print_report(result: dict) -> None:
    n = result["n"]
    print("=" * 60)
    print(f"评测集: {n} 题 | 检索器: {result['label']}")
    print("=" * 60)
    for k in (1, 3, 5):
        hit = result["hit"][str(k)]
        hit_rate = result["hit_rate"][str(k)]
        recall = result["recall"][str(k)]
        print(f"  hit@{k} : {hit:>3}/{n} = {hit_rate:.1%}   recall@{k} = {recall:.3f}")
    print(f"  MRR   : {result['mrr']:.3f}")
    fails = [d for d in result["details"] if not d["hit5"]]
    print(f"hit@5 未命中 {len(fails)} 题")
    print()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["tfidf", "hybrid", "both"], default="tfidf")
    args = parser.parse_args()

    eval_set = json.load(open("data/eval/eval_set.json", encoding="utf-8"))
    questions = eval_set["questions"]

    modes = ["tfidf", "hybrid"] if args.mode == "both" else [args.mode]
    all_results = {}

    for mode in modes:
        retriever, label = make_retriever(mode)
        result = run_eval(retriever, label, questions, retriever.chunks)
        print_report(result)
        all_results[mode] = result

    out_path = Path("data/eval/eval_results.json")
    if args.mode == "both":
        payload = {"comparison": all_results}
    else:
        payload = all_results[modes[0]]
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"详细结果 -> {out_path}")


if __name__ == "__main__":
    main()
