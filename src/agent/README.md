# Agent 层说明

村寨数字代言人的核心逻辑，包含 4 个文件：

| 文件 | 职责 |
|------|------|
| `config.py` | 所有可调参数（API key、模型、路径、检索参数） |
| `personas.py` | 村寨人格 Prompt 定义 |
| `retriever.py` | 档案检索器（加载索引 + TF-IDF 相似度检索） |
| `rag.py` | 检索增强生成（检索 + LLM 生成 + 来源标注） |
| `main.py` | 命令行测试入口 |

## 数据流

```
用户提问
   ↓
retriever.search()      检索最相关的档案片段（Top-K）
   ↓
personas.build_system_prompt()  组装村寨人格 prompt
   ↓
rag.ask()               LLM 基于档案内容生成回答
   ↓
回答 + 档案来源标注
```

## 快速测试

```bash
# 先设置 API key（二选一）
set DEEPSEEK_API_KEY=sk-xxx        # Windows 临时设置
# 或直接编辑 config.py 里的 DEEPSEEK_API_KEY

# 运行交互式测试
python src/agent/main.py
```

## 修改村寨人格

编辑 `personas.py` 中的 `VILLAGE_PERSONAS` 字典，新增或修改村寨即可。
