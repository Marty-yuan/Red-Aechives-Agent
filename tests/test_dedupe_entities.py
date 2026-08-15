# -*- coding: utf-8 -*-
"""实体消歧模块单元测试"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from kg.dedupe_entities import normalize, is_hash_id, find_duplicates, merge_exact


def test_normalize():
    assert normalize("红二、六军团入滇") == normalize("红二六军团入滇")
    assert normalize("扎西 会议") == "扎西会议"
    assert normalize("") == ""


def test_is_hash_id():
    assert is_hash_id("E_8A9E70EE")
    assert not is_hash_id("E_RED26_ENTER_YUNNAN")
    assert not is_hash_id("P_001")


def test_find_duplicates():
    graph = {
        "entities": [
            {"id": "E_A", "name": "红二六军团入滇", "type": "event"},
            {"id": "E_8A9E70EE", "name": "红二、六军团入滇", "type": "event"},
            {"id": "P_B", "name": "贺龙", "type": "person"},
        ],
        "relations": [],
    }
    exact, similar = find_duplicates(graph)
    assert len(exact) == 1
    assert len(exact[0]) == 2


def test_merge_exact_keeps_manual_id():
    graph = {
        "entities": [
            {"id": "E_A", "name": "红二六军团入滇", "type": "event", "aliases": ["原别名"]},
            {"id": "E_8A9E70EE", "name": "红二、六军团入滇", "type": "event", "aliases": ["自动别名"]},
        ],
        "relations": [
            {"id": "R_1", "source": "E_8A9E70EE", "target": "P_X", "relation": "participant"},
        ],
    }
    merged = merge_exact(graph, dry_run=False)
    assert merged == 1
    ids = {e["id"] for e in graph["entities"]}
    assert ids == {"E_A"}  # 保留非哈希 id
    assert graph["relations"][0]["source"] == "E_A"  # 关系重定向
    assert "自动别名" in graph["entities"][0]["aliases"]
