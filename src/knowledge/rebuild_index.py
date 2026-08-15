"""
只重建索引 - 优化分块策略
解决：OCR 文本被换行切得太碎，导致 chunk 平均只有 35 字
改进：合并相邻短行，生成 400-600 字的语义完整块
"""
import os, sys, io, json, pickle
from collections import Counter
from datetime import datetime
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from scipy.sparse import save_npz

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

TXT_DIR = r"D:\agent kf\Red-Aechives-Agent\data\ocr_output"
INDEX_DIR = r"D:\agent kf\Red-Aechives-Agent\data\index"

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

def merge_lines_to_chunks(text: str) -> list:
    """
    把 OCR 产生的碎片化短行，合并成 500 字左右的语义完整块。
    关键改进：不再逐行切分，而是累积相邻行直到达到目标长度。
    """
    # 先按空行分割成自然段落
    raw_paragraphs = text.split("\n")
    
    chunks = []
    current = ""
    
    for line in raw_paragraphs:
        line = line.strip()
        if not line:
            # 空行是自然段落边界，先保存当前块
            if len(current) >= MIN_CHUNK_SIZE:
                chunks.append(current)
                current = ""
            continue
        
        # 累积文本
        if current:
            current += line
        else:
            current = line
        
        # 达到目标长度就切块
        if len(current) >= TARGET_CHUNK_SIZE:
            chunks.append(current)
            current = ""
    
    # 保存最后剩余的部分
    if len(current) >= MIN_CHUNK_SIZE:
        chunks.append(current)
    elif current and chunks:
        # 太短的尾巴拼到前一个块
        chunks[-1] += current
    
    return chunks

def chunk_text(text: str, source_file: str) -> list:
    """分块并标注地点"""
    raw_chunks = merge_lines_to_chunks(text)
    
    final_chunks = []
    for raw in raw_chunks:
        locations = [kw for kw in VILLAGE_KEYWORDS if kw in raw]
        final_chunks.append({
            "text": raw,
            "locations": locations,
            "source": source_file
        })
    
    return final_chunks

def rebuild():
    os.makedirs(INDEX_DIR, exist_ok=True)
    
    txt_files = sorted([f for f in os.listdir(TXT_DIR) if f.endswith(".txt")])
    print(f"读取 {len(txt_files)} 个 txt 文件...")
    
    all_chunks = []
    file_stats = []
    
    for fname in txt_files:
        with open(os.path.join(TXT_DIR, fname), "r", encoding="utf-8") as f:
            text = f.read()
        chunks = chunk_text(text, fname)
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
    
    summary = {
        "built_at": datetime.now().isoformat(),
        "total_chunks": total,
        "avg_chunk_len": avg_total,
        "total_villages": len(village_index),
        "villages": dict(loc_counter.most_common(30)),
        "vector_shape": list(embeddings.shape)
    }
    with open(os.path.join(INDEX_DIR, "_index_summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    
    print(f"\n索引重建完成: {INDEX_DIR}")

if __name__ == "__main__":
    rebuild()