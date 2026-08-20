"""
检索器工厂
----------
统一创建 ArchiveRetriever / HybridArchiveRetriever，供 Agent 全链路使用。
"""
from __future__ import annotations

import os

from . import config
from .retriever import ArchiveRetriever


def create_retriever(index_dir: str | None = None):
    """默认优先混合检索（若第二路索引已构建），否则回退 TF-IDF。"""
    use_hybrid = os.environ.get("RED_ARCHIVE_USE_HYBRID", "1") != "0"
    index = index_dir or config.INDEX_DIR
    meta_path = os.path.join(index, "semantic_meta.json")
    word_emb = os.path.join(index, "word_embeddings.npz")
    bge_emb = os.path.join(index, "semantic_embeddings.npy")

    if use_hybrid and (os.path.exists(meta_path) or os.path.exists(word_emb) or os.path.exists(bge_emb)):
        from .hybrid_retriever import HybridArchiveRetriever

        return HybridArchiveRetriever(index_dir=index)
    return ArchiveRetriever(index_dir=index)
