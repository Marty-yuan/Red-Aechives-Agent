# -*- coding: utf-8 -*-
"""
知识图谱实体消歧脚本
--------------------
检测并合并图谱中的同名 / 近名实体（A 部分"实体链接"待办）。

用法：
    # 只报告候选，不修改数据
    python src/kg/dedupe_entities.py

    # 自动合并"规范化后完全同名"的实体（安全操作）
    python src/kg/dedupe_entities.py --merge exact

    # 连同高相似度近名实体一起合并（需人工确认候选后再用）
    python src/kg/dedupe_entities.py --merge all --similarity 0.85

规则：
    - exact   : 名称去除空格/标点/繁简差异后完全一致 → 自动合并
    - similar : 字符相似度 >= 阈值 → 报告候选（默认不自动合并）
    - 合并时保留"手工实体"（id 非哈希），关系重定向到保留实体
    - 泛化实体（如"长征"）只报告，不自动删除
"""
import argparse
import json
import os
import re
import sys
from difflib import SequenceMatcher
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[2]
GRAPH_PATH = PROJECT_DIR / "data" / "knowledge_graph" / "knowledge_graph.json"


def normalize(name: str) -> str:
    """名称规范化：全角转半角、去空格与标点，用于同名比较。"""
    if not name:
        return ""
    s = name
    # 全角转半角
    s = "".join(chr(ord(c) - 0xFEE0) if 0xFF01 <= ord(c) <= 0xFF5E else c for c in s)
    s = s.replace("　", " ")
    # 去掉常见分隔/标点（引号、书名号等对名称比较无意义，一并去除）
    s = re.sub(r"[\s、，。．·（）()\-—_/《》「」『』]", "", s)
    return s


def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def is_hash_id(eid: str) -> bool:
    """自动抽取实体使用 8 位大写十六进制哈希 id（如 E_8A9E70EE）。"""
    m = re.match(r"^[A-Z]_[0-9A-F]{8}$", eid or "")
    return bool(m)


def find_duplicates(graph):
    entities = graph.get("entities", [])
    by_norm = {}
    for e in entities:
        key = normalize(e.get("name", ""))
        by_norm.setdefault(key, []).append(e)

    exact_pairs = []   # 规范化同名
    for key, group in by_norm.items():
        if len(group) > 1 and key:
            exact_pairs.append(group)

    similar_pairs = []  # 近名
    names = [(e.get("id"), e.get("name", "")) for e in entities if e.get("name")]
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            id1, n1 = names[i]
            id2, n2 = names[j]
            if normalize(n1) == normalize(n2):
                continue  # 已归为同名
            sim = similarity(normalize(n1), normalize(n2))
            if sim >= 0.8 and min(len(n1), len(n2)) >= 2:
                similar_pairs.append((id1, n1, id2, n2, round(sim, 3)))

    return exact_pairs, similar_pairs


def merge_exact(graph, dry_run: bool = True):
    """合并规范化同名实体；保留非哈希 id 的实体，关系重定向。"""
    exact_pairs, _ = find_duplicates(graph)
    if not exact_pairs:
        print("未发现同名实体。")
        return 0

    removed = 0
    for group in exact_pairs:
        # 保留规则：优先非哈希 id（手工实体），否则保留第一个
        keep = next((e for e in group if not is_hash_id(e.get("id", ""))), group[0])
        keep_id = keep.get("id", "")
        keep_name = keep.get("name", "")
        for e in group:
            if e.get("id") == keep_id:
                continue
            eid = e.get("id", "")
            ename = e.get("name", "")
            # 合并 aliases / properties
            for alias in e.get("aliases", []):
                if alias not in keep.setdefault("aliases", []):
                    keep["aliases"].append(alias)
            props = keep.setdefault("properties", {})
            for k, v in (e.get("properties") or {}).items():
                props.setdefault(k, v)
            if dry_run:
                print(f"  [DRY] 合并 {ename}({eid}) -> {keep_name}({keep_id})")
            else:
                print(f"  合并 {ename}({eid}) -> {keep_name}({keep_id})")
            removed += 1

    if dry_run:
        return removed

    # 重定向关系 + 删除被合并实体
    remove_ids = set()
    for group in exact_pairs:
        keep = next((e for e in group if not is_hash_id(e.get("id", ""))), group[0])
        for e in group:
            if e.get("id") != keep.get("id"):
                remove_ids.add(e.get("id", ""))

    rels = graph.get("relations", [])
    for rel in rels:
        for key in ("source", "target"):
            if rel.get(key) in remove_ids:
                # 找到保留实体
                for group in exact_pairs:
                    keep = next((e for e in group if not is_hash_id(e.get("id", ""))), group[0])
                    if any(e.get("id") == rel.get(key) for e in group):
                        rel[key] = keep.get("id")
                        break

    graph["entities"] = [e for e in graph.get("entities", []) if e.get("id") not in remove_ids]
    return removed


def main():
    ap = argparse.ArgumentParser(description="知识图谱实体消歧")
    ap.add_argument("--merge", choices=["exact", "all"], default=None,
                    help="exact: 合并规范化同名实体；all: 连近名一起（慎用）")
    ap.add_argument("--similarity", type=float, default=0.85)
    ap.add_argument("--graph", default=str(GRAPH_PATH))
    args = ap.parse_args()

    with open(args.graph, "r", encoding="utf-8-sig") as f:
        graph = json.load(f)

    exact_pairs, similar_pairs = find_duplicates(graph)

    print("=" * 60)
    print("同名实体组（规范化后名称一致）:")
    if exact_pairs:
        for group in exact_pairs:
            print("  组:", " | ".join(f"{e.get('name')}({e.get('id')})" for e in group))
    else:
        print("  无")

    print()
    print("=" * 60)
    print(f"近名实体候选（相似度 >= {args.similarity}）:")
    shown = 0
    for id1, n1, id2, n2, sim in similar_pairs:
        if sim >= args.similarity:
            print(f"  {n1} <-> {n2}  (sim={sim})")
            shown += 1
    if not shown:
        print("  无")

    # 泛化实体提示
    generic = [e for e in graph.get("entities", []) if normalize(e.get("name", "")) in ("长征", "红军")]
    if generic:
        print()
        print("泛化/低价值实体（建议人工确认后删除）:")
        for e in generic:
            print(f"  {e.get('name')}({e.get('id')}) type={e.get('type')}")

    if args.merge:
        print()
        print("=" * 60)
        if args.merge == "exact":
            merged = merge_exact(graph, dry_run=False)
            print(f"合并完成，共合并 {merged} 个实体")
        else:
            print("--merge all 暂未实现自动近名合并，请人工处理近名候选。")
        # 写回
        with open(args.graph, "w", encoding="utf-8") as f:
            json.dump(graph, f, ensure_ascii=False, indent=2)
        print(f"已写回: {args.graph}  (entities={len(graph.get('entities', []))}, relations={len(graph.get('relations', []))})")
    else:
        print()
        print("（仅报告模式。确认无误后运行 --merge exact 自动合并同名实体）")


if __name__ == "__main__":
    main()
