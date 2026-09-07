"""
智能体工具集
------------
提供可被大模型调用的结构化工具。Planner 负责生成调用计划，
ToolRegistry 负责真正执行工具，并返回可读结果。

这是把“聊天机器人”升级为“智能体”的关键：模型不只生成文字，
还能根据任务自主选择并调用工具。
"""
import json
import math
from urllib.parse import quote
from typing import Any, Dict, List, Optional

from openai import OpenAI

from . import config, study_course
from .knowledge import (
    DEPARTURE_CITIES, ROUTES, TIMELINE, VILLAGE_COORDS,
    VILLAGE_ENERGY, VILLAGE_EXPERIENCE, VILLAGE_LODGING,
)
from .graph_store import KnowledgeGraphStore
from .retriever_factory import create_retriever


# ===================== 城际交通模式模型（公式可复算，非实时票务） =====================
# speed_kmh：综合时速；overhead_h：候机/候车/两端接驳的固定附加时间；
# detour：球面直线距离→实际线路里程的绕行系数；min_km：该交通方式合理的最短距离
TRANSPORT_MODES: Dict[str, Dict[str, Any]] = {
    "road": {"label": "旅游大巴", "icon": "🚌", "speed_kmh": 50.0, "overhead_h": 0.0, "detour": 1.35, "min_km": 0.0},
    "rail": {"label": "高铁/动车", "icon": "🚄", "speed_kmh": 200.0, "overhead_h": 0.75, "detour": 1.20, "min_km": 80.0},
    "air":  {"label": "民航航班", "icon": "✈️", "speed_kmh": 700.0, "overhead_h": 2.5, "detour": 1.05, "min_km": 400.0},
}
# 按课程总天数给出可接受的单程交通上限（小时）与教学点之间转场上限
OUTBOUND_LIMIT_HOURS = {1: 2.5, 2: 5.0, 3: 8.0}
TRANSFER_LIMIT_HOURS = {1: 2.5, 2: 3.0, 3: 5.5}


