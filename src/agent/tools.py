"""
智能体工具集
------------
提供可被大模型调用的结构化工具。Planner 负责生成调用计划，
ToolRegistry 负责真正执行工具，并返回可读结果。

这是把“聊天机器人”升级为“智能体”的关键：模型不只生成文字，
还能根据任务自主选择并调用工具。
"""
import json
from typing import Any, Dict, List, Optional

from . import config
from .knowledge import ROUTES, TIMELINE, VILLAGE_COORDS
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
                        "node_type": {"type": "string", "description": "???person / location / event / army"}
                    }
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
