# -*- coding: utf-8 -*-
"""检索器工厂单元测试"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from agent.retriever_factory import create_retriever


def test_create_retriever_returns_results():
    ret = create_retriever()
    results = ret.search("扎西会议", top_k=3)
    assert len(results) >= 1
    assert "text" in results[0]
    assert "source" in results[0]
