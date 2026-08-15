# -*- coding: utf-8 -*-
"""
档案篇目目录（TOC）解析与页码标注
---------------------------------
数据源：C:\\Users\\damn\\Desktop\\华为杯\\云南省红军长征档案文献\\红军长征过云南相关档案文献目录.xlsx
（18 部书的篇目名 + 对应页码，共 1225 行）

溯源标注采用双方案：
    1. anchor_annotate()  精确锚定：在正文中定位篇目标题（跳过目录页），
                          仅当该书锚定可靠时使用，confidence="exact"
    2. approx_annotate()  近似插值：用"篇目页码区间 + 文本比例"估算 chunk
                          所属篇目与页码，confidence="approx"
    3. annotate_chunks()  自动选择：可靠锚定优先，否则近似插值
"""
import bisect
import json
import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

PROJECT_DIR = Path(__file__).resolve().parents[2]
INDEX_DIR = PROJECT_DIR / "data" / "index"
# 正式 TOC 资产（提交到 git，队友克隆后无需 xlsx 即可溯源）
CACHE_PATH = PROJECT_DIR / "data" / "knowledge_graph" / "book_toc.json"

# 默认 xlsx 路径（可通过环境变量 RED_ARCHIVE_TOC_XLSX 覆盖）
DEFAULT_XLSX = Path(
    r"C:\\Users\\damn\\Desktop\\华为杯\\云南省红军长征档案文献\\红军长征过云南相关档案文献目录.xlsx"
)

# 正文起点估计：封面/目录约占文本前部比例
FRONT_MATTER_RATIO = 0.03


def normalize_text(s: str) -> str:
    """归一化：全角转半角、去空白与标点（用于匹配）。"""
    if not s:
        return ""
    s = "".join(chr(ord(c) - 0xFEE0) if 0xFF01 <= ord(c) <= 0xFF5E else c for c in s)
    return re.sub(r"[\s\u3000、，。．·；：！？（）()\-—_/《》「」『』]", "", s)


def _parse_page(page) -> Optional[int]:
    """页码解析：'23' -> 23；'23-30' -> 23；'-'/空 -> None。"""
    if page is None or page == "-" or page == "无":
        return None
    m = re.match(r"(\d+)", str(page).strip())
    return int(m.group(1)) if m else None


