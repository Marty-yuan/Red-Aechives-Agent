# -*- coding: utf-8 -*-
"""
查询归一化（Query Normalization）
--------------------------------
在检索前把用户问题中的 OCR 风格错字归一化，提升小样本评测与线上问答的鲁棒性。

两级策略：
    1. 精确纠错表：复用 knowledge.ocr_fixes.OCR_FIXES（人工核对过的 68 条+）。
    2. 地点/事件模糊归一：对村寨地名与关键事件做"同长、恰差一字"的模糊匹配
       （如 巧度金沙江→巧渡金沙江、扎西会设→扎西会议、较平渡→皎平渡）。
       仅对地名/事件生效，不碰人物与部队番号（避免把 红五军团 误改成 红二军团）。

关闭方式：环境变量 RED_ARCHIVE_QUERY_NORM=0。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

_SRC_DIR = Path(__file__).resolve().parents[1]
_PROJECT_DIR = _SRC_DIR.parent

# 关键事件（地名之外的领域词表；长度 >=3 才参与模糊匹配）
_EVENT_TERMS = ("扎西会议", "遵义会议", "巧渡金沙江", "石鼓渡江", "万急渡江令", "金沙江")


def _load_fixes() -> tuple[tuple[str, str], ...]:
    try:
        from knowledge.ocr_fixes import OCR_FIXES
        return tuple(OCR_FIXES)
    except Exception:
        ns: dict = {}
        fixes_file = _SRC_DIR / "knowledge" / "ocr_fixes.py"
        if fixes_file.exists():
            exec(fixes_file.read_text(encoding="utf-8"), ns)
        return tuple(ns.get("OCR_FIXES", ()))


def _load_place_terms() -> tuple[str, ...]:
    """地名词表：取自已建索引的村寨倒排键 + 关键事件。"""
    terms: set[str] = set(_EVENT_TERMS)
    village_file = _PROJECT_DIR / "data" / "index" / "village_index.json"
    if village_file.exists():
        try:
            terms.update(json.loads(village_file.read_text(encoding="utf-8")).keys())
        except Exception:
            pass
    return tuple(sorted(t for t in terms if len(t) >= 3))


_FIXES = _load_fixes()
_PLACE_TERMS = _load_place_terms()


def _one_char_diff(a: str, b: str) -> bool:
    """同长度、恰好一个字符不同。"""
    if len(a) != len(b):
        return False
    return sum(1 for x, y in zip(a, b) if x != y) == 1


_ADMIN_SUFFIX = "县市省区镇乡村"
_CORPS_SUFFIX = "军师部团"

def _fuzzy_replace_places(text: str) -> tuple[str, list[str]]:
    """对地名/事件做同长 1 字差替换；先收集后替换，避免位置漂移。"""
    edits: list[str] = []
    occupied = [False] * len(text)
    result = list(text)
    for term in sorted(_PLACE_TERMS, key=len, reverse=True):
        n = len(term)
        if n > len(text):
            continue
        term_suffix = term[-1]
        for i in range(len(text) - n + 1):
            if any(occupied[i:i + n]):
                continue
            window = text[i:i + n]
            if window == term or window in _PLACE_TERMS:
                continue
            if not _one_char_diff(window, term):
                continue
            # 保护真实行政区名/番号：窗口以行政或番号字结尾而术语不是时跳过
            if window[-1] != term_suffix and (window[-1] in _ADMIN_SUFFIX or window[-1] in _CORPS_SUFFIX):
                continue
            result[i:i + n] = list(term)
            for j in range(i, i + n):
                occupied[j] = True
            edits.append(f"{window}→{term}")
    return "".join(result), edits


def normalize_query(query: str) -> str:
    """归一化查询文本；RED_ARCHIVE_QUERY_NORM=0 时原样返回。"""
    if not query:
        return query
    if os.environ.get("RED_ARCHIVE_QUERY_NORM", "1") == "0":
        return query

    text = query.strip()
    # 1) 精确纠错表（长串优先，迭代至稳定）
    ordered = sorted(_FIXES, key=lambda x: len(x[0]), reverse=True)
    for _ in range(6):
        changed = False
        for wrong, right in ordered:
            if not wrong or wrong == right:
                continue
            if wrong in text:
                text = text.replace(wrong, right)
                changed = True
        if not changed:
            break
    # 2) 地点/事件模糊归一
    text, _ = _fuzzy_replace_places(text)
    return text


if __name__ == "__main__":
    import io
    import sys

    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    samples = [
        "巧度金沙江用了几天？",
        "扎西会设是什么时候开的？",
        "较平渡在哪个县？",
        "红五军团经过了哪里？",
        "周付主席在哪里指挥渡江？",
    ]
    for s in samples:
        print(f"{s}  ->  {normalize_query(s)}")
