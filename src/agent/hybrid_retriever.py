"""
混合检索器：字符 TF-IDF + 第二路检索 + 可选字段通道 + RRF 融合 + 可选交叉编码重排
--------------------------------------------------------------------------------
第二路默认使用词级 TF-IDF（build_semantic_index.py --backend word_tfidf）；
若已构建 BGE 索引则自动切换为语义向量。

增强（可用环境变量控制）：
    RED_ARCHIVE_QUERY_NORM=0        关闭查询错字归一化
    RED_ARCHIVE_FIELD_LEG=0         关闭字段通道（结构化元数据，需先构建 field_* 索引）
    RED_ARCHIVE_RERANK=0            关闭交叉编码重排
    RED_ARCHIVE_RERANK_MODEL=...    重排模型（默认 BAAI/bge-reranker-v2-m3，本机离线可用）
    RED_ARCHIVE_RERANK_TOPN=48      参与重排的候选数
"""
from __future__ import annotations

import json
import math
import os
import pickle

import numpy as np
from scipy.sparse import load_npz
from sklearn.metrics.pairwise import cosine_similarity

from . import config
from .query_normalize import normalize_query
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

        # 字段通道（结构化上下文：档案名 / 篇目 / 村寨）
        self.field_vectorizer = None
        self.field_embeddings = None

        # 交叉编码重排
        self.reranker = None
        self._reranker_loaded = False
        self.rerank_enabled = os.environ.get("RED_ARCHIVE_RERANK", "0").lower() not in {"0", "off", "none"}
        self.rerank_model = os.environ.get("RED_ARCHIVE_RERANK_MODEL", "BAAI/bge-reranker-v2-m3")
        self.rerank_topn = int(os.environ.get("RED_ARCHIVE_RERANK_TOPN", "48"))

        meta_path = os.path.join(self.index_dir, "semantic_meta.json")
        if os.path.exists(meta_path):
            with open(meta_path, "r", encoding="utf-8") as f:
                self.semantic_meta = json.load(f)
            self.secondary_backend = self.semantic_meta.get("backend", "bge")
            self._load_secondary_index()
        self._load_field_index()

    def _load_field_index(self) -> None:
        """字段通道：档案名 + 篇目 + 村寨的字符 TF-IDF 索引（结构化上下文）。

        实测（60 题）：任何字段组合与权重均未超过基线，默认关闭；
        需要实验时 RED_ARCHIVE_FIELD_LEG=1 开启（可配 RED_ARCHIVE_FIELD_WEIGHT）。
        """
        if os.environ.get("RED_ARCHIVE_FIELD_LEG", "0").lower() in {"0", "off", "none"}:
            return
        vec_path = os.path.join(self.index_dir, "field_vectorizer.pkl")
        emb_path = os.path.join(self.index_dir, "field_embeddings.npz")
        if os.path.exists(vec_path) and os.path.exists(emb_path):
            with open(vec_path, "rb") as f:
                self.field_vectorizer = pickle.load(f)
            self.field_embeddings = load_npz(emb_path)

    def _ensure_reranker(self) -> None:
        if self._reranker_loaded:
            return
        self._reranker_loaded = True
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
        os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
        try:
            from sentence_transformers import CrossEncoder
            self.reranker = CrossEncoder(self.rerank_model)
        except Exception as exc:  # noqa: BLE001
            self.reranker = None
            print(f"[warn] reranker unavailable ({type(exc).__name__}: {str(exc)[:80]}); fallback to RRF")

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
    def _rrf_fuse(rank_lists: list[list[int]], k: int = 60, weights: list[float] | None = None) -> list[tuple[int, float]]:
        scores: dict[int, float] = {}
        if weights is None:
            weights = [1.0] * len(rank_lists)
        for w, ranks in zip(weights, rank_lists):
            for rank, idx in enumerate(ranks):
                scores[idx] = scores.get(idx, 0.0) + w / (k + rank + 1)
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

    def _rank_field(self, query: str, candidates: list[int] | None, top_n: int) -> list[int]:
        """字段通道排名：在档案名/篇目/村寨字段上做字符 TF-IDF 相似度。"""
        if self.field_vectorizer is None or self.field_embeddings is None:
            return []
        query_vec = self.field_vectorizer.transform([query])
        sims = cosine_similarity(query_vec, self.field_embeddings)[0]
        if candidates is not None:
            ranked = sorted([(i, sims[i]) for i in candidates], key=lambda x: x[1], reverse=True)
        else:
            ranked = sorted(enumerate(sims), key=lambda x: x[1], reverse=True)
        return [idx for idx, _ in ranked[:top_n]]

    @staticmethod
    def _sigmoid(x: float) -> float:
        try:
            return 1.0 / (1.0 + math.exp(-x))
        except OverflowError:
            return 0.0 if x < 0 else 1.0

    def _rerank(self, query: str, fused: list[tuple[int, float]], top_k: int) -> list[tuple[int, float]]:
        """用交叉编码器对融合结果的头部做精排；不可用时原样返回。"""
        if not self.rerank_enabled or len(fused) <= top_k:
            return fused
        self._ensure_reranker()
        if self.reranker is None:
            return fused
        pool = fused[: max(self.rerank_topn, top_k)]
        pairs = [(query, self.chunks[idx]["text"]) for idx, _ in pool]
        try:
            scores = self.reranker.predict(pairs)
        except Exception as exc:  # noqa: BLE001
            print(f"[warn] rerank failed ({type(exc).__name__}: {str(exc)[:80]}); keep RRF order")
            return fused
        order = sorted(range(len(pool)), key=lambda j: -float(scores[j]))
        reranked = [(pool[j][0], self._sigmoid(float(scores[j]))) for j in order]
        return reranked + fused[len(pool):]

    def search(self, query: str, village: str = None, top_k: int = None) -> list:
        top_k = top_k or config.TOP_K
        query = normalize_query(query)
        candidates = self._candidate_indices(village)
        pool = max(top_k * 8, 40)

        tfidf_ranks = self._rank_tfidf(query, candidates, pool)
        secondary_ranks = self._rank_secondary(query, candidates, pool)
        field_ranks = self._rank_field(query, candidates, pool)

        rank_lists = [tfidf_ranks]
        modes = ["tfidf"]
        if secondary_ranks:
            rank_lists.append(secondary_ranks)
            modes.append(self.secondary_backend or "secondary")
        if field_ranks:
            rank_lists.append(field_ranks)
            modes.append("field")

        if len(rank_lists) > 1:
            field_weight = float(os.environ.get("RED_ARCHIVE_FIELD_WEIGHT", "0.5"))
            weights = [1.0] * len(rank_lists)
            if field_ranks:
                weights[-1] = field_weight
            # 说明：字段通道是弱信号，默认 0.5 权重参与融合（RED_ARCHIVE_FIELD_WEIGHT 可调）
            fused = self._rrf_fuse(rank_lists, k=self.rrf_k, weights=weights)
            mode = "+".join(modes) + "+rrf"
        else:
            fused = [(idx, float(len(tfidf_ranks) - rank)) for rank, idx in enumerate(tfidf_ranks)]
            mode = "tfidf"

        fused = self._rerank(query, fused, top_k)
        if self.rerank_enabled and self.reranker is not None:
            mode += "+rerank"

        results = []
        for idx, score in fused[:top_k]:
            chunk = self.chunks[idx]
            results.append({
                "chunk_id": idx,
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
