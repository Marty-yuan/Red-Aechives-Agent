# -*- coding: utf-8 -*-
"""LLM 调用的共用健壮性封装。

背景：项目当前使用推理类模型（如 deepseek-v4-flash-vision-exp），正式回答前会先产生
reasoning tokens。若 max_tokens 被推理过程耗尽，choices[0].message.content 会是空串且
finish_reason="length"，上层会因此得到空回答，前端只能显示"出错了"。

本模块统一处理：正文为空且因长度截断时，自动放大额度重试一次；仍为空则返回兜底提示，
保证任何链路都不会把空字符串当成"回答"返回给用户。
"""
from typing import Any, Dict, List

# 所有重试都失败时的用户可见兜底，避免前端拿到空字符串
EMPTY_FALLBACK = "抱歉，模型这次没有生成有效内容，请再问一次或换个说法。"


def chat_content(
    client: Any,
    messages: List[Dict[str, str]],
    *,
    model: str,
    temperature: float,
    max_tokens: int,
    retry_factor: float = 1.5,
) -> str:
    """调用 chat.completions 并返回正文文本。

    - 首次使用 ``max_tokens``；
    - 若正文为空且 finish_reason 为 length（推理过程吃光额度），放大额度重试一次；
    - 非长度原因的空内容重试无意义，直接退出；
    - 始终返回非空字符串（最差返回 EMPTY_FALLBACK）。
    """
    enlarged = max(int(max_tokens * retry_factor), max_tokens + 256)
    budgets = [max_tokens, enlarged]
    content = ""
    for idx, budget in enumerate(budgets):
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=budget,
        )
        choice = response.choices[0]
        content = (choice.message.content or "").strip()
        if content:
            return content
        finish_reason = getattr(choice, "finish_reason", "") or ""
        # 只有长度截断才值得放大额度重试；其它情况（内容过滤等）重试无益
        if finish_reason != "length":
            break
    return content or EMPTY_FALLBACK
