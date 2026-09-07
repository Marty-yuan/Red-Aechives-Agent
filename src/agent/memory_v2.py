"""
记忆升级 MVP：摘要压缩 + 检索回注
=================================
- 短期：保留最近 N 轮原话（与现版本一致）
- 长期：当历史超过 N 轮，用 LLM 把"较早"的轮次摘要成 2-3 句"用户画像/事实"，存入用户画像
- 检索：新问题到来时，从长期记忆中用关键词/jaccard 召回相关摘要，注入 prompt
- 设计为可选升级，默认不启用（与现版本兼容）

使用：
    from agent.memory_v2 import MemoryManager
    mm = MemoryManager()
    mm.add_turn("皎平渡", "user", "皎平渡用了几条船？")
    mm.add_turn("皎平渡", "assistant", "档案记载六条木船…")
    ...
    ctx = mm.build_context("皎平渡", "船工是谁？", top_k=2)
    # ctx: relevant long-term summaries, to inject into prompt
"""
from __future__ import annotations
import re
from typing import List, Dict, Optional
from collections import defaultdict


def _lexical_tokens(text: str) -> set:
    """把文本切成用于相似度计算的 token 集合。

    中文没有空格，若按整段连续汉字切，整句只会得到一个 token，词面重叠恒为 0。
    这里与项目字符级检索（char 2-4 gram）保持同一思路：中文按字 bigram 切分，
    英文/数字按词切分并小写，无需引入 jieba 等额外依赖。
    """
    tokens = set()
    for segment in re.findall(r"[一-鿿]+|[A-Za-z0-9]+", text or ""):
        if re.match(r"[一-鿿]", segment):
            if len(segment) == 1:
                tokens.add(segment)
            else:
                tokens.update(segment[i:i + 2] for i in range(len(segment) - 1))
        else:
            tokens.add(segment.lower())
    return tokens


def _jaccard(a: str, b: str) -> float:
    sa = _lexical_tokens(a)
    sb = _lexical_tokens(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


class MemoryManager:
    """Long-term memory via LLM-summarized turns + keyword retrieval.

    Keeps per-village, per-user (or anonymous) two stores:
      short: list[dict(role, content)]   last K turns verbatim
      long:  list[str]                   summarized older turns
    """

    SHORT_LIMIT = 8          # keep last 8 turns verbatim
    SUMMARIZE_THRESHOLD = 8  # when short > threshold, summarize oldest
    SUMMARY_BATCH = 6        # summarize this many oldest at a time

    def __init__(self, llm_client=None, model: Optional[str] = None):
        self.client = llm_client
        self.model = model
        self.short: Dict[str, List[dict]] = defaultdict(list)
        self.long: Dict[str, List[str]] = defaultdict(list)

    def _key(self, village: str, user_id: Optional[str]) -> str:
        return f"{user_id or 'guest'}::{village}"

    def add_turn(self, village: str, role: str, content: str,
                 user_id: Optional[str] = None) -> None:
        k = self._key(village, user_id)
        self.short[k].append({"role": role, "content": content})
        if len(self.short[k]) > self.SHORT_LIMIT:
            self._maybe_summarize(k)

    def _maybe_summarize(self, k: str) -> None:
        if not self.client or not self.model:
            return  # no LLM available, skip
        short = self.short[k]
        if len(short) <= self.SUMMARIZE_THRESHOLD:
            return
        batch = short[: self.SUMMARY_BATCH]
        text = "\n".join(f"{t['role']}: {t['content']}" for t in batch)
        prompt = (
            "请把以下对话压缩成 2-3 句中文摘要，保留用户偏好、关键事实、待解决问题：\n"
            f"{text}\n---\n摘要："
        )
        try:
            r = self.client.chat.completions.create(
                # 推理模型会先消耗 reasoning tokens，200 会导致摘要为空，放宽到 700
                model=self.model, temperature=0.0, max_tokens=700,
                messages=[{"role": "user", "content": prompt}],
            )
            summary = (r.choices[0].message.content or "").strip()
            if summary:
                self.long[k].append(summary)
                self.short[k] = short[self.SUMMARY_BATCH:]
        except Exception:
            pass  # degrade gracefully

    def build_context(self, village: str, query: str,
                      user_id: Optional[str] = None, top_k: int = 2) -> str:
        """Return relevant long-term summaries to inject into the prompt."""
        k = self._key(village, user_id)
        mems = self.long.get(k, [])
        if not mems:
            return ""
        scored = sorted(((m, _jaccard(query, m)) for m in mems),
                        key=lambda x: -x[1])
        # 字 bigram 下，命中一个两字关键词的相似度约 0.03-0.06，
        # 阈值过严会漏掉最常见的"单关键词相关"，故取 0.03，并用 top_k 控制噪声。
        top = [m for m, s in scored[:top_k] if s >= 0.03]
        if not top:
            return ""
        return "【长期记忆摘要】\n" + "\n".join(f"- {m}" for m in top)

    def short_history(self, village: str, user_id: Optional[str] = None,
                      limit: Optional[int] = None) -> List[dict]:
        k = self._key(village, user_id)
        limit = limit or self.SHORT_LIMIT
        return self.short.get(k, [])[-limit:]


# ---- demo / self-test ----
if __name__ == "__main__":
    mm = MemoryManager()
    mm.add_turn("皎平渡", "user", "皎平渡用了几条船？")
    mm.add_turn("皎平渡", "assistant", "档案记载六条木船。")
    mm.add_turn("皎平渡", "user", "船工是哪里人？")
    mm.add_turn("皎平渡", "assistant", "多为附近村民，如张朝满等。")
    print("short:", len(mm.short_history("皎平渡")))
    print("ctx for '船工':", mm.build_context("皎平渡", "船工是谁"))
