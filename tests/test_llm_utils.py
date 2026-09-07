# -*- coding: utf-8 -*-
"""llm_utils 健壮性封装测试：用桩 client 模拟推理模型空正文/长度截断，不打真实网络。"""
from agent import llm_utils


class _Message:
    def __init__(self, content):
        self.content = content


class _Choice:
    def __init__(self, content, finish_reason):
        self.message = _Message(content)
        self.finish_reason = finish_reason


class _Response:
    def __init__(self, content, finish_reason):
        self.choices = [_Choice(content, finish_reason)]


class _Completions:
    """按调用顺序依次返回预设响应，并记录每次的 max_tokens。"""

    def __init__(self, scripted):
        self._scripted = scripted
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        content, finish = self._scripted[min(len(self.calls) - 1, len(self._scripted) - 1)]
        return _Response(content, finish)


class _FakeClient:
    def __init__(self, scripted):
        self.chat = type("_Chat", (), {"completions": _Completions(scripted)})()


def _messages():
    return [{"role": "user", "content": "hi"}]


def test_first_empty_length_then_succeeds_retries_with_bigger_budget():
    client = _FakeClient([("", "length"), ("有效回答", "stop")])
    out = llm_utils.chat_content(
        client, _messages(), model="m", temperature=0.0, max_tokens=100
    )
    assert out == "有效回答"
    # 第一次 100；第二次放大 = max(int(100*1.5), 100+256) = 356
    assert client.chat.completions.calls[0]["max_tokens"] == 100
    assert client.chat.completions.calls[1]["max_tokens"] == 356


def test_always_empty_returns_nonempty_fallback():
    client = _FakeClient([("", "length"), ("", "length")])
    out = llm_utils.chat_content(
        client, _messages(), model="m", temperature=0.0, max_tokens=100
    )
    assert out == llm_utils.EMPTY_FALLBACK
    assert out.strip()


def test_non_length_empty_does_not_retry():
    client = _FakeClient([("", "content_filter")])
    out = llm_utils.chat_content(
        client, _messages(), model="m", temperature=0.0, max_tokens=100
    )
    assert out == llm_utils.EMPTY_FALLBACK
    # 非长度截断只调用一次，不做无意义重试
    assert len(client.chat.completions.calls) == 1


def test_normal_answer_no_retry():
    client = _FakeClient([("一次成功", "stop")])
    out = llm_utils.chat_content(
        client, _messages(), model="m", temperature=0.0, max_tokens=100
    )
    assert out == "一次成功"
    assert len(client.chat.completions.calls) == 1
