# -*- coding: utf-8 -*-
"""
上下文感知检索消融评测
========================
对比（同 60 题评测集，gold_chunk_ids）：
  - 基线 char_tfidf        80.0%  (官方 run_eval.py)
  - 基线 char_word_rrf     88.3%  (官方 run_eval.py)
  - 上下文 char_tfidf       <-- 本脚本
  - 上下文 word_tfidf       <-- 本脚本
  - 上下文 char_word_rrf    <-- 本脚本
BGE 腿沿用 data/index/semantic_embeddings.npy（上下文前缀不重编码语义向量）。
"""
from __future__ import annotations
import argparse, json, time, sys, os
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
EVAL = ROOT / "data" / "eval" / "eval_set.json"
CTX = ROOT / "data" / "index_contextual"
BASE = ROOT / "data" / "index"

# 官方基线（来自 run_eval.py）
BASELINE_CHAR = 0.800
BASELINE_CHARWORD = 0.883

OFFICIAL = {
    "char_tfidf":    {"hit@1": 0.800, "hit@3": 0.900, "hit@5": 0.917, "MRR": 0.843, "n": 60},
    "char_word_rrf": {"hit@1": 0.883, "hit@3": 0.900, "hit@5": 0.933, "MRR": 0.896, "n": 60},
}


def rrf_fuse(rank_lists, k=60):
    s = {}
    for rl in rank_lists:
        for r, idx in enumerate(rl):
            s[idx] = s.get(idx, 0.0) + 1.0 / (k + r + 1)
    return [i for i, _ in sorted(s.items(), key=lambda x: -x[1])]


def evaluate(predictions, golds, ks=(1, 3, 5)):
    hit = {k: 0 for k in ks}
    rr = 0.0
    n = len(predictions)
    for pred, gold in zip(predictions, golds):
        if not gold:
            continue
        for k in ks:
            if any(p in gold for p in pred[:k]):
                hit[k] += 1
        for r, p in enumerate(pred, start=1):
            if p in gold:
                rr += 1.0 / r
                break
    return {"n": n, "hit@1": hit[1] / n, "hit@3": hit[3] / n,
            "hit@5": hit[5] / n, "MRR": rr / n}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--topk", type=int, default=20)
    ap.add_argument("--rrf_k", type=int, default=60)
    args = ap.parse_args()

    qs = json.loads(EVAL.read_text(encoding="utf-8"))["questions"]
    golds = [set(int(x) for x in q.get("gold_chunk_ids", [])) for q in qs]
    queries = [q["question"] for q in qs]
    print(f"[*] {len(qs)} questions")

    import joblib
    from scipy import sparse
    from sklearn.preprocessing import normalize

    char_vec = joblib.load(CTX / "vectorizer.pkl")
    Xc = normalize(sparse.load_npz(CTX / "embeddings.npz").astype("float32"),
                   norm="l2", axis=1, copy=False)
    word_vec = joblib.load(CTX / "word_vectorizer.pkl")
    Xw = normalize(sparse.load_npz(CTX / "word_embeddings.npz").astype("float32"),
                   norm="l2", axis=1, copy=False)
    Qc = normalize(char_vec.transform(queries), norm="l2", axis=1, copy=False)
    Qw = normalize(word_vec.transform(queries), norm="l2", axis=1, copy=False)
    print(f"    ctx char {Xc.shape}  word {Xw.shape}")

    village_index = json.loads((CTX / "village_index.json").read_text(encoding="utf-8"))
    min_v = 20
    char_preds, word_preds, cw_preds = [], [], []
    for i, q in enumerate(qs):
        v = q.get("village") or None
        cand = village_index[v] if (v and v in village_index and len(village_index[v]) >= min_v) else list(range(Xc.shape[0]))

        def topk_sparse(X, qrow, cand, k):
            sims = (X[cand] @ qrow.T).toarray().ravel()
            if k >= len(sims):
                order = np.argsort(-sims)
            else:
                part = np.argpartition(-sims, k)[:k]
                order = part[np.argsort(-sims[part])]
            return [cand[j] for j in order[:k]]

        cR = topk_sparse(Xc, Qc.getrow(i), cand, args.topk)
        wR = topk_sparse(Xw, Qw.getrow(i), cand, args.topk)
        char_preds.append(cR); word_preds.append(wR)
        cw_preds.append(rrf_fuse([cR, wR], args.rrf_k)[:args.topk])

    ctx_char = evaluate(char_preds, golds)
    ctx_word = evaluate(word_preds, golds)
    ctx_cw = evaluate(cw_preds, golds)

    print("\n=== 上下文感知检索 vs 基线（60Q）===")
    print(f"{'method':<22}{'hit@1':>10}{'hit@3':>10}{'hit@5':>10}{'MRR':>10}")
    rows = [
        ("基线 char_tfidf", BASELINE_CHAR, None, None, None),
        ("上下文 char_tfidf", ctx_char["hit@1"], ctx_char["hit@3"], ctx_char["hit@5"], ctx_char["MRR"]),
        ("基线 char+word", BASELINE_CHARWORD, None, None, None),
        ("上下文 char+word", ctx_cw["hit@1"], ctx_cw["hit@3"], ctx_cw["hit@5"], ctx_cw["MRR"]),
        ("上下文 word_tfidf", ctx_word["hit@1"], ctx_word["hit@3"], ctx_word["hit@5"], ctx_word["MRR"]),
    ]
    md = ["# 上下文感知检索消融（60 题）\n",
          "| method | hit@1 | hit@3 | hit@5 | MRR |",
          "|---|---:|---:|---:|---:|"]
    for name, h1, h3, h5, mrr in rows:
        if h3 is None:
            print(f"{name:<22}{h1*100:>9.1f}%")
            md.append(f"| {name} | {h1*100:.1f}% | - | - | - |")
        else:
            print(f"{name:<22}{h1*100:>9.1f}%{h3*100:>9.1f}%{h5*100:>9.1f}%{mrr:>10.3f}")
            md.append(f"| {name} | {h1*100:.1f}% | {h3*100:.1f}% | {h5*100:.1f}% | {mrr:.3f} |")
    print()
    delta = (ctx_char["hit@1"] - BASELINE_CHAR) * 100
    delta_cw = (ctx_cw["hit@1"] - BASELINE_CHARWORD) * 100
    print(f"Δ char_tfidf (hit@1): {delta:+.1f} pt")
    print(f"Δ char+word (hit@1):  {delta_cw:+.1f} pt")

    out = {
        "ctx_char_tfidf": ctx_char, "ctx_word_tfidf": ctx_word,
        "ctx_char_word_rrf": ctx_cw,
        "baseline_char_tfidf": BASELINE_CHAR, "baseline_char_word_rrf": BASELINE_CHARWORD,
    }
    (ROOT / "data" / "eval" / "retrieval_contextual.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    (ROOT / "data" / "eval" / "retrieval_contextual.md").write_text(
        "\n".join(md) + "\n", encoding="utf-8")
    print(f"[+] data/eval/retrieval_contextual.md")


if __name__ == "__main__":
    main()
