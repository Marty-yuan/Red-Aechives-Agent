# -*- coding: utf-8 -*-
"""TOC 溯源模块单元测试"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from knowledge.toc_index import (
    normalize_text,
    _parse_page,
    match_book,
    approx_annotate,
)


def test_normalize_text():
    assert normalize_text("红军长征过云南 （节录）") == "红军长征过云南节录"
    assert normalize_text("ＡＢＣ１２３") == "ABC123"
    assert normalize_text("") == ""


def test_parse_page():
    assert _parse_page("23") == 23
    assert _parse_page("23-30") == 23
    assert _parse_page("-") is None
    assert _parse_page("无") is None
    assert _parse_page(None) is None


def test_approx_annotate_basic():
    items = [("甲篇", 1), ("乙篇", 50), ("丙篇", 100)]
    # offset 在文本 25% 处（正文起点 5% 之后），应归入约 25 页的篇目
    text_len = 10000
    # 25% 文本 -> page ≈ 1 + 0.21 * 99 ≈ 21 -> 甲篇(1-50)
    sec, page, conf = approx_annotate(text_len, 2500, items, front_ratio=0.05)
    assert sec == "甲篇"
    assert page is not None
    assert conf == "approx"
    # 75% 文本 -> page ≈ 74 -> 乙篇(50-100)
    sec2, page2, _ = approx_annotate(text_len, 7500, items, front_ratio=0.05)
    assert sec2 == "乙篇"
    # 文本末尾 -> page ≈ 100 -> 丙篇(100-101)
    sec3, page3, _ = approx_annotate(text_len, 9999, items, front_ratio=0.05)
    assert sec3 == "丙篇" and page3 == 100


def test_approx_annotate_no_pages():
    items = [("无页码", None), ("也无", None)]
    sec, page, conf = approx_annotate(1000, 500, items)
    assert sec is None and page is None and conf is None


def test_match_book():
    books = {
        "红军长征过云南": [("篇", 1)],
        "金沙江的记忆 1935-2006 红军长征过云南纪实": [("篇", 1)],
    }
    assert match_book("红军长征过云南 -- 编写组 -- 1985.txt", books) == "红军长征过云南"
    assert match_book("金沙江的记忆 1935-2006 红军长征过云南纪实 (史石编).txt", books) == "金沙江的记忆 1935-2006 红军长征过云南纪实"
