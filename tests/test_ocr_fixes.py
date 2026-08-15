# -*- coding: utf-8 -*-
"""OCR 纠错表单元测试"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from knowledge.ocr_fixes import apply_fixes, OCR_FIXES


def test_basic_fixes():
    assert apply_fixes("周付主席指挥渡江") == "周副主席指挥渡江"
    assert apply_fixes("金小江边") == "金沙江边"
    assert apply_fixes("扎西会设召开") == "扎西会议召开"
    assert apply_fixes("毛洋东同志") == "毛泽东同志"


def test_long_first():
    """长串优先：'巧度金沙江' 应先于 '金小江' 被替换"""
    assert apply_fixes("巧度金沙江") == "巧渡金沙江"
    assert apply_fixes("巧度金小江") == "巧渡金沙江"


def test_pingdu_variants():
    for wrong in ("拉平渡", "饮平渡", "控平渡", "佼平渡", "饺平渡", "胶平渡"):
        assert apply_fixes(f"中央红军从{wrong}渡江") == "中央红军从皎平渡渡江"


def test_no_false_positive():
    """太平渡（四川真实地名）不应被替换"""
    assert "太平渡" not in [w for w, _ in OCR_FIXES]
    assert "绞车渡" not in [w for w, _ in OCR_FIXES]


def test_empty_and_idempotent():
    assert apply_fixes("") == ""
    t = "周副主席在金沙江畔部署巧渡金沙江"
    assert apply_fixes(t) == t  # 无错字时保持原样


def test_ocr_fixes_nonempty():
    assert len(OCR_FIXES) >= 50
