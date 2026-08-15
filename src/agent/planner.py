"""
任务规划器
----------
让大模型把用户的复杂问题拆解成工具调用计划。

典型流程：
    用户问题 -> Planner -> [{tool: search_archives, arguments: {...}}, ...]
    -> ToolRegistry 执行 -> Orchestrator 汇总生成最终回答

这个模块是“多智能体 / 智能体任务规划”的核心。
"""
import json
import re
from typing import Any, Dict, List, Optional

from openai import OpenAI

from . import config


class PlannerAgent:
    """负责复杂任务解析与工具调用规划。"""

    def __init__(self, api_key: Optional[str] = None):
        self.client = OpenAI(
            api_key=api_key or config.DEEPSEEK_API_KEY,
            base_url=config.BASE_URL,
        )

    def plan(
        self,
        question: str,
        village: Optional[str],
        tool_specs: List[Dict[str, Any]],
        history: Optional[List[Dict[str, str]]] = None,
    ) -> Dict[str, Any]:
        """
        生成任务计划。

        返回格式：
            {
                "is_complex": True/False,
                "task_type": "archive_qa" | "timeline_analysis" | "route_plan" | "chat",
                "reasoning": "为什么这样规划",
                "steps": [
                    {"tool": "search_archives", "arguments": {...}, "purpose": "..."}
                ]
            }
        """
        history_text = ""
        if history:
            recent = history[-6:]
            history_text = "\n".join(
                f"{'用户' if h['role'] == 'user' else '助手'}：{h['content']}" for h in recent
            )

        tools_json = json.dumps(tool_specs, ensure_ascii=False, indent=2)

        system_prompt = (
            "你是云南红军长征档案智能体的任务规划器。\n"
            "你的职责是判断用户问题是否复杂，并把复杂任务拆解成可执行工具步骤。\n\n"
            "可用工具如下：\n" + tools_json + "\n\n"
            "输出必须是合法 JSON，不要输出 Markdown 代码块。\n"
            "JSON 格式：\n"
            "{\n"
            '  "is_complex": true,\n'
            '  "task_type": "archive_qa",\n'
            '  "reasoning": "简短说明规划理由",\n'
            '  "steps": [\n'
            '    {"tool": "search_archives", "arguments": {"query": "..."}, "purpose": "..."}\n'
            "  ]\n"
            "}\n\n"
            "规则：\n"
            "1. 普通寒暄、自我介绍、追问且不需要查档案时，is_complex=false，steps=[]。\n"
            "2. 历史事实问题优先调用 search_archives。\n"
            "3. 涉及时间顺序、年份、路线，可调用 query_timeline 或 get_route。\n"
            "4. 涉及某个具体村寨，可先调用 get_village_profile。\n"
            "5. 涉及人物、部队、地点、事件之间的关系，优先调用 query_knowledge_graph；\n"
            "   如果需要了解图谱可查询范围，可调用 list_graph_nodes。\n"
            "6. 复杂问题可以包含多个步骤，步骤顺序要合理。\n"
            "7. arguments 中的 query 要尽量把用户意图写完整。\n"
        )

        user_prompt = (
            f"当前村寨：{village or '未指定'}\n"
            f"最近对话：\n{history_text or '无'}\n\n"
            f"用户当前问题：{question}\n\n"
            "请输出 JSON 计划。"
        )

        try:
            response = self.client.chat.completions.create(
                model=config.MODEL_NAME,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.1,
                max_tokens=800,
                response_format={"type": "json_object"},
            )
            content = response.choices[0].message.content or "{}"
            return self._parse_json(content)
        except Exception:
            return {
                "is_complex": False,
                "task_type": "chat",
                "reasoning": "Planner 解析失败，回退为普通对话",
                "steps": [],
            }

    @staticmethod
    def _parse_json(content: str) -> Dict[str, Any]:
        """稳健解析 LLM 返回的 JSON。"""
        content = content.strip()
        # 去掉可能的 Markdown 代码块
        content = re.sub(r"^```(?:json)?\s*", "", content)
        content = re.sub(r"\s*```$", "", content)

        try:
            data = json.loads(content)
        except Exception:
            # 再尝试截取第一个 { 到最后一个 }
            start = content.find("{")
            end = content.rfind("}")
            if start == -1 or end == -1:
                raise
            data = json.loads(content[start:end + 1])

        steps = data.get("steps") or []
        if not isinstance(steps, list):
            steps = []

        return {
            "is_complex": bool(data.get("is_complex", False)),
            "task_type": data.get("task_type", "chat"),
            "reasoning": data.get("reasoning", ""),
            "steps": steps,
        }