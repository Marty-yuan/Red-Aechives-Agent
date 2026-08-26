"""
检索消融对比：char-TF-IDF / word-TF-IDF / Hybrid (RRF)
====================================================
直接调用项目自带的 HybridArchiveRetriever 的内部 ranking 函数
（与 `create_retriever()` 全链路一致），对 60 题评测集分别计算：
  - char-only: 字符 TF-IDF 单路
  - word-only: 词级 TF-IDF 单路（第二路）
  - hybrid:    RRF(char, word) 双路融合

用途：项目文档 3.2 技术细节 / 2.2 技术创新点的量化支撑；
      答辩"为什么用混合检索 / 各路贡献多少"的硬数据。

运行：
    python scripts/eval_retrieval_compare.py
    python scripts/eval_retrieval_compare.py --topk 10
"""
from __future__ import annotations
import argparse, json, time, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

EVAL = ROOT / "data" / "eval" / "eval_set.json"
CHUNKS = ROOT / "data" / "index" / "chunks.json"
OUT_JSON = ROOT / "data" / "eval" / "retrieval_compare.json"
OUT_MD = ROOT / "data" / "eval" / "retrieval_compare.md"


def evaluate(predictions, golds, ks=(1, 3, 5)):
    hit = {k: 0 for k in ks}
    rr_sum = 0.0
    n = len(predictions)
    for pred, gold in zip(predictions, golds):
        if not gold:
            continue
        for k in ks:
            if any(p in gold for p in pred[:k]):
                hit[k] += 1
        for r, p in enumerate(pred, start=1):
            if p in gold:
                rr_sum += 1.0 / r
                break
    return {
        "n": n,
        "hit@1": hit[1] / n,
        "hit@3": hit[3] / n,
        "hit@5": hit[5] / n,
        "MRR": rr_sum / n,
    }


def rrf_fuse(rank_lists, k=60):
    scores: dict[int, float] = {}
    for rl in rank_lists:
        for rank, idx in enumerate(rl):
            scores[idx] = scores.get(idx, 0.0) + 1.0 / (k + rank + 1)
    return [i for i, _ in sorted(scores.items(), key=lambda x: -x[1])]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--topk", type=int, default=20,
                    help="ranking pool size (project uses max(top_k*8, 40))")
    ap.add_argument("--rrf_k", type=int, default=60)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    print("[*] loading project hybrid retriever …")
    from agent.retriever_factory import create_retriever
    ret = create_retriever()
    print(f"    retriever={type(ret).__name__}, secondary={ret.secondary_backend}")

    qs = json.loads(EVAL.read_text(encoding="utf-8"))["questions"]
    if args.limit:
        qs = qs[: args.limit]
    golds = [set(int(x) for x in q.get("gold_chunk_ids", [])) for q in qs]
    print(f"    {len(qs)} questions, {len(ret.chunks)} chunks")

    char_preds, word_preds, hybrid_preds = [], [], []
    n_filtered, n_unfiltered = 0, 0
    t0 = time.time()
    for i, q in enumerate(qs):
        query = q["question"]
        village = q.get("village") or None
        candidates = ret._candidate_indices(village)
        if candidates is not None:
            n_filtered += 1
        else:
            n_unfiltered += 1

        pool = max(args.topk * 8, 40)
        tfidf_ranks = ret._rank_tfidf(query, candidates, pool)
        secondary_ranks = ret._rank_secondary(query, candidates, pool)

        # char leg
        char_preds.append(tfidf_ranks[: args.topk])
        # word leg (only if secondary exists)
        word_preds.append(secondary_ranks[: args.topk] if secondary_ranks else [])
        # hybrid
        if secondary_ranks:
            fused = rrf_fuse([tfidf_ranks, secondary_ranks], k=args.rrf_k)
        else:
            fused = tfidf_ranks
        hybrid_preds.append(fused[: args.topk])

    print(f"    village filter: {n_filtered} filtered, {n_unfiltered} full-pool, "
          f"{time.time()-t0:.1f}s")

    results = {
        "char_tfidf": evaluate(char_preds, golds),
        "word_tfidf": evaluate(word_preds, golds),
        "hybrid_rrf": evaluate(hybrid_preds, golds),
    }

    # Print + save
    print("\n=== Retrieval Comparison (60Q, project pipeline) ===")
    header = f"{'method':<22}{'hit@1':>10}{'hit@3':>10}{'hit@5':>10}{'MRR':>10}"
    print(header)
    md = ["| method | hit@1 | hit@3 | hit@5 | MRR |", "|---|---:|---:|---:|---:|"]
    for k in ["char_tfidf", "word_tfidf", "hybrid_rrf"]:
        r = results[k]
        print(f"{k:<22}{r['hit@1']*100:>9.1f}%{r['hit@3']*100:>9.1f}%"
              f"{r['hit@5']*100:>9.1f}%{r['MRR']:>10.3f}")
        md.append(f"| `{k}` | {r['hit@1']*100:.1f}% | {r['hit@3']*100:.1f}% "
                  f"| {r['hit@5']*100:.1f}% | {r['MRR']:.3f} |")
    print()

    OUT_JSON.write_text(json.dumps(results, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    md_text = ("# 检索消融对比（60 题，项目自建评测）\n\n"
               "数据：data/eval/eval_set.json (60 题 gold_chunk_ids)\n"
               "管道：HybridArchiveRetriever（与 create_retriever() 一致），"
               f"pool=max(topk*8, 40)={max(args.topk*8,40)}，RRF k={args.rrf_k}\n\n"
               + "\n".join(md) + "\n")
    OUT_MD.write_text(md_text, encoding="utf-8")
    print(f"[+] {OUT_JSON}")
    print(f"[+] {OUT_MD}")


if __name__ == "__main__":
    main()
