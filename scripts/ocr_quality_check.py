# -*- coding: utf-8 -*-
"""OCR 文本质量评估脚本 - A 部分数据质量盘点"""
import re
from pathlib import Path

OCR_DIR = Path(__file__).resolve().parents[1] / "data" / "ocr_output"
files = sorted(OCR_DIR.glob("*.txt"))

HAN = re.compile(r"[\u4e00-\u9fff]")
NOISE = re.compile(r"[A-Za-z0-9]")

print("=== OCR 文件可读性评估（按噪声比例排序） ===")
print(f"{'噪声%':>6} {'汉字':>9} {'字母数字':>9}  文件")
print("-" * 100)
results = []
for f in files:
    text = f.read_text(encoding="utf-8", errors="replace")
    han = len(HAN.findall(text))
    noise = len(NOISE.findall(text))
    total = max(len(text), 1)
    ratio = noise / total * 100
    results.append((ratio, han, noise, f.name))
results.sort(key=lambda x: -x[0])
for ratio, han, noise, name in results:
    print(f"{ratio:6.1f}% {han:>9,} {noise:>9,}  {name[:55]}")

print()
print("=== 每个文件可读片段抽查（第一个连续 10+ 汉字） ===")
for f in files:
    text = f.read_text(encoding="utf-8", errors="replace").strip()
    seg = text
    mm = re.search(r"[\u4e00-\u9fff]{10,}", seg)
    snippet = (mm.group(0)[:70] if mm else seg[:70]).replace("\n", " ")
    print(f"  [{f.name[:24]:<26}] {snippet}")
