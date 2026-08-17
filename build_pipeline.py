"""
============================================================================
 红色村寨数字代言人 - 完整知识管道
 步骤: OCR PDF -> 文本清洗 -> 地名分块 -> TF-IDF索引 -> 村寨知识库
============================================================================
"""
import fitz
import os, sys, io, json, pickle, re
from collections import Counter
from datetime import datetime

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from scipy.sparse import save_npz

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# 原始 PDF 目录：用环境变量 RED_ARCHIVE_PDF_DIR 指定，默认本机开发路径
PDF_DIR = os.environ.get("RED_ARCHIVE_PDF_DIR", "")
# 项目根目录：优先环境变量，否则按脚本位置推导（build_pipeline.py 位于项目根）
PROJECT_DIR = os.environ.get(
    "RED_ARCHIVE_PROJECT_DIR",
    os.path.dirname(os.path.abspath(__file__)),
)
TXT_DIR = os.path.join(PROJECT_DIR, "data", "ocr_output")
INDEX_DIR = os.path.join(PROJECT_DIR, "data", "index")
CHUNK_SIZE = 500
CHUNK_OVERLAP = 80

VILLAGE_KEYWORDS = [
    "皎平渡", "石鼓", "扎西", "寻甸", "柯渡", "禄劝", "楚雄", "昭通", "曲靖",
    "丽江", "金沙江", "威信", "镇雄", "彝良", "巧家", "会泽", "富民", "嵩明",
    "元谋", "武定", "禄丰", "大姚", "姚安", "南华", "祥云", "宾川", "鹤庆",
    "昆明", "渡口", "乌蒙", "宣威", "富源", "沾益", "马龙", "丹桂",
    "蒙自", "东川", "永善", "绥江", "盐津", "大关", "鲁甸"
]

def clean_ocr_text(text: str) -> str:
    text = re.sub(r'(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])', '', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r'\n\d{1,4}\n', '\n', text)
    return text.strip()

def step1_extract():
    print("=" * 60)
    print("STEP 1: OCR PDF -> 清洗 -> txt")
    print("=" * 60)
    
    os.makedirs(TXT_DIR, exist_ok=True)
    
    pdf_files = sorted([f for f in os.listdir(PDF_DIR) if f.lower().endswith(".pdf")])
    stats = []
    
    for i, fname in enumerate(pdf_files):
        txt_name = os.path.splitext(fname)[0][:80] + ".txt"
        txt_path = os.path.join(TXT_DIR, txt_name)
        
        # 断点续跑：跳过已处理的
        if os.path.exists(txt_path) and os.path.getsize(txt_path) > 1000:
            chars = os.path.getsize(txt_path)
            stats.append({"file": fname, "chars": chars})
            print(f"  [{i+1:>2}/{len(pdf_files)}] SKIP (已存在)  {fname[:55]}")
            continue
        
        path = os.path.join(PDF_DIR, fname)
        doc = fitz.open(path)
        total_pages = len(doc)
        
        pages_text = []
        for page_num in range(total_pages):
            try:
                text = doc[page_num].get_text()
                if text.strip():
                    # 保留页码标记 [PAGE:n]，供索引层做"某页可溯源"
                    pages_text.append(f"[PAGE:{page_num + 1}]\n" + clean_ocr_text(text))
            except Exception:
                pass
            
            # 大文件显示进度
            if total_pages > 200 and (page_num + 1) % 100 == 0:
                print(f"    ... {page_num+1}/{total_pages} 页")
        
        doc.close()
        full_text = "\n\n".join(pages_text)
        
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(full_text)
        
        stats.append({"file": fname, "chars": len(full_text)})
        pct = f"{len(pages_text)}/{total_pages}页" if total_pages > 0 else ""
        print(f"  [{i+1:>2}/{len(pdf_files)}] {len(full_text):>8} 字符 {pct}  {fname[:55]}")
    
    total = sum(s["chars"] for s in stats)
    print(f"\n  DONE: {total:,} 字符, {len(stats)} 个 txt -> {TXT_DIR}")
    return stats

# ---- chunk_text, step2_index, step3_verify unchanged ----
def chunk_text(text: str, source_file: str) -> list:
    paragraphs = [p.strip() for p in text.split("\n") if len(p.strip()) > 15]
    chunks = []
    for para in paragraphs:
        locations = [kw for kw in VILLAGE_KEYWORDS if kw in para]
        if len(para) <= CHUNK_SIZE:
            chunks.append({"text": para, "locations": locations, "source": source_file})
        else:
            for start in range(0, len(para), CHUNK_SIZE - CHUNK_OVERLAP):
                sub = para[start:start + CHUNK_SIZE]
                sub_locs = [kw for kw in VILLAGE_KEYWORDS if kw in sub]
                chunks.append({"text": sub, "locations": sub_locs or locations, "source": source_file})
    return chunks

