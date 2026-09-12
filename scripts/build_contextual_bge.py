# -*- coding: utf-8 -*-
"""
为上下文感知检索构建 BGE 语义向量（离线，无需 API）
====================================================
读取 chunks_contextual.json，用 BAAI/bge-small-zh-v1.5 重新编码
（text = 前缀 + 原文），输出 data/index_contextual/semantic_embeddings.npy。
用于对比 BGE-only / char+BGE RRF 在上下文前后的召回差异。
"""
from __future__ import annotations
import json, sys, os
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
OUT_DIR = ROOT / "data" / "index_contextual"
IN_CHUNKS = ROOT / "data" / "index" / "chunks_contextual.json"


def main():
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    from sentence_transformers import SentenceTransformer

    chunks = json.loads(IN_CHUNKS.read_text(encoding="utf-8"))
    texts = [c["text"] for c in chunks]
    model = SentenceTransformer("BAAI/bge-small-zh-v1.5")
    print(f"[*] encoding {len(texts)} contextual chunks ...")
    emb = model.encode(texts, batch_size=64, show_progress_bar=True,
                       normalize_embeddings=True).astype("float32")
    np.save(OUT_DIR / "semantic_embeddings.npy", emb)
    print(f"[+] {OUT_DIR / 'semantic_embeddings.npy'}  shape={emb.shape}")


if __name__ == "__main__":
    main()
