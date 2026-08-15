"""
从 OCR 文本自动抽取档案知识图谱实体
----------------------------------
把已经识别好的 OCR 文本，自动抽取成知识图谱节点和关系，并与现有手工图谱合并。

用法：
    1. 抽取 + 生成合并预览（不覆盖手工图谱）：
       python src/kg/extract_entities.py --mode llm --limit-files 5

    2. 使用规则模式快速验证（不需要 API）：
       python src/kg/extract_entities.py --mode rule --limit-files 2

    3. 审查后正式提交到 knowledge_graph.json：
       python src/kg/extract_entities.py --mode llm --commit

输出文件：
    data/knowledge_graph/auto_extracted.json        # 本次抽取的原始结果
    data/knowledge_graph/knowledge_graph_auto.json  # 手工图谱 + 本次抽取的合并预览
"""
import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# 把 src 加入 sys.path，便于在任意目录运行
SRC_DIR = Path(__file__).resolve().parents[1]
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from agent import config  # noqa: E402
from agent.knowledge import TIMELINE, VILLAGE_COORDS  # noqa: E402

PROJECT_DIR = Path(os.environ.get("RED_ARCHIVE_PROJECT_DIR") or config.PROJECT_DIR)
if not PROJECT_DIR.exists():
    PROJECT_DIR = SRC_DIR.parent
OCR_DIR = PROJECT_DIR / "data" / "ocr_output"
KG_DIR = PROJECT_DIR / "data" / "knowledge_graph"
BASE_GRAPH_PATH = KG_DIR / "knowledge_graph.json"
AUTO_RAW_PATH = KG_DIR / "auto_extracted.json"
AUTO_MERGED_PATH = KG_DIR / "knowledge_graph_auto.json"

# ===================== 类型与关系规范 =====================
TYPE_PREFIX = {
    "person": "P",
    "location": "L",
    "event": "E",
    "army": "A",
    "organization": "O",
    "document": "D",
    "other": "X",
}

ALLOWED_ENTITY_TYPES = set(TYPE_PREFIX)
ALLOWED_RELATIONS = {
    "commander", "participant", "occurred_at", "located_in", "army",
    "next_event", "next_on_route", "alias", "member_of", "related_to",
}

# 规则模式使用的种子实体
KNOWN_PERSONS = {
    "毛泽东": {"type": "person", "aliases": ["毛主席"], "description": "中共中央领导人"},
    "贺龙": {"type": "person", "aliases": ["贺老总"], "description": "红二、六军团总指挥"},
    "任弼时": {"type": "person", "aliases": [], "description": "红二、六军团政治委员"},
    "朱德": {"type": "person", "aliases": ["朱总司令"], "description": "红军总司令"},
    "周恩来": {"type": "person", "aliases": [], "description": "中共中央领导人"},
    "刘伯承": {"type": "person", "aliases": [], "description": "红军高级指挥员"},
}

RELATION_DIRECTION_RULES = {
    "commander": ({"event", "army"}, {"person"}),
    "participant": ({"event"}, {"person", "army"}),
    "occurred_at": ({"event"}, {"location"}),
    "located_in": ({"location"}, {"location"}),
    "army": ({"event"}, {"army"}),
    "next_event": ({"event"}, {"event"}),
    "next_on_route": ({"location"}, {"location"}),
    "alias": (set(), set()),
    "member_of": ({"person", "army", "organization"}, {"organization", "army"}),
    "related_to": (set(), set()),
}

RELATION_LABELS = {
    "commander": "指挥者",
    "participant": "参与者",
    "occurred_at": "发生地",
    "located_in": "位于",
    "army": "所属部队",
    "next_event": "后续事件",
    "next_on_route": "行军路线",
    "alias": "同地异名",
    "member_of": "所属组织",
    "related_to": "相关",
}


def normalize_name(name: str) -> str:
    """用于实体去重的规范化名称。"""
    name = str(name or "").strip().lower()
    name = re.sub(r"(省|市|县|区|镇|乡|村|州)$", "", name)
    return name


