# -*- coding: utf-8 -*-
"""memory_v2.MemoryManager 单元测试：短期窗口、LLM 摘要压缩、相关性召回。"""
from types import SimpleNamespace

from agent.memory_v2 import MemoryManager


def _fake_llm(summary: str = "用户反复询问皎平渡船工与渡江细节。"):
    """构造一个只返回固定摘要的假 OpenAI 客户端，避免测试发起网络请求。"""

    def _create(**kwargs):
        message = SimpleNamespace(content=summary)
        choice = SimpleNamespace(message=message)
        return SimpleNamespace(choices=[choice])

    completions = SimpleNamespace(create=_create)
    chat = SimpleNamespace(completions=completions)
    return SimpleNamespace(chat=chat)


def test_short_history_window_without_llm():
    """没有 LLM 客户端时只保留短期原话，不报错也不产生长期摘要。"""
    mm = MemoryManager()
    for i in range(5):
        mm.add_turn("扎西", "user", f"问题{i}")
        mm.add_turn("扎西", "assistant", f"回答{i}")

    # short_history 默认只回最近 8 条，这里直接检查内部短期缓存为 10 条
    assert len(mm.short["guest::扎西"]) == 10
    assert mm.build_context("扎西", "问题") == ""


def test_overflow_triggers_llm_summary():
    """超过短期窗口后，最早的轮次被压缩为长期摘要，短期窗口被裁剪。"""
    mm = MemoryManager(llm_client=_fake_llm(), model="fake-model")
    key = "guest::扎西"
    for i in range(10):
        mm.add_turn("扎西", "user", f"第{i}个问题，关于船工")
        mm.add_turn("扎西", "assistant", f"第{i}个回答")

    assert len(mm.long[key]) >= 1
    # 摘要批次被移出短期窗口
    assert len(mm.short[key]) < 20


def test_build_context_recalls_relevant_summary():
    """build_context 只召回与当前问题关键词相关的长期摘要。"""
    mm = MemoryManager(llm_client=_fake_llm(), model="fake-model")
    for i in range(10):
        mm.add_turn("皎平渡", "user", f"船工问题{i}")
        mm.add_turn("皎平渡", "assistant", f"回答{i}")

    ctx = mm.build_context("皎平渡", "船工是谁", top_k=2)
    assert "长期记忆摘要" in ctx
    # 完全不相关的问题不回注
    assert mm.build_context("皎平渡", "天气怎么样", top_k=2) == ""


def test_user_isolation_by_user_id():
    """不同用户的长期记忆按键隔离，互不串扰。"""
    mm = MemoryManager(llm_client=_fake_llm(), model="fake-model")
    for i in range(10):
        mm.add_turn("扎西", "user", f"甲的问题{i}", user_id="user_a")
        mm.add_turn("扎西", "assistant", f"甲的回答{i}", user_id="user_a")

    assert "user_a::扎西" in mm.long
    assert "user_b::扎西" not in mm.long
