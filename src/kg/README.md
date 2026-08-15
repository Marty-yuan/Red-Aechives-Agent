# 知识图谱模块

## 文件说明

- `data/knowledge_graph/knowledge_graph.json`
  手工整理的基础图谱，是当前 Web 和 Agent 使用的数据源。

- `src/kg/build_graph.py`
  校验图谱节点和关系是否完整：
  ```powershell
  python src/kg/build_graph.py validate
  python src/kg/build_graph.py summary
  ```

- `src/kg/extract_entities.py`
  从 `data/ocr_output/*.txt` 自动抽取实体和关系：
  ```powershell
  # 离线规则演示（不需要 API）
  python src/kg/extract_entities.py --mode rule --limit-files 2

  # DeepSeek 抽取
  python src/kg/extract_entities.py --mode llm --limit-files 10

  # 审查合并结果后正式提交
  python src/kg/extract_entities.py --mode llm --commit
  ```

  输出：
  - `data/knowledge_graph/auto_extracted.json`
    本次抽取的原始实体/关系。
  - `data/knowledge_graph/knowledge_graph_auto.json`
    基础图谱 + 本次抽取的合并预览。

## 建议流程

1. 先小样本运行，观察 `knowledge_graph_auto.json`。
2. 人工修正明显的错别名、错别字和重复实体。
3. 确认无误后加 `--commit` 写回 `knowledge_graph.json`。
4. 重启 Web 后即可在前端“知识图谱”中看到新增内容。

## OCR 实体自动校验

如果资料没看过、不想逐条人工复核，建议先抽取，再自动校验：

```powershell
# 抽取原始实体
python src/kg/extract_entities.py --mode llm --limit-files 10 --max-chars 3000

# 自动校验实体质量
python src/kg/validate_entities.py --mode llm

# 查看仅需人工处理的存疑项
data/knowledge_graph/review_required.json

# 确认 clean 图谱后提交
python src/kg/validate_entities.py --commit
```

自动校验会做两件事：
1. 用频次判断：只出现一次的实体优先标记为存疑。
2. 用 DeepSeek 判断：是否为真实历史人物/地点/事件，并自动修正明显 OCR 错字。

你只需要看 `review_required.json` 里的少量存疑项，不需要从头阅读原始档案。