class ToolRegistry:
    """工具注册与执行器。"""

    def __init__(self, retriever=None, llm_client=None):
        self.retriever = retriever or create_retriever()
        self.graph_store = KnowledgeGraphStore()
        # 课程包等"工具内部再调一次 LLM 润色"的场景复用同一客户端
        self.llm_client = llm_client or OpenAI(
            api_key=config.DEEPSEEK_API_KEY, base_url=config.BASE_URL
        )

    def tool_specs(self) -> List[Dict[str, Any]]:
        """返回工具定义，供 Planner 生成 function calling 风格计划。"""
        return [
            {
                "name": "search_archives",
                "description": "根据问题检索云南红军长征档案文本块，返回档案片段和来源。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "检索关键词或问题"},
                        "village": {"type": "string", "description": "可选，限定村寨，例如：皎平渡、扎西、石鼓"},
                        "top_k": {"type": "integer", "description": "返回数量，默认 4，最大 6"},
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "query_timeline",
                "description": "查询长征时间轴事件，可按年份、村寨、关键词过滤。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "year": {"type": "integer", "description": "年份，例如 1935 或 1936"},
                        "village": {"type": "string", "description": "村寨名"},
                        "keyword": {"type": "string", "description": "关键词，例如：渡江、会议"},
                    },
                },
            },
            {
                "name": "get_village_profile",
                "description": "查询一个村寨的基本档案：位置、年份、事件、所属部队。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "village": {"type": "string", "description": "村寨名，例如：皎平渡"}
                    },
                    "required": ["village"],
                },
            },
            {
                "name": "get_route",
                "description": "获取中央红军和红二、六军团两条行军路线。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "army": {"type": "string", "description": "可选：中央红军 / 红二、六军团"}
                    },
                },
            },
            {
                "name": "query_knowledge_graph",
                "description": "查询档案知识图谱，回答人物、地点、部队、事件之间的人物关系、发生地、所属部队、路线先后和事件前后关系。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "topic": {"type": "string", "description": "模糊主题，例如：贺龙、金沙江、1936"},
                        "entity": {"type": "string", "description": "实体名称，例如：皎平渡、扎西会议、红二、六军团"},
                        "relation": {"type": "string", "description": "可选关系类型，例如：commander / occurred_at / next_on_route / next_event"},
                        "event": {"type": "string", "description": "事件名称，例如：扎西会议、石鼓渡江"},
                        "year": {"type": "integer", "description": "年份，例如 1935 或 1936"},
                        "limit": {"type": "integer", "description": "最多返回关系数，默认 10"}
                    }
                },
            },
            {
                "name": "list_graph_nodes",
                "description": "列出知识图谱中的节点类型，例如人物、地点、事件、部队，用于了解可查询范围。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "node_type": {"type": "string", "description": "可选：person / location / event / army"}
                    }
                },
            },
            {
                                "name": "generate_study_route",
                "description": "红旅路线（旅游/行程规划，不是课程教案）：根据村寨、天数和偏好生成多套红色旅游路线，包含推荐方案、备选方案、交通时间、住宿建议、每日体力值和景点/美食参考链接。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "villages": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "可选，指定村寨名称列表，例如：扎西、皎平渡、石鼓"
                        },
                        "days": {"type": "integer", "description": "可选，计划天数，默认按村寨数量自动估算"},
                        "theme": {"type": "string", "description": "可选，主题，例如：中央红军、红二六军团、渡江战役、扎西会议"},
                        "start": {"type": "string", "description": "可选，起点村寨"},
                        "travel_style": {"type": "string", "description": "可选，路线策略：historical=历史顺序，nearest=最少车程，low_energy=低体力精简"},
                        "low_energy": {"type": "boolean", "description": "可选，是否低体力/轻松"},
                        "food_focus": {"type": "boolean", "description": "可选，是否重点推荐美食"},
                        "family": {"type": "boolean", "description": "可选，是否亲子出行"},
                        "group": {"type": "string", "description": "可选，出行人群，例如：亲子、老人、研究者、学生"}
                    }
                },
            },
            {
                "name": "generate_course_pack",
                "description": (
                    "生成红色研学课程包（教学方案，不是旅游路线）：在红旅路线骨架基础上，按学段（小学/初中/高中/党校成人）"
                    "输出课程目标、每日课程安排（知识点与探究任务）、研学手册任务和费用估算。"
                    "当用户要求'课程包/研学课程/教案/课时/备课/课程方案/课程表/研学手册'时使用；"
                    "若只是旅游路线规划，仍用 generate_study_route。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "villages": {"type": "array", "items": {"type": "string"}, "description": "覆盖的村寨列表"},
                        "days": {"type": "integer", "description": "课程天数，默认 2"},
                        "stage": {"type": "string", "description": "学段：小学/初中/高中/党校成人，默认初中"},
                        "group_size": {"type": "integer", "description": "班级人数，默认 40"},
                        "theme": {"type": "string", "description": "课程主题，如'巧渡金沙江'"},
                        "start": {"type": "string", "description": "出发城市，如昆明/攀枝花/大理/成都/贵阳/昭通，用于计算往返交通车程；用户未说明时不要编造"},
                        "transport_mode": {"type": "string", "description": "交通方式：road大巴/rail高铁/air飞机，仅在用户明确指定时填写，否则留空由系统按距离自动选择"},
                    },
                    "required": [],
                },
            },
            {
                "name": "compare_villages",
                "description": "对比两个村寨的历史事件、所属部队、年份和知识图谱关系，用于跨村寨比较。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "village_a": {"type": "string", "description": "第一个村寨名"},
                        "village_b": {"type": "string", "description": "第二个村寨名"},
                        "aspect": {"type": "string", "description": "可选，对比角度，例如：渡江、会议、部队、时间"}
                    },
                    "required": ["village_a", "village_b"],
                },
            },
            {
                "name": "estimate_travel",
                "description": "估算两个村寨之间的直线距离、估算公路里程和驾车时间。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "origin": {"type": "string", "description": "起点村寨名"},
                        "destination": {"type": "string", "description": "终点村寨名"},
                        "speed_kmh": {"type": "number", "description": "平均车速，默认 50 km/h"}
                    },
                    "required": ["origin", "destination"],
                },
            },
        ]

    def execute(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        """执行指定工具，返回字符串结果。"""
        method = getattr(self, "_" + tool_name, None)
        if method is None:
            return json.dumps({"error": f"未知工具：{tool_name}"}, ensure_ascii=False)

        try:
            return method(**arguments)
        except Exception as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    def _search_archives(self, query: str, village: Optional[str] = None, top_k: int = 4) -> str:
        top_k = max(1, min(int(top_k or config.TOP_K), 6))
        results = self.retriever.search(query, village=village, top_k=top_k)
        if not results:
            return json.dumps({"message": "未检索到相关档案"}, ensure_ascii=False)

        items = []
        for i, r in enumerate(results, 1):
            items.append({
                "rank": i,
                "text": r["text"][:800],
                "source": r["source"],
                "score": round(r["score"], 4),
            })
        return json.dumps(items, ensure_ascii=False, indent=2)

    def _query_timeline(self, year: Optional[int] = None, village: Optional[str] = None, keyword: Optional[str] = None) -> str:
        events = TIMELINE
        if year:
            events = [e for e in events if str(e["date"]).startswith(str(year))]
        if village:
            events = [e for e in events if village in e.get("village", "")]
        if keyword:
            events = [e for e in events if keyword in e.get("label", "") or keyword in e.get("desc", "")]

        if not events:
            return json.dumps({"message": "没有匹配的时间轴事件"}, ensure_ascii=False)
        return json.dumps(events, ensure_ascii=False, indent=2)

    def _get_village_profile(self, village: str) -> str:
        if village not in VILLAGE_COORDS:
            return json.dumps({"message": f"未找到村寨：{village}"}, ensure_ascii=False)
        profile = dict(VILLAGE_COORDS[village])
        profile["name"] = village
        return json.dumps(profile, ensure_ascii=False, indent=2)

    def _get_route(self, army: Optional[str] = None) -> str:
        routes = ROUTES
        if army:
            routes = [r for r in routes if army in r["name"]]
        return json.dumps(routes, ensure_ascii=False, indent=2)

    def _query_knowledge_graph(
        self,
        topic: Optional[str] = None,
        entity: Optional[str] = None,
        relation: Optional[str] = None,
        event: Optional[str] = None,
        year: Optional[int] = None,
        limit: int = 10,
    ) -> str:
        """执行知识图谱邻居查询工具。"""
        result = self.graph_store.query(
            topic=topic,
            entity=entity,
            relation=relation,
            event=event,
            year=year,
            limit=limit,
        )
        return json.dumps(result, ensure_ascii=False, indent=2)

    def _list_graph_nodes(self, node_type: Optional[str] = None) -> str:
        """执行知识图谱节点列表工具。"""
        nodes = self.graph_store.list_nodes(node_type=node_type)
        if not nodes:
            return json.dumps({"message": "图谱中暂无该类型节点"}, ensure_ascii=False)
        return json.dumps(nodes, ensure_ascii=False, indent=2)

    def _generate_study_route(
        self,
        villages: Optional[List[str]] = None,
        days: Optional[int] = None,
        theme: Optional[str] = None,
        start: Optional[str] = None,
        travel_style: Optional[str] = None,
        low_energy: bool = False,
        food_focus: bool = False,
        family: bool = False,
        group: Optional[str] = None,
    ) -> str:
        """生成多套红色研学路线：推荐方案、备选方案、交通、住宿、体力值与参考链接。"""
        if isinstance(villages, str):
            villages = [v.strip() for v in villages.replace("，", ",").split(",") if v.strip()]
        if not isinstance(villages, list):
            villages = []

        provided_villages = bool(villages or start)

        preferences = {
            "travel_style": (travel_style or "historical").lower(),
            "low_energy": bool(low_energy or family),
            "food_focus": bool(food_focus),
            "family": bool(family),
            "group": group or "通用",
        }
        if preferences["travel_style"] not in {"historical", "nearest", "low_energy"}:
            preferences["travel_style"] = "low_energy" if preferences["low_energy"] else "historical"

        if start and start not in villages:
            villages.insert(0, start)

        if not villages:
            villages = self._default_route_villages()

        valid, unknown = self._validate_villages(villages)
        valid = self._dedupe_villages(valid)
        if not valid:
            return json.dumps({
                "message": "没有找到可用的村寨，请提供明确村寨名。",
                "available_villages": sorted(VILLAGE_COORDS.keys()),
                "unknown": unknown,
            }, ensure_ascii=False, indent=2)

        try:
            requested_days = int(days) if days is not None else None
        except Exception:
            requested_days = None

        if requested_days and len(valid) == 1:
            valid = self._expand_single_route(valid[0], requested_days)
            valid = self._dedupe_villages(valid)

        route_days = self._resolve_route_days(valid, requested_days)

        force_one_per_day = False
        if not provided_villages and requested_days and len(valid) > route_days:
            valid = self._select_compact_route(valid, route_days, start)
            force_one_per_day = True

        historical_order = self._order_villages(valid)
        nearest_order = self._order_nearest(valid, start)
        low_order = self._order_low_energy(valid, route_days)

        style = preferences["travel_style"]
        if style == "nearest":
            selected_order, selected_label, selected_strategy = nearest_order, "推荐方案", "最少车程"
        elif style == "low_energy":
            selected_order, selected_label, selected_strategy = low_order, "推荐方案", "低体力精简"
        else:
            selected_order, selected_label, selected_strategy = historical_order, "推荐方案", "历史顺序"

        route_prefix = f"{theme or '云南红军长征'}红旅路线"
        selected_payload = self._build_route_payload(selected_order, route_days, route_prefix, selected_strategy, one_per_day=force_one_per_day)

        if style == "nearest":
            alt_order = historical_order
            alt_label, alt_strategy = "备选方案", "历史顺序"
        elif style == "low_energy":
            alt_order = historical_order if historical_order != low_order else nearest_order
            alt_label, alt_strategy = "备选方案", "历史顺序" if alt_order == historical_order else "最少车程"
        else:
            alt_order = low_order if low_order != historical_order else nearest_order
            alt_label, alt_strategy = "备选方案", "低体力精简" if alt_order == low_order else "最少车程"

        alt_payload = self._build_route_payload(alt_order, route_days, route_prefix, alt_strategy, one_per_day=force_one_per_day)

        recommended_plan = {
            "id": "recommended",
            "label": selected_label,
            "strategy": selected_strategy,
            "reason": self._plan_reason(selected_strategy, preferences),
            **selected_payload,
        }
        alternative_plan = {
            "id": "alternative",
            "label": alt_label,
            "strategy": alt_strategy,
            "reason": self._plan_reason(alt_strategy, preferences),
            **alt_payload,
        }

        return json.dumps({
            **selected_payload,
            "preferences": preferences,
            "plans": [recommended_plan, alternative_plan],
            "why_not_other_routes": self._why_not_other_routes(selected_strategy, alt_strategy, preferences),
            "unknown_villages": unknown,
        }, ensure_ascii=False, indent=2)

    @staticmethod
    def _parse_tool_json(text: str) -> Optional[dict]:
        """从 LLM 输出中稳健提取 JSON 对象（兼容 ```json 代码块包裹）。"""
        if not text:
            return None
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("```", 2)[1]
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start != -1 and end > start:
            try:
                return json.loads(cleaned[start:end + 1])
            except json.JSONDecodeError:
                return None
        return None

    def _generate_course_pack(
        self,
        villages: Optional[List[str]] = None,
        days: Optional[int] = None,
        stage: Optional[str] = None,
        group_size: Optional[int] = None,
        theme: Optional[str] = None,
        start: Optional[str] = None,
        transport_mode: Optional[str] = None,
    ) -> str:
        """生成研学课程包：可行性选址 + 交通住宿物流 + LLM 课程化 + 代码费用模型。"""
        # 0) 课程总天数（用户要几天就是几天，与现场教学点覆盖天数分开）
        try:
            requested_days = int(days) if days is not None else None
        except (TypeError, ValueError):
            requested_days = None
        course_days = max(1, min(requested_days or 2, 7))

        # 0.1) 确定候选教学点：用户点名用用户的；没点名用长征路线默认池
        if isinstance(villages, str):
            villages = [v.strip() for v in villages.replace("，", ",").split(",") if v.strip()]
        candidates, unknown = self._validate_villages(villages or self._default_route_villages())
        candidates = self._dedupe_villages(candidates)
        if not candidates:
            return json.dumps({
                "message": "没有找到可用的村寨，请提供明确村寨名。",
                "available_villages": sorted(VILLAGE_COORDS.keys()),
                "unknown": unknown,
            }, ensure_ascii=False, indent=2)

        # 0.2) 先按"最近可达"锚点确定交通方式，再按天数可行性精简教学点
        mode = transport_mode if transport_mode in TRANSPORT_MODES else None
        if start:
            anchor = self._greedy_from_origin(candidates, start)[0]
            mode, _, mode_note = self._choose_transport_mode(start, anchor, course_days, mode)
        else:
            mode, mode_note = "road", ""
        trimmed = self._feasible_course_sites(candidates, start, course_days, mode)
        trimmed_note = ""
        if len(trimmed) < len(candidates):
            dropped = [v for v in candidates if v not in trimmed]
            trimmed_note = (
                f"{course_days}天行程内为保证教学与休息时间，"
                f"只安排可达性最好的 {len(trimmed)} 个教学点（{ '、'.join(trimmed) }），"
                f"舍弃转场过远的：{ '、'.join(dropped) }"
            )

        # 1) 复用红旅路线工具拿分天 stops；显式传精简后的点，天数=点数防止单点被自动扩展
        route_kwargs = {"villages": trimmed, "days": len(trimmed), "theme": theme,
                        "travel_style": "nearest"}
        if start:
            route_kwargs["start"] = start
        route_raw = self._generate_study_route(**route_kwargs)
        route = json.loads(route_raw)
        if "stops" not in route:
            return route_raw

        route_days = int(route.get("days", 1))
        try:
            actual_group = max(1, min(int(group_size or 40), 200))
        except (TypeError, ValueError):
            actual_group = 40

        # 2) 费用与师生比由代码确定性计算，LLM 不参与；按课程总天数计费
        pricing = study_course.estimate_price(stage or "初中", course_days, actual_group)

        # 3) 交通与住宿物流层：全部由代码按真实坐标/知识库确定性计算，LLM 不参与
        stops = route.get("stops", [])
        logistics = self._build_course_logistics(route, start, course_days, mode)
        if mode_note:
            logistics["mode_note"] = mode_note
        if trimmed_note:
            logistics["trimmed_note"] = trimmed_note

        # 4) 给 LLM 的路线摘要（带上城市、现场资源、讲解要点，让任务设计有地方特色）
        route_brief = []
        for stop in stops:
            route_brief.append({
                "day": stop.get("day"),
                "visit_time": stop.get("visit_time"),
                "site": stop.get("name"),
                "city": stop.get("city"),
                "event": stop.get("event"),
                "attractions": (stop.get("attractions") or [])[:3],
                "tips": stop.get("tips"),
                "timeline": [
                    (ev.get("label") or ev.get("desc") or "")
                    for ev in (stop.get("timeline_events") or [])[:3]
                ],
            })

        transit_brief = self._transit_brief_text(logistics)
        curriculum = self._llm_curriculum(route_brief, pricing, theme, route_days, transit_brief)
        if curriculum is None:
            curriculum = study_course.build_fallback_curriculum(
                route, stage or "初中", total_days=course_days
            )
            curriculum_source = "template_fallback"
        else:
            curriculum["stage"] = pricing["stage"]
            curriculum_source = "llm"

        # 5) 交通/住宿按天确定性挂到课程表上（LLM 失败也不影响这一层）
        self._attach_logistics_to_curriculum(curriculum, logistics)

        payload = {
            "tool": "generate_course_pack",
            "theme": theme or "云南红军长征",
            "villages": [s.get("name") for s in stops],
            "days": course_days,
            "route_days": route_days,
            "start": start or "",
            "transport_mode": logistics.get("mode", "road"),
            "route_brief": route_brief,
            "pricing": pricing,
            "logistics": logistics,
            "curriculum": curriculum,
            "curriculum_source": curriculum_source,
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    def _build_course_logistics(
        self, route: Dict[str, Any], start: Optional[str], course_days: int,
        mode: str = "road",
    ) -> Dict[str, Any]:
        """按真实坐标计算往返/内部交通，按知识库给出每晚住宿（确定性，不经过 LLM）。

        城际往返使用选定交通方式（大巴/高铁/飞机），教学点之间转场始终走公路。
        """
        stops = route.get("stops", [])
        internal = route.get("travel_segments", [])

        # 去程：出发城市 → 第一个教学点；返程：最后一个教学点 → 出发城市
        outbound = None
        return_seg = None
        if start and stops:
            first_site = stops[0].get("name")
            last_site = stops[-1].get("name")
            outbound = self._travel_segment(start, first_site, mode)
            return_seg = self._travel_segment(last_site, start, mode)

        # 内部转场归属到"到达日"：segment(i→i+1) 属于后一个 stop 的 day
        seg_by_day: Dict[int, List[Dict[str, Any]]] = {}
        for i in range(len(stops) - 1):
            day = int(stops[i + 1].get("day", 1))
            seg = internal[i] if i < len(internal) else self._travel_segment(
                stops[i].get("name"), stops[i + 1].get("name")
            )
            seg_by_day.setdefault(day, []).append(seg)

        # 每日住宿：取当天最后一个教学点的知识库住宿建议；补足课程总天数
        lodging_by_day: Dict[int, str] = {}
        day_last_site: Dict[int, str] = {}
        for stop in stops:
            day_last_site[int(stop.get("day", 1))] = stop.get("name", "")
        for day in range(1, int(route.get("days", 1)) + 1):
            site = day_last_site.get(day)
            if site:
                lodging_by_day[day] = VILLAGE_LODGING.get(site, "研学基地或县城商务酒店")
        last_lodging = next(
            (lodging_by_day[d] for d in sorted(lodging_by_day, reverse=True)),
            "研学基地或县城商务酒店",
        )
        for day in range(int(route.get("days", 1)) + 1, course_days + 1):
            lodging_by_day[day] = last_lodging  # 专题/结营日延续驻地住宿

        # 把去程挂到第 1 天的转场列表
        if outbound:
            seg_by_day.setdefault(1, []).insert(0, outbound)

        daily = []
        for day in range(1, course_days + 1):
            is_last = day == course_days
            daily.append({
                "day": day,
                "transit": seg_by_day.get(day, []),
                # 最后一天返程，不安排住宿
                "lodging": None if is_last and return_seg else lodging_by_day.get(day),
                "return": return_seg if is_last else None,
            })

        total_km = 0.0
        total_hours = 0.0
        for seg in [outbound] + internal + [return_seg]:
            if seg:
                total_km += float(seg.get("estimated_road_km", 0.0))
                total_hours += float(seg.get("estimated_travel_hours", 0.0))
        mode_cfg = TRANSPORT_MODES.get(mode, TRANSPORT_MODES["road"])
        return {
            "departure": start or "",
            "mode": mode,
            "mode_label": mode_cfg["label"],
            "outbound": outbound,
            "return": return_seg,
            "internal": internal,
            "daily": daily,
            "total_road_km": round(total_km, 1),
            "total_travel_hours": round(total_hours, 2),
            "note": ("城际交通按真实经纬度球面距离×绕行系数、结合大巴50/高铁200/飞机700km/h"
                     "综合时速并含接驳候机时间估算；教学点间为公路；住宿来自知识库，实际以预订为准。"),
        }

    @staticmethod
    def _attach_logistics_to_curriculum(curriculum: Dict[str, Any], logistics: Dict[str, Any]) -> None:
        """把代码算好的交通/住宿按天写进课程表，原地修改，保证 LLM 失败也有完整物流。"""
        daily_map = {item["day"]: item for item in logistics.get("daily", [])}
        for plan in curriculum.get("daily_plans", []):
            if not isinstance(plan, dict):
                continue
            day = int(plan.get("day", 0))
            info = daily_map.get(day, {})
            transit = info.get("transit", [])
            plan["transit"] = transit
            plan["lodging"] = info.get("lodging")
            plan["return"] = info.get("return")
            # 确定性修正：去程超过 2.5 小时，第 1 天上午在赶路，现场教学只能排下午；
            # 返程超过 2.5 小时，最后一天下午在赶路，现场教学只能排上午
            outbound_h = transit[0]["estimated_travel_hours"] if transit else 0.0
            return_h = (plan.get("return") or {}).get("estimated_travel_hours", 0.0)
            for act in plan.get("activities", []):
                if not isinstance(act, dict):
                    continue
                if day == 1 and outbound_h > 2.5 and act.get("slot") == "上午":
                    act["slot"] = "下午（上午乘车抵达）"
                if plan.get("return") and return_h > 2.5 and act.get("slot") in ("下午", "14:00-17:00"):
                    act["slot"] = "上午（下午返程）"

    @staticmethod
    def _transit_brief_text(logistics: Dict[str, Any]) -> str:
        """把每日交通压成一行给 LLM 排课时避让（如：第1天上午 昆明→皎平渡约3小时52分）。"""
        parts = []
        for item in logistics.get("daily", []):
            legs = [f"{s['from']}→{s['to']}约{s.get('estimated_travel_time', '')}"
                    for s in item.get("transit", []) if s.get("from")]
            ret = item.get("return")
            if ret and ret.get("from"):
                legs.append(f"下午 {ret['from']}→{ret['to']}约{ret.get('estimated_travel_time', '')}返程")
            if legs:
                parts.append(f"第{item['day']}天 " + "，".join(legs))
        return "；".join(parts)

    def _llm_curriculum(
        self,
        route_brief: List[Dict[str, Any]],
        pricing: Dict[str, Any],
        theme: Optional[str],
        route_days: Optional[int] = None,
        transit_brief: str = "",
    ) -> Optional[dict]:
        """让 LLM 把路线骨架改写为结构化课程表；任何异常都返回 None 交给模板兜底。"""
        stage_cfg = study_course.load_pricing_model().get("stages", {}).get(pricing["stage"], {})
        focus = stage_cfg.get("focus", "史实准确、循序渐进")
        total_days = pricing["days"]
        site_days = route_days or total_days
        extra_day_hint = ""
        if total_days > site_days:
            extra_day_hint = (
                f"注意：现场教学点只覆盖前 {site_days} 天，另外 {total_days - site_days} 天"
                "不换场地，请安排专题教学、情景体验、研学手册指导或结营汇报等环节，"
                "daily_plans 必须完整覆盖全部 {n} 天。".format(n=total_days)
            )
        prompt = (
            "你是资深红色研学课程设计师。请严格依据给定的每日路线骨架，为【{stage}】学段设计研学课程，"
            "学段特点：{focus}。课程主题：{theme}，共 {days} 天。\n"
            "{extra_hint}"
            "只输出一个 JSON 对象，禁止输出 JSON 以外的任何文字，禁止使用示例之外的自创字段名：\n"
            "{{\"course_goals\": [\"3条以内课程目标\"], "
            "\"daily_plans\": [{{\"day\": 1, \"theme\": \"当日主题\", "
            "\"activities\": [{{\"slot\": \"上午\", \"site\": \"必须使用骨架里的教学点名\", "
            "\"knowledge\": [\"只能来自该教学点的event/timeline/attractions\"], "
            "\"task\": \"结合该教学点独有史实与现场资源的探究任务\"}}]}}], "
            "\"handbook_tasks\": [\"研学手册任务\"], \"closing\": \"结营安排\"}}\n"
            "硬性要求：\n"
            "1. daily_plans 必须恰好 {days} 天，day 从 1 连续编号；\n"
            "2. 每个教学点的 task 必须引用该点独有的事件、遗址或资源细节，"
            "不同教学点的任务严禁雷同、严禁使用'完成研学手册'这类空话；\n"
            "3. knowledge 只能来自路线骨架，不得虚构史实、日期和数字；\n"
            "4. 任务深度适配{stage}学段（小学重体验扮演、初中重探究取证、高中重思辨论证、成人重执政启示）；\n"
            "5. 每日交通时段：{transit}。现场教学活动必须避开乘车时段——"
            "上午在赶路就只安排下午教学并注明'上午乘车抵达'，下午返程就只安排上午教学；\n"
            "6. 交通与住宿由系统另行计算，你不需要输出交通字段。\n"
            "路线骨架：{brief}"
        ).format(
            stage=pricing["stage"], focus=focus, theme=theme or "云南红军长征",
            days=total_days, extra_hint=extra_day_hint,
            transit=transit_brief or "无跨城交通",
            brief=json.dumps(route_brief, ensure_ascii=False),
        )
        # 推理模型思考过程很长（实测可达 5000-6000 reasoning tokens），
        # 首次常因思考耗尽额度而正文为空：逐级放大额度重试，给正文留足空间
        for budget in (8000, 12000):
            try:
                resp = self.llm_client.chat.completions.create(
                    model=config.MODEL_NAME,
                    messages=[
                        {"role": "system", "content": "你是严谨的红色研学课程设计师，只输出 JSON。"},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.3,
                    max_tokens=budget,
                )
                parsed = self._parse_tool_json(resp.choices[0].message.content)
                if self._valid_curriculum(parsed, total_days):
                    return parsed
            except Exception:
                continue
        return None

    @staticmethod
    def _valid_curriculum(parsed: Any, total_days: int) -> bool:
        """校验 LLM 课程 JSON 是否合规：天数匹配且每天都有具体活动。"""
        if not isinstance(parsed, dict) or not isinstance(parsed.get("daily_plans"), list):
            return False
        plans = parsed["daily_plans"]
        if len(plans) != total_days:
            return False
        for plan in plans:
            acts = plan.get("activities") if isinstance(plan, dict) else None
            if not isinstance(acts, list) or not acts:
                return False
            for act in acts:
                if not (isinstance(act, dict) and act.get("site") and act.get("task")):
                    return False
        return True

    def _resolve_route_days(self, villages: List[str], requested_days: Optional[int]) -> int:
        count = len(villages)
        if count <= 0:
            return 1
        if requested_days is None:
            return max(1, math.ceil(count / 2))
        return max(1, min(int(requested_days), count))

    def _build_route_payload(self, ordered: List[str], days: int, route_name: str, strategy: str, one_per_day: bool = False) -> Dict[str, Any]:
        count = len(ordered)
        if count == 0:
            return {
                "route_name": route_name,
                "strategy": strategy,
                "days": 0,
                "stop_count": 0,
                "stops": [],
                "travel_segments": [],
                "daily_energy": [],
                "daily_lodging": [],
            }

        durations = [int(VILLAGE_EXPERIENCE.get(name, {}).get("duration_hours", 3)) for name in ordered]
        assignments = self._assign_days(ordered, durations, strategy, one_per_day=one_per_day)
        actual_days = max(assignments) if assignments else 1
        day_slots = {}
        stops = []
        for idx, name in enumerate(ordered):
            day = assignments[idx]
            slot_index = day_slots.get(day, 0)
            stops.append(self._build_route_stop(name, day, idx + 1, slot_index))
            day_slots[day] = slot_index + 1

        travel_segments = []
        for i in range(len(ordered) - 1):
            travel_segments.append(self._travel_segment(ordered[i], ordered[i + 1]))

        return {
            "route_name": route_name,
            "strategy": strategy,
            "days": actual_days,
            "stop_count": count,
            "stops": stops,
            "travel_segments": travel_segments,
            "daily_energy": self._summarize_daily_energy(stops),
            "daily_lodging": self._summarize_daily_lodging(stops),
        }

    def _assign_days(self, ordered: List[str], durations: List[int], strategy: str, one_per_day: bool = False) -> List[int]:
        """按车程和游玩时长把村寨分配到每天，避免一天内出现无法完成的长途转场。"""
        if not ordered:
            return []
        if one_per_day:
            return list(range(1, len(ordered) + 1))
        max_stops_per_day = 2 if strategy == "低体力精简" else 3
        daily_capacity = 8.0 if strategy == "低体力精简" else 10.0

        assignments = [1] * len(ordered)
        day = 1
        used = float(durations[0])
        stop_count = 1

        for idx in range(1, len(ordered)):
            transfer = self._segment_travel_hours(ordered[idx - 1], ordered[idx])
            duration = float(durations[idx])
            can_fit = (
                stop_count < max_stops_per_day
                and transfer + duration <= daily_capacity - used
            )
            if can_fit:
                used += transfer + duration
                stop_count += 1
            else:
                day += 1
                used = duration
                stop_count = 1
            assignments[idx] = day

        return assignments

    def _segment_travel_hours(self, origin: str, destination: str) -> float:
        """返回两个村寨之间的估算驾车小时数。"""
        segment = self._travel_segment(origin, destination)
        return float(segment.get("estimated_travel_hours", 0.0))

    def _build_route_stop(self, name: str, day: int, order: int, slot_index: int) -> Dict[str, Any]:
        profile = VILLAGE_COORDS[name]
        exp = VILLAGE_EXPERIENCE.get(name, {})
        events = [e for e in TIMELINE if e.get("village") == name]
        attractions = exp.get("attractions", [])
        food = exp.get("food", [])
        lodging = VILLAGE_LODGING.get(name, "")
        return {
            "day": day,
            "order": order,
            "name": name,
            "city": profile.get("city", ""),
            "event": profile.get("event", ""),
            "year": profile.get("year", ""),
            "army": profile.get("army", ""),
            "lat": profile.get("lat"),
            "lng": profile.get("lng"),
            "visit_time": self._visit_window(slot_index),
            "duration_hours": exp.get("duration_hours", 3),
            "energy_level": int(VILLAGE_ENERGY.get(name, 2)),
            "attractions": attractions,
            "attraction_links": self._make_links(attractions, f"{name} 红色旅游 景点"),
            "food": food,
            "food_links": self._make_links(food, f"{name} 特色美食"),
            "lodging": lodging,
            "lodging_link": self._make_link(lodging, f"{name} 住宿") if lodging else None,
            "tips": exp.get("tips", ""),
            "timeline_events": events,
        }

    def _make_links(self, names: List[str], keyword: str) -> List[Dict[str, str]]:
        return [{"name": n, "url": self._xhs_search_url(f"{keyword} {n}")} for n in names if n]

    def _make_link(self, name: str, keyword: str) -> Optional[Dict[str, str]]:
        if not name:
            return None
        return {"name": name, "url": self._xhs_search_url(f"{keyword} {name}")}

    @staticmethod
    def _xhs_search_url(keyword: str) -> str:
        return "https://www.xiaohongshu.com/search_result?keyword=" + quote(keyword) + "&source=web_search_result_notes"

    def _summarize_daily_energy(self, stops: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        sums = {}
        for stop in stops:
            day = stop.get("day", 1)
            sums[day] = sums.get(day, 0) + int(stop.get("energy_level", 2))
        result = []
        for day in sorted(sums):
            score = sums[day]
            level = "轻松" if score <= 3 else ("适中" if score <= 6 else "较耗体力")
            result.append({"day": day, "score": score, "level": level})
        return result

    def _summarize_daily_lodging(self, stops: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        day_stops = {}
        for stop in stops:
            day_stops.setdefault(stop.get("day", 1), []).append(stop)
        result = []
        for day in sorted(day_stops):
            last = day_stops[day][-1]
            if last.get("lodging"):
                result.append({
                    "day": day,
                    "village": last.get("name", ""),
                    "lodging": last.get("lodging", ""),
                    "lodging_link": last.get("lodging_link"),
                })
        return result

    def _dedupe_villages(self, villages: List[str]) -> List[str]:
        """把坐标相同的别名村寨合并，避免生成 0 公里转场。"""
        result = []
        seen = set()
        for name in villages:
            profile = VILLAGE_COORDS.get(name)
            key = (round(profile["lat"], 4), round(profile["lng"], 4)) if profile else name
            if key not in seen:
                seen.add(key)
                result.append(name)
        return result

    def _select_compact_route(self, villages: List[str], max_stops: int, start: Optional[str] = None) -> List[str]:
        """没有明确村寨时，从候选地里选出一小簇彼此较近的村寨，避免横跨全省。"""
        villages = list(villages)
        max_stops = max(1, min(len(villages), int(max_stops or 1)))
        if len(villages) <= max_stops:
            return self._order_nearest(villages, start)

        best = None
        best_cost = float("inf")
        for anchor in villages:
            candidate = self._order_nearest(villages, anchor)[:max_stops]
            cost = self._route_cost(candidate)
            if cost < best_cost:
                best_cost = cost
                best = candidate
        return best or villages[:max_stops]

    def _route_cost(self, ordered: List[str]) -> float:
        if len(ordered) <= 1:
            return 0.0
        return sum(self._segment_travel_hours(ordered[i], ordered[i + 1]) for i in range(len(ordered) - 1))

    def _order_nearest(self, villages: List[str], start: Optional[str] = None) -> List[str]:
        remaining = list(villages)
        if not remaining:
            return []
        current = start if start in remaining else self._order_villages(remaining)[0]
        ordered = []
        while remaining:
            if current in remaining:
                remaining.remove(current)
            else:
                current = min(remaining, key=lambda v: self._haversine(
                    VILLAGE_COORDS[ordered[-1]]["lat"], VILLAGE_COORDS[ordered[-1]]["lng"],
                    VILLAGE_COORDS[v]["lat"], VILLAGE_COORDS[v]["lng"],
                ))
                remaining.remove(current)
            ordered.append(current)
            if remaining:
                current = min(remaining, key=lambda v: self._haversine(
                    VILLAGE_COORDS[current]["lat"], VILLAGE_COORDS[current]["lng"],
                    VILLAGE_COORDS[v]["lat"], VILLAGE_COORDS[v]["lng"],
                ))
        return ordered

    def _order_low_energy(self, villages: List[str], days: int) -> List[str]:
        max_stops = max(2, min(len(villages), int(days or 1) * 2))
        candidates = sorted(villages, key=lambda v: (int(VILLAGE_ENERGY.get(v, 2)), self._earliest_date(v)))
        selected = set(candidates[:max_stops])
        return [v for v in self._order_villages(villages) if v in selected]

    def _plan_reason(self, strategy: str, preferences: Dict[str, Any]) -> str:
        if strategy == "低体力精简":
            base = "每日只保留核心村寨，减少徒步和转场强度，适合亲子、老人或低体力用户。"
            if preferences.get("food_focus"):
                base += "同时突出当地特色美食。"
            return base
        if strategy == "最少车程":
            return "优先选择相邻村寨串线，减少跨地车程，适合时间紧张或不想久坐车的用户。"
        return "按长征历史时间先后串联，历史脉络最完整，适合研究者或希望系统了解长征的用户。"

    def _why_not_other_routes(self, selected_strategy: str, alt_strategy: str, preferences: Dict[str, Any]) -> List[str]:
        reasons = []
        if selected_strategy == "低体力精简":
            reasons.append("未把历史顺序作为默认：完整历史线村寨更多，每天体力消耗更高，不适合亲子或低体力出行。")
            reasons.append("未把最少车程作为默认：它会优先省路程，但可能打乱长征事件发生顺序。")
        elif selected_strategy == "最少车程":
            reasons.append("未把历史顺序作为默认：历史顺序更完整，但会增加往返车程。")
            reasons.append("未把低体力精简作为默认：你未明确要求低体力，当前方案优先减少车程。")
        else:
            reasons.append("未把低体力精简作为默认：它会减少每日村寨数量，历史覆盖不如完整历史线。")
            reasons.append("未把最少车程作为默认：它可以少坐车，但会打乱历史叙事顺序。")
        return reasons


    def _expand_single_route(self, start: str, target_days) -> List[str]:
        """从单个村寨出发时，按长征路线顺序自动扩展为多日行程。"""
        route_order = []
        for route in ROUTES:
            for lat, lng in route["points"]:
                name = self._match_village(lat, lng)
                if name and name not in route_order:
                    route_order.append(name)

        target_stops = max(1, min(int(target_days or 1), len(route_order)))
        if start not in route_order:
            others = [v for v in VILLAGE_COORDS if v != start]
            others.sort(key=lambda v: self._haversine(
                VILLAGE_COORDS[start]["lat"], VILLAGE_COORDS[start]["lng"],
                VILLAGE_COORDS[v]["lat"], VILLAGE_COORDS[v]["lng"],
            ))
            return [start] + others[:target_stops - 1]

        idx = route_order.index(start)
        expanded = [start]
        for name in route_order[idx + 1:]:
            if len(expanded) >= target_stops:
                break
            expanded.append(name)
        if len(expanded) < target_stops:
            for name in reversed(route_order[:idx]):
                if len(expanded) >= target_stops:
                    break
                expanded.append(name)
        return expanded

    def _default_route_villages(self) -> List[str]:
        ordered = []
        for route in ROUTES:
            for lat, lng in route["points"]:
                name = self._match_village(lat, lng)
                if name and name not in ordered:
                    ordered.append(name)
        return ordered

    def _validate_villages(self, villages: List[str]):
        valid = []
        unknown = []
        for name in villages:
            if name in VILLAGE_COORDS:
                valid.append(name)
            else:
                unknown.append(name)
        return valid, unknown

    def _order_villages(self, villages: List[str]) -> List[str]:
        route_order = []
        for route in ROUTES:
            for lat, lng in route["points"]:
                name = self._match_village(lat, lng)
                if name and name not in route_order:
                    route_order.append(name)

        def sort_key(name):
            route_index = route_order.index(name) if name in route_order else 999
            return route_index, self._earliest_date(name)

        return sorted(villages, key=sort_key)

    def _earliest_date(self, village: str) -> str:
        events = [e for e in TIMELINE if e.get("village") == village]
        if not events:
            return "9999-99-99"
        return events[0].get("date", "9999-99-99")

    def _visit_window(self, slot_index: int) -> str:
        if slot_index == 0:
            return "09:00-12:00"
        if slot_index == 1:
            return "14:00-17:00"
        if slot_index == 2:
            return "19:00-20:30"
        return "自由安排"

    @staticmethod
    def _place_latlng(name: str):
        """村寨或常见出发城市的经纬度；未知地点返回 None。"""
        if name in VILLAGE_COORDS:
            p = VILLAGE_COORDS[name]
            return p["lat"], p["lng"]
        if name in DEPARTURE_CITIES:
            p = DEPARTURE_CITIES[name]
            return p["lat"], p["lng"]
        return None

    def _travel_segment(self, origin: str, destination: str, mode: str = "road") -> Dict[str, Any]:
        coords = [self._place_latlng(origin), self._place_latlng(destination)]
        if not coords[0] or not coords[1]:
            return {
                "from": origin, "to": destination, "mode": mode,
                "straight_km": 0.0, "estimated_road_km": 0.0,
                "estimated_travel_hours": 0.0, "estimated_travel_time": "车程待核实",
            }
        cfg = TRANSPORT_MODES.get(mode, TRANSPORT_MODES["road"])
        p1, p2 = coords
        straight_km = self._haversine(p1[0], p1[1], p2[0], p2[1])
        line_km = round(straight_km * cfg["detour"], 1)
        hours = line_km / cfg["speed_kmh"] + cfg["overhead_h"]
        whole, mins = int(hours), round((hours - int(hours)) * 60)
        if mins == 60:
            whole, mins = whole + 1, 0
        time_text = f"{whole}小时{mins}分钟" if whole else f"{mins}分钟"
        return {
            "from": origin,
            "to": destination,
            "mode": mode,
            "mode_label": cfg["label"],
            "mode_icon": cfg["icon"],
            "straight_km": round(straight_km, 1),
            "estimated_road_km": line_km,
            "estimated_travel_hours": round(hours, 2),
            "estimated_travel_time": f"{cfg['icon']}{cfg['label']}约{time_text}",
        }

    def _choose_transport_mode(self, origin: str, destination: str, course_days: int,
                               requested: Optional[str] = None):
        """按距离和天数选择可行交通方式，返回 (mode_key, segment, 说明)。"""
        limit = OUTBOUND_LIMIT_HOURS.get(min(course_days, 3), 10.0)
        order = [requested] if requested in TRANSPORT_MODES else ["road", "rail", "air"]
        tried_notes = []
        for mode in order:
            cfg = TRANSPORT_MODES[mode]
            seg = self._travel_segment(origin, destination, mode)
            if seg["estimated_road_km"] < cfg["min_km"]:
                tried_notes.append(f"{cfg['label']}距离过短不适用")
                continue
            if seg["estimated_travel_hours"] <= limit or mode == order[-1]:
                note = ""
                if mode != "road":
                    note = (f"出发地到教学点公路车程过长，已改用{cfg['label']}"
                            f"（综合时速{int(cfg['speed_kmh'])}km/h，含接驳/候机估算）")
                if seg["estimated_travel_hours"] > limit:
                    note = (note + "；" if note else "") + \
                        f"单程仍需约{seg['estimated_travel_time']}，建议适当增加天数"
                return mode, seg, note
        # 兜底：公路
        return "road", self._travel_segment(origin, destination, "road"), ""

    def _feasible_course_sites(self, candidates: List[str], start: Optional[str],
                               course_days: int, mode: str) -> List[str]:
        """按出发距离与点间转场时长精简教学点：远距离短天数只保留最可达的一簇。"""
        if not candidates:
            return []
        transfer_limit = TRANSFER_LIMIT_HOURS.get(min(course_days, 3), 7.0)
        # 有出发地时按"离出发地最近"贪心排序，保证先留最可达的点
        if start and self._place_latlng(start):
            ordered = self._order_nearest(candidates, start) if start in candidates \
                else self._greedy_from_origin(candidates, start)
        else:
            ordered = self._order_villages(candidates)
        kept = [ordered[0]]
        for name in ordered[1:]:
            if len(kept) >= course_days:
                break
            leg = self._travel_segment(kept[-1], name, "road")
            if leg["estimated_travel_hours"] > transfer_limit:
                continue  # 转场太久，舍弃这个更远的点
            kept.append(name)
        return kept

    def _greedy_from_origin(self, villages: List[str], origin: str) -> List[str]:
        """从外部出发城市起，按最近邻贪心排序教学点。"""
        origin_xy = self._place_latlng(origin)
        remaining = list(villages)
        ordered = []
        current_xy = origin_xy
        while remaining:
            nxt = min(remaining, key=lambda v: self._haversine(
                current_xy[0], current_xy[1], *self._place_latlng(v)))
            remaining.remove(nxt)
            ordered.append(nxt)
            current_xy = self._place_latlng(nxt)
        return ordered

    def _compare_villages(
        self,
        village_a: str,
        village_b: str,
        aspect: Optional[str] = None,
    ) -> str:
        """对比两个村寨的历史档案。"""
        result = {
            "aspect": aspect or "综合对比",
            "village_a": self._village_summary(village_a),
            "village_b": self._village_summary(village_b),
        }
        return json.dumps(result, ensure_ascii=False, indent=2)

    def _village_summary(self, village: str) -> Dict[str, Any]:
        profile = VILLAGE_COORDS.get(village, {})
        if not profile:
            return {"name": village, "found": False}
        timeline = [e for e in TIMELINE if e.get("village") == village]
        kg = self.graph_store.query(entity=village, limit=5)
        return {
            "name": village,
            "found": True,
            "profile": profile,
            "timeline_events": timeline,
            "knowledge_graph": kg,
        }

    def _estimate_travel(
        self,
        origin: str,
        destination: str,
        speed_kmh: float = 50.0,
    ) -> str:
        """估算两个村寨之间的直线距离和参考驾车时间。"""
        if origin not in VILLAGE_COORDS:
            return json.dumps({"message": f"未找到起点村寨：{origin}"}, ensure_ascii=False)
        if destination not in VILLAGE_COORDS:
            return json.dumps({"message": f"未找到终点村寨：{destination}"}, ensure_ascii=False)

        p1 = VILLAGE_COORDS[origin]
        p2 = VILLAGE_COORDS[destination]
        straight_km = self._haversine(p1["lat"], p1["lng"], p2["lat"], p2["lng"])
        road_km = round(straight_km * 1.35, 1)
        speed = max(float(speed_kmh or 50.0), 1.0)
        hours = road_km / speed
        hours_text = f"{int(hours)}小时{round((hours - int(hours)) * 60)}分钟"

        return json.dumps({
            "origin": origin,
            "destination": destination,
            "straight_km": round(straight_km, 1),
            "estimated_road_km": road_km,
            "average_speed_kmh": speed,
            "estimated_travel_time": hours_text,
        }, ensure_ascii=False, indent=2)

    @staticmethod
    def _haversine(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
        r = 6371.0
        lat1, lng1, lat2, lng2 = map(math.radians, [lat1, lng1, lat2, lng2])
        dlat = lat2 - lat1
        dlng = lng2 - lng1
        a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
        return 2 * r * math.asin(math.sqrt(a))

    @staticmethod
    def _match_village(lat: float, lng: float) -> Optional[str]:
        for name, info in VILLAGE_COORDS.items():
            if abs(info["lat"] - lat) < 0.01 and abs(info["lng"] - lng) < 0.01:
                return name
        return None