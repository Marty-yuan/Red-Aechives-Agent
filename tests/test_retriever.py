# -*- coding: utf-8 -*-
"""检索器单元测试（依赖本地 data/index 索引）"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from agent.retriever import ArchiveRetriever


def test_retriever_loads():
    ret = ArchiveRetriever()
    assert len(ret.chunks) > 1000
    assert ret.vectorizer is not None


def test_search_structure():
    ret = ArchiveRetriever()
    results = ret.search("扎西会议", top_k=3)
    assert len(results) <= 3
    for r in results:
        assert "text" in r
        assert "source" in r
        assert "score" in r
        assert "offset" in r


def test_search_village_filter():
    ret = ArchiveRetriever()
    results = ret.search("巧渡金沙江", village="皎平渡", top_k=5)
    for r in results:
        assert r["score"] >= 0


def test_search_traceability_fields():
    """溯源字段：section/page/confidence 应存在（可能为 None）"""
    ret = ArchiveRetriever()
    results = ret.search("巧渡金沙江 皎平渡", top_k=3)
    for r in results:
        assert "section" in r
        assert "page" in r
        assert "confidence" in r
        assert r["confidence"] in ("exact", "approx", None)
