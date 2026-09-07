"""
智能体编排器
------------
把 Planner、ToolRegistry 和最终生成器串起来：

    用户复杂问题
        -> Planner 生成工具计划
        -> ToolRegistry 逐步执行
        -> 汇总工具结果
        -> 大模型生成最终回答

普通聊天和简单问答不会进入这个流程，而是回退到原有 RAG 问答，
这样可以兼顾“复杂任务规划”和“日常聊天体验”。
"""
import json
import re
from typing import Any, Dict, List, Optional

from openai import OpenAI

from . import config
from . import llm_utils
from . import study_course
from .knowledge import DEPARTURE_CITIES, VILLAGE_COORDS
from .personas import build_system_prompt
from .planner import PlannerAgent
from .retriever_factory import create_retriever
from .tools import ToolRegistry
from .verifier import FactCheckerAgent

# 这些关键词出现时，才尝试走复杂任务规划，避免每句话都多调用一次 Planner
COMPLEX_HINTS = [
    "路线", "规划", "几天", "研学", "行程", "安排", "先后", "顺序",
    "旅游", "线路",
    "对比", "比较", "不同", "区别", "差异", "哪些", "时间线", "时间轴", "经过", "推荐", "怎么走",
    "从", "到", "每天", "第一站", "第二站",
    "课程", "教案", "课时", "备课", "课程包", "研学手册",
]

# 旅游/研学路线兜底：即使 Planner 没调用，也保证前端有路线卡片
ROUTE_TOOL_HINTS = ["旅游", "研学", "路线", "行程", "规划", "几天", "怎么走", "推荐", "线路"]

# 村寨对比兜底：只要命中对比类词，并且能识别出两个村寨，就生成对比卡片
COMPARE_TOOL_HINTS = ["对比", "比较", "不同", "区别", "差异"]

# 课程包意图词：命中即必须走 generate_course_pack（Planner 可能被"研学"误导，用规则兜底纠偏）
COURSE_INTENT_HINTS = ("课程包", "课程方案", "课程表", "课程设计", "研学课程", "教案", "课时", "备课", "研学手册")


