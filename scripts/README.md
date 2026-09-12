# scripts/ 脚本地图

> 25+ 个脚本平铺在此目录，按用途分三类。**保持平铺的原因**：每个脚本用
> `Path(__file__).resolve().parents[1]` 定位项目根，移入子目录会破坏路径解析；
> 且《项目文档》及 docs/ 下 10+ 份报告以 `scripts/xxx.py` 路径引用这些脚本供评委复现。
> 因此用本 README 做逻辑分层，而非物理移动。（2026-09-12）

## 一、核心流水线（数据 → 索引 → 评测，可一键复现）

| 脚本 | 用途 |
|---|---|
| `build_eval_set.py` | 构建 60 题检索评测集（关键词弱标注基线） |
| `run_eval.py` | **官方评测入口**：TF-IDF / Hybrid 对比，`--mode both` |
| `eval_factcheck.py` | FactChecker 量化评测（10 正 / 10 负样本对） |
| `annotate_gold.py` | 精标集标注工具（CLI 交互式 gold 段落标注） |
| `upgrade_eval_gold.py` | 为评测集自动标注 gold_chunk_ids（严格 recall 用） |
| `bench_orchestrator.py` | Orchestrator 延迟与成本基准 |
| `build_field_index.py` | 构建字段通道索引（结构化上下文） |

## 二、数据治理与知识图谱（流水线组成，按需运行）

| 脚本 | 用途 |
|---|---|
| `ocr_quality_check.py` | OCR 文本质量评估（A 部分数据质量盘点） |
| `find_ocr_variants.py` | OCR 错字候选发现器（以专名为锚扫描变体） |
| `ocr_llm_correction_pilot.py` | OCR LLM 批量纠错**试点**（小样本验证） |
| `ocr_llm_correction_batch.py` | OCR LLM 批量纠错（可续跑全量版） |
| `apply_entity_review.py` | 应用存疑实体的人工复核结论到知识图谱 |
| `reextract_missing_books.py` | 补抽取 LLM 抽取为 0 的档案并合并进图谱 |
| `update_stats.py` | 自动生成数据统计文档 |

## 三、一次性实验脚本（结果已产出并写入评测报告，保留仅供复现）

| 脚本 | 实验 |
|---|---|
| `eval_retrieval_compare.py` | char / word / Hybrid 消融（+8.3pp 拆解） |
| `eval_retrieval_4way.py` | 4 路消融：char / word / BGE / 各组合 RRF |
| `eval_improvements.py` | 检索增强评测（60 题） |
| `build_contextual_chunks.py` | Contextual Retrieval：生成 50-100 字背景前缀 |
| `rebuild_contextual_index.py` | Contextual Retrieval：独立评测索引 |
| `build_contextual_bge.py` | Contextual Retrieval：BGE 向量（离线） |
| `eval_retrieval_contextual.py` | Contextual Retrieval 消融评测 |
| `eval_retrieval_contextual_real.py` | Contextual Retrieval（复刻 run_eval 判定逻辑） |
| `eval_retrieval_contextual_bge.py` | Contextual Retrieval：BGE 语义腿消融 |
| `eval_oracle_prefix.py` | Oracle 上界验证（注入 gold 实体测收益上限） |

> 第三类脚本的结论均为**诚实否定结果**（Contextual Retrieval 无收益、BGE 在 OCR
> 噪声下失效），归因分析见 `docs/检索消融对比报告.md` 与项目文档 3.2.11 / 3.2.12。
> 重跑它们不会改变线上系统行为（线上索引在 `data/index/`，实验索引在
> `data/index_contextual/`，互不覆盖）。
