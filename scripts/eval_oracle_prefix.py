# -*- coding: utf-8 -*-
"""
Oracle 上界验证：把评测题的 anchor/keywords 人工注入 gold chunk 前缀，
若 hit@1 接近 100%，说明「实体化前缀」方向有提升空间（LLM 重跑值得做）。
"""
from __future__ import annotations
import json, sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

EVAL = ROOT / "data" / "eval" / "eval_set.json"
BASE = ROOT / "data" / "index"


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
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.preprocessing import normalize

    qs = json.loads(EVAL.read_text(encoding="utf-8"))["questions"]
    chunks = json.loads((BASE / "chunks.json").read_text(encoding="utf-8"))

    # gold + oracle 前缀
    texts = [c["text"] for c in chunks]
    golds = []
    for q in qs:
        anchor = q["anchor"]
        kws = q.get("keywords", [])
        g = [i for i, c in enumerate(chunks) if anchor in c["text"]]
        golds.append(g)
        pfx = f"【关键实体】{anchor}" + ("".join("、" + k for k in kws)) + "。"
        for i in g:
            texts[i] = pfx + texts[i]

    # 重建 char 索引
    # 注意：用基线词表只 transform（不 refit），隔离「前缀内容」与「词表重拟合」两个因素
    import joblib
    from scipy import sparse
    vec = joblib.load(BASE / "vectorizer.pkl")
    X = normalize(vec.transform(texts), norm="l2", axis=1, copy=False).astype("float32")
    Q = normalize(vec.transform([q["question"] for q in qs]), norm="l2", axis=1, copy=False).astype("float32")

    village_index = json.loads((BASE / "village_index.json").read_text(encoding="utf-8"))
    preds = []
    for i, q in enumerate(qs):
        v = q.get("village") or None
        cand = village_index[v] if (v and v in village_index and len(village_index[v]) >= 20) else list(range(X.shape[0]))
        sims = np.asarray(X[cand].dot(Q[i].T.todense()).ravel()).ravel()
        order = np.argsort(-sims)
        preds.append([cand[j] for j in order[:5]])

    r = evaluate(preds, golds)
    print("=== Oracle 上界（实体注入 gold 前缀，char-TFIDF）===")
    print(f"hit@1={r['hit@1']*100:.1f}%  hit@3={r['hit@3']*100:.1f}%  "
          f"hit@5={r['hit@5']*100:.1f}%  MRR={r['mrr']:.3f}")
    print(f"基线 char-TFIDF hit@1=80.0%（官方）")


if __name__ == "__main__":
    main()
