"""
OCR 实体自动校验器
------------------
解决“资料没看过、人工复核困难”的问题：

1. 规则校验：统计实体在 OCR 中出现的频次，低频实体自动标记为存疑。
2. LLM 校验：让 DeepSeek 判断每个 OCR 实体是否为真实历史人物/地点/部队/事件，
   并给出规范名、类型、状态和置信度。
3. 自动合并：只把 confirmed 实体和关系写入 clean 图谱；
   suspicious 单独导出，方便你只处理极少数存疑项。

用法：
    # 规则模式（不需要 API）
    python src/kg/validate_entities.py --mode rule

    # DeepSeek 自动校验
    python src/kg/validate_entities.py --mode llm

    # 校验并正式提交 clean 图谱
    python src/kg/validate_entities.py --mode llm --commit

输出：
    data/knowledge_graph/validated_entities.json   # 全部校验结果
    data/knowledge_graph/review_required.json      # 仅存疑项
    data/knowledge_graph/knowledge_graph_clean.json # 基础图谱 + 确认实体
"""
import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# 把 src 加入 sys.path，便于导入 kg 包和 agent 配置
SRC_DIR = Path(__file__).resolve().parents[1]
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from agent import config  # noqa: E402
from kg.extract_entities import (  # noqa: E402
    GraphMerger,
    coerce_entity_type,
    load_json,
    normalize_name,
    parse_llm_json,
    save_json,
)

PROJECT_DIR = Path(os.environ.get("RED_ARCHIVE_PROJECT_DIR") or config.PROJECT_DIR)
if not PROJECT_DIR.exists():
    PROJECT_DIR = SRC_DIR.parent

KG_DIR = PROJECT_DIR / "data" / "knowledge_graph"
BASE_GRAPH_PATH = KG_DIR / "knowledge_graph.json"
RAW_PATH = KG_DIR / "auto_extracted.json"
VALIDATED_PATH = KG_DIR / "validated_entities.json"
REVIEW_PATH = KG_DIR / "review_required.json"
CLEAN_PATH = KG_DIR / "knowledge_graph_clean.json"


