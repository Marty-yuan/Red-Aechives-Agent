"""
============================================================================
 红色村寨数字代言人 - 完整知识管道（薄封装）
 步骤: OCR PDF -> 文本清洗（含 [PAGE:n] 页码标记） -> 委托 rebuild_index 建索引
============================================================================

【2026-09-12 重构说明】
本文件原先的 step2/step3（3 字段 chunk + 词级 TF-IDF）已过时——
与现役 7 字段 chunks.json（text/source/offset/page/section/confidence/locations）
及字符级 2-4gram 索引不一致。真正的索引构建器是：

    python src/knowledge/rebuild_index.py

本文件现在只做两件事：
1. step1_extract()：PDF -> data/ocr_output/*.txt（带 [PAGE:n] 页码标记，断点续跑）
2. 调用 src.knowledge.rebuild_index.rebuild() 完成纠错 + 分块 + 索引
"""
import fitz
import os, sys, io, re
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

PROJECT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_DIR / "src"))

# 原始 PDF 目录：用环境变量 RED_ARCHIVE_PDF_DIR 指定
PDF_DIR = os.environ.get("RED_ARCHIVE_PDF_DIR", "")
TXT_DIR = PROJECT_DIR / "data" / "ocr_output"


def clean_ocr_text(text: str) -> str:
    text = re.sub(r'(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])', '', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r'\n\d{1,4}\n', '\n', text)
    return text.strip()


def step1_extract():
    """PDF -> 清洗 -> txt（保留 [PAGE:n] 页码标记，供索引层做页码溯源）。断点续跑。"""
    print("=" * 60)
    print("STEP 1: OCR PDF -> 清洗 -> txt")
    print("=" * 60)

    if not PDF_DIR or not os.path.isdir(PDF_DIR):
        print(f"  跳过：未设置 RED_ARCHIVE_PDF_DIR 或目录不存在（当前: {PDF_DIR!r}）")
        print("  若只需重建索引，直接运行: python src/knowledge/rebuild_index.py")
        return

    TXT_DIR.mkdir(parents=True, exist_ok=True)
    pdf_files = sorted(f for f in os.listdir(PDF_DIR) if f.lower().endswith(".pdf"))

    for i, fname in enumerate(pdf_files):
        txt_name = os.path.splitext(fname)[0][:80] + ".txt"
        txt_path = TXT_DIR / txt_name

        if txt_path.exists() and txt_path.stat().st_size > 1000:
            print(f"  [{i+1:>2}/{len(pdf_files)}] SKIP (已存在)  {fname[:55]}")
            continue

        doc = fitz.open(os.path.join(PDF_DIR, fname))
        total_pages = len(doc)
        pages_text = []
        for page_num in range(total_pages):
            try:
                text = doc[page_num].get_text()
                if text.strip():
                    pages_text.append(f"[PAGE:{page_num + 1}]\n" + clean_ocr_text(text))
            except Exception:
                pass
            if total_pages > 200 and (page_num + 1) % 100 == 0:
                print(f"    ... {page_num+1}/{total_pages} 页")
        doc.close()

        full_text = "\n\n".join(pages_text)
        txt_path.write_text(full_text, encoding="utf-8")
        print(f"  [{i+1:>2}/{len(pdf_files)}] {len(full_text):>8} 字符  {fname[:55]}")


def step2_rebuild_index():
    """委托给现役索引构建器（OCR 纠错 + 语义分块 + 篇目/页码标注 + char TF-IDF）。"""
    print("\n" + "=" * 60)
    print("STEP 2: 重建索引（委托 src/knowledge/rebuild_index.py）")
    print("=" * 60)
    from knowledge.rebuild_index import rebuild
    rebuild()


def main():
    print("红色村寨数字代言人 - 知识管道（薄封装）")
    step1_extract()
    step2_rebuild_index()
    print("\n管道完成! python src/web/app.py 启动服务")


if __name__ == "__main__":
    main()
