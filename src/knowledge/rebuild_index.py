"""
只重建索引 - 优化分块策略
解决：OCR 文本被换行切得太碎，导致 chunk 平均只有 35 字
改进：合并相邻短行，生成 400-600 字的语义完整块
"""
import os, sys, io, json, pickle, re
from collections import Counter
from datetime import datetime
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[1]
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from knowledge.ocr_fixes import apply_fixes  # noqa: E402
from knowledge.toc_index import load_toc, match_book, annotate_chunks  # noqa: E402
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from scipy.sparse import save_npz

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

PROJECT_DIR = Path(__file__).resolve().parents[2]
TXT_DIR = PROJECT_DIR / "data" / "ocr_output"
INDEX_DIR = PROJECT_DIR / "data" / "index"

# 目标 chunk 大小（字符），比之前的 35 字大幅提升
TARGET_CHUNK_SIZE = 500
MIN_CHUNK_SIZE = 100

VILLAGE_KEYWORDS = [
    "皎平渡", "石鼓", "扎西", "寻甸", "柯渡", "禄劝", "楚雄", "昭通", "曲靖",
    "丽江", "金沙江", "威信", "镇雄", "彝良", "巧家", "会泽", "富民", "嵩明",
    "元谋", "武定", "禄丰", "大姚", "姚安", "南华", "祥云", "宾川", "鹤庆",
    "昆明", "渡口", "乌蒙", "宣威", "富源", "沾益", "马龙", "丹桂",
    "蒙自", "东川", "永善", "绥江", "盐津", "大关", "鲁甸"
]

# 页码标记：build_pipeline.py 提取 PDF 时在每页文本前插入 [PAGE:n]
PAGE_RE = re.compile(r"\[PAGE:(\d+)\]")


def merge_lines_to_chunks(text: str) -> list:
    """
    把 OCR 产生的碎片化短行，合并成 500 字左右的语义完整块。
    返回 [(chunk_text, start_offset, page), ...]，其中：
      - start_offset: chunk 在源文件中的字符偏移（用于定位原文）
      - page: 该 chunk 所属页码（仅在文本含 [PAGE:n] 标记时有值）
    """
    raw_paragraphs = text.split("\n")
    
    chunks = []
    current = ""
    current_start = 0
    current_page = None
    chunk_page = None
    line_offset = 0
    
    for line in raw_paragraphs:
        stripped = line.strip()
        
        # 提取页码标记（新格式 OCR 输出）
        m = PAGE_RE.search(stripped)
        if m:
            current_page = int(m.group(1))
            stripped = PAGE_RE.sub("", stripped).strip()
        
        if not stripped:
            # 空行是自然段落边界，先保存当前块
            if len(current) >= MIN_CHUNK_SIZE:
                chunks.append((current, current_start, chunk_page))
                current = ""
            line_offset += len(line) + 1
            continue
        
        # 累积文本
        if current:
            current += stripped
        else:
            # chunk 起点：记录起始偏移与起始页码
            current = stripped
            current_start = line_offset
            chunk_page = current_page
        
        # 达到目标长度就切块
        if len(current) >= TARGET_CHUNK_SIZE:
            chunks.append((current, current_start, chunk_page))
            current = ""
        
        line_offset += len(line) + 1
    
    # 保存最后剩余的部分
    if len(current) >= MIN_CHUNK_SIZE:
        chunks.append((current, current_start, chunk_page))
    elif current and chunks:
        # 太短的尾巴拼到前一个块（保持原 offset/page）
        chunks[-1] = (chunks[-1][0] + current, chunks[-1][1], chunks[-1][2])
    
    return chunks

def chunk_text(text: str, source_file: str) -> list:
    """分块并标注地点、偏移与页码"""
    raw_chunks = merge_lines_to_chunks(text)
    
    final_chunks = []
    for raw, offset, page in raw_chunks:
        locations = [kw for kw in VILLAGE_KEYWORDS if kw in raw]
        final_chunks.append({
            "text": raw,
            "locations": locations,
            "source": source_file,
            "offset": offset,
            "page": page,
        })
    
    return final_chunks

