"""
4 路检索消融：char-TF-IDF / word-TF-IDF / BGE / 各组合 RRF
====================================================
对 60 题评测集：
  - char-only:     run_eval.py --mode tfidf (官方 80.0%)
  - word-only:     eval_retrieval_compare.py (消融, ≈53%)
  - BGE-only:      本脚本 (bge-small-zh-v1.5, 离线)
  - char+word:     run_eval.py --mode hybrid (官方 88.3%, 旧 word 腿)
  - char+BGE:      本脚本
  - char+word+BGE: 本脚本
"""
from __future__ import annotations
import argparse, json, time, sys, os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
EVAL = ROOT / "data" / "eval" / "eval_set.json"
OUT = ROOT / "data" / "eval" / "retrieval_4way.json"
OUT_MD = ROOT / "data" / "eval" / "retrieval_4way.md"

# fixed official numbers from the project pipeline (run_eval.py)
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
    return {"n": n,
            "hit@1": hit[1] / n, "hit@3": hit[3] / n, "hit@5": hit[5] / n,
            "MRR": rr / n}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--topk", type=int, default=20)
    ap.add_argument("--rrf_k", type=int, default=60)
    args = ap.parse_args()

    qs = json.loads(EVAL.read_text(encoding="utf-8"))["questions"]
    golds = [set(int(x) for x in q.get("gold_chunk_ids", [])) for q in qs]
    queries = [q["question"] for q in qs]
    print(f"[*] {len(qs)} questions")

    # ---- char + word 索引（项目已有）----
    import joblib, numpy as np
    from scipy import sparse
    from sklearn.preprocessing import normalize
    char_vec = joblib.load(ROOT / "data" / "index" / "vectorizer.pkl")
    Xc = normalize(sparse.load_npz(ROOT / "data" / "index" / "embeddings.npz").astype("float32"), norm="l2", axis=1, copy=False)
    word_vec = joblib.load(ROOT / "data" / "index" / "word_vectorizer.pkl")
    Xw = normalize(sparse.load_npz(ROOT / "data" / "index" / "word_embeddings.npz").astype("float32"), norm="l2", axis=1, copy=False)
    Qc = normalize(char_vec.transform(queries), norm="l2", axis=1, copy=False)
    Qw = normalize(word_vec.transform(queries), norm="l2", axis=1, copy=False)

    # ---- BGE 索引与查询编码（离线）----
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    from sentence_transformers import SentenceTransformer
    Xb = np.load(ROOT / "data" / "index" / "semantic_embeddings.npy").astype("float32")
    print(f"    char {Xc.shape}  word {Xw.shape}  bge {Xb.shape}")
    t = time.time(); m = SentenceTransformer("BAAI/bge-small-zh-v1.5"); print(f"    model load {time.time()-t:.1f}s")
    t = time.time(); Qb = m.encode(queries, batch_size=32, show_progress_bar=False, normalize_embeddings=True).astype("float32")
    print(f"    bge encode {time.time()-t:.1f}s")

    # ---- 检索（village 过滤 + topk，模拟项目 _candidate_indices）----
    village_index = json.loads((ROOT / "data" / "index" / "village_index.json").read_text(encoding="utf-8"))
    min_v = 20
    char_preds, word_preds, bge_preds = [], [], []
    char_word_preds, char_bge_preds, three_preds = [], [], []
    for i, q in enumerate(qs):
        v = q.get("village") or None
        if v and v in village_index and len(village_index[v]) >= min_v:
            cand = village_index[v]
        else:
            cand = list(range(Xc.shape[0]))
        # per-leg cosine on the candidate pool
        def topk_sparse(X, qrow, cand, k):
            sims = (X[cand] @ qrow.T).toarray().ravel()
            if k >= len(sims):
                order = np.argsort(-sims)
            else:
                part = np.argpartition(-sims, k)[:k]
                order = part[np.argsort(-sims[part])]
            return [cand[j] for j in order[:k]]
        def topk_dense(X, q, cand, k):
            sims = X[cand] @ q
            if k >= len(sims):
                order = np.argsort(-sims)
            else:
                part = np.argpartition(-sims, k)[:k]
                order = part[np.argsort(-sims[part])]
            return [cand[j] for j in order[:k]]
        cR = topk_sparse(Xc, Qc.getrow(i), cand, args.topk)
        wR = topk_sparse(Xw, Qw.getrow(i), cand, args.topk)
        bR = topk_dense(Xb, Qb[i], cand, args.topk)
        char_preds.append(cR); word_preds.append(wR); bge_preds.append(bR)
        char_word_preds.append(rrf_fuse([cR, wR], args.rrf_k)[: args.topk])
        char_bge_preds.append(rrf_fuse([cR, bR], args.rrf_k)[: args.topk])
        three_preds.append(rrf_fuse([cR, wR, bR], args.rrf_k)[: args.topk])

    # ---- 评测 ----
    results = {}
    results["char_tfidf"]   = OFFICIAL["char_tfidf"]
    results["word_tfidf"]   = OFFICIAL["char_tfidf"]  # placeholder, overwrite
    # 用本脚本的 word 跑（与 standalone 消融一致）
    results["word_tfidf"]   = evaluate(word_preds, golds)
    results["bge"]          = evaluate(bge_preds, golds)
    results["char_word_rrf_off"]   = evaluate(char_word_preds, golds)
    results["char_bge_rrf"]        = evaluate(char_bge_preds, golds)
    results["char_word_bge_rrf"]   = evaluate(three_preds, golds)
    # 官方 char+word
    results["char_word_rrf_official"] = OFFICIAL["char_word_rrf"]

    print("\n=== 4-way Retrieval Ablation (60Q) ===")
    keys = ["char_tfidf", "word_tfidf", "bge",
            "char_word_rrf_official", "char_word_rrf_off",
            "char_bge_rrf", "char_word_bge_rrf"]
    print(f"{'method':<28}{'hit@1':>10}{'hit@3':>10}{'hit@5':>10}{'MRR':>10}")
    md = ["| method | hit@1 | hit@3 | hit@5 | MRR |", "|---|---:|---:|---:|---:|"]
    for k in keys:
        r = results[k]
        print(f"{k:<28}{r['hit@1']*100:>9.1f}%{r['hit@3']*100:>9.1f}%"
              f"{r['hit@5']*100:>9.1f}%{r['MRR']:>10.3f}")
        md.append(f"| `{k}` | {r['hit@1']*100:.1f}% | {r['hit@3']*100:.1f}% | "
                  f"{r['hit@5']*100:.1f}% | {r['MRR']:.3f} |")
    print()

    OUT.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    md_text = (
        "# 4 路检索消融（60 题）\n\n"
        "char / word / BGE 单路 + 各组合 RRF。\n"
        "- char_tfidf / char_word_rrf_official 来自 `scripts/run_eval.py --mode both`\n"
        "- 其余由本脚本在同评测集上实跑（village 过滤 min 20，RRF k=60, topk=20）\n\n"
        + "\n".join(md) + "\n"
    )
    OUT_MD.write_text(md_text, encoding="utf-8")
    print(f"[+] {OUT_MD}")


if __name__ == "__main__":
    main()
