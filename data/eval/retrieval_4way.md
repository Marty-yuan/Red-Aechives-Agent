# 4 路检索消融（60 题）

char / word / BGE 单路 + 各组合 RRF。
- char_tfidf / char_word_rrf_official 来自 `scripts/run_eval.py --mode both`
- 其余由本脚本在同评测集上实跑（village 过滤 min 20，RRF k=60, topk=20）

| method | hit@1 | hit@3 | hit@5 | MRR |
|---|---:|---:|---:|---:|
| `char_tfidf` | 80.0% | 90.0% | 91.7% | 0.843 |
| `word_tfidf` | 11.7% | 11.7% | 11.7% | 0.117 |
| `bge` | 3.3% | 5.0% | 8.3% | 0.069 |
| `char_word_rrf_official` | 88.3% | 90.0% | 93.3% | 0.896 |
| `char_word_rrf_off` | 8.3% | 15.0% | 20.0% | 0.120 |
| `char_bge_rrf` | 1.7% | 10.0% | 16.7% | 0.074 |
| `char_word_bge_rrf` | 8.3% | 8.3% | 15.0% | 0.113 |