def load_toc(xlsx_path: Optional[str] = None) -> Dict[str, List[Tuple[str, Optional[int]]]]:
    """解析 xlsx 目录为 {书名: [(篇目名, 页码), ...]}，带缓存。"""
    if CACHE_PATH.exists():
        raw = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        return {k: [(i["item"], i.get("page")) for i in v] for k, v in raw.items()}

    try:
        import openpyxl
    except ImportError:
        print("缺少 openpyxl，无法解析目录 xlsx")
        return {}

    path = xlsx_path or os.environ.get("RED_ARCHIVE_TOC_XLSX") or str(DEFAULT_XLSX)
    if not Path(path).exists():
        print(f"未找到目录文件: {path}")
        return {}

    wb = openpyxl.load_workbook(path, read_only=True)
    ws = wb.active
    books: Dict[str, List[Tuple[str, Optional[int]]]] = {}
    for row in ws.iter_rows(values_only=True):
        if not row or not row[0]:
            continue
        title = str(row[0]).strip()
        # 列结构：书名 | 编者 | 具体篇目名 | 对应页码
        item = str(row[2]).strip() if len(row) > 2 and row[2] else ""
        page = _parse_page(row[3]) if len(row) > 3 else None
        if title in ("书名",) or not title:
            continue  # 跳过表头
        if item and item != "None":
            books.setdefault(title, []).append((item, page))
    wb.close()

    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(
        json.dumps({k: [{"item": i, "page": p} for i, p in v] for k, v in books.items()},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return books


def match_book(txt_filename: str, books: Dict[str, List]) -> Optional[str]:
    """把 TXT 文件名匹配到目录书名（归一化包含匹配）。"""
    fn = normalize_text(txt_filename)
    best, best_len = None, 0
    for title in books:
        tn = normalize_text(title)
        if tn and (tn in fn or fn in tn):
            if len(tn) > best_len:
                best, best_len = title, len(tn)
    return best


# ===================== 方案一：精确锚定 =====================

def _is_dir_entry(text: str, pos: int, vlen: int) -> bool:
    """目录项特征：篇目名后紧跟空白 + 页码数字（正文标题后是正文文字）。"""
    after = text[pos + vlen: pos + vlen + 12]
    return bool(re.match(r"[\s,，．。·、—\-]*\d{1,4}", after))


def _collect_anchor_positions(text: str, items) -> List[List[int]]:
    """收集每个篇目的非目录项出现位置。"""
    all_positions = []
    for item, _page in items:
        variants = [item, normalize_text(item)]
        pos_set = []
        for v in variants:
            if not v:
                continue
            start = 0
            while True:
                idx = text.find(v, start)
                if idx == -1:
                    break
                if not _is_dir_entry(text, idx, len(v)):
                    pos_set.append(idx)
                start = idx + 1
        all_positions.append(sorted(set(pos_set)))
    return all_positions


def anchor_annotate(text: str, items) -> Tuple[List[dict], str]:
    """
    精确锚定：返回区间表 [{"section","page","offset","end"}]。
    仅当锚定可靠（有锚点篇目占比 >= 30% 且锚点分散）时返回 "exact"。
    """
    all_pos = _collect_anchor_positions(text, items)
    n = len(items)
    anchored = sum(1 for p in all_pos if p)
    if anchored < max(3, n * 0.3):
        return [], "unreliable"

    # 正文起点估计：非目录项首次出现位置的 75 分位
    firsts = sorted(p[0] for p in all_pos if p)
    body_start = firsts[min(len(firsts) - 1, int(len(firsts) * 0.75))]

    anchors = []
    cursor = body_start
    for (item, _page), pos_list in zip(items, all_pos):
        pos = None
        if pos_list:
            i = bisect.bisect_left(pos_list, cursor)
            if i < len(pos_list):
                pos = pos_list[i]
        # 取该篇目的 page
        page = items[[x[0] for x in items].index(item)][1] if item else None
        anchors.append({"offset": pos, "section": item, "page": page})
        if pos is not None:
            cursor = pos + max(len(item), 1)

    segments = []
    last = None
    for a in anchors:
        if a["offset"] is not None:
            last = a
        if last is not None:
            segments.append(last.copy())
    for i in range(len(segments)):
        nxt = None
        for j in range(i + 1, len(segments)):
            if segments[j]["offset"] is not None and segments[j]["offset"] > segments[i]["offset"]:
                nxt = segments[j]["offset"]
                break
        segments[i]["end"] = nxt if nxt is not None else len(text)
    return segments, "exact" if len(segments) >= max(3, n * 0.3) else "unreliable"


# ===================== 方案二：近似插值 =====================

def _next_page(items: List[Tuple[str, Optional[int]]], i: int, last_page: int) -> int:
    """找第 i 个篇目之后第一个有效页码（跳过 None）。"""
    for j in range(i + 1, len(items)):
        if items[j][1] is not None:
            return items[j][1]
    return last_page + 1


def approx_annotate(text_len: int, offset: int, items, front_ratio: float = FRONT_MATTER_RATIO):
    """
    页码比例插值：offset -> 估算书页 -> 篇目区间。
    返回 (section, page, confidence="approx")；找不到返回 (None, None, None)。
    """
    pages = [pg for _, pg in items if pg is not None]
    if not pages:
        return None, None, None
    first_page, last_page = min(pages), max(pages)
    body_start = text_len * front_ratio
    body_span = max(text_len * (1 - front_ratio), 1)
    rel = max(0.0, min(1.0, (offset - body_start) / body_span))
    page = round(first_page + rel * (last_page - first_page))

    for i, (item, pg) in enumerate(items):
        if pg is None:
            continue
        nxt = _next_page(items, i, last_page)
        if pg <= page < nxt:
            return item, page, "approx"
    return None, None, None


# ===================== 统一入口 =====================

def annotate_chunks(text: str, items: List[Tuple[str, Optional[int]]],
                    chunk_offsets: List[int]) -> List[dict]:
    """
    为一批 chunk 标注 (section, page, confidence)。
    优先精确锚定；锚定不可靠时退化为近似插值。
    """
    segments, mode = anchor_annotate(text, items)
    result = []
    if mode == "exact":
        for off in chunk_offsets:
            sec, pg = None, None
            for seg in segments:
                if seg["offset"] is not None and seg["offset"] <= off < seg["end"]:
                    sec, pg = seg["section"], seg["page"]
                    break
            if sec is None:
                # 精确区间未命中（锚点稀疏区域），回落到近似插值
                sec, pg, _ = approx_annotate(len(text), off, items)
                result.append({"section": sec, "page": pg,
                               "confidence": "approx" if sec else None})
            else:
                result.append({"section": sec, "page": pg, "confidence": "exact"})
    else:
        for off in chunk_offsets:
            sec, pg, conf = approx_annotate(len(text), off, items)
            result.append({"section": sec, "page": pg, "confidence": conf})
    return result


if __name__ == "__main__":
    books = load_toc()
    print(f"目录书籍数: {len(books)}")
    for b, items in books.items():
        print(f"  {b[:44]:<46} {len(items)} 篇目")
