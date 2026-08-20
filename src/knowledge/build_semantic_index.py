# -*- coding: utf-8 -*-
"""
构建第二路检索索引（供 HybridRetriever RRF 融合）
------------------------------------------------
默认使用离线词级 TF-IDF（无需下载模型）；可选 BGE 语义向量。

用法：
    python src/knowledge/build_semantic_index.py
    python src/knowledge/build_semantic_index.py --backend bge
"""
from __future__ import annotations

import json
import pickle
import sys
from datetime import datetime
from pathlib import Path

import numpy as np

SRC_DIR = Path(__file__).resolve().parents[1]
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

PROJECT_DIR = Path(__file__).resolve().parents[2]
INDEX_DIR = PROJECT_DIR / "data" / "index"
DEFAULT_MODEL = "BAAI/bge-small-zh-v1.5"
BATCH_SIZE = 64


def build_word_tfidf_index(chunks: list[dict]) -> None:
    """离线备选：词级 TF-IDF 作为第二路检索。"""
    from scipy.sparse import save_npz
    from sklearn.feature_extraction.text import TfidfVectorizer

    texts = [c["text"] for c in chunks]
    vectorizer = TfidfVectorizer(analyzer="word", ngram_range=(1, 2), max_features=8000)
    embeddings = vectorizer.fit_transform(texts)
    with open(INDEX_DIR / "word_vectorizer.pkl", "wb") as f:
        pickle.dump(vectorizer, f)
    save_npz(INDEX_DIR / "word_embeddings.npz", embeddings)
    meta = {
        "backend": "word_tfidf",
        "model": "sklearn-word-1-2gram",
        "dim": int(embeddings.shape[1]),
        "count": len(texts),
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    (INDEX_DIR / "semantic_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"词级 TF-IDF 索引已写入 {INDEX_DIR}  shape={embeddings.shape}")


def build_bge_index(chunks: list[dict], model_name: str) -> None:
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise SystemExit(
            "缺少 sentence-transformers，请先安装：\n"
            "  python -m pip install sentence-transformers\n"
            f"原始错误: {exc}"
        ) from exc

    texts = [c["text"] for c in chunks]
    print(f"加载 BGE 模型: {model_name}")
    model = SentenceTransformer(model_name)
    embeddings = model.encode(
        texts,
        batch_size=BATCH_SIZE,
        show_progress_bar=True,
        normalize_embeddings=True,
    )
    embeddings = np.asarray(embeddings, dtype=np.float32)
    np.save(INDEX_DIR / "semantic_embeddings.npy", embeddings)
    meta = {
        "backend": "bge",
        "model": model_name,
        "dim": int(embeddings.shape[1]),
        "count": len(texts),
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    (INDEX_DIR / "semantic_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"BGE 索引已写入 semantic_embeddings.npy  shape={embeddings.shape}")


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument(
        "--backend",
        choices=["bge", "word_tfidf"],
        default="word_tfidf",
        help="word_tfidf=离线词级 TF-IDF（默认）；bge=下载语义模型",
    )
    args = parser.parse_args()

    chunks_path = INDEX_DIR / "chunks.json"
    if not chunks_path.exists():
        raise SystemExit("请先运行 python src/knowledge/rebuild_index.py 生成 chunks.json")

    chunks = json.loads(chunks_path.read_text(encoding="utf-8"))
    print(f"加载 {len(chunks)} 个 chunk，backend={args.backend}")

    if args.backend == "word_tfidf":
        build_word_tfidf_index(chunks)
    else:
        build_bge_index(chunks, args.model)


if __name__ == "__main__":
    main()