class RuleValidator:
    """基于频次和命名规则做基础校验。"""

    def validate(self, entities: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        counts = Counter(normalize_name(e.get("name", "")) for e in entities)
        results = []

        for entity in entities:
            name = str(entity.get("name", "")).strip()
            key = normalize_name(name)
            frequency = counts.get(key, 0)
            issues = []

            if len(name) < 2:
                issues.append("名称过短")
            if len(name) > 24:
                issues.append("名称过长")
            if re.search(r"[0-9]{4,}", name):
                issues.append("名称包含连续数字")
            if frequency == 1:
                issues.append("仅出现一次，可能是 OCR 噪声")

            status = "suspicious" if issues else "confirmed"
            confidence = 0.85 if frequency >= 2 else 0.55

            item = dict(entity)
            item["status"] = status
            item["issues"] = issues
            item["frequency"] = frequency
            item["confidence"] = float(entity.get("confidence", confidence))
            item["canonical_name"] = name
            results.append(item)

        return results


class LLMValidator:
    """调用 DeepSeek 判断实体真实性，并给出规范名。"""

    def __init__(self):
        from openai import OpenAI

        self.client = OpenAI(
            api_key=config.DEEPSEEK_API_KEY,
            base_url=config.BASE_URL,
        )

    def validate_batch(self, entities: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """校验一批实体，返回带 status 的实体列表。"""
        brief_items = []
        for entity in entities:
            brief_items.append({
                "original_name": entity.get("name", ""),
                "type": entity.get("type", ""),
                "description": (entity.get("description") or "")[:120],
                "evidence": (entity.get("evidence") or "")[:160],
            })

        system_prompt = (
            "你是云南红军长征档案的实体校验专家。\n"
            "任务：判断 OCR 识别出的实体是否是真实历史人物、地点、部队或事件，并给出规范名。\n"
            "注意：OCR 经常把历史人名写错，例如“甘油淇”应规范为“甘泗淇”。\n"
            "如果实体是明确的历史人物/地点/事件，status 用 confirmed，并给出 canonical_name。\n"
            "如果实体看起来像真实名称但 OCR 写法不确定，status 用 suspicious。\n"
            "如果明显不是实体或只是普通词汇，status 用 reject。\n"
            "只返回 JSON，不要输出 Markdown。"
        )

        user_prompt = (
            "请校验下面这些 OCR 实体：\n"
            + json.dumps(brief_items, ensure_ascii=False, indent=2)
            + "\n\n返回格式：\n"
            '{"items": [\n'
            '  {"original_name": "甘油淇", "canonical_name": "甘泗淇", "type": "person", '
            '"status": "confirmed", "reason": "OCR 常见错字", "confidence": 0.9}\n'
            "]}"
        )

        response = self.client.chat.completions.create(
            model=config.MODEL_NAME,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0,
            max_tokens=2200,
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content or "{}"
        data = parse_llm_json(content)
        return data.get("items", [])


def validate_entities(
    raw_entities: List[Dict[str, Any]],
    mode: str,
) -> List[Dict[str, Any]]:
    """对全部实体进行校验，返回带 status 的结果。"""
    if mode == "llm" and (not config.DEEPSEEK_API_KEY or "sk-你的key" in config.DEEPSEEK_API_KEY):
        print("未检测到有效 DEEPSEEK_API_KEY，自动切换为 rule 模式。")
        mode = "rule"

    if mode == "rule":
        return RuleValidator().validate(raw_entities)

    validator = LLMValidator()
    results: List[Dict[str, Any]] = []
    batch_size = 15

    for i in range(0, len(raw_entities), batch_size):
        batch = raw_entities[i:i + batch_size]
        try:
            items = validator.validate_batch(batch)
        except Exception as e:
            print(f"  校验批次 {i // batch_size + 1} 失败：{e}")
            items = []

        by_name = {str(item.get("original_name", "")): item for item in items}
        for entity in batch:
            name = str(entity.get("name", ""))
            checked = by_name.get(name)
            if not checked:
                checked = {
                    "original_name": name,
                    "canonical_name": name,
                    "type": entity.get("type", "other"),
                    "status": "suspicious",
                    "reason": "LLM 未返回该校验项",
                    "confidence": 0.5,
                }

            item = dict(entity)
            item["canonical_name"] = checked.get("canonical_name") or name
            item["type"] = coerce_entity_type(checked.get("type") or entity.get("type"))
            item["status"] = checked.get("status", "suspicious")
            item["reason"] = checked.get("reason", "")
            item["confidence"] = float(checked.get("confidence", 0.6))
            results.append(item)

    return results


def build_clean_graph(
    raw: Dict[str, Any],
    validated: List[Dict[str, Any]],
    include_suspicious: bool = False,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """用确认后的实体和关系重新合并，返回 clean 图、确认实体和存疑实体。"""
    base_graph = load_json(BASE_GRAPH_PATH)

    confirmed = []
    suspicious = []
    name_to_canonical = {}

    for item in validated:
        name = str(item.get("name", ""))
        canonical_name = str(item.get("canonical_name") or name).strip()
        name_to_canonical[normalize_name(name)] = canonical_name

        if item.get("status") == "reject":
            continue

        clean_item = dict(item)
        clean_item["name"] = canonical_name
        if item.get("status") == "confirmed":
            confirmed.append(clean_item)
        else:
            suspicious.append(clean_item)

    selected_entities = confirmed[:]
    if include_suspicious:
        selected_entities += suspicious

    # 合并实体
    merger = GraphMerger(base_graph)
    merger.merge_entities(selected_entities, "validated")

    # 规范化关系中的实体名称，再合并关系
    relations = []
    for rel in raw.get("relations", []):
        source_name = str(rel.get("source", "")).strip()
        target_name = str(rel.get("target", "")).strip()
        canonical_source = name_to_canonical.get(normalize_name(source_name), source_name)
        canonical_target = name_to_canonical.get(normalize_name(target_name), target_name)
        rel_copy = dict(rel)
        rel_copy["source"] = canonical_source
        rel_copy["target"] = canonical_target
        relations.append(rel_copy)

    merger.merge_relations(relations, "validated")

    clean_graph = merger.merged_graph()
    clean_graph["meta"]["validation_mode"] = "llm" if config.DEEPSEEK_API_KEY else "rule"
    clean_graph["meta"]["review_required_count"] = len(suspicious)

    return clean_graph, confirmed, suspicious


def main() -> None:
    parser = argparse.ArgumentParser(description="校验 OCR 抽取的实体并生成 clean 图谱")
    parser.add_argument("--mode", choices=["llm", "rule"], default="llm", help="校验模式")
    parser.add_argument("--project-dir", type=str, default=None, help="项目根目录")
    parser.add_argument("--include-suspicious", action="store_true", help="把存疑实体也纳入 clean 图")
    parser.add_argument("--commit-clean", action="store_true", help="Commit existing knowledge_graph_clean.json without re-validating")
    parser.add_argument("--commit", action="store_true", help="Commit the clean graph as the active graph")
    args = parser.parse_args()

    global PROJECT_DIR, KG_DIR, BASE_GRAPH_PATH, RAW_PATH, VALIDATED_PATH, REVIEW_PATH, CLEAN_PATH
    if args.project_dir:
        PROJECT_DIR = Path(args.project_dir).expanduser().resolve()
        KG_DIR = PROJECT_DIR / "data" / "knowledge_graph"
        BASE_GRAPH_PATH = KG_DIR / "knowledge_graph.json"
        RAW_PATH = KG_DIR / "auto_extracted.json"
        VALIDATED_PATH = KG_DIR / "validated_entities.json"
        REVIEW_PATH = KG_DIR / "review_required.json"
        CLEAN_PATH = KG_DIR / "knowledge_graph_clean.json"

    if args.commit_clean:
        if not CLEAN_PATH.exists():
            print(f"Clean graph not found: {CLEAN_PATH}")
            return
        clean_graph = load_json(CLEAN_PATH)
        backup = KG_DIR / f"knowledge_graph.json.bak_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        save_json(backup, load_json(BASE_GRAPH_PATH))
        save_json(BASE_GRAPH_PATH, clean_graph)
        print(f"Committed existing clean graph. Backup: {backup}")
        return

    if not RAW_PATH.exists():
        print(f"未找到抽取结果：{RAW_PATH}")
        print("请先运行 src/kg/extract_entities.py")
        return

    raw = load_json(RAW_PATH)
    raw_entities = raw.get("entities", [])
    raw_relations = raw.get("relations", [])

    validated = validate_entities(raw_entities, args.mode)
    clean_graph, confirmed, suspicious = build_clean_graph(
        raw=raw,
        validated=validated,
        include_suspicious=args.include_suspicious,
    )

    save_json(VALIDATED_PATH, {
        "meta": {
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "mode": args.mode,
            "entity_count": len(validated),
            "confirmed_count": len(confirmed),
            "suspicious_count": len(suspicious),
        },
        "entities": validated,
    })
    save_json(REVIEW_PATH, {
        "meta": {
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "review_required_count": len(suspicious),
        },
        "entities": suspicious,
    })
    save_json(CLEAN_PATH, clean_graph)

    print("\n===== 自动校验结果 =====")
    print(f"原始抽取实体：{len(raw_entities)}，关系：{len(raw_relations)}")
    print(f"确认实体：{len(confirmed)}")
    print(f"存疑实体：{len(suspicious)}")
    print(f"clean 图谱实体：{len(clean_graph.get('entities', []))}，关系：{len(clean_graph.get('relations', []))}")
    print(f"全部校验结果：{VALIDATED_PATH}")
    print(f"仅存疑项：{REVIEW_PATH}")
    print(f"clean 图谱预览：{CLEAN_PATH}")

    if args.commit:
        backup = KG_DIR / f"knowledge_graph.json.bak_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        save_json(backup, load_json(BASE_GRAPH_PATH))
        save_json(BASE_GRAPH_PATH, clean_graph)
        print(f"已提交 clean 图谱，原图谱备份到：{backup}")
    else:
        print("未使用 --commit，正式图谱未被修改。")
        print("查看 review_required.json 后，可加 --commit 提交 clean 图谱。")


if __name__ == "__main__":
    main()
