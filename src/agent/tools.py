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
from typing import Any, Dict, List, Optional

from . import config
from .knowledge import ROUTES, TIMELINE, VILLAGE_COORDS, VILLAGE_EXPERIENCE
from .graph_store import KnowledgeGraphStore
from .retriever import ArchiveRetriever


class ToolRegistry:
    """工具注册与执行器。"""

    def __init__(self, retriever: Optional[ArchiveRetriever] = None):
        self.retriever = retriever or ArchiveRetriever()
        self.graph_store = KnowledgeGraphStore()

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
                "description": "根据村寨、天数和主题生成红色研学路线，返回每天的参观点、事件、年份和部队。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "villages": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "可选，指定村寨名称列表，例如：[\"扎西\", \"皎平渡\", \"石鼓\"]"
                        },
                        "days": {"type": "integer", "description": "可选，计划天数，默认按村寨数量自动估算"},
                        "theme": {"type": "string", "description": "可选，主题，例如：中央红军、红二六军团、渡江战役、扎西会议"},
                        "start": {"type": "string", "description": "可选，起点村寨"}
                    }
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
    ) -> str:
        """生成结构更完整的研学路线：时间、景点、美食、交通。"""
        if isinstance(villages, str):
            villages = [v.strip() for v in villages.replace("，", ",").split(",") if v.strip()]
        if not isinstance(villages, list):
            villages = []

        if start and start not in villages:
            villages.insert(0, start)

        if not villages:
            villages = self._default_route_villages()

        valid, unknown = self._validate_villages(villages)
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

        ordered = self._order_villages(valid)
        stop_count = len(ordered)
        days = max(1, min(int(days or math.ceil(stop_count / 2)), stop_count))
        per_day = math.ceil(stop_count / days)

        stops = []
        for idx, name in enumerate(ordered):
            day = min(days, idx // per_day + 1)
            slot_index = idx % per_day
            profile = VILLAGE_COORDS[name]
            exp = VILLAGE_EXPERIENCE.get(name, {})
            events = [e for e in TIMELINE if e.get("village") == name]
            stops.append({
                "day": day,
                "order": idx + 1,
                "name": name,
                "city": profile.get("city", ""),
                "event": profile.get("event", ""),
                "year": profile.get("year", ""),
                "army": profile.get("army", ""),
                "lat": profile.get("lat"),
                "lng": profile.get("lng"),
                "visit_time": self._visit_window(slot_index),
                "duration_hours": exp.get("duration_hours", 3),
                "attractions": exp.get("attractions", []),
                "food": exp.get("food", []),
                "tips": exp.get("tips", ""),
                "timeline_events": events,
            })

        travel_segments = []
        for i in range(len(ordered) - 1):
            travel_segments.append(self._travel_segment(ordered[i], ordered[i + 1]))

        return json.dumps({
            "route_name": f"{theme or '云南红军长征'}红色研学路线",
            "days": days,
            "stop_count": stop_count,
            "stops": stops,
            "travel_segments": travel_segments,
            "unknown_villages": unknown,
        }, ensure_ascii=False, indent=2)

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

    def _travel_segment(self, origin: str, destination: str) -> Dict[str, Any]:
        p1 = VILLAGE_COORDS[origin]
        p2 = VILLAGE_COORDS[destination]
        straight_km = self._haversine(p1["lat"], p1["lng"], p2["lat"], p2["lng"])
        road_km = round(straight_km * 1.35, 1)
        speed = 50.0
        hours = road_km / speed
        return {
            "from": origin,
            "to": destination,
            "straight_km": round(straight_km, 1),
            "estimated_road_km": road_km,
            "estimated_travel_time": f"{int(hours)}小时{round((hours - int(hours)) * 60)}分钟",
        }

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