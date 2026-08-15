# -*- coding: utf-8 -*-
"""
OCR 错字候选发现器
------------------
以"已知正确的专名表"（地名/人名/事件）为锚，扫描 18 部 OCR 文本中
与该专名相似但不同的高频形态（编辑距离 <= 2），输出疑似 OCR 错字候选。

用法:
    python scripts/find_ocr_variants.py [--min-count 3] [--max-dist 2]
输出:
    data/index/_ocr_variants_report.json
"""
import argparse
import json
import re
import sys
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
OCR_DIR = PROJECT_DIR / "data" / "ocr_output"

# 专名表：红军长征云南档案中的高频正确地名/人名/事件（与 VILLAGE_KEYWORDS 对齐）
CANONICAL_NAMES = [
    "皎平渡", "金沙江", "扎西", "威信", "寻甸", "柯渡", "丹桂", "禄劝",
    "武定", "元谋", "富民", "嵩明", "曲靖", "宣威", "丽江", "石鼓",
    "楚雄", "昭通", "镇雄", "彝良", "巧家", "会泽", "沾益", "马龙",
    "昆明", "祥云", "宾川", "鹤庆", "渡口", "乌蒙",
    "贺龙", "任弼时", "王震", "朱德", "周恩来", "毛泽东", "刘伯承", "陈云",
    "张闻天", "王稼祥", "扎西会议", "万急渡江令", "遵义会议", "中央红军",
    "红二军团", "红六军团", "红九军团", "红一方面军", "红二方面军",
    "巧渡金沙江", "石鼓渡江", "金沙水拍",
]


def norm_sim(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-count", type=int, default=3, help="候选最低出现次数")
    ap.add_argument("--max-dist", type=float, default=0.4,
                    help="最大距离（1 - 相似度），低于该值视为候选")
    args = ap.parse_args()

    han = re.compile(r"[\u4e00-\u9fff]+")
    counter = Counter()
    for f in sorted(OCR_DIR.glob("*.txt")):
        text = f.read_text(encoding="utf-8", errors="replace")
        # 提取所有连续汉字串（过滤封面噪声：只取 2-8 字串）
        for seg in han.findall(text):
            n = len(seg)
            if 2 <= n <= 8:
                counter[seg] += 1
    print(f"提取到 {len(counter)} 个不同汉字串")

    # 只看高频串，与专名比对
    candidates = {}
    for seg, cnt in counter.items():
        if cnt < args.min_count:
            continue
        if seg in CANONICAL_NAMES:
            continue
        for canon in CANONICAL_NAMES:
            if len(seg) < 2 or abs(len(seg) - len(canon)) > 2:
                continue
            if seg[0] != canon[0]:
                continue
            sim = norm_sim(seg, canon)
            if 1 - sim <= args.max_dist and sim < 1.0:
                candidates.setdefault(canon, []).append((seg, cnt, round(sim, 3)))

    # 按"相似度 × 频次"排序
    report = []
    for canon, items in candidates.items():
        for seg, cnt, sim in items:
            report.append({"canonical": canon, "variant": seg, "count": cnt, "sim": sim})
    report.sort(key=lambda x: (-x["count"], -x["sim"]))

    out = PROJECT_DIR / "data" / "index" / "_ocr_variants_report.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"共发现 {len(report)} 个候选，写入 {out}")
    print()
    print("Top 60 候选:")
    for r in report[:60]:
        print(f"  {r['canonical']} <- {r['variant']}  x{r['count']}  sim={r['sim']}")


if __name__ == "__main__":
    main()
