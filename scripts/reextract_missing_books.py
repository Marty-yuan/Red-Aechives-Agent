# -*- coding: utf-8 -*-
"""
补抽取 LLM 抽取为 0 的档案（3 部），合并进现有 auto_extracted 与正式图谱
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR / "src"))

from datetime import datetime  # noqa: E402
from kg.extract_entities import (  # noqa: E402
    AUTO_MERGED_PATH,
    AUTO_RAW_PATH,
    BASE_GRAPH_PATH,
    GraphMerger,
    extract_from_ocr,
    load_json,
    save_json,
)

MISSING_KEYWORDS = [
    "中共楚雄党史资料",
    "中国工农红军长征过云南史",
    "乌蒙磅礴走泥丸",
]


def _match_source(name: str) -> bool:
    return any(k in name for k in MISSING_KEYWORDS)


def merge_extraction(existing: dict, new_part: dict) -> dict:
    """替换 3 部书的旧抽取结果，保留其余 15 部。"""
    kept_entities = [e for e in existing.get("entities", []) if not _match_source(e.get("source", ""))]
    kept_relations = [r for r in existing.get("relations", []) if not _match_source(r.get("source_file", ""))]
    merged = {
        "meta": {
            **existing.get("meta", {}),
            "reextract_at": datetime.now().isoformat(timespec="seconds"),
            "reextract_files": new_part.get("meta", {}).get("source_files", []),
            "entity_count": len(kept_entities) + len(new_part.get("entities", [])),
            "relation_count": len(kept_relations) + len(new_part.get("relations", [])),
        },
        "entities": kept_entities + new_part.get("entities", []),
        "relations": kept_relations + new_part.get("relations", []),
    }
    return merged


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--commit", action="store_true")
    parser.add_argument("--max-chars", type=int, default=6000)
    args = parser.parse_args()

    ocr_dir = PROJECT_DIR / "data" / "ocr_output"
    targets = [f for f in sorted(ocr_dir.glob("*.txt")) if _match_source(f.name)]
    if not targets:
        print("未找到待补抽取 OCR 文件")
        return

    print("待补抽取：")
    for f in targets:
        print(" ", f.name)

    if args.dry_run:
        return

    existing = load_json(AUTO_RAW_PATH)
    new_part = extract_from_ocr(
        mode="llm",
        max_chars_per_file=args.max_chars,
        only_patterns=MISSING_KEYWORDS,
        max_chunks_per_file=4,
    )
    print(f"新抽取: {len(new_part.get('entities', []))} 实体, {len(new_part.get('relations', []))} 关系")

    merged_raw = merge_extraction(existing, new_part)
    save_json(AUTO_RAW_PATH, merged_raw)

    base_graph = load_json(BASE_GRAPH_PATH)
    merger = GraphMerger(base_graph)
    merger.merge_entities(merged_raw.get("entities", []), "reextract")
    merger.merge_relations(merged_raw.get("relations", []), "reextract")
    merged_graph = merger.merged_graph()
    save_json(AUTO_MERGED_PATH, merged_graph)

    if args.commit:
        backup = BASE_GRAPH_PATH.with_suffix(f".json.bak_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
        save_json(backup, base_graph)
        save_json(BASE_GRAPH_PATH, merged_graph)
        print(f"已提交图谱，备份: {backup.name}")
    else:
        print(f"预览: {AUTO_MERGED_PATH}（加 --commit 写入正式图谱）")

    # 校验
    subprocess.check_call([sys.executable, str(PROJECT_DIR / "src" / "kg" / "build_graph.py"), "validate"], cwd=str(PROJECT_DIR))


if __name__ == "__main__":
    main()
