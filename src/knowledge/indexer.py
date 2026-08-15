"""知识索引构建器 - OCR 文本 → 向量索引"""
import os, json, pickle, sys
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from scipy.sparse import save_npz

OCR_DIR = "data/ocr_output"
INDEX_DIR = "data/index"
CHUNK_SIZE = 500
CHUNK_OVERLAP = 50

VILLAGE_KEYWORDS = [
    "皎平渡", "石鼓", "扎西", "寻甸", "柯渡", "禄劝", "楚雄", "昭通", "曲靖",
    "丽江", "金沙江", "威信", "镇雄", "彝良", "巧家", "会泽", "富民", "嵩明",
    "元谋", "武定", "禄丰", "大姚", "姚安", "南华", "祥云", "宾川", "鹤庆",
    "昆明", "渡口", "乌蒙", "宣威", "富源", "沾益", "马龙"
]

def split_chunks(text, source_info):
    """将长文本切分为带重叠的 chunks"""
    chunks = []
    start = 0
    while start < len(text):
        end = start + CHUNK_SIZE
        chunk_text = text[start:end]
        if len(chunk_text) < 50:
            break

        # 找最近的地点关键词
        locations = [kw for kw in VILLAGE_KEYWORDS if kw in chunk_text]

        chunks.append({
            "text": chunk_text,
            "locations": locations,
            "source_file": source_info.get("file", ""),
            "source_page": source_info.get("page", ""),
            "char_count": len(chunk_text)
        })

        start = end - CHUNK_OVERLAP

    return chunks

def build_index():
    os.makedirs(INDEX_DIR, exist_ok=True)

    # 读取 OCR 输出
    ocr_files = [f for f in os.listdir(OCR_DIR) if f.endswith(".json") and not f.startswith("_")]
    print(f"找到 {len(ocr_files)} 个 OCR 输出文件")

    all_chunks = []
    for fname in ocr_files:
        with open(os.path.join(OCR_DIR, fname), "r", encoding="utf-8") as f:
            data = json.load(f)

        for page_data in data.get("pages", []):
            chunks = split_chunks(page_data["text"], {
                "file": data["file"],
                "page": page_data["page"]
            })
            all_chunks.extend(chunks)

    print(f"总计 {len(all_chunks)} 个 chunks")

    if not all_chunks:
        print("❌ 没有数据！请先运行 OCR 处理")
        return

    # 统计地点分布
    from collections import Counter
    loc_counter = Counter()
    for c in all_chunks:
        for loc in c["locations"]:
            loc_counter[loc] += 1

    print("\n地点分布 (Top 15):")
    for loc, count in loc_counter.most_common(15):
        print(f"  {loc}: {count} chunks")

    # 构建 TF-IDF 索引
    texts = [c["text"] for c in all_chunks]
    vectorizer = TfidfVectorizer(max_features=1000)
    embeddings = vectorizer.fit_transform(texts)
    print(f"\nTF-IDF 矩阵: {embeddings.shape}")

    # 构建村寨索引
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

    # 汇总
    summary = {
        "total_chunks": len(all_chunks),
        "total_villages": len(village_index),
        "villages": {k: len(v) for k, v in sorted(village_index.items(), key=lambda x: -len(x[1]))},
        "vector_dimensions": embeddings.shape[1]
    }
    with open(os.path.join(INDEX_DIR, "_index_summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(f"\n✅ 索引构建完成")
    print(f"   Chunks: {len(all_chunks)}")
    print(f"   村寨数: {len(village_index)}")
    print(f"   输出: {os.path.abspath(INDEX_DIR)}")

if __name__ == "__main__":
    build_index()
