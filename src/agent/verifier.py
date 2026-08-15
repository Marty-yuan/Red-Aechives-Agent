"""
事实校验 Agent
---------------
在最终回答生成后，对回答中的日期、数字、人名、地名、部队番号等
关键事实进行二次校验，避免“会说但不可信”。

校验流程：
    回答草稿 + 工具结果/档案证据 -> 校验 Agent -> 修正后的回答 + 问题清单
"""
import json
import re
from typing import Any, Dict, List, Optional

from openai import OpenAI

from . import config


class FactCheckerAgent:
    """对回答中的关键事实进行证据核对。"""

    def __init__(self, api_key: Optional[str] = None):
        self.client = OpenAI(
            api_key=api_key or config.DEEPSEEK_API_KEY,
            base_url=config.BASE_URL,
        )

    def verify(
        self,
        question: str,
        draft_answer: str,
        evidence_text: str,
    ) -> Dict[str, Any]:
        """
        校验回答草稿。

        返回:
            {
                "verified": True/False,
                "confidence": 0.0-1.0,
                "issues": [
                    {"claim": "...", "evidence": "...", "severity": "high/medium/low"}
                ],
                "revised_answer": "修正后的最终回答"
            }
        """
        evidence_text = (evidence_text or "").strip()
        if not evidence_text:
            return {
                "verified": None,
                "confidence": 0.0,
                "issues": [{"claim": "没有可用证据", "evidence": "无", "severity": "high"}],
                "revised_answer": draft_answer,
            }

        system_prompt = (
            "你是云南红军长征档案智能体的事实校验员。\n"
            "你的任务是检查回答中的关键历史事实是否有证据支持。\n\n"
            "关键事实包括：日期、年份、数字、人名、地名、部队番号、战斗名称、会议名称。\n"
            "注意：路线建议、语气词、寒暄不属于关键事实，不要误报。\n\n"
            "请输出严格 JSON，不要输出 Markdown。格式：\n"
            "{\n"
            '  "verified": true,\n'
            '  "confidence": 0.9,\n'
            '  "issues": [\n'
            '    {"claim": "有问题的表述", "evidence": "支持或不支持的证据", "severity": "high"}\n'
            "  ],\n"
            '  "revised_answer": "修正后的完整回答"\n'
            "}\n\n"
            "规则：\n"
            "规则：\n"
            "1. 工具结果和证据是权威材料，不要因为表述不同就误判为无证据。\n"
            "2. 只有与证据冲突，或明显是证据中没有的具体日期、数字、人名、部队番号，才标记问题。\n"
            "3. 对一般性总结、路线概述、研学建议，不要过度标记。\n"
            "4. 如果整体可靠，revised_answer 应基本保留原回答，不要删成空泛话。\n"
            "5. 对未证实的高风险事实，可改为“档案未明确记载”，但不要把已由路线/时间轴支持的正常地点也删掉。\n"
        )

        user_prompt = (
            f"用户问题：{question}\n\n"
            f"回答草稿：\n{draft_answer}\n\n"
            f"可用证据：\n{evidence_text}\n\n"
            "请输出校验 JSON。"
        )

        try:
            response = self.client.chat.completions.create(
                model=config.MODEL_NAME,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.0,
                max_tokens=1200,
                response_format={"type": "json_object"},
            )
            content = response.choices[0].message.content or "{}"
            return self._parse_json(content, draft_answer)
        except Exception:
            return {
                "verified": None,
                "confidence": 0.0,
                "issues": [{"claim": "校验器不可用", "evidence": "无", "severity": "low"}],
                "revised_answer": draft_answer,
            }

    @staticmethod
    def _parse_json(content: str, draft_answer: str) -> Dict[str, Any]:
        """稳健解析校验器返回的 JSON。"""
        content = content.strip()
        content = re.sub(r"^```(?:json)?\s*", "", content)
        content = re.sub(r"\s*```$", "", content)

        try:
            data = json.loads(content)
        except Exception:
            start = content.find("{")
            end = content.rfind("}")
            if start == -1 or end == -1:
                raise
            data = json.loads(content[start:end + 1])

        issues = data.get("issues") or []
        if not isinstance(issues, list):
            issues = []

        revised = data.get("revised_answer") or draft_answer
        if not isinstance(revised, str) or not revised.strip():
            revised = draft_answer

        return {
            "verified": bool(data.get("verified", False)),
            "confidence": float(data.get("confidence", 0.0)),
            "issues": issues,
            "revised_answer": revised,
        }
