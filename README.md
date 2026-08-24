# 红色档案智能体

基于云南省红军长征档案构建的多村寨 AI 数字代言人。项目结合 RAG、多智能体任务规划、事实校验、知识图谱和地图/时间轴可视化。

## 当前功能

- OCR 档案文本清洗与 TF-IDF 检索
- 村寨数字代言人多轮问答
- DeepSeek 驱动的复杂任务规划与工具调用
- 事实校验 Agent
- 档案知识图谱：手工图谱 + OCR 自动抽取 + 实体自动校验
- FastAPI Web：地图、双路线、时间轴、战士动画、语音朗读、知识图谱可视化

## 目录

```text
src/
├── agent/        # RAG、规划、工具、事实校验、图谱查询
├── knowledge/    # 文本清洗、索引构建
├── kg/           # 知识图谱抽取、校验、合并
├── ocr/          # OCR 相关脚本
└── web/          # FastAPI 后端与前端页面

data/
├── ocr_output/        # OCR 档案文本
├── index/             # TF-IDF 索引
└── knowledge_graph/   # 知识图谱 + 档案篇目目录(book_toc.json)

docs/
├── 当前项目技术文档.md
└── 后续功能技术文档.md
```

## 队友从零运行项目

### 1. 克隆仓库

```powershell
git clone <你的仓库地址>
cd Red-Aechives-Agent
```

### 2. 准备本地数据

以下数据默认不会上传到 GitHub，需要从团队共享位置复制到本地：

```text
data/ocr_output/    OCR 档案文本（18 部）
data/index/         TF-IDF 索引
```

以下数据已入库（克隆后自带），无需额外准备：

```text
data/knowledge_graph/knowledge_graph.json   知识图谱（473 实体 / 282 关系，LLM 抽取 + 校验）
data/knowledge_graph/book_toc.json          档案篇目目录（18 部书、1,225 条篇目-页码，用于"某书某页"溯源）
```

如果本地没有索引，需要先重建（需要 `data/ocr_output/` 就位）：

```powershell
python src/knowledge/rebuild_index.py
```

> 重建索引会自动做三件事：① 应用 OCR 错字纠错表（`src/knowledge/ocr_fixes.py`，53 条）；
> ② 按篇目目录标注每个文本块的篇目名与页码（`src/knowledge/toc_index.py`）；
> ③ 生成 TF-IDF 索引与村寨倒排。
> 如需**重新生成** `book_toc.json`（例如目录 xlsx 更新过），设置环境变量 `RED_ARCHIVE_TOC_XLSX` 指向 xlsx 后重跑索引；否则直接使用入库的目录即可。

### 3. 创建虚拟环境

Windows PowerShell：

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

### 4. 安装依赖

```powershell
python -m pip install -r requirements.txt
```

### 5. 配置 DeepSeek API Key

项目根目录的 `.env` 默认不存在，需要自己创建。

先复制示例文件：

```powershell
Copy-Item .env.example .env
```

然后用 VS Code 打开 `.env`，改成：

```text
DEEPSEEK_API_KEY=sk-你的真实Key
```

也可以不创建 `.env`，而是临时设置环境变量：

```powershell
$env:DEEPSEEK_API_KEY="你的真实Key"
```

> 为什么看不到 `.env`：它不是一个自动生成的系统文件，只有执行 `Copy-Item .env.example .env` 后才会出现。VS Code 文件树默认应该能看到；如果看不到，点击左侧资源管理器刷新，或直接在终端运行 `Get-ChildItem -Force` 查看。

### 6. 命令行测试

```powershell
python src/agent/main.py
```

### 7. 启动 Web

```powershell
python src/web/app.py
```

浏览器打开：`http://127.0.0.1:5000`

> 该服务基于 **FastAPI + Uvicorn**。如需热重载或更完整的 ASGI 部署，也可以在项目根目录运行：
> ```powershell
> $env:PYTHONPATH = "src"
> python -m uvicorn web.app:app --reload --port 5000
> ```
> 交互式 API 文档见 `http://127.0.0.1:5000/docs`。

## 详细文档

- [当前项目技术文档](docs/当前项目技术文档.md)
- [后续功能技术文档](docs/后续功能技术文档.md)
- [代码规范与协作约定（必读）](docs/CODE_STYLE.md)

## 协作须知（两人开发）

- **环境**：统一 Python 3.10+，用 `requirements-lock.txt` 复现环境；虚拟环境命名 `venv`。
- **路径**：禁止硬编码本机绝对路径（如 `D:\...`），项目根用 `RED_ARCHIVE_PROJECT_DIR` 或代码推导。
- **换行/编码**：仓库已配置 `.gitattributes`（LF + UTF-8），合并冲突最小化；保存文件请用 UTF-8。
- **密钥**：`.env` 不入库，用 `.env.example` 占位；API Key 只在本地 `.env`。
- **数据**：`data/ocr_output`、`data/index` 不入库（体积大），克隆后复制或重建；图谱/目录/评测等结构化资产入库。
- **提交**：合并前 `git fetch && git rebase origin/main`，跑 `python -m pytest tests/`，Commit Message 用 Conventional Commits。

## 注意事项

- `.env` 已经被 `.gitignore` 忽略，不要把真实 Key 提交到 GitHub。
- `.env.example` 可以提交，里面只有占位符。
- OCR 原始文本和索引体积较大，默认不提交。
- 上传前请阅读 `docs/当前项目技术文档.md` 的“GitHub 上传前建议”。
