"""
档案知识图谱存储层
------------------
把云南红军长征档案中的人物、地点、部队、事件组织成结构化图数据。

设计目标：
    1. 让智能体不只是“检索文本”，还能回答“谁指挥了哪场事件”“事件发生地
       在哪里”“事件之间的先后关系是什么”这类图谱查询问题。
    2. 同一份数据既可以被 Agent 工具调用，也可以被 Web 前端绘制成可视化图。
    3. 后续如果要从 OCR 文本自动抽取实体，只需要替换 / 扩展 JSON 数据源，
       上层查询接口保持不变。
"""
import json
import os
from typing import Any, Dict, List, Optional


class KnowledgeGraphStore:
    """加载并查询档案知识图谱。"""

    def __init__(self, graph_path: Optional[str] = None):
        """
        参数:
            graph_path: 图谱 JSON 文件路径。默认优先使用项目 data 目录，
                        其次回退到本文件同级的 data 目录。
        """
        self.graph_path = graph_path or self._default_graph_path()
        self.graph = self._load_graph()
        self._entity_by_id = {e["id"]: e for e in self.graph.get("entities", [])}

    @staticmethod
    def _default_graph_path() -> str:
        """推断图谱 JSON 的默认路径。"""
        candidates = []

        # 1. 从环境变量读取，便于部署时指定
        env_path = os.environ.get("ARCHIVE_KNOWLEDGE_GRAPH_PATH")
        if env_path:
            candidates.append(env_path)

        # 2. 项目根目录下的 data/knowledge_graph/knowledge_graph.json
        current_dir = os.path.dirname(os.path.abspath(__file__))
        project_dir = os.path.dirname(os.path.dirname(current_dir))
        candidates.append(os.path.join(project_dir, "data", "knowledge_graph", "knowledge_graph.json"))

        # 3. 兼容旧的 D 盘部署路径（仅当 RED_ARCHIVE_PROJECT_DIR 被显式设置时）
        legacy_env = os.environ.get("RED_ARCHIVE_PROJECT_DIR")
        if legacy_env:
            candidates.append(os.path.join(legacy_env, "data", "knowledge_graph", "knowledge_graph.json"))

        for path in candidates:
            if os.path.exists(path):
                return path

        # 默认返回项目路径；如果文件不存在，调用方会得到清晰的空数据
        return candidates[1] if len(candidates) > 1 else candidates[0]

    def _load_graph(self) -> Dict[str, Any]:
        """读取图谱 JSON，文件缺失时返回空图而不是让整个服务崩溃。"""
        if not self.graph_path or not os.path.exists(self.graph_path):
            return {"meta": {"error": "knowledge_graph.json not found"}, "entities": [], "relations": []}

        try:
            with open(self.graph_path, "r", encoding="utf-8-sig") as f:
                data = json.load(f)
        except Exception as e:
            return {"meta": {"error": str(e)}, "entities": [], "relations": []}

        data.setdefault("entities", [])
        data.setdefault("relations", [])
        return data

    # ===================== 图谱查询 =====================
    def query(
        self,
        topic: Optional[str] = None,
        entity: Optional[str] = None,
        relation: Optional[str] = None,
        event: Optional[str] = None,
        year: Optional[int] = None,
        limit: int = 10,
    ) -> Dict[str, Any]:
        """
        查询与指定实体、事件或主题相关的图谱邻居。

        参数:
            topic:    模糊主题，例如“金沙江”“贺龙”“1936”
            entity:   实体名称，例如“皎平渡”
            relation: 关系类型，例如 next_on_route / commander / occurred_at
            event:    事件名称，例如“扎西会议”
            year:     年份，例如 1935 或 1936
            limit:    最多返回多少条关系

        返回:
            可被 LLM 阅读的结构化结果，包含命中节点、邻居节点和关系列表。
        """
        relations = self.graph.get("relations", [])
        entities = self.graph.get("entities", [])
        by_id = self._entity_by_id

        # 1. 确定种子节点
        seeds: List[str] = []
        for item in entities:
            node_id = item.get("id", "")
            name = item.get("name", "")
            aliases = item.get("aliases", [])
            searchable = [name] + list(aliases)

            matched = False
            if entity and any(entity == s for s in searchable):
                matched = True
            if event and item.get("type") == "event" and any(event in s for s in searchable):
                matched = True
            if topic and any(topic in s or topic in item.get("description", "") for s in searchable):
                matched = True
            if year is not None:
                node_year = item.get("properties", {}).get("year")
                if str(node_year) == str(year):
                    matched = True
            if matched:
                seeds.append(node_id)

        # 2. 如果没有命中种子，则返回空结果
        if not seeds:
            return self._build_result(
                nodes=[],
                relations=[],
                message="图谱中未命中指定实体，请尝试更具体的人名、地名或事件名。",
            )

        # 3. 找出与种子节点直接相连的关系
        seed_set = set(seeds)
        matched_relations = []
        for rel in relations:
            if rel.get("source") in seed_set or rel.get("target") in seed_set:
                matched_relations.append(rel)

        # 4. 按关系类型过滤
        if relation:
            matched_relations = [r for r in matched_relations if r.get("relation") == relation]

        # 5. 限制数量，并把相关邻居节点也带回
        matched_relations = matched_relations[: max(1, int(limit))]
        neighbor_ids: set = set()
        for rel in matched_relations:
            neighbor_ids.add(rel.get("source", ""))
            neighbor_ids.add(rel.get("target", ""))

        result_nodes = [by_id[nid] for nid in neighbor_ids if nid in by_id]
        return self._build_result(nodes=result_nodes, relations=matched_relations)

    def list_nodes(self, node_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """列出节点摘要，可选的 node_type 为 person/location/event/army。"""
        nodes = self.graph.get("entities", [])
        if node_type:
            nodes = [n for n in nodes if n.get("type") == node_type]

        return [
            {
                "id": n.get("id", ""),
                "type": n.get("type", ""),
                "name": n.get("name", ""),
                "description": n.get("description", ""),
                "aliases": n.get("aliases", []),
                "properties": n.get("properties", {}),
            }
            for n in nodes
        ]

    def get_graph(self) -> Dict[str, Any]:
        """返回前端可视化所需的完整图数据。"""
        return {
            "meta": self.graph.get("meta", {}),
            "nodes": [
                {
                    "id": n.get("id", ""),
                    "type": n.get("type", ""),
                    "name": n.get("name", ""),
                    "description": n.get("description", ""),
                    "properties": n.get("properties", {}),
                }
                for n in self.graph.get("entities", [])
            ],
            "edges": [
                {
                    "id": r.get("id", ""),
                    "source": r.get("source", ""),
                    "target": r.get("target", ""),
                    "relation": r.get("relation", ""),
                    "label": r.get("label", r.get("relation", "")),
                    "properties": r.get("properties", {}),
                }
                for r in self.graph.get("relations", [])
            ],
        }

    def describe(self) -> Dict[str, Any]:
        """返回图谱概况，便于工具向 LLM 报告可查询范围。"""
        return {
            "entity_count": len(self.graph.get("entities", [])),
            "relation_count": len(self.graph.get("relations", [])),
            "node_types": {
                t: sum(1 for n in self.graph.get("entities", []) if n.get("type") == t)
                for t in {n.get("type") for n in self.graph.get("entities", [])}
            },
            "relation_types": sorted(
                {r.get("relation") for r in self.graph.get("relations", []) if r.get("relation")}
            ),
        }

    @staticmethod
    def _build_result(
        nodes: List[Dict[str, Any]],
        relations: List[Dict[str, Any]],
        message: Optional[str] = None,
    ) -> Dict[str, Any]:
        """统一工具查询的返回格式。"""
        result: Dict[str, Any] = {
            "nodes": nodes,
            "relations": relations,
        }
        if message:
            result["message"] = message
        return result


def query_knowledge_graph(
    topic: Optional[str] = None,
    entity: Optional[str] = None,
    relation: Optional[str] = None,
    event: Optional[str] = None,
    year: Optional[int] = None,
    limit: int = 10,
) -> str:
    """
    工具入口：查询知识图谱，返回 JSON 字符串。

    该函数独立于 ToolRegistry，方便在 Web API 或命令行中单独复用。
    """
    store = KnowledgeGraphStore()
    result = store.query(
        topic=topic,
        entity=entity,
        relation=relation,
        event=event,
        year=year,
        limit=limit,
    )
    return json.dumps(result, ensure_ascii=False, indent=2)


def get_graph_payload() -> Dict[str, Any]:
    """工具入口：返回完整图数据，供前端可视化。"""
    return KnowledgeGraphStore().get_graph()


if __name__ == "__main__":
    # 方便在 VS Code 中直接运行验证图谱加载是否正常
    store = KnowledgeGraphStore()
    print(json.dumps(store.describe(), ensure_ascii=False, indent=2))
