"""
混合检索器：字符 TF-IDF + 第二路检索 + RRF 融合
----------------------------------------------
第二路默认使用词级 TF-IDF（build_semantic_index.py --backend word_tfidf）；
若已构建 BGE 索引则自动切换为语义向量。
"""
from __future__ import annotations

import json
import os
import pickle

import numpy as np
from scipy.sparse import load_npz
from sklearn.metrics.pairwise import cosine_similarity

from . import config
from .retriever import ArchiveRetriever


class HybridArchiveRetriever(ArchiveRetriever):
    """双路检索 + Reciprocal Rank Fusion。"""

    def __init__(self, index_dir: str | None = None, rrf_k: int = 60):
        super().__init__(index_dir=index_dir)
        self.rrf_k = rrf_k
        self.secondary_backend = None
        self.word_vectorizer = None
        self.word_embeddings = None
        self.semantic_embeddings = None
        self.semantic_model = None
        self.semantic_meta = {}

        meta_path = os.path.join(self.index_dir, "semantic_meta.json")
        if os.path.exists(meta_path):
            with open(meta_path, "r", encoding="utf-8") as f:
                self.semantic_meta = json.load(f)
            self.secondary_backend = self.semantic_meta.get("backend", "bge")
            self._load_secondary_index()

    def _load_secondary_index(self) -> None:
        if self.secondary_backend == "word_tfidf":
            word_vec = os.path.join(self.index_dir, "word_vectorizer.pkl")
            word_emb = os.path.join(self.index_dir, "word_embeddings.npz")
            if os.path.exists(word_vec) and os.path.exists(word_emb):
                with open(word_vec, "rb") as f:
                    self.word_vectorizer = pickle.load(f)
                self.word_embeddings = load_npz(word_emb)
            return

        sem_path = os.path.join(self.index_dir, "semantic_embeddings.npy")
        if os.path.exists(sem_path):
            self.semantic_embeddings = np.load(sem_path)
            model_name = self.semantic_meta.get("model")
            if model_name:
                try:
                    from sentence_transformers import SentenceTransformer

                    self.semantic_model = SentenceTransformer(model_name)
                except ImportError:
                    self.semantic_model = None

    @staticmethod
    def _rrf_fuse(rank_lists: list[list[int]], k: int = 60) -> list[tuple[int, float]]:
        scores: dict[int, float] = {}
        for ranks in rank_lists:
            for rank, idx in enumerate(ranks):
                scores[idx] = scores.get(idx, 0.0) + 1.0 / (k + rank + 1)
        return sorted(scores.items(), key=lambda x: x[1], reverse=True)

    def _candidate_indices(self, village: str | None) -> list[int] | None:
        min_village_chunks = 20
        if (
            village is not None
            and village in self.village_index
            and len(self.village_index[village]) >= min_village_chunks
        ):
            return self.village_index[village]
        return None

    def _rank_tfidf(self, query: str, candidates: list[int] | None, top_n: int) -> list[int]:
        query_vec = self.vectorizer.transform([query])
        sims = cosine_similarity(query_vec, self.embeddings)[0]
        if candidates is not None:
            ranked = sorted([(i, sims[i]) for i in candidates], key=lambda x: x[1], reverse=True)
        else:
            ranked = sorted(enumerate(sims), key=lambda x: x[1], reverse=True)
        return [idx for idx, _ in ranked[:top_n]]

    def _rank_secondary(self, query: str, candidates: list[int] | None, top_n: int) -> list[int]:
        if self.word_vectorizer is not None and self.word_embeddings is not None:
            query_vec = self.word_vectorizer.transform([query])
            sims = cosine_similarity(query_vec, self.word_embeddings)[0]
        elif self.semantic_embeddings is not None and self.semantic_model is not None:
            q_vec = self.semantic_model.encode([query], normalize_embeddings=True)
            sims = cosine_similarity(q_vec, self.semantic_embeddings)[0]
        else:
            return []

        if candidates is not None:
            ranked = sorted([(i, sims[i]) for i in candidates], key=lambda x: x[1], reverse=True)
        else:
            ranked = sorted(enumerate(sims), key=lambda x: x[1], reverse=True)
        return [idx for idx, _ in ranked[:top_n]]

    def search(self, query: str, village: str = None, top_k: int = None) -> list:
        top_k = top_k or config.TOP_K
        candidates = self._candidate_indices(village)
        pool = max(top_k * 8, 40)

        tfidf_ranks = self._rank_tfidf(query, candidates, pool)
        secondary_ranks = self._rank_secondary(query, candidates, pool)

        if secondary_ranks:
            fused = self._rrf_fuse([tfidf_ranks, secondary_ranks], k=self.rrf_k)
            mode = self.secondary_backend or "hybrid"
        else:
            fused = [(idx, float(len(tfidf_ranks) - rank)) for rank, idx in enumerate(tfidf_ranks)]
            mode = "tfidf"

        results = []
        for idx, score in fused[:top_k]:
            chunk = self.chunks[idx]
            results.append({
                "text": chunk["text"],
                "locations": chunk.get("locations", []),
                "source": chunk.get("source", "未知档案"),
                "offset": chunk.get("offset"),
                "page": chunk.get("page"),
                "section": chunk.get("section"),
                "confidence": chunk.get("confidence"),
                "score": float(score),
                "retriever": mode,
            })
        return results
