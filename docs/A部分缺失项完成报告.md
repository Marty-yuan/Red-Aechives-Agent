# A 部分交付成果（最终版）

> 更新日期：2026-08-20 · 状态：**A 部分已完成**

---

## 核心交付物

| 资产 | 最终状态 |
|------|----------|
| 档案索引 | **9,132 chunks**，100% 篇目+页码溯源 |
| OCR 纠错表 | **69 条**（含皎平渡 11 变体、巡检司等） |
| 知识图谱 | **536 实体 / 352 关系**（校验通过） |
| 存疑实体复核 | **36 条全部处理**，`review_required.json` 已清空 |
| 检索评测 | 60 题，均已标注 `gold_chunk_ids` |
| 混合检索 | hit@1 **88.3%**，MRR **0.896**（+8.3pp / +0.053） |
| Agent 接入 | `HybridArchiveRetriever` 已接入 tools/rag/orchestrator |
| 单元测试 | **20/20 通过** |

---

## 检索指标对比

| 指标 | TF-IDF | Hybrid (RRF) |
|------|--------|--------------|
| hit@1 | 80.0% | **88.3%** |
| hit@3 | 90.0% | 90.0% |
| hit@5 | 91.7% | **93.3%** |
| MRR | 0.843 | **0.896** |

---

## 新增脚本与模块

- `scripts/apply_entity_review.py` — 存疑实体复核
- `scripts/reextract_missing_books.py` — 补抽/合并 3 部零实体档案
- `scripts/upgrade_eval_gold.py` — 评测集 gold_chunk_ids 标注
- `src/knowledge/build_semantic_index.py` — 第二路索引
- `src/agent/hybrid_retriever.py` — RRF 混合检索
- `src/agent/retriever_factory.py` — Agent 统一检索入口

---

## 已知限制（非阻塞）

1. **3 部档案 LLM 补抽**：DeepSeek API 余额不足（402），已用规则模式写入 `auto_extracted.json`（16 实体）；充值后可重跑 `--commit`
2. **BGE 语义向量**：可选升级，当前词级 TF-IDF 混合已达目标
3. **LLM 批量 OCR 纠错**：未做（耗 API，非必需）
4. **API Key 轮换**：建议比赛前在控制台重置

---

## 一键复现

```powershell
cd C:\Users\damn\Desktop\Red-Aechives-Agent
python src/knowledge/rebuild_index.py
python src/knowledge/build_semantic_index.py
python scripts/run_eval.py --mode both
python src/kg/build_graph.py validate
python -m pytest tests/ -q
```
