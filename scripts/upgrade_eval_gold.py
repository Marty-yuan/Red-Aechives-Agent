# -*- coding: utf-8 -*-
"""
为评测集自动标注 gold_chunk_ids（严格 recall 用）
-----------------------------------------------
基于 anchor 在索引 chunks 中的匹配，为每题写入 gold_chunk_ids。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, "src")
from agent.retriever import ArchiveRetriever

EVAL_PATH = Path("data/eval/eval_set.json")
GOLD_CAP = 20


def main() -> None:
    ret = ArchiveRetriever()
    chunks = ret.chunks
    data = json.loads(EVAL_PATH.read_text(encoding="utf-8"))
    upgraded = 0

    for q in data["questions"]:
        anchor = q["anchor"]
        kws = q.get("keywords", [])
        gold = []
        for i, c in enumerate(chunks):
            text = c["text"]
            if anchor in text or any(k in text for k in kws):
                gold.append(i)
        gold = gold[:GOLD_CAP]
        if gold:
            q["gold_chunk_ids"] = gold
            q["gold_size"] = len(gold)
            upgraded += 1

    data["meta"]["annotation"] = "auto gold_chunk_ids from anchor/keywords"
    data["meta"]["gold_labeled"] = upgraded
    EVAL_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已标注 {upgraded}/{len(data['questions'])} 题的 gold_chunk_ids -> {EVAL_PATH}")


if __name__ == "__main__":
    main()