def step2_index():
    print("\n" + "=" * 60)
    print("STEP 2: 构建知识索引")
    print("=" * 60)
    os.makedirs(INDEX_DIR, exist_ok=True)
    
    txt_files = sorted([f for f in os.listdir(TXT_DIR) if f.endswith(".txt")])
    print(f"  读取 {len(txt_files)} 个文本文件...")
    
    all_chunks = []
    for fname in txt_files:
        with open(os.path.join(TXT_DIR, fname), "r", encoding="utf-8") as f:
            text = f.read()
        chunks = chunk_text(text, fname)
        all_chunks.extend(chunks)
    
    print(f"  总计: {len(all_chunks):,} 个文本块")
    
    loc_counter = Counter()
    for c in all_chunks:
        for loc in c["locations"]:
            loc_counter[loc] += 1
    
    print(f"\n  地点覆盖 (Top 20):")
    for loc, cnt in loc_counter.most_common(20):
        bar = "#" * min(cnt // 100, 40)
        print(f"    {loc:<8} {cnt:>6} {bar}")
    
    print(f"\n  构建 TF-IDF 向量索引...")
    texts = [c["text"] for c in all_chunks]
    vectorizer = TfidfVectorizer(max_features=2000, sublinear_tf=True)
    embeddings = vectorizer.fit_transform(texts)
    print(f"  向量维度: {embeddings.shape}")
    
    village_index = {}
    for i, c in enumerate(all_chunks):
        for loc in c["locations"]:
            village_index.setdefault(loc, []).append(i)
    
    with open(os.path.join(INDEX_DIR, "chunks.json"), "w", encoding="utf-8") as f:
        json.dump(all_chunks, f, ensure_ascii=False, indent=2)
    with open(os.path.join(INDEX_DIR, "vectorizer.pkl"), "wb") as f:
        pickle.dump(vectorizer, f)
    save_npz(os.path.join(INDEX_DIR, "embeddings.npz"), embeddings)
    with open(os.path.join(INDEX_DIR, "village_index.json"), "w", encoding="utf-8") as f:
        json.dump(village_index, f, ensure_ascii=False)
    
    summary = {
        "built_at": datetime.now().isoformat(),
        "source": f"{len(txt_files)} OCR PDFs",
        "total_chunks": len(all_chunks),
        "total_villages": len(village_index),
        "villages": dict(loc_counter.most_common(30)),
        "vector_shape": list(embeddings.shape)
    }
    with open(os.path.join(INDEX_DIR, "_index_summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    
    print(f"\n  OK: {INDEX_DIR}")
    return all_chunks, vectorizer, embeddings, village_index

def step3_verify(chunks, vectorizer, embeddings, village_index):
    print("\n" + "=" * 60)
    print("STEP 3: 搜索验证")
    print("=" * 60)
    
    tests = [
        ("皎平渡", "红军怎么渡过金沙江"),
        ("扎西", "扎西会议做了什么决定"),
        ("石鼓", "红二六军团如何渡江"),
        ("寻甸", "万急渡江令是什么"),
    ]
    
    for village, query in tests:
        q_vec = vectorizer.transform([query])
        sims = cosine_similarity(q_vec, embeddings)[0]
        
        if village in village_index:
            indices = village_index[village]
            top = sorted([(i, sims[i]) for i in indices], key=lambda x: -x[1])[:1]
        else:
            top = sorted(enumerate(sims), key=lambda x: -x[1])[:1]
        
        if top:
            i, score = top[0]
            chunk = chunks[i]
            print(f"\n  [{village}] {query}")
            print(f"    匹配 {score:.3f} | {chunk['source'][:40]}")
            print(f"    {chunk['text'][:150]}...")
    
    print(f"\n{'='*60}")
    print("管道完成! python src/web/app.py 启动服务")
    print(f"{'='*60}")

def main():
    start = datetime.now()
    print(f"红色村寨数字代言人 - 知识管道")
    print(f"启动: {start.strftime('%Y-%m-%d %H:%M:%S')}")
    
    step1_extract()
    chunks, vectorizer, embeddings, village_index = step2_index()
    step3_verify(chunks, vectorizer, embeddings, village_index)
    
    elapsed = (datetime.now() - start).total_seconds()
    print(f"\n总耗时: {elapsed:.1f} 秒")

if __name__ == "__main__":
    main()
