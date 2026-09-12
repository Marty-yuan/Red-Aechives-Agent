# -*- coding: utf-8 -*-
"""
构建字段通道索引（结构化上下文）
--------------------------------
用"档案名 + 篇目 + 村寨"等结构化元数据建立字符 TF-IDF 索引，作为第三路
检索通道参与 RRF 融合——替代此前"把 LLM 生成的前缀拼进正文"的上下文检索
（该方案在 60 题关键词式提问上实测无收益）。

输出：
    data/index/field_vectorizer.pkl
    data/index/field_embeddings.npz

用法：
    python scripts/build_field_index.py
"""
from __future__ import annotations

import json
import pickle
import re
import sys
from pathlib import Path

import numpy as np
from scipy.sparse import save_npz
from sklearn.feature_extraction.text import TfidfVectorizer

ROOT = Path(__file__).resolve().parents[1]
INDEX_DIR = ROOT / "data" / "index"


def book_title(source: str) -> str:
    """从 OCR 文件名中提取书名（去掉来源/版本等噪声后缀）。"""
    stem = Path(source or "").stem
    stem = re.split(r"\s--\s|\(z-lib|（z-lib|z-library|Anna", stem)[0]
    return stem.strip()


def build_field_text(chunk: dict) -> str:
    parts = [book_title(chunk.get("source", ""))]
    section = chunk.get("section")
    if section:
        parts.append(section)
    locations = chunk.get("locations") or []
    if locations:
        parts.append(" ".join(locations))
    return " ".join(p for p in parts if p)


def main() -> None:
    chunks_path = INDEX_DIR / "chunks.json"
    if not chunks_path.exists():
        raise SystemExit("请先运行 src/knowledge/rebuild_index.py 生成 chunks.json")

    chunks = json.loads(chunks_path.read_text(encoding="utf-8"))
    fields = [build_field_text(c) for c in chunks]
    with_section = sum(1 for c in chunks if c.get("section"))
    print(f"加载 {len(chunks)} 个 chunk（其中 {with_section} 个有篇目标注）")

    vectorizer = TfidfVectorizer(
        max_features=2000, sublinear_tf=True, analyzer="char_wb", ngram_range=(2, 4)
    )
    X = vectorizer.fit_transform(fields)
    print(f"字段向量: {X.shape}")

    with open(INDEX_DIR / "field_vectorizer.pkl", "wb") as f:
        pickle.dump(vectorizer, f)
    save_npz(INDEX_DIR / "field_embeddings.npz", X)

    sample = fields[0][:80] if fields else ""
    print(f"字段示例: {sample}")
    print(f"完成 -> {INDEX_DIR}")


if __name__ == "__main__":
    main()