def rebuild():
    os.makedirs(INDEX_DIR, exist_ok=True)
    
    txt_files = sorted([f for f in os.listdir(TXT_DIR) if f.endswith(".txt")])
    print(f"读取 {len(txt_files)} 个 txt 文件...")
    
    all_chunks = []
    file_stats = []
    
    # 加载篇目目录（用于"篇目 + 页码"级溯源，见 toc_index.py）
    toc = load_toc()
    book_anchor_stats = {}
    
    for fname in txt_files:
        with open(os.path.join(TXT_DIR, fname), "r", encoding="utf-8") as f:
            text = f.read()
        # OCR 错字纠错（见 ocr_fixes.py，可扩展条目）
        text = apply_fixes(text)
        chunks = chunk_text(text, fname)
        
        # 篇目/页码标注：精确锚定优先，不可靠时近似插值（见 toc_index.py）
        book = match_book(fname, toc)
        annotated = 0
        if book and toc.get(book):
            anns = annotate_chunks(text, toc[book], [c.get("offset", 0) for c in chunks])
            for c, ann in zip(chunks, anns):
                c["section"] = ann["section"]
                c["page"] = ann["page"]
                c["confidence"] = ann["confidence"]
                if ann["section"]:
                    annotated += 1
        else:
            for c in chunks:
                c["section"] = None
                c["page"] = None
                c["confidence"] = None
        book_anchor_stats[fname[:40]] = f"{annotated}/{len(chunks)} chunks 标注篇目"
        
        all_chunks.extend(chunks)
        
        avg_len = sum(len(c["text"]) for c in chunks) // len(chunks) if chunks else 0
        file_stats.append({"file": fname[:50], "chunks": len(chunks), "avg_len": avg_len})
        print(f"  {len(chunks):>5} chunks | 均 {avg_len:>4} 字 | {fname[:45]}")
    
    total = len(all_chunks)
    avg_total = sum(len(c["text"]) for c in all_chunks) // total if total else 0
    print(f"\n总计: {total:,} chunks, 平均 {avg_total} 字（之前是 35 字）")
    
    # 地点统计
    loc_counter = Counter()
    for c in all_chunks:
        for loc in c["locations"]:
            loc_counter[loc] += 1
    
    print(f"\n地点覆盖 Top 20:")
    for loc, cnt in loc_counter.most_common(20):
        print(f"  {loc:<8} {cnt:>6}")
    
    # TF-IDF
    print(f"\n构建 TF-IDF 索引...")
    texts = [c["text"] for c in all_chunks]
    vectorizer = TfidfVectorizer(max_features=3000, sublinear_tf=True, 
                                 analyzer="char_wb", ngram_range=(2, 4))
    embeddings = vectorizer.fit_transform(texts)
    print(f"向量: {embeddings.shape}")
    
    # 村寨倒排
    village_index = {}
    for i, c in enumerate(all_chunks):
        for loc in c["locations"]:
            village_index.setdefault(loc, []).append(i)
    
    # 保存
    with open(os.path.join(INDEX_DIR, "chunks.json"), "w", encoding="utf-8") as f:
        json.dump(all_chunks, f, ensure_ascii=False, indent=2)
    with open(os.path.join(INDEX_DIR, "vectorizer.pkl"), "wb") as f:
        pickle.dump(vectorizer, f)
    save_npz(os.path.join(INDEX_DIR, "embeddings.npz"), embeddings)
    with open(os.path.join(INDEX_DIR, "village_index.json"), "w", encoding="utf-8") as f:
        json.dump(village_index, f, ensure_ascii=False)
    
    with_page = sum(1 for c in all_chunks if c.get("page"))
    with_section = sum(1 for c in all_chunks if c.get("section"))
    summary = {
        "built_at": datetime.now().isoformat(),
        "total_chunks": total,
        "avg_chunk_len": avg_total,
        "total_villages": len(village_index),
        "villages": dict(loc_counter.most_common(30)),
        "vector_shape": list(embeddings.shape),
        "chunks_with_page": with_page,
        "chunks_with_section": with_section,
        "chunks_with_offset": total,
        "book_anchor_stats": book_anchor_stats,
    }
    with open(os.path.join(INDEX_DIR, "_index_summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    
    print(f"\n索引重建完成: {INDEX_DIR}")

if __name__ == "__main__":
    rebuild()