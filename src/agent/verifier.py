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
            "你是云南红军长征档案智能体的事实校验员，职责是把回答中每一条关键历史事实逐条与给出的证据核对。\n\n"
            "【关键事实类型】日期/年份、数字/人数/数量、人名、地名、部队番号、战斗名称、会议名称。\n"
            "【非关键事实，忽略】游览路线建议、交通时长、食宿推荐、当地小吃、语气词、寒暄、一般性总结、"
            "人物评价/角色定位（如「XX是核心人物」）等不可直接核对的表述。\n\n"
            "必须输出一个 claims 数组，把回答中所有关键硬事实逐条列出（宁可多列，不可漏列；"
            "包括句末括号补充句里的事实）。每条给出：\n"
            "  claim    —— 事实原文（尽量保留原句）\n"
            "  status   —— supported（证据有对应，可同义/近义/数字等价）| unsupported（证据完全没有）| contradicted（证据冲突）\n"
            "  evidence —— 证据中的对应原文；若没有，写“证据中无此信息”\n"
            "  severity —— contradicted 或 unsupported 的日期/年份/数字/人数/番号/人名/战斗名/会议名 记 high；"
            "unsupported 的普通地名/边缘细节记 medium；supported 记 none\n\n"
            "判定依据（极重要）：你只能以「给出的证据」为唯一依据，禁止使用你自己的历史知识，"
            "禁止假设「证据可能不完整，所以该事实也许是对的」。凡是无法在证据里找到对应表述的硬事实，"
            "一律记 unsupported，不要放过。\n"
            "【OCR 容忍】证据来自扫描件 OCR，可能有错字、异体字、繁简差异（如「皎平渡」可能被 OCR 成"
            "「绞平渡/绞车渡」，「金沙江」可能成「金沙汪」）。比对时先做字形/同音近似判断：若证据中出现"
            "高度相似的词，视为同一事实（supported），不要仅因 OCR 字形差异就判 unsupported。\n"
            "铁律：任何具体日期、数字、人名、番号，只要证据里找不到，就必须进 claims 并记 unsupported/high；"
            "但不要把导览/食宿内容当问题凑数。\n"
            "特别注意：回答末尾或中间的括号补充句（含「据传/据记载/考证/言/述/闻/云/提/载/注/补充」等引导词）里的事实，"
            "同样要进 claims 核对，不要因为「与问题主体不同话题」或「有据传前缀」就跳过。\n\n"
            "输出严格 JSON（不要 Markdown 代码块，不要输出 confidence 字段）：\n"
            "{\n"
            '  "claims": [\n'
            '    {"claim": "事实原文", "status": "unsupported", "evidence": "证据中无此信息", "severity": "high"}\n'
            "  ],\n"
            '  "revised_answer": "修正后的完整回答（删除或改写被标记的错误事实）"\n'
            "}\n"
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
                # deepseek-v4-flash 为推理模型：reasoning tokens 与正文共享额度，
                # 额度不足会出现「正文为空 / JSON 被截断」→ 校验失效，故放宽到 8000。
                max_tokens=8000,
            )
            content = response.choices[0].message.content or "{}"
            try:
                return self._parse_json(content, draft_answer)
            except Exception:
                # 模型偶发输出非法 JSON：用一次修复重试兜底，避免整条校验作废。
                repair_user = (
                    "你上一条输出不是合法 JSON，解析失败。请只输出「严格合法」的 JSON，"
                    "字符串内的引号必须转义、不要有裸换行，不要输出任何解释文字。\n\n"
                    "上次输出：\n" + content[:6000]
                )
                retry = self.client.chat.completions.create(
                    model=config.MODEL_NAME,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": repair_user},
                    ],
                    temperature=0.0,
                    max_tokens=8000,
                )
                content2 = retry.choices[0].message.content or "{}"
                return self._parse_json(content2, draft_answer)
        except Exception as exc:
            import sys
            print(f"[fact-checker] unavailable: {type(exc).__name__}: {exc}", file=sys.stderr)
            return {
                "verified": None,
                "confidence": None,
                "issues": [{"claim": "自动事实校验暂时不可用，本轮未修改回答", "evidence": "无", "severity": "low", "kind": "checker_unavailable"}],
                "revised_answer": draft_answer,
            }

    @staticmethod
    def _parse_json(content: str, draft_answer: str) -> Dict[str, Any]:
        """稳健解析校验器返回的 JSON。"""
        content = content.strip()
        content = re.sub(r"^```(?:json)?\s*", "", content)
        content = re.sub(r"\s*```$", "", content)

        try:
            data = json.loads(content, strict=False)
        except Exception:
            start = content.find("{")
            end = content.rfind("}")
            if start == -1 or end == -1:
                raise
            data = json.loads(content[start:end + 1], strict=False)

        # 从 claims 派生 issues（模型必须逐条列出硬事实，无法静默略过）
        claims = data.get("claims") or []
        if not isinstance(claims, list):
            claims = []

        issues = []
        for c in claims:
            if not isinstance(c, dict):
                continue
            st = str(c.get("status") or "").strip().lower()
            if st not in ("unsupported", "contradicted"):
                continue
            sev = str(c.get("severity") or "").strip().lower()
            if st == "contradicted":
                sev = "high"
            elif sev not in ("high", "medium", "low"):
                sev = "medium"
            issues.append({
                "claim": c.get("claim", ""),
                "evidence": c.get("evidence", ""),
                "severity": sev,
                "status": st,
            })

        # 兼容模型直接返回 issues 的旧格式
        raw_issues = data.get("issues") or []
        if isinstance(raw_issues, list):
            for i in raw_issues:
                if isinstance(i, dict):
                    issues.append(i)

        revised = data.get("revised_answer") or draft_answer
        if not isinstance(revised, str) or not revised.strip():
            revised = draft_answer

        # 置信度与 verified 一律由 issues 反推，不信任模型自报值，避免“自信但错”。
        high = any(isinstance(i, dict) and i.get("severity") == "high" for i in issues)
        medium = any(isinstance(i, dict) and i.get("severity") == "medium" for i in issues)
        low = any(isinstance(i, dict) and i.get("severity") == "low" for i in issues)

        if high:
            confidence = 0.35
        elif medium:
            confidence = 0.60
        elif low:
            confidence = 0.80
        else:
            confidence = 0.90

        return {
            "verified": not high,
            "confidence": round(confidence, 2),
            "issues": issues,
            "revised_answer": revised,
        }
