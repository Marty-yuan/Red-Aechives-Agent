"""
档案检索器
----------
从已构建的 TF-IDF 索引中，根据用户问题检索最相关的档案文本块。

工作流程：
    1. 加载索引文件（chunks.json、vectorizer.pkl、embeddings.npz）
    2. 将用户问题向量化
    3. 计算问题与所有文本块的余弦相似度
    4. 返回最相关的 Top-K 个文本块

检索策略：
    - 优先在指定村寨的文本块中检索
    - 若村寨文本块太少（OCR 地名识别不全），自动回退到全库检索
"""
import os, json, pickle
import numpy as np
from scipy.sparse import load_npz
from sklearn.metrics.pairwise import cosine_similarity

from . import config


class ArchiveRetriever:
    """档案检索器：负责从索引中找出与问题最相关的档案片段"""

    def __init__(self, index_dir: str = None):
        """初始化检索器，加载索引文件"""
        self.index_dir = index_dir or config.INDEX_DIR

        with open(os.path.join(self.index_dir, "chunks.json"), "r", encoding="utf-8") as f:
            self.chunks = json.load(f)
        with open(os.path.join(self.index_dir, "vectorizer.pkl"), "rb") as f:
            self.vectorizer = pickle.load(f)
        self.embeddings = load_npz(os.path.join(self.index_dir, "embeddings.npz"))
        with open(os.path.join(self.index_dir, "village_index.json"), "r", encoding="utf-8") as f:
            self.village_index = json.load(f)

    def search(self, query: str, village: str = None, top_k: int = None) -> list:
        """
        检索与问题最相关的档案文本块。

        参数:
            query:   用户的问题
            village: 可选，限定在某个村寨的档案中检索
            top_k:   返回的文本块数量，默认用 config.TOP_K

        返回:
            列表，每项是一个 dict，包含 text / locations / source / score
        """
        top_k = top_k or config.TOP_K

        # 将问题转为向量
        query_vec = self.vectorizer.transform([query])

        # 计算与所有文本块的余弦相似度
        similarities = cosine_similarity(query_vec, self.embeddings)[0]

        # 判断是否走村寨过滤
        # 关键改进：如果某村寨的文本块太少（<20个），说明 OCR 地名识别不全，
        # 此时回退到全库检索，避免"检索不到"的问题
        MIN_VILLAGE_CHUNKS = 20
        use_village_filter = (
            village is not None
            and village in self.village_index
            and len(self.village_index[village]) >= MIN_VILLAGE_CHUNKS
        )

        if use_village_filter:
            candidate_indices = self.village_index[village]
            ranked = sorted(
                [(i, similarities[i]) for i in candidate_indices],
                key=lambda x: x[1],
                reverse=True
            )
        else:
            # 全库检索
            ranked = sorted(enumerate(similarities), key=lambda x: x[1], reverse=True)

        # 过滤低分结果并取 Top-K
        results = []
        for idx, score in ranked[:top_k]:
            if score < config.MIN_SCORE:
                continue
            chunk = self.chunks[idx]
            results.append({
                "text": chunk["text"],
                "locations": chunk.get("locations", []),
                "source": chunk.get("source", "未知档案"),
                "score": float(score),
            })

        return results