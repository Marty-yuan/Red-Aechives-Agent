# -*- coding: utf-8 -*-
"""
自动生成数据统计文档
--------------------
从 data/ 下的结构化资产与 src/knowledge/ocr_fixes.py 读取真实数字，
生成 docs/数据统计.md，避免 README / 交付报告里的统计数字与数据脱节。

用法（项目根目录下）：
    python scripts/update_stats.py

约定：README、交付报告中涉及"实体数 / 关系数 / 篇目条数 / 纠错表条数 /
评测指标"的数字，以本脚本的输出为准；数据更新后重跑一次即可同步。
"""
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR / "src"))

KG_PATH = PROJECT_DIR / "data" / "knowledge_graph" / "knowledge_graph.json"
TOC_PATH = PROJECT_DIR / "data" / "knowledge_graph" / "book_toc.json"
EVAL_SET_PATH = PROJECT_DIR / "data" / "eval" / "eval_set.json"
EVAL_RESULTS_PATH = PROJECT_DIR / "data" / "eval" / "eval_results.json"
INDEX_DIR = PROJECT_DIR / "data" / "index"
OUT_PATH = PROJECT_DIR / "docs" / "数据统计.md"

ENTITY_TYPE_LABELS = {
    "person": "人物",
    "location": "地点",
    "event": "事件",
    "army": "部队",
    "organization": "组织",
    "document": "文献",
    "other": "其他",
}


def count_ocr_fixes() -> int:
    from knowledge.ocr_fixes import OCR_FIXES

    # 与 apply_fixes 的语义一致：空串或 wrong == right 的条目不生效
    return sum(1 for wrong, right in OCR_FIXES if wrong and wrong != right)


def graph_stats() -> dict:
    kg = json.loads(KG_PATH.read_text(encoding="utf-8"))
    entities = kg.get("entities", [])
    relations = kg.get("relations", [])

    entity_ids = {e.get("id") for e in entities}
    dangling = sum(
        1 for r in relations
        if r.get("source") not in entity_ids or r.get("target") not in entity_ids
    )
    return {
        "entities": len(entities),
        "relations": len(relations),
        "type_counts": Counter(e.get("type", "other") for e in entities),
        "dangling": dangling,
    }


def toc_stats() -> dict:
    toc = json.loads(TOC_PATH.read_text(encoding="utf-8"))
    return {"books": len(toc), "entries": sum(len(v) for v in toc.values())}


def eval_stats() -> dict:
    stats = {}
    eval_set = json.loads(EVAL_SET_PATH.read_text(encoding="utf-8"))
    stats["questions"] = len(eval_set.get("questions", []))

    results = json.loads(EVAL_RESULTS_PATH.read_text(encoding="utf-8"))
    comparison = results.get("comparison", {})
    stats["metrics"] = {
        name: {
            "label": payload.get("label", name),
            "hit1": payload.get("hit_rate", {}).get("1"),
            "mrr": payload.get("mrr"),
        }
        for name, payload in comparison.items()
    }
    return stats


def index_stats() -> str:
    if not INDEX_DIR.exists():
        return "未构建（本地缺失 data/index，运行 `python src/knowledge/rebuild_index.py` 生成）"
    chunks = list(INDEX_DIR.glob("*.json")) + list(INDEX_DIR.glob("*.pkl"))
    return f"存在 {len(chunks)} 个索引文件（详细 chunk 数以重建日志为准）"


def render_markdown(stats: dict) -> str:
    g, t, ev = stats["graph"], stats["toc"], stats["eval"]
    lines = [
        "# 数据统计（自动生成）",
        "",
        f"> 本文件由 `python scripts/update_stats.py` 生成于 {datetime.now().strftime('%Y-%m-%d %H:%M')}，"
        "请勿手改；README 与交付报告中的统计数字以本文件为准。",
        "",
        "## 知识图谱（data/knowledge_graph/knowledge_graph.json）",
        "",
        f"- 实体：**{g['entities']}** 个",
    ]
    for etype, label in ENTITY_TYPE_LABELS.items():
        if g["type_counts"].get(etype):
            lines.append(f"  - {label}（{etype}）：{g['type_counts'][etype]}")
    lines += [
        f"- 关系：**{g['relations']}** 条（悬挂关系：{g['dangling']} 条，应为 0）",
        "",
        "## 档案篇目目录（data/knowledge_graph/book_toc.json）",
        "",
        f"- 书目：**{t['books']}** 部",
        f"- 篇目-页码条目：**{t['entries']}** 条",
        "",
        "## OCR 纠错表（src/knowledge/ocr_fixes.py）",
        "",
        f"- 有效条目：**{stats['ocr_fixes']}** 条（不含 wrong == right 的无效项）",
        "",
        "## 检索评测（data/eval/）",
        "",
        f"- 评测集：{ev['questions']} 题",
    ]
    for name, m in ev["metrics"].items():
        hit1 = f"{m['hit1']:.1%}" if m["hit1"] is not None else "N/A"
        mrr = f"{m['mrr']:.4f}" if m["mrr"] is not None else "N/A"
        lines.append(f"- {m['label']}：hit@1 **{hit1}**，MRR **{mrr}**")
    lines += [
        "",
        "## 档案索引（data/index/）",
        "",
        f"- {stats['index']}",
        "",
        "---",
        "",
        "*评测判定为关键词弱标注（详见 docs/检索评测报告.md），指标用于横向对比而非绝对精度。*",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    stats = {
        "graph": graph_stats(),
        "toc": toc_stats(),
        "ocr_fixes": count_ocr_fixes(),
        "eval": eval_stats(),
        "index": index_stats(),
    }
    OUT_PATH.write_text(render_markdown(stats), encoding="utf-8")
    print(f"已生成 {OUT_PATH}")
    print(f"  图谱：{stats['graph']['entities']} 实体 / {stats['graph']['relations']} 关系"
          f"（悬挂 {stats['graph']['dangling']}）")
    print(f"  目录：{stats['toc']['books']} 部 / {stats['toc']['entries']} 条")
    print(f"  纠错表：{stats['ocr_fixes']} 条")
    print(f"  评测：{stats['eval']['questions']} 题")


if __name__ == "__main__":
    main()