def stable_id(entity_type: str, name: str) -> str:
    """为新增实体生成稳定、可复现的 ID。"""
    prefix = TYPE_PREFIX.get(entity_type, "X")
    digest = hashlib.sha1(f"{entity_type}:{name}".encode("utf-8")).hexdigest()[:8].upper()
    return f"{prefix}_{digest}"


def load_json(path: Path) -> Dict[str, Any]:
    """读取 JSON，兼容带 BOM 的文件。"""
    if not path.exists():
        return {"entities": [], "relations": [], "meta": {}}
    with path.open("r", encoding="utf-8-sig") as f:
        return json.load(f)


def save_json(path: Path, data: Dict[str, Any]) -> None:
    """保存 JSON，保证中文可读。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def chunk_text(text: str, max_chars: int = 3500, overlap: int = 300) -> List[str]:
    """把长文本切成适合 LLM 抽取的小块，并保留少量上下文重叠。"""
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text).strip()
    if len(text) <= max_chars:
        return [text]

    chunks = []
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        chunks.append(text[start:end])
        if end == len(text):
            break
        start = end - overlap
    return chunks


def parse_llm_json(content: str) -> Dict[str, Any]:
    """稳健解析 LLM 返回的 JSON。"""
    content = (content or "").strip()
    content = re.sub(r"^```(?:json)?\s*", "", content)
    content = re.sub(r"\s*```$", "", content)
    try:
        return json.loads(content)
    except Exception:
        start = content.find("{")
        end = content.rfind("}")
        if start == -1 or end == -1:
            raise
        return json.loads(content[start:end + 1])


def coerce_entity_type(raw_type: str) -> str:
    """把 LLM 输出的类型归一到允许集合。"""
    t = str(raw_type or "").strip().lower()
    if t in ALLOWED_ENTITY_TYPES:
        return t
    if any(k in t for k in ("person", "人物", "人")):
        return "person"
    if any(k in t for k in ("location", "地点", "地名", "place")):
        return "location"
    if any(k in t for k in ("event", "事件")):
        return "event"
    if any(k in t for k in ("army", "部队", "军队")):
        return "army"
    if any(k in t for k in ("organization", "组织", "机构")):
        return "organization"
    if any(k in t for k in ("document", "文献", "档案")):
        return "document"
    return "other"


class LLMExtractor:
    """调用 DeepSeek 从 OCR 文本块中抽取实体和关系。"""

    def __init__(self):
        self.client = None
        self.api_key = config.DEEPSEEK_API_KEY

    def _ensure_client(self):
        if self.client is None:
            from openai import OpenAI

            self.client = OpenAI(
                api_key=self.api_key,
                base_url=config.BASE_URL,
            )

    def extract_chunk(self, text: str, source: str, existing_names: List[str]) -> Dict[str, Any]:
        """抽取单个文本块。"""
        self._ensure_client()

        existing_text = "、".join(existing_names[:80])
        system_prompt = (
            "你是云南红军长征档案的知识图谱抽取器。\n"
            "任务：从给定 OCR 文本中抽取实体和实体关系。\n"
            "只能抽取文本中明确出现的内容，不得编造。\n\n"
            "实体类型只能是：person, location, event, army, organization, document, other。\n"
            "关系类型只能是：commander, participant, occurred_at, located_in, army, "
            "next_event, next_on_route, alias, member_of, related_to。\n"
            "关系和实体的 name 要尽量与原文一致。\n"
            "description 只用一句话，不要换行，不要包含双引号。\n"
            "注意：不要抽取图书编辑出版人员（主编、副主编、责任编辑、执行主编、编委、"
            "监制、摄影、设计、校对、印制、法律顾问等），也不要抽取与长征历史无关的"
            "现代行政/商业职务人物（如现代县委书记、县长、董事长、会长等），"
            "除非该人物直接参与 1935-1936 年红军长征相关历史事件。\n"
            "返回严格 JSON，不要输出 Markdown。"
        )

        user_prompt = (
            "已有实体名称（可用于引用，但不要受其限制）：\n"
            f"{existing_text}\n\n"
            f"来源文件：{source}\n"
            "OCR 文本：\n"
            f"{text}\n\n"
            "请输出 JSON，格式如下：\n"
            "{\n"
            '  "entities": [\n'
            '    {"name": "贺龙", "type": "person", "aliases": ["贺老总"], '
            '"description": "红二、六军团总指挥", "properties": {}}\n'
            "  ],\n"
            '  "relations": [\n'
            '    {"source": "贺龙", "target": "红二六军团入滇", '
            '"relation": "commander", "label": "指挥者"}\n'
            "  ]\n"
            "}\n"
            "注意：不要把原文证据写进 JSON，避免引号、换行破坏 JSON。"
        )

        response = self.client.chat.completions.create(
            model=config.MODEL_NAME,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1,
            max_tokens=4000,
            response_format={"type": "json_object"},
        )

        content = response.choices[0].message.content or "{}"
        try:
            return parse_llm_json(content)
        except Exception as first_error:
            print(f"  JSON 解析失败，尝试让模型修复：{first_error}")
            return self._repair_json(content)

    def _repair_json(self, broken_json: str) -> Dict[str, Any]:
        """让模型把不合法 JSON 修复为合法 JSON。"""
        repair_response = self.client.chat.completions.create(
            model=config.MODEL_NAME,
            messages=[
                {
                    "role": "system",
                    "content": "你是 JSON 修复器。只输出修复后的合法 JSON，不要解释。",
                },
                {
                    "role": "user",
                    "content": "下面这段 JSON 不合法，请修复并只返回合法 JSON：\n" + broken_json,
                },
            ],
            temperature=0,
            max_tokens=4000,
            response_format={"type": "json_object"},
        )
        return parse_llm_json(repair_response.choices[0].message.content or "{}")

class RuleExtractor:
    """无 API 的规则抽取器，用于快速验证和离线演示。"""

    def extract_chunk(self, text: str, source: str, existing_names: List[str]) -> Dict[str, Any]:
        entities = []
        relations = []

        # 1. 已知人物
        for name, info in KNOWN_PERSONS.items():
            if name in text or any(alias in text for alias in info.get("aliases", [])):
                entities.append({
                    "name": name,
                    "type": info["type"],
                    "aliases": info.get("aliases", []),
                    "description": info.get("description", ""),
                    "properties": {},
                    "evidence": f"在 {source} 中命中人物名称",
                })

        # 2. 已知地点
        for village, coord in VILLAGE_COORDS.items():
            if village in text:
                entities.append({
                    "name": village,
                    "type": "location",
                    "aliases": [coord.get("city", "")] if coord.get("city") else [],
                    "description": coord.get("event", ""),
                    "properties": {
                        "lat": coord.get("lat"),
                        "lng": coord.get("lng"),
                        "city": coord.get("city", ""),
                    },
                    "evidence": f"在 {source} 中命中地点名称",
                })

        # 3. 已知事件
        for event in TIMELINE:
            if event.get("label") in text or event.get("desc", "")[:12] in text:
                event_name = event.get("label", "")
                entities.append({
                    "name": event_name,
                    "type": "event",
                    "aliases": [],
                    "description": event.get("desc", ""),
                    "properties": {"date": event.get("date", ""), "year": event.get("year")},
                    "evidence": f"在 {source} 中命中时间轴事件",
                })
                village = event.get("village", "")
                if village:
                    relations.append({
                        "source": event_name,
                        "target": village,
                        "relation": "occurred_at",
                        "label": RELATION_LABELS["occurred_at"],
                        "evidence": f"来自时间轴：{event.get('date', '')}",
                    })

        # 4. 文本中出现的日期可作为事件线索
        date_pattern = re.compile(r"(193[56])[年.-]([0-9]{1,2})[月.-]([0-9]{1,2})")
        for m in date_pattern.finditer(text):
            year, month, day = m.groups()
            date_str = f"{year}-{int(month):02d}-{int(day):02d}"
            event_name = f"{year}年{int(month)}月{int(day)}日档案事件"
            entities.append({
                "name": event_name,
                "type": "event",
                "aliases": [],
                "description": f"OCR 文本中出现的日期事件线索：{date_str}",
                "properties": {"date": date_str, "year": int(year)},
                "evidence": m.group(0),
            })

        return {"entities": entities, "relations": relations}


class GraphMerger:
    """把抽取结果合并到现有图谱。"""

    def __init__(self, base_graph: Dict[str, Any]):
        self.base_graph = base_graph
        self.entities: List[Dict[str, Any]] = list(base_graph.get("entities", []))
        self.relations: List[Dict[str, Any]] = list(base_graph.get("relations", []))
        self.id_by_name: Dict[str, str] = {}
        self.name_by_id: Dict[str, str] = {}
        self.type_by_id: Dict[str, str] = {}
        self._build_index()

    def _build_index(self) -> None:
        for entity in self.entities:
            eid = entity.get("id", "")
            name = entity.get("name", "")
            self.name_by_id[eid] = name
            self.type_by_id[eid] = entity.get("type", "other")
            self._add_name_index(eid, name)
            for alias in entity.get("aliases", []):
                self._add_name_index(eid, alias)

    def _add_name_index(self, eid: str, name: str) -> None:
        key = normalize_name(name)
        if key:
            self.id_by_name.setdefault(key, eid)

    def _resolve_id(self, name: str) -> Optional[str]:
        key = normalize_name(name)
        return self.id_by_name.get(key)

    def _relation_valid(self, relation: str, source_type: str, target_type: str) -> bool:
        """Check relation direction. Empty sets mean no restriction."""
        rule = RELATION_DIRECTION_RULES.get(relation)
        if not rule:
            return True
        allowed_sources, allowed_targets = rule
        if not allowed_sources and not allowed_targets:
            return True
        return source_type in allowed_sources and target_type in allowed_targets

    def merge_entities(self, extracted_entities: List[Dict[str, Any]], source: str) -> Tuple[List[Dict[str, Any]], int]:
        """合并实体，返回新实体列表和新增数量。"""
        new_entities = []
        added = 0

        for item in extracted_entities:
            name = str(item.get("name", "")).strip()
            if not name:
                continue

            entity_type = coerce_entity_type(item.get("type", "other"))
            existing_id = self._resolve_id(name)

            if existing_id:
                # 已经存在，只补充缺失的别名和描述
                for entity in self.entities:
                    if entity.get("id") == existing_id:
                        entity.setdefault("description", item.get("description", ""))
                        existing_aliases = set(entity.get("aliases", []))
                        for alias in item.get("aliases", []):
                            if alias and alias not in existing_aliases:
                                entity.setdefault("aliases", []).append(alias)
                                self._add_name_index(existing_id, alias)
                        break
                continue

            entity_id = stable_id(entity_type, name)
            entity = {
                "id": entity_id,
                "type": entity_type,
                "name": name,
                "aliases": item.get("aliases", []),
                "description": item.get("description", ""),
                "properties": item.get("properties", {}),
                "source": source,
                "evidence": item.get("evidence", ""),
                "confidence": item.get("confidence", 0.8),
            }
            self.entities.append(entity)
            self.name_by_id[entity_id] = name
            self.type_by_id[entity_id] = entity_type
            self._add_name_index(entity_id, name)
            for alias in item.get("aliases", []):
                self._add_name_index(entity_id, alias)
            new_entities.append(entity)
            added += 1

        return new_entities, added

    def merge_relations(self, extracted_relations: List[Dict[str, Any]], source: str) -> Tuple[List[Dict[str, Any]], int]:
        """合并关系，返回新关系列表和新增数量。"""
        new_relations = []
        added = 0
        existing_keys = {
            (r.get("source"), r.get("target"), r.get("relation"))
            for r in self.relations
        }

        for item in extracted_relations:
            source_name = str(item.get("source", "")).strip()
            target_name = str(item.get("target", "")).strip()
            relation = str(item.get("relation", "")).strip()

            if relation not in ALLOWED_RELATIONS:
                continue

            source_id = self._resolve_id(source_name)
            target_id = self._resolve_id(target_name)
            if not source_id or not target_id:
                continue

            source_type = self.type_by_id.get(source_id, "other")
            target_type = self.type_by_id.get(target_id, "other")
            if not self._relation_valid(relation, source_type, target_type):
                if self._relation_valid(relation, target_type, source_type):
                    source_id, target_id = target_id, source_id
                    source_name, target_name = target_name, source_name
                else:
                    continue

            key = (source_id, target_id, relation)
            if key in existing_keys:
                continue

            relation_id = stable_id("relation", f"{source_id}->{target_id}->{relation}")
            relation_item = {
                "id": relation_id,
                "source": source_id,
                "target": target_id,
                "relation": relation,
                "label": item.get("label") or RELATION_LABELS.get(relation, relation),
                "properties": item.get("properties", {}),
                "source_file": source,
                "evidence": item.get("evidence", ""),
                "confidence": item.get("confidence", 0.8),
            }
            self.relations.append(relation_item)
            existing_keys.add(key)
            new_relations.append(relation_item)
            added += 1

        return new_relations, added

    def merged_graph(self) -> Dict[str, Any]:
        """返回合并后的完整图数据。"""
        return {
            "meta": {
                "name": "云南红军长征档案知识图谱（含 OCR 自动抽取）",
                "version": "auto-0.1",
                "base_entity_count": len(self.base_graph.get("entities", [])),
                "base_relation_count": len(self.base_graph.get("relations", [])),
            },
            "entities": self.entities,
            "relations": self.relations,
        }


def collect_ocr_files(limit_files: Optional[int] = None) -> List[Path]:
    """收集 OCR 文本文件。"""
    if not OCR_DIR.exists():
        print(f"OCR 目录不存在：{OCR_DIR}")
        return []

    files = sorted(OCR_DIR.glob("*.txt"))
    if limit_files:
        files = files[: int(limit_files)]
    return files


def extract_from_ocr(
    mode: str,
    limit_files: Optional[int] = None,
    max_chars_per_file: int = 6000,
) -> Dict[str, Any]:
    """对 OCR 文本执行实体抽取，返回抽取原始结果。"""
    extractor = LLMExtractor() if mode == "llm" else RuleExtractor()
    base_graph = load_json(BASE_GRAPH_PATH)
    existing_names = [e.get("name", "") for e in base_graph.get("entities", [])]

    all_entities: List[Dict[str, Any]] = []
    all_relations: List[Dict[str, Any]] = []

    for file_path in collect_ocr_files(limit_files):
        print(f"处理：{file_path.name}")
        try:
            text = file_path.read_text(encoding="utf-8-sig", errors="ignore")
        except Exception as e:
            print(f"  读取失败：{e}")
            continue

        # 跳过封面/版权页（约前 12%），避免抽出编委会、监制等非历史噪声；
        # 短文件保护：保证至少取 max_chars_per_file 字符
        skip = int(len(text) * 0.12)
        if len(text) - skip < int(max_chars_per_file):
            skip = max(0, len(text) - int(max_chars_per_file))
        limited_text = text[skip : skip + int(max_chars_per_file)]
        for chunk in chunk_text(limited_text, max_chars=max_chars_per_file):
            try:
                result = extractor.extract_chunk(chunk, file_path.name, existing_names)
            except Exception as e:
                print(f"  抽取失败：{e}")
                continue

            for entity in result.get("entities", []):
                entity["source"] = file_path.name
                all_entities.append(entity)
            for relation in result.get("relations", []):
                relation["source_file"] = file_path.name
                all_relations.append(relation)

    return {
        "meta": {
            "mode": mode,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "source_files": [f.name for f in collect_ocr_files(limit_files)],
            "entity_count": len(all_entities),
            "relation_count": len(all_relations),
        },
        "entities": all_entities,
        "relations": all_relations,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="从 OCR 文本自动抽取知识图谱实体")
    parser.add_argument("--mode", choices=["llm", "rule"], default="llm", help="抽取模式")
    parser.add_argument("--limit-files", type=int, default=None, help="最多处理多少个 OCR 文件")
    parser.add_argument("--max-chars", type=int, default=4500, help="每个文件最多参与抽取的字符数")
    parser.add_argument("--project-dir", type=str, default=None, help="项目根目录，默认读取 config.PROJECT_DIR")
    parser.add_argument("--remerge", action="store_true", help="Use existing auto_extracted.json and re-merge without calling LLM")
    parser.add_argument("--commit-preview", action="store_true", help="Commit knowledge_graph_auto.json as the active graph")
    parser.add_argument("--commit", action="store_true", help="Confirm and commit the newly merged result to knowledge_graph.json")
    args = parser.parse_args()

    global PROJECT_DIR, OCR_DIR, KG_DIR, BASE_GRAPH_PATH, AUTO_RAW_PATH, AUTO_MERGED_PATH
    if args.project_dir:
        PROJECT_DIR = Path(args.project_dir).expanduser().resolve()
        OCR_DIR = PROJECT_DIR / "data" / "ocr_output"
        KG_DIR = PROJECT_DIR / "data" / "knowledge_graph"
        BASE_GRAPH_PATH = KG_DIR / "knowledge_graph.json"
        AUTO_RAW_PATH = KG_DIR / "auto_extracted.json"
        AUTO_MERGED_PATH = KG_DIR / "knowledge_graph_auto.json"

    if args.remerge:
        if not AUTO_RAW_PATH.exists():
            print(f"Auto extraction result not found: {AUTO_RAW_PATH}")
            return
        extracted = load_json(AUTO_RAW_PATH)
        base_graph = load_json(BASE_GRAPH_PATH)
        merger = GraphMerger(base_graph)
        new_entities, entity_added = merger.merge_entities(extracted.get("entities", []), "auto")
        new_relations, relation_added = merger.merge_relations(extracted.get("relations", []), "auto")
        merged = merger.merged_graph()
        save_json(AUTO_MERGED_PATH, merged)
        print("\n===== Re-merge completed =====")
        print(f"Raw entities: {len(extracted.get('entities', []))}, raw relations: {len(extracted.get('relations', []))}")
        print(f"New entities: {entity_added}, new relations: {relation_added}")
        print(f"Merged preview: {AUTO_MERGED_PATH}")
        return

    if args.commit_preview:
        if not AUTO_MERGED_PATH.exists():
            print(f"Merged preview not found: {AUTO_MERGED_PATH}")
            return
        preview = load_json(AUTO_MERGED_PATH)
        old_graph = load_json(BASE_GRAPH_PATH)
        backup = KG_DIR / f"knowledge_graph.json.bak_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        save_json(backup, old_graph)
        save_json(BASE_GRAPH_PATH, preview)
        print(f"Preview committed. Backup: {backup}")
        return

    if args.mode == "llm" and (not config.DEEPSEEK_API_KEY or "sk-你的key" in config.DEEPSEEK_API_KEY):
        print("未检测到有效 DEEPSEEK_API_KEY，自动切换为 rule 模式进行离线演示。")
        args.mode = "rule"

    extracted = extract_from_ocr(
        mode=args.mode,
        limit_files=args.limit_files,
        max_chars_per_file=args.max_chars,
    )
    save_json(AUTO_RAW_PATH, extracted)

    base_graph = load_json(BASE_GRAPH_PATH)
    merger = GraphMerger(base_graph)
    new_entities, entity_added = merger.merge_entities(extracted.get("entities", []), "auto")
    new_relations, relation_added = merger.merge_relations(extracted.get("relations", []), "auto")
    merged = merger.merged_graph()
    save_json(AUTO_MERGED_PATH, merged)

    print("\n===== 抽取结果 =====")
    print(f"模式：{args.mode}")
    print(f"原始抽取实体：{len(extracted.get('entities', []))}，关系：{len(extracted.get('relations', []))}")
    print(f"合并后新增实体：{entity_added}，新增关系：{relation_added}")
    print(f"合并预览：{AUTO_MERGED_PATH}")

    if args.commit:
        backup = KG_DIR / f"knowledge_graph.json.bak_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        save_json(backup, base_graph)
        save_json(BASE_GRAPH_PATH, merged)
        print(f"已提交合并结果，原图谱备份到：{backup}")
    else:
        print("未使用 --commit，手工图谱未被修改。")
        print("审查 knowledge_graph_auto.json 后，可加 --commit 正式写入。")


if __name__ == "__main__":
    main()
