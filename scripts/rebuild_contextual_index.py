# -*- coding: utf-8 -*-
"""
为上下文感知检索（contextual retrieval）构建独立评测索引
======================================================
读取 chunks_contextual.json（每个 chunk 的 text = 前缀 + 原文），
重建 char-TF-IDF + word-TF-IDF 索引，写入 data/index_contextual/，
不覆盖线上 data/index/。用于与基线 80.0% / 88.3% 做消融对比。
"""
from __future__ import annotations
import json, pickle, sys, os
from pathlib import Path
from datetime import datetime

import numpy as np
from scipy.sparse import save_npz
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import normalize

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from knowledge.toc_index import load_toc, match_book, annotate_chunks  # noqa: E402

IN_CHUNKS = ROOT / "data" / "index" / "chunks_contextual.json"
OUT_DIR = ROOT / "data" / "index_contextual"

VILLAGE_KEYWORDS = [
    "皎平渡", "石鼓", "扎西", "寻甸", "柯渡", "禄劝", "楚雄", "昭通", "曲靖",
    "丽江", "金沙江", "威信", "镇雄", "彝良", "巧家", "会泽", "富民", "嵩明",
    "元谋", "武定", "禄丰", "大姚", "姚安", "南华", "祥云", "宾川", "鹤庆",
    "昆明", "渡口", "乌蒙", "宣威", "富源", "沾益", "马龙", "丹桂",
    "蒙自", "东川", "永善", "绥江", "盐津", "大关", "鲁甸",
]


def build():
    os.makedirs(OUT_DIR, exist_ok=True)
    chunks = json.loads(IN_CHUNKS.read_text(encoding="utf-8"))
    print(f"[*] {len(chunks)} contextual chunks")

    texts = [c["text"] for c in chunks]

    # ---- char TF-IDF（与 rebuild_index.py 同参）----
    char_vec = TfidfVectorizer(max_features=3000, sublinear_tf=True,
                               analyzer="char_wb", ngram_range=(2, 4))
    Xc = normalize(char_vec.fit_transform(texts), norm="l2", axis=1, copy=False)
    print(f"    char {Xc.shape}")
    pickle.dump(char_vec, open(OUT_DIR / "vectorizer.pkl", "wb"))
    save_npz(OUT_DIR / "embeddings.npz", Xc)

    # ---- word TF-IDF（与 build_semantic_index.py 同参）----
    word_vec = TfidfVectorizer(analyzer="word", ngram_range=(1, 2), max_features=8000)
    Xw = normalize(word_vec.fit_transform(texts), norm="l2", axis=1, copy=False)
    print(f"    word {Xw.shape}")
    pickle.dump(word_vec, open(OUT_DIR / "word_vectorizer.pkl", "wb"))
    save_npz(OUT_DIR / "word_embeddings.npz", Xw)

    # ---- village 倒排（基于 contextual 文本仍可命中地点关键词）----
    village_index = {}
    for i, t in enumerate(texts):
        for kw in VILLAGE_KEYWORDS:
            if kw in t:
                village_index.setdefault(kw, []).append(i)
    (OUT_DIR / "village_index.json").write_text(
        json.dumps(village_index, ensure_ascii=False), encoding="utf-8")
    print(f"    villages: {len(village_index)}")

    meta = {
        "built_at": datetime.now().isoformat(timespec="seconds"),
        "source": "chunks_contextual.json",
        "char_shape": list(Xc.shape),
        "word_shape": list(Xw.shape),
        "total_chunks": len(chunks),
    }
    (OUT_DIR / "_index_summary.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[+] {OUT_DIR}")


if __name__ == "__main__":
    build()
