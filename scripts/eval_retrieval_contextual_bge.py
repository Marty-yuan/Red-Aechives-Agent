# -*- coding: utf-8 -*-
"""
上下文感知检索：BGE 语义腿消融
==============================
对比（同 60 题，anchor/keywords 判定，与 run_eval.py 一致）：
  - 基线 BGE-only        （data/index/semantic_embeddings.npy，原文）
  - 上下文 BGE-only       （data/index_contextual/semantic_embeddings.npy，前缀+原文）
  - 基线 char+BGE RRF
  - 上下文 char+BGE RRF
"""
from __future__ import annotations
import json, sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
BASE = ROOT / "data" / "index"
CTX = ROOT / "data" / "index_contextual"
EVAL = ROOT / "data" / "eval" / "eval_set.json"


def rrf(rank_lists, k=60):
    s = {}
    for rl in rank_lists:
        for r, idx in enumerate(rl):
            s[idx] = s.get(idx, 0.0) + 1.0 / (k + r + 1)
    return [i for i, _ in sorted(s.items(), key=lambda x: -x[1])]


def evaluate(preds, golds, ks=(1, 3, 5)):
    hit = {k: 0 for k in ks}
    rr = 0.0
    n = len(preds)
    for pred, gold in zip(preds, golds):
        if not gold:
            continue
        for k in ks:
            if any(p in gold for p in pred[:k]):
                hit[k] += 1
        for r, p in enumerate(pred, 1):
            if p in gold:
                rr += 1.0 / r
                break
    return {"hit@1": hit[1] / n, "hit@3": hit[3] / n, "hit@5": hit[5] / n, "mrr": rr / n}


def main():
    qs = json.loads(EVAL.read_text(encoding="utf-8"))["questions"]
    chunks = json.loads((BASE / "chunks.json").read_text(encoding="utf-8"))
    golds = []
    for q in qs:
        anchor = q["anchor"]
        golds.append([i for i, c in enumerate(chunks) if anchor in c["text"]])

    Xb_base = np.load(BASE / "semantic_embeddings.npy").astype("float32")
    Xb_ctx = np.load(CTX / "semantic_embeddings.npy").astype("float32")

    # char 索引（用于 RRF）
    import joblib
    from scipy import sparse
    from sklearn.preprocessing import normalize
    char_vec = joblib.load(BASE / "vectorizer.pkl")
    Xc = normalize(sparse.load_npz(BASE / "embeddings.npz").astype("float32"), norm="l2", axis=1, copy=False)
    Qc = normalize(char_vec.transform([q["question"] for q in qs]), norm="l2", axis=1, copy=False)
    char_vec_c = joblib.load(CTX / "vectorizer.pkl")
    Xc_c = normalize(sparse.load_npz(CTX / "embeddings.npz").astype("float32"), norm="l2", axis=1, copy=False)
    Qc_c = normalize(char_vec_c.transform([q["question"] for q in qs]), norm="l2", axis=1, copy=False)

    village_index = json.loads((BASE / "village_index.json").read_text(encoding="utf-8"))
    Qb_base = Xb_base  # already normalized at build
    Qb_ctx = Xb_ctx

    base_bge, ctx_bge, base_cb, ctx_cb = [], [], [], []
    for i, q in enumerate(qs):
        v = q.get("village") or None
        cand = village_index[v] if (v and v in village_index and len(village_index[v]) >= 20) else list(range(Xb_base.shape[0]))

        def topk(X, qrow, cand, k=20):
            from scipy import sparse as _sp
            if _sp.issparse(qrow):
                q = np.asarray(qrow.todense()).ravel()
            else:
                q = np.asarray(qrow).ravel()
            sims = X[cand].dot(q) if _sp.issparse(X) else X[cand] @ q
            order = np.argsort(-sims)
            return [cand[j] for j in order[:k]]

        bR_base = topk(Xb_base, Qb_base[i], cand)
        bR_ctx = topk(Xb_ctx, Qb_ctx[i], cand)
        cR_base = topk(Xc, Qc[i], cand)
        cR_ctx = topk(Xc_c, Qc_c[i], cand)
        base_bge.append(bR_base); ctx_bge.append(bR_ctx)
        base_cb.append(rrf([cR_base, bR_base])[:20])
        ctx_cb.append(rrf([cR_ctx, bR_ctx])[:20])

    rb = evaluate(base_bge, golds)
    rc = evaluate(ctx_bge, golds)
    rcb = evaluate(base_cb, golds)
    rcc = evaluate(ctx_cb, golds)

    print("\n=== 上下文感知检索：BGE 腿（60Q）===")
    print(f"{'method':<22}{'hit@1':>10}{'hit@3':>10}{'hit@5':>10}{'MRR':>10}")
    rows = [("基线 BGE-only", rb), ("上下文 BGE-only", rc),
            ("基线 char+BGE", rcb), ("上下文 char+BGE", rcc)]
    for name, r in rows:
        print(f"{name:<22}{r['hit@1']*100:>9.1f}%{r['hit@3']*100:>9.1f}%{r['hit@5']*100:>9.1f}%{r['mrr']:>10.3f}")
    print(f"\nΔ BGE-only hit@1: {(rc['hit@1']-rb['hit@1'])*100:+.1f} pt")
    print(f"Δ char+BGE hit@1: {(rcc['hit@1']-rcb['hit@1'])*100:+.1f} pt")

    out = {"baseline_bge": rb, "ctx_bge": rc, "baseline_char_bge": rcb, "ctx_char_bge": rcc}
    (ROOT / "data" / "eval" / "retrieval_contextual_bge.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[+] data/eval/retrieval_contextual_bge.json")


if __name__ == "__main__":
    main()
