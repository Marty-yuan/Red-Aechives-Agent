"""
繁体转简体 + 重新索引
使用 OpenCC 将 OCR 文本统一转为简体，提升检索命中率。
"""
import os, sys, io, json
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

TXT_DIR = r"D:\agent kf\Red-Aechives-Agent\data\ocr_output"

def convert_files():
    try:
        from opencc import OpenCC
        cc = OpenCC('t2s')  # 繁体转简体
    except ImportError:
        print("缺少 opencc，请先安装:")
        print("  pip install opencc-python-reimplemented")
        sys.exit(1)

    txt_files = sorted(Path(TXT_DIR).glob("*.txt"))
    print(f"找到 {len(txt_files)} 个 txt 文件")
    
    total_before = 0
    total_after = 0
    changed = 0
    
    for f in txt_files:
        text = f.read_text(encoding="utf-8")
        total_before += len(text)
        converted = cc.convert(text)
        total_after += len(converted)
        
        if converted != text:
            changed += 1
        
        # 覆盖写回
        f.write_text(converted, encoding="utf-8")
        print(f"  {f.name[:50]}...  ({len(text)} -> {len(converted)} 字符)")
    
    print(f"\n完成: {changed}/{len(txt_files)} 个文件有转换")
    print(f"总字符: {total_before:,} -> {total_after:,}")

if __name__ == "__main__":
    convert_files()
