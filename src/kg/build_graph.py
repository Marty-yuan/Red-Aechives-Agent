"""
档案知识图谱构建 / 校验脚本
--------------------------
用法：
    python src/kg/build_graph.py validate
    python src/kg/build_graph.py summary

说明：
    - 当前图谱 MVP 的数据源是 `data/knowledge_graph/knowledge_graph.json`。
    - 本脚本负责校验所有关系的实体 ID 是否存在，并输出图谱概况。
    - 后续如果要从 OCR 文本中自动抽取实体，建议把抽取结果写入同样的 JSON
      结构，本脚本可以继续作为质量检查入口。
"""
import json
import os
import sys
from typing import Dict, List


PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GRAPH_PATH = os.path.join(PROJECT_DIR, "data", "knowledge_graph", "knowledge_graph.json")


def load_graph(path: str) -> Dict:
    """读取图谱 JSON。"""
    with open(path, "r", encoding="utf-8-sig") as f:
        return json.load(f)


def validate_graph(graph: Dict) -> List[str]:
    """校验节点和关系引用，返回所有问题列表。"""
    problems = []
    entities = graph.get("entities", [])
    relations = graph.get("relations", [])

    ids = {e.get("id") for e in entities}
    if len(ids) != len(entities):
        problems.append("存在重复的实体 id")

    for rel in relations:
        source = rel.get("source")
        target = rel.get("target")
        if source not in ids:
            problems.append(f"关系 {rel.get('id', '?')} 的 source 不存在：{source}")
        if target not in ids:
            problems.append(f"关系 {rel.get('id', '?')} 的 target 不存在：{target}")
        if not rel.get("relation"):
            problems.append(f"关系 {rel.get('id', '?')} 缺少 relation")

    return problems


def summary(graph: Dict) -> Dict:
    """统计图谱概况。"""
    entities = graph.get("entities", [])
    relations = graph.get("relations", [])
    node_types = {}
    for e in entities:
        t = e.get("type", "unknown")
        node_types[t] = node_types.get(t, 0) + 1

    return {
        "graph_path": GRAPH_PATH,
        "entity_count": len(entities),
        "relation_count": len(relations),
        "node_types": node_types,
        "relation_types": sorted({r.get("relation") for r in relations if r.get("relation")}),
    }


def main() -> None:
    if not os.path.exists(GRAPH_PATH):
        print(f"未找到图谱文件：{GRAPH_PATH}")
        sys.exit(1)

    graph = load_graph(GRAPH_PATH)
    command = sys.argv[1] if len(sys.argv) > 1 else "summary"

    if command == "validate":
        problems = validate_graph(graph)
        if problems:
            print("发现以下问题：")
            for p in problems:
                print(" -", p)
            sys.exit(1)
        print("图谱校验通过：所有实体引用均有效。")
        return

    print(json.dumps(summary(graph), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
