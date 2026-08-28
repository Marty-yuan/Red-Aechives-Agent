# 检索消融对比（60 题，项目自建评测）

数据：data/eval/eval_set.json (60 题 gold_chunk_ids)
管道：HybridArchiveRetriever（与 create_retriever() 一致），pool=max(topk*8, 40)=160，RRF k=60

| method | hit@1 | hit@3 | hit@5 | MRR |
|---|---:|---:|---:|---:|
| `char_tfidf` | 1.7% | 10.0% | 15.0% | 0.083 |
| `word_tfidf` | 3.3% | 5.0% | 8.3% | 0.069 |
| `hybrid_rrf` | 1.7% | 5.0% | 13.3% | 0.068 |
