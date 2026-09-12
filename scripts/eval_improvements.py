# -*- coding: utf-8 -*-
"""
检索增强评测（60 题）
====================
对比（全部走生产检索器 HybridArchiveRetriever，仅切换开关）：
    1. baseline          char + word 双路 RRF（当前线上，88.3% 口径）
    2. +query_norm       查询错字归一化
    3. +field@w          结构化字段通道（档案名/篇目/村寨，权重 w）
    4. +rerank           BGE 交叉编码器重排（bge-reranker-v2-m3）
    5. bge_only_*        BGE 双编码单路（无指令 / 加检索指令）
    6. typo_robust       错字提问下 baseline vs +query_norm

weak 口径与官方 run_eval.py 一致（anchor / keywords 命中）；
另给 gold_chunk_ids 口径（与 4 路消融一致）。

结果会与既有 retrieval_improvements.json 合并（重跑 --skip-rerank 不会丢失此前的重排结果）。

用法：
    python scripts/eval_improvements.py
    python scripts/eval_improvements.py --skip-rerank
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

# 离线模式必须在任何 HF 相关导入之前生效（本机已缓存模型）
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"

EVAL_PATH = ROOT / "data" / "eval" / "eval_set.json"
OUT_JSON = ROOT / "data" / "eval" / "retrieval_improvements.json"
OUT_MD = ROOT / "data" / "eval" / "retrieval_improvements.md"

TOPK = 5
CONFUSE = [
    ("会议", "会设"), ("巧渡金沙江", "巧度金沙江"), ("皎平渡", "较平渡"),
    ("扎西", "札西"), ("石鼓", "石古"), ("寻甸", "寻店"), ("禄劝", "绿劝"),
    ("宣威", "宣伟"), ("曲靖", "曲敬"), ("金沙江", "金沙砂"), ("楚雄", "楚熊"),
]


def corrupt_word(word: str):
    """按混淆表把词中一个字符改错；找不到可用映射时返回 None。"""
    for a, b in CONFUSE:
        if a in word and a != word:
            return word.replace(a, b, 1)
    for a, b in CONFUSE:
        if word == a:
            return b
    return None


def load_questions():
    return json.loads(EVAL_PATH.read_text(encoding="utf-8"))["questions"]


def search_all(retriever, questions, texts):
    out = []
    for q, text in zip(questions, texts):
        out.append(retriever.search(text, village=q.get("village"), top_k=TOPK))
    return out


def evaluate(questions, all_results, texts=None):
    """run_eval 口径：anchor / keywords 命中。texts 仅用于记录（可选）。"""
    stats = {k: 0 for k in (1, 3, 5)}
    mrr = 0.0
    n = len(questions)
    for i, (q, results) in enumerate(zip(questions, all_results)):
        anchor, kws = q["anchor"], q.get("keywords", [])
        flags = [anchor in r["text"] or any(k in r["text"] for k in kws) for r in results]
        for k in (1, 3, 5):
            if any(flags[:k]):
                stats[k] += 1
        first = next((j + 1 for j, f in enumerate(flags) if f), None)
        if first:
            mrr += 1.0 / first
    return {"n": n, "hit@1": stats[1] / n, "hit@3": stats[3] / n, "hit@5": stats[5] / n, "MRR": mrr / n}


def eval_gold_ids(questions, all_results, text2idx):
    hit1 = 0
    mrr = 0.0
    n = 0
    for q, results in zip(questions, all_results):
        gold = {int(x) for x in q.get("gold_chunk_ids", [])}
        if not gold:
            continue
        n += 1
        pred = [r.get("chunk_id", text2idx.get(r["text"], -1)) for r in results]
        if pred and pred[0] in gold:
            hit1 += 1
        for rank, p in enumerate(pred, 1):
            if p in gold:
                mrr += 1.0 / rank
                break
    return {"gold_n": n, "gold_hit@1": hit1 / n if n else 0.0, "gold_MRR": mrr / n if n else 0.0}


def make_typo_questions(questions):
    """破坏每题最多两个实体词（各 1 字），模拟真实输入错字。"""
    typed, kept = [], 0
    for q in questions:
        text = q["question"]
        corrupted = 0
        for word in [q["anchor"], q.get("village")] + list(q.get("keywords", [])):
            if not word:
                continue
            cw = corrupt_word(word)
            if cw and cw != word and word in text:
                text = text.replace(word, cw, 1)
                corrupted += 1
            if corrupted >= 2:
                break
        if corrupted:
            kept += 1
        typed.append(text)
    return typed, kept


def run_variant(r, questions, texts, tag, use_norm, use_field, use_rerank,
                field_pair, do_gold=True, text2idx=None):
    os.environ["RED_ARCHIVE_QUERY_NORM"] = "1" if use_norm else "0"
    r.field_vectorizer, r.field_embeddings = field_pair if use_field else (None, None)
    r.rerank_enabled = use_rerank
    t = time.time()
    all_results = search_all(r, questions, texts)
    m = evaluate(questions, all_results)
    m["seconds"] = round(time.time() - t, 1)
    if do_gold and text2idx is not None:
        m.update(eval_gold_ids(questions, all_results, text2idx))
    print(f"    {tag:<16} hit@1={m['hit@1']*100:.1f}%  MRR={m['MRR']:.3f}  ({m['seconds']}s)")
    return m


def bge_single_path(questions, use_instr: bool, chunks):
    """BGE 双编码单路；同时给 weak 与 gold 两种口径。"""
    import numpy as np
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer("BAAI/bge-small-zh-v1.5")
    Xb = np.load(ROOT / "data" / "index" / "semantic_embeddings.npy").astype("float32")
    village_index = json.loads((ROOT / "data" / "index" / "village_index.json").read_text(encoding="utf-8"))
    queries = [q["question"] for q in questions]
    if use_instr:
        queries = ["为这个句子生成表示以用于检索相关文章：" + q for q in queries]
    Q = model.encode(queries, batch_size=32, show_progress_bar=False, normalize_embeddings=True).astype("float32")

    hit = {k: 0 for k in (1, 3, 5)}
    mrr = 0.0
    gold_hit1 = 0
    gold_mrr = 0.0
    gold_n = 0
    n = len(questions)
    for i, q in enumerate(questions):
        v = q.get("village")
        cand = village_index[v] if (v and v in village_index and len(village_index[v]) >= 20) else list(range(Xb.shape[0]))
        sims = Xb[cand] @ Q[i]
        order = sorted(range(len(cand)), key=lambda j: -sims[j])[:TOPK]
        pred = [cand[j] for j in order]
        texts = [chunks[p]["text"] for p in pred]
        anchor, kws = q["anchor"], q.get("keywords", [])
        flags = [anchor in t or any(k in t for k in kws) for t in texts]
        for k in (1, 3, 5):
            if any(flags[:k]):
                hit[k] += 1
        first = next((r + 1 for r, f in enumerate(flags) if f), None)
        if first:
            mrr += 1.0 / first
        gold = {int(x) for x in q.get("gold_chunk_ids", [])}
        if gold:
            gold_n += 1
            if pred[0] in gold:
                gold_hit1 += 1
            for rank, p in enumerate(pred, 1):
                if p in gold:
                    gold_mrr += 1.0 / rank
                    break
    return {"n": n, "hit@1": hit[1] / n, "hit@3": hit[3] / n, "hit@5": hit[5] / n, "MRR": mrr / n,
            "gold_n": gold_n, "gold_hit@1": gold_hit1 / gold_n if gold_n else 0.0,
            "gold_MRR": gold_mrr / gold_n if gold_n else 0.0}


def main():
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-rerank", action="store_true")
    args = ap.parse_args()

    from agent.hybrid_retriever import HybridArchiveRetriever

    questions = load_questions()
    texts = [q["question"] for q in questions]
    print(f"[*] {len(questions)} questions")

    r = HybridArchiveRetriever()
    text2idx = {c["text"]: i for i, c in enumerate(r.chunks)}
    field_pair = (r.field_vectorizer, r.field_embeddings)
    if field_pair[0] is None:
        # 评测页始终加载字段索引做消融；生产默认关闭（见 hybrid_retriever 说明）
        import pickle

        from scipy.sparse import load_npz
        vp = ROOT / "data" / "index" / "field_vectorizer.pkl"
        ep = ROOT / "data" / "index" / "field_embeddings.npz"
        if vp.exists() and ep.exists():
            field_pair = (pickle.load(open(vp, "rb")), load_npz(ep))
            print("    (field index loaded for ablation; production default off)")
    print(f"    field leg: {'on' if field_pair[0] is not None else 'off'} | rerank model: {r.rerank_model}")

    prev = {}
    if OUT_JSON.exists():
        try:
            prev = json.loads(OUT_JSON.read_text(encoding="utf-8"))
        except Exception:
            prev = {}

    results = {}
    def dump():
        OUT_JSON.write_text(json.dumps({**prev, **results}, ensure_ascii=False, indent=2), encoding="utf-8")

    print("[1] production-path variants")
    results["baseline"] = run_variant(r, questions, texts, "baseline", False, False, False, field_pair, True, text2idx)
    results["+query_norm"] = run_variant(r, questions, texts, "+query_norm", True, False, False, field_pair, False)
    for fw in ("0.25", "0.5", "1.0"):
        os.environ["RED_ARCHIVE_FIELD_WEIGHT"] = fw
        results[f"+field@{fw}"] = run_variant(r, questions, texts, f"+field@{fw}", False, True, False, field_pair, False)
    os.environ["RED_ARCHIVE_FIELD_WEIGHT"] = "0.5"
    dump()
    if not args.skip_rerank:
        results["+rerank"] = run_variant(r, questions, texts, "+rerank", False, False, True, field_pair, True, text2idx)
        dump()

    print("[2] typo robustness (typo'd questions)")
    typed, kept = make_typo_questions(questions)
    m_base = run_variant(r, questions, typed, "typo_baseline", False, False, False, field_pair, False)
    m_norm = run_variant(r, questions, typed, "typo_query_norm", True, False, False, field_pair, False)
    m_base["typo_count"] = kept
    m_norm["typo_count"] = kept
    results["typo_baseline"] = m_base
    results["typo_query_norm"] = m_norm
    print(f"    typo questions: {kept}/{len(questions)}")
    dump()

    print("[3] BGE bi-encoder single path (reference)")
    results["bge_only_plain"] = bge_single_path(questions, False, r.chunks)
    results["bge_only_instr"] = bge_single_path(questions, True, r.chunks)
    print(f"    bge plain hit@1={results['bge_only_plain']['hit@1']*100:.1f}%"
          f"  gold={results['bge_only_plain']['gold_hit@1']*100:.1f}%"
          f"  | instr hit@1={results['bge_only_instr']['hit@1']*100:.1f}%"
          f"  gold={results['bge_only_instr']['gold_hit@1']*100:.1f}%")

    OUT_JSON.write_text(json.dumps({**prev, **results}, ensure_ascii=False, indent=2), encoding="utf-8")
    allres = {**prev, **results}

    md = ["# 检索增强评测（60 题）", "",
          "口径：与 `run_eval.py` 一致（anchor / keywords 命中），village 过滤 min20，RRF k=60。", "",
          "| 方案 | hit@1 | hit@3 | hit@5 | MRR | 耗时 |", "|---|---:|---:|---:|---:|---:|"]
    tags = ["baseline", "+query_norm", "+field@0.25", "+field@0.5", "+field@1.0", "+rerank", "+field+rerank"]
    for tag in tags:
        if tag in allres:
            m = allres[tag]
            md.append(f"| `{tag}` | {m['hit@1']*100:.1f}% | {m['hit@3']*100:.1f}% | {m['hit@5']*100:.1f}% | {m['MRR']:.3f} | {m.get('seconds','')}s |")
    md += ["", "## gold_chunk_ids 口径（⚠️ 已失真，仅供参考）", "",
           "> 当前评测集 gold 为旧分块时代标注，与现行 500 字分块索引不对应（char-only gold hit@1 仅 1.7%，weak 口径 80%）。",
           "> 如需 gold 级评测，请按现行 chunks 重新标注。", "",
           "| 方案 | gold hit@1 | gold MRR |", "|---|---:|---:|"]
    for tag in ["baseline", "+rerank"]:
        if tag in allres and "gold_hit@1" in allres[tag]:
            m = allres[tag]
            md.append(f"| `{tag}` | {m['gold_hit@1']*100:.1f}% | {m['gold_MRR']:.3f} |")
    if "typo_baseline" in allres and "typo_query_norm" in allres:
        mb, mn = allres["typo_baseline"], allres["typo_query_norm"]
        md += ["", "## 错字提问鲁棒性", "",
               f"替换了 {mb.get('typo_count','?')}/{len(questions)} 题的实体词（每题最多两处、各 1 字）。", "",
               "| 方案 | hit@1 | MRR |", "|---|---:|---:|",
               f"| 未归一化 | {mb['hit@1']*100:.1f}% | {mb['MRR']:.3f} |",
               f"| +query_norm | {mn['hit@1']*100:.1f}% | {mn['MRR']:.3f} |"]
    if "bge_only_plain" in allres and "bge_only_instr" in allres:
        bp, bi = allres["bge_only_plain"], allres["bge_only_instr"]
        md += ["", "## BGE 双编码单路（参考）", "",
               "| 方案 | weak hit@1 | weak MRR | gold hit@1 | gold MRR |", "|---|---:|---:|---:|---:|",
               f"| 无指令 | {bp['hit@1']*100:.1f}% | {bp['MRR']:.3f} | {bp['gold_hit@1']*100:.1f}% | {bp['gold_MRR']:.3f} |",
               f"| 查询加检索指令 | {bi['hit@1']*100:.1f}% | {bi['MRR']:.3f} | {bi['gold_hit@1']*100:.1f}% | {bi['gold_MRR']:.3f} |", ""]
    OUT_MD.write_text("\n".join(md), encoding="utf-8")
    print(f"[+] {OUT_MD}")


if __name__ == "__main__":
    main()