class OrchestratorAgent:
    """负责任务规划、工具调用和结果汇总。"""

    def __init__(self, api_key: Optional[str] = None, retriever=None):
        self.client = OpenAI(
            api_key=api_key or config.DEEPSEEK_API_KEY,
            base_url=config.BASE_URL,
        )
        self.retriever = retriever or create_retriever()
        self.tools = ToolRegistry(self.retriever, llm_client=self.client)
        self.planner = PlannerAgent(api_key=api_key)
        self.fact_checker = FactCheckerAgent(api_key=api_key)

    def should_plan(self, question: str) -> bool:
        """用轻量规则判断是否值得进入复杂任务规划。"""
        return any(hint in question for hint in COMPLEX_HINTS)

    def run(
        self,
        question: str,
        village: Optional[str],
        history: Optional[List[Dict[str, str]]] = None,
        persona_mode: str = "tourist",
        user_profile: Optional[Dict[str, Any]] = None,
        memory_context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """尝试处理复杂任务；如果不需要规划，返回 handled=False。

        memory_context: memory_v2 召回的长期记忆摘要，透传给最终回答生成。
        """
        compare_hit = any(hint in question for hint in COMPARE_TOOL_HINTS)
        compare_villages = [name for name in VILLAGE_COORDS if name in question]
        compare_villages.sort(key=lambda name: question.find(name))

        if compare_hit and len(compare_villages) >= 2:
            args = {"village_a": compare_villages[0], "village_b": compare_villages[1]}
            result = self.tools.execute("compare_villages", args)
            compare_plan = {
                "is_complex": True,
                "task_type": "village_compare",
                "reasoning": "用户要求对比两个村寨，自动生成对比结果。",
                "steps": [
                    {"tool": "compare_villages", "arguments": args, "purpose": "对比两个村寨的历史事件、部队、年份和知识图谱关系"}
                ],
            }
            tool_results = [
                {"tool": "compare_villages", "purpose": "对比两个村寨", "arguments": args, "result": result}
            ]
            draft_answer = self._generate_answer(
                question, village, compare_plan, tool_results, persona_mode,
                user_profile, memory_context=memory_context,
            )
            evidence_text = self._format_tool_results(tool_results)
            verification = self.fact_checker.verify(question, draft_answer, evidence_text)
            answer = verification.get("revised_answer") or draft_answer
            return {
                "handled": True,
                "plan": compare_plan,
                "tool_results": tool_results,
                "verification": verification,
                "answer": answer,
            }

        if not self.should_plan(question):
            return {"handled": False}

        plan = self.planner.plan(
            question=question,
            village=village,
            tool_specs=self.tools.tool_specs(),
            history=history,
        )
        # 确定性纠偏：课程类意图必须走课程包工具，防止被"研学"字样误导成红旅路线
        plan = self._enforce_course_pack(question, plan)

        route_hit = any(hint in question for hint in ROUTE_TOOL_HINTS)
        if route_hit and (not plan.get("is_complex") or not plan.get("steps")):
            route_villages = [name for name in VILLAGE_COORDS if name in question]
            route_days = self._extract_days(question)
            route_args = self._make_route_args(route_villages, route_days, question)
            result = self.tools.execute("generate_study_route", route_args)
            route_plan = {
                "is_complex": True,
                "task_type": "route_plan",
                "reasoning": "用户请求旅游或红旅路线，Planner 未给出可用步骤，自动生成路线。",
                "steps": [
                    {
                        "tool": "generate_study_route",
                        "arguments": route_args,
                        "purpose": "自动生成红旅路线",
                    }
                ],
            }
            tool_results = [
                {
                    "tool": "generate_study_route",
                    "purpose": "自动生成红旅路线",
                    "arguments": route_args,
                    "result": result,
                }
            ]
            draft_answer = self._generate_answer(
            question, village, route_plan, tool_results, persona_mode,
            user_profile, memory_context=memory_context,
        )
            evidence_text = self._format_tool_results(tool_results)
            verification = self.fact_checker.verify(question, draft_answer, evidence_text)
            answer = verification.get("revised_answer") or draft_answer
            return {
                "handled": True,
                "plan": route_plan,
                "tool_results": tool_results,
                "verification": verification,
                "answer": answer,
            }

        if not plan.get("is_complex") or not plan.get("steps"):
            return {
                "handled": False,
                "plan": plan,
            }

        # 逐步执行工具
        tool_results = []
        for step in plan["steps"]:
            tool_name = step.get("tool", "")
            arguments = step.get("arguments") or {}
            purpose = step.get("purpose", "")
            if tool_name == "generate_study_route":
                arguments = {**self._infer_route_preferences(question), **arguments}
            elif tool_name == "generate_course_pack":
                # Planner 没显式给村寨/天数/出发地时，从问题文本里兜底提取
                if not arguments.get("villages"):
                    mentioned = [name for name in VILLAGE_COORDS if name in question]
                    if mentioned:
                        arguments = {**arguments, "villages": mentioned}
                mentioned_days = self._extract_days(question)
                if mentioned_days and not arguments.get("days"):
                    arguments = {**arguments, "days": mentioned_days}
                if not arguments.get("stage"):
                    stage = study_course.detect_stage(question)
                    if stage:
                        arguments = {**arguments, "stage": stage}
                if not arguments.get("start"):
                    departure = self.detect_departure(question)
                    if departure:
                        arguments = {**arguments, "start": departure}
                if not arguments.get("transport_mode"):
                    mode = self.detect_transport_mode(question)
                    if mode:
                        arguments = {**arguments, "transport_mode": mode}
            result = self.tools.execute(tool_name, arguments)
            tool_results.append({
                "tool": tool_name,
                "purpose": purpose,
                "arguments": arguments,
                "result": result,
            })

        route_hit = any(hint in question for hint in ROUTE_TOOL_HINTS)
        # 课程包工具内部已生成路线，视为路线需求已满足，避免重复追加路线工具
        has_route_tool = any(
            item.get("tool") in ("generate_study_route", "generate_course_pack")
            for item in tool_results
        )
        if route_hit and not has_route_tool:
            route_villages = [name for name in VILLAGE_COORDS if name in question]
            route_days = self._extract_days(question)
            route_args = self._make_route_args(route_villages, route_days, question)
            result = self.tools.execute("generate_study_route", route_args)
            tool_results.append({
                "tool": "generate_study_route",
                "purpose": "自动补充红旅路线",
                "arguments": {},
                "result": result,
            })

        draft_answer = self._generate_answer(
            question, village, plan, tool_results, persona_mode,
            user_profile, memory_context=memory_context,
        )

        # ??????????????????????????
        evidence_text = self._format_tool_results(tool_results)
        verification = self.fact_checker.verify(question, draft_answer, evidence_text)
        answer = verification.get("revised_answer") or draft_answer

        return {
            "handled": True,
            "plan": plan,
            "tool_results": tool_results,
            "verification": verification,
            "answer": answer,
        }

    @staticmethod
    def _extract_days(question: str) -> Optional[int]:
        match = re.search(r"(\d+)\s*天", question or "")
        return int(match.group(1)) if match else None

    @staticmethod
    def detect_departure(text: str) -> Optional[str]:
        """从文本中识别出发城市（支持'从昆明出发'等说法）；未识别返回 None。"""
        if not text:
            return None
        for city in DEPARTURE_CITIES:
            if city in text:
                return city
        return None

    @staticmethod
    def detect_transport_mode(text: str) -> Optional[str]:
        """识别用户指定的交通方式：飞机 air / 高铁 rail / 大巴 road；未指定返回 None。"""
        if not text:
            return None
        if any(w in text for w in ("飞机", "航班", "坐飞机", "飞过去", "乘机")):
            return "air"
        if any(w in text for w in ("高铁", "动车", "火车", "铁路")):
            return "rail"
        if any(w in text for w in ("大巴", "包车", "自驾", "坐汽车", "客车")):
            return "road"
        return None

    @staticmethod
    def _course_step_from_question(question: str, args: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """从问题文本/原路线参数构造一个课程包步骤参数。"""
        args = args or {}
        villages = args.get("villages") or [name for name in VILLAGE_COORDS if name in question]
        stage = args.get("stage") or study_course.detect_stage(question)
        start = args.get("start") or OrchestratorAgent.detect_departure(question)
        transport_mode = args.get("transport_mode") or OrchestratorAgent.detect_transport_mode(question)
        arguments: Dict[str, Any] = {"villages": villages}
        if args.get("days") or OrchestratorAgent._extract_days(question):
            arguments["days"] = args.get("days") or OrchestratorAgent._extract_days(question)
        if stage:
            arguments["stage"] = stage
        if start:
            arguments["start"] = start
        if transport_mode:
            arguments["transport_mode"] = transport_mode
        if args.get("group_size"):
            arguments["group_size"] = args["group_size"]
        if args.get("theme"):
            arguments["theme"] = args["theme"]
        return {
            "tool": "generate_course_pack",
            "arguments": arguments,
            "purpose": "生成研学课程包（课程意图纠偏）",
        }

    @staticmethod
    def _enforce_course_pack(question: str, plan: Dict[str, Any]) -> Dict[str, Any]:
        """课程类意图的确定性纠偏：错选路线工具则替换，漏选则补上，且不允许再叠加路线工具。"""
        if not any(hint in (question or "") for hint in COURSE_INTENT_HINTS):
            return plan
        steps = [s for s in (plan.get("steps") or []) if isinstance(s, dict)]
        course_steps = [s for s in steps if s.get("tool") == "generate_course_pack"]

        if course_steps:
            # 已有课程包步骤：移除冗余的红旅路线步骤（课程包内部自带路线），
            # 并从问题文本补全出发地/交通方式/学段等 Planner 可能漏填的槽位
            merged = []
            for step in steps:
                if step.get("tool") == "generate_course_pack":
                    merged.append(OrchestratorAgent._course_step_from_question(
                        question, step.get("arguments") or {}))
                elif step.get("tool") != "generate_study_route":
                    merged.append(step)
            plan["steps"] = merged
        else:
            new_steps = []
            replaced = False
            for step in steps:
                if step.get("tool") == "generate_study_route":
                    # 把错选的路线步骤替换为课程包步骤，尽量沿用已抽取的参数
                    new_steps.append(
                        OrchestratorAgent._course_step_from_question(question, step.get("arguments") or {})
                    )
                    replaced = True
                else:
                    new_steps.append(step)
            if not replaced:
                # Planner 完全没选路线也没选课程包：直接补一个课程包步骤
                new_steps.append(OrchestratorAgent._course_step_from_question(question))
            plan["steps"] = new_steps

        plan["is_complex"] = True
        plan["task_type"] = "study_course"
        return plan

    @staticmethod
    def _infer_route_preferences(question: str) -> Dict[str, Any]:
        """从用户自然语言中提取研学路线偏好。"""
        q = question or ""
        prefs = {}
        family = any(w in q for w in ["亲子", "孩子", "儿童", "小朋友"])
        low_energy = any(w in q for w in ["低体力", "轻松", "休闲", "少走路", "老人"])
        food_focus = any(w in q for w in ["美食", "吃", "小吃", "餐厅", "特产"])
        if family:
            prefs.update({"travel_style": "low_energy", "low_energy": True, "family": True, "group": "亲子"})
        elif low_energy:
            prefs.update({"travel_style": "low_energy", "low_energy": True, "group": "低体力"})
        elif any(w in q for w in ["最短", "最近", "顺路", "车程", "不走回头路"]):
            prefs["travel_style"] = "nearest"
        if food_focus:
            prefs["food_focus"] = True
        return prefs

    def _make_route_args(self, route_villages: List[str], route_days: Optional[int], question: str) -> Dict[str, Any]:
        """把识别出的村寨、天数和偏好合并为 generate_study_route 参数。"""
        args = {}
        if route_villages:
            args["villages"] = route_villages
        if route_days:
            args["days"] = route_days
        args.update(self._infer_route_preferences(question))
        return args

    @staticmethod
    @staticmethod
    def _coord_name(lat, lng):
        """????????????????????"""
        try:
            lat = round(float(lat), 2)
            lng = round(float(lng), 2)
        except Exception:
            return f"({lat}, {lng})"
        for name, info in VILLAGE_COORDS.items():
            if abs(info["lat"] - lat) < 0.03 and abs(info["lng"] - lng) < 0.03:
                return name
        return f"({lat}, {lng})"

    @classmethod
    def _format_tool_results(cls, tool_results: List[Dict[str, Any]]) -> str:
        """???????????????????????????"""
        parts = []
        for i, item in enumerate(tool_results, 1):
            tool = item.get("tool", "")
            raw = item.get("result", "")
            purpose = item.get("purpose") or ""

            try:
                data = json.loads(raw)
            except Exception:
                readable = raw
            else:
                readable = cls._readable_result(tool, data)

            parts.append(
                f"【证据{i}】工具：{tool}\n"
                f"目的：{purpose}\n"
                f"内容：\n{readable}"
            )
        return "\n\n".join(parts)

    @staticmethod
    def _readable_result(tool: str, data: Any) -> str:
        """???????? JSON ???????????"""
        if tool == "get_route":
            lines = []
            for route in data:
                if not isinstance(route, dict):
                    continue
                name = route.get("name", "")
                direction = route.get("direction", "")
                points = route.get("points", [])
                named = []
                for point in points:
                    if isinstance(point, list) and len(point) >= 2:
                        named.append(OrchestratorAgent._coord_name(point[0], point[1]))
                route_line = name
                if named:
                    route_line += "：" + " -> ".join(named)
                if direction:
                    route_line += "；方向：" + direction
                lines.append(route_line)
            return "\n".join(lines)

        if tool == "generate_study_route":
            if isinstance(data, dict):
                stops = data.get("stops") or []
                lines = []
                for s in stops:
                    lines.append(
                        f"第{s.get('day', '')}天：{s.get('name', '')}，{s.get('city', '')}，"
                        f"{s.get('event', '')}，{s.get('visit_time', '')}，停留{s.get('duration_hours', '')}小时"
                    )
                reasons = data.get("why_not_other_routes") or []
                return "推荐方案：\n" + "\n".join(lines) + ("\n\n未选其他路线的原因：\n" + "\n".join(reasons) if reasons else "")
            return str(data)

        if tool == "generate_course_pack":
            if isinstance(data, dict):
                pricing = data.get("pricing") or {}
                curriculum = data.get("curriculum") or {}
                lines = [
                    f"学段：{pricing.get('stage', '')}；天数：{data.get('days', '')}；"
                    f"班额：{pricing.get('group_size', '')}人",
                    f"人均费用：{pricing.get('per_student_fee', '')}{pricing.get('currency', '元')}，"
                    f"合计约：{pricing.get('total_fee', '')}{pricing.get('currency', '元')}，"
                    f"需导师{pricing.get('required_guides', '')}名",
                ]
                goals = curriculum.get("course_goals") or []
                if goals:
                    lines.append("课程目标：" + "；".join(goals))
                for plan in curriculum.get("daily_plans", []):
                    if not isinstance(plan, dict):
                        continue
                    sites = "、".join(
                        a.get("site", "") for a in plan.get("activities", []) if isinstance(a, dict)
                    )
                    lines.append(f"第{plan.get('day', '')}天 {plan.get('theme', '')}：{sites}")
                return "\n".join(lines)
            return str(data)

        if tool == "query_timeline":
            if isinstance(data, list):
                lines = []
                for e in data:
                    if not isinstance(e, dict):
                        continue
                    lines.append(
                        f"{e.get('date', '')} {e.get('label', '')}，地点：{e.get('village', '')}，部队：{e.get('army', '')}，"
                        f"内容：{e.get('desc', '')}"
                    )
                return "\n".join(lines) if lines else str(data)
            return str(data)

        if tool == "get_village_profile":
            if isinstance(data, dict):
                return (
                    f"村寨：{data.get('name', '')}，城市：{data.get('city', '')}，"
                    f"事件：{data.get('event', '')}，年份：{data.get('year', '')}，"
                    f"部队：{data.get('army', '')}"
                )
            return str(data)

        if tool == "query_knowledge_graph":
            if isinstance(data, dict):
                nodes = data.get("nodes") or []
                relations = data.get("relations") or []
                if not relations:
                    return data.get("message", "图谱未返回关系")
                id_to_name = {}
                for node in nodes:
                    if isinstance(node, dict):
                        id_to_name[node.get("id", "")] = node.get("name", node.get("id", ""))
                lines = []
                for rel in relations:
                    if not isinstance(rel, dict):
                        continue
                    source = id_to_name.get(rel.get("source", ""), rel.get("source", ""))
                    target = id_to_name.get(rel.get("target", ""), rel.get("target", ""))
                    label = rel.get("label") or rel.get("relation") or "关联"
                    lines.append(f"{source} --[{label}]--> {target}")
                return "\n".join(lines) if lines else str(data)
            return str(data)

        if tool == "list_graph_nodes":
            if isinstance(data, list):
                lines = []
                for node in data[:20]:
                    if not isinstance(node, dict):
                        continue
                    lines.append(
                        f"类型：{node.get('type', '')}；名称：{node.get('name', '')}；"
                        f"说明：{node.get('description', '')}"
                    )
                return "\n".join(lines) if lines else str(data)
            return str(data)

        if tool == "search_archives":
            if isinstance(data, list):
                lines = []
                for item in data:
                    if not isinstance(item, dict):
                        continue
                    lines.append(f"来源：{item.get('source', '')}\n{item.get('text', '')}")
                return "\n\n".join(lines) if lines else str(data)
            return str(data)

        return json.dumps(data, ensure_ascii=False, indent=2)

    def _generate_answer(
        self,
        question: str,
        village: Optional[str],
        plan: Dict[str, Any],
        tool_results: List[Dict[str, Any]],
        persona_mode: str = "tourist",
        user_profile: Optional[Dict[str, Any]] = None,
        memory_context: Optional[str] = None,
    ) -> str:
        """把工具执行结果汇总成面向用户的自然语言回答。"""
        results_block = self._format_tool_results(tool_results)

        system_prompt = build_system_prompt(village, persona_mode, user_profile) if village else build_system_prompt("扎西", persona_mode, user_profile)
        if memory_context:
            system_prompt += "\n\n" + memory_context

        user_prompt = (
            f"你是云南红军长征档案智能体的最终回答者。\n\n"
            f"用户问题：{question}\n\n"
            f"智能体已经完成以下规划与工具调用：\n"
            f"规划理由：{plan.get('reasoning', '')}\n\n"
            f"{results_block}\n\n"
            "请综合这些结果，用村寨代言人的口吻给用户一个完整、自然、可执行的回答。\n"
            "要求：\n"
            "1. 如果用户要路线或计划，请按步骤、按天或按地点组织。\n"
            "2. 历史数字、人名、日期必须来自工具结果，不能编造。\n"
            "3. 不要在回答末尾罗列档案来源，前端证据链会单独展示来源。"
        )

        # 推理模型可能把额度耗在 reasoning 上导致正文为空，统一走带重试的封装
        return llm_utils.chat_content(
            self.client,
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            model=config.MODEL_NAME,
            temperature=config.TEMPERATURE,
            max_tokens=config.MAX_TOKENS,
        )
