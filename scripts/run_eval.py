# -*- coding: utf-8 -*-
"""
检索效果评测（基线）
--------------------
指标定义：
    - hit@k   : 前 k 个检索结果中至少 1 个相关（相关=含 anchor 或任一 keyword）
    - recall@k: 前 k 个结果中相关数 / min(黄金集大小, k)；
                黄金集 = 索引中含 anchor 的 chunk 数（封顶 GOLD_CAP）
    - MRR     : 第一个相关结果的 1/排名（k=5 内）
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, "src")
from agent.retriever import ArchiveRetriever

GOLD_CAP = 20
TOPK = 5

def main():
    ret = ArchiveRetriever()
    chunks = ret.chunks
    eval_set = json.load(open("data/eval/eval_set.json", encoding="utf-8"))
    questions = eval_set["questions"]

    # 预计算黄金集：含 anchor 的 chunk 索引
    gold_by_q = {}
    for q in questions:
        anchor = q["anchor"]
        gold = [i for i, c in enumerate(chunks) if anchor in c["text"]]
        gold_by_q[q["id"]] = gold

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

        results = ret.search(question, village=village, top_k=TOPK)
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
            "id": qid, "question": question, "village": village,
            "anchor": anchor, "gold_size": len(gold),
            "hit5": any(rel_flags), "first_rel": first_rel,
            "top_texts": [t[:40].replace("\n", " ") for t in texts[:3]],
        })

    n = len(questions)
    print("=" * 60)
    print(f"评测集: {n} 题 | 检索器: TF-IDF char 2-4gram")
    print("=" * 60)
    for k in (1, 3, 5):
        hit_rate = stats[k]["hit"] / n
        recall = stats[k]["recall_sum"] / stats[k]["gold_total"]
        print(f"  hit@{k} : {stats[k]['hit']:>3}/{n} = {hit_rate:.1%}   recall@{k} = {recall:.3f}")
    mrr = mrr_sum / n
    print(f"  MRR   : {mrr:.3f}")
    print()

    # 失败案例 Top 15（hit@5 未命中）
    fails = [d for d in detail if not d["hit5"]]
    print(f"hit@5 未命中 {len(fails)} 题（失败案例）:")
    for d in fails[:15]:
        print(f"  #{d['id']:>2} [{d['village'] or '-'}] {d['question'][:30]} | anchor={d['anchor']} gold={d['gold_size']}")
        for t in d["top_texts"]:
            print(f"       {t}")

    # 保存详细结果
    out = {"n": n, "hit": {str(k): stats[k]["hit"] for k in (1, 3, 5)},
           "recall": {str(k): round(stats[k]["recall_sum"] / stats[k]["gold_total"], 4) for k in (1, 3, 5)},
           "mrr": round(mrr, 4), "details": detail}
    Path("data/eval/eval_results.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print()
    print("详细结果 -> data/eval/eval_results.json")

if __name__ == "__main__":
    main()
