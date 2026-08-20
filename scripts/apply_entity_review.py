# -*- coding: utf-8 -*-
"""
应用 36 条存疑实体的人工复核结论
--------------------------------
读取 data/knowledge_graph/review_decisions.json，对 knowledge_graph.json 执行：
  - approve：保留并清除 review 标记
  - rename：更新 name / canonical_name，同步关系端点名称索引
  - remove：删除实体及其关联关系

用法：
    python scripts/apply_entity_review.py
    python scripts/apply_entity_review.py --dry-run
"""
from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
KG_DIR = PROJECT_DIR / "data" / "knowledge_graph"
GRAPH_PATH = KG_DIR / "knowledge_graph.json"
DECISIONS_PATH = KG_DIR / "review_decisions.json"
REVIEW_PATH = KG_DIR / "review_required.json"


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8-sig") as f:
        return json.load(f)


def save_json(path: Path, data: dict) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def entity_key(entity: dict) -> str:
    return str(entity.get("name", "")).strip()


def apply_decisions(graph: dict, decisions: list[dict], dry_run: bool = False) -> dict:
    by_name = {d["name"]: d for d in decisions}
    entities = graph.get("entities", [])
    relations = graph.get("relations", [])

    removed_ids: set[str] = set()
    rename_map: dict[str, str] = {}
    stats = {"approve": 0, "rename": 0, "remove": 0, "missing": 0}

    new_entities = []
    for entity in entities:
        name = entity_key(entity)
        decision = by_name.get(name)
        if not decision:
            new_entities.append(entity)
            continue

        action = decision["action"]
        if action == "approve":
            entity.pop("status", None)
            entity.pop("review_reason", None)
            entity["review_status"] = "approved"
            new_entities.append(entity)
            stats["approve"] += 1
        elif action == "rename":
            new_name = decision.get("canonical_name") or decision.get("new_name")
            if not new_name:
                raise ValueError(f"rename 缺少 canonical_name: {name}")
            rename_map[name] = new_name
            entity["name"] = new_name
            entity["review_status"] = "renamed"
            entity.pop("status", None)
            new_entities.append(entity)
            stats["rename"] += 1
        elif action == "remove":
            removed_ids.add(entity.get("id", ""))
            stats["remove"] += 1
        else:
            raise ValueError(f"未知 action: {action}")

    for d in decisions:
        if d["name"] not in {entity_key(e) for e in entities}:
            stats["missing"] += 1

    # 关系端点若被删则整条删除；rename 需同步关系里的名称引用（图谱用 id，一般不用改）
    new_relations = [
        r for r in relations
        if r.get("source") not in removed_ids and r.get("target") not in removed_ids
    ]

    graph["entities"] = new_entities
    graph["relations"] = new_relations
    graph.setdefault("meta", {})
    graph["meta"]["review_applied_at"] = datetime.now().isoformat(timespec="seconds")
    graph["meta"]["review_required_count"] = 0
    graph["meta"]["entity_count"] = len(new_entities)
    graph["meta"]["relation_count"] = len(new_relations)
    if rename_map:
        graph["meta"]["entity_renames"] = rename_map

    return stats


def update_review_file(decisions: list[dict]) -> None:
    remaining = []
    resolved_names = {d["name"] for d in decisions}
    if REVIEW_PATH.exists():
        review = load_json(REVIEW_PATH)
        for item in review.get("entities", []):
            if item.get("name") not in resolved_names:
                remaining.append(item)
        review["entities"] = remaining
        review.setdefault("meta", {})["review_required_count"] = len(remaining)
        review["meta"]["resolved_at"] = datetime.now().isoformat(timespec="seconds")
        save_json(REVIEW_PATH, review)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not DECISIONS_PATH.exists():
        raise SystemExit(f"未找到复核结论：{DECISIONS_PATH}")

    graph = load_json(GRAPH_PATH)
    decisions_data = load_json(DECISIONS_PATH)
    decisions = decisions_data["decisions"]

    stats = apply_decisions(graph, decisions, dry_run=args.dry_run)
    print("复核统计:", stats)

    if args.dry_run:
        print("dry-run 模式，未写入文件")
        return

    backup = GRAPH_PATH.with_suffix(f".json.bak_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    shutil.copy2(GRAPH_PATH, backup)
    save_json(GRAPH_PATH, graph)
    update_review_file(decisions)
    print(f"已备份: {backup.name}")
    print(f"已更新: {GRAPH_PATH}")
    print(f"已清空 review_required（剩余见 {REVIEW_PATH.name}）")


if __name__ == "__main__":
    main()
