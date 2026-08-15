# 红色档案智能体 · 代码规范与协作约定

> 适用对象：项目全部协作者（A 部分：数据与知识图谱；B 部分：Agent / 前端 / 语音）
> 目标：**保证两人在不同机器（Windows / macOS / Linux）上开发、合并、提交时环境一致、冲突最小**。
> 配套文件：`.gitattributes`、`.editorconfig`、`.python-version`、`requirements-lock.txt`。

---

## 1. 环境兼容（最高优先级）

### 1.1 Python 版本

- **统一使用 Python 3.10+**（当前开发环境为 3.13.9，见 `.python-version`）。
- 不要使用 Python 2 语法、不要依赖 3.13 独有的新特性（除非团队确认都已升级）。
- 虚拟环境统一命名 `venv`（已 gitignore）。

### 1.2 依赖管理

- **`requirements.txt`**：保持 `>=` 下限约束（便于快速安装），这是"约定版本范围"。
- **`requirements-lock.txt`**：精确版本锁定（`==`），记录**当前开发机实测可用**的版本组合。**新增依赖时同步更新两个文件**。
- 安装命令：`python -m pip install -r requirements.txt`（快速）或 `-r requirements-lock.txt`（复现环境）。
- 不要在代码里 import 未写入 requirements 的库；测试库（pytest）单独标注。

### 1.3 路径可移植性（禁止绝对路径）

- **严禁硬编码本机绝对路径**（如 `D:\agent kf\...`、`C:\Users\xxx\...`）。
- 项目根目录统一通过 `RED_ARCHIVE_PROJECT_DIR` 环境变量或代码位置推导（`Path(__file__).resolve().parents[2]`）。
- 参考既有实现：`src/agent/config.py`、`src/kg/extract_entities.py`、`src/knowledge/toc_index.py`。
- 新增数据路径时，优先使用 `config.PROJECT_DIR` 相对拼接。

### 1.4 换行符与编码（合并冲突的头号来源）

- 仓库通过 `.gitattributes` 强制：**文本文件统一 LF 换行**（`* text=auto eol=lf`），避免 Windows CRLF 与 macOS/Linux LF 在合并时全文件冲突。
- **所有源码与数据文件一律 UTF-8（无 BOM）**；Windows 记事本编辑后另存为 UTF-8。
- 中文注释、中文 JSON 内容均按 UTF-8 处理（`json.dump(ensure_ascii=False)`）。

### 1.5 其他环境约定

- 编辑器统一使用 `.editorconfig`（缩进 4 空格、UTF-8、LF）；VS Code 建议开启 `files.autoGuessEncoding` 并安装 EditorConfig 插件。
- 不提交：`.env`（API Key）、`data/ocr_output/`、`data/index/`、`data/tmp/`、`__pycache__/`、`venv/`（`.gitignore` 已配置，勿改动或注释掉）。

---

## 2. Git 协作规范

### 2.1 分支与提交流程

1. **`main` 为主干线**：保持可运行、可演示状态；不要直接往 main 推未验证代码。
2. 新功能/修复在 `feature/<描述>` 分支开发，完成后发起 Pull Request 合并。
3. **合并前**：
   - `git fetch origin` && `git rebase origin/main`（或 merge），先解决冲突再合入；
   - 跑一遍 `python -m pytest tests/` 确认测试通过；
   - 确认没有本机绝对路径、没有 `.env` 被误提交（`git status` 检查）。

### 2.2 Commit Message 规范（Conventional Commits）

```text
<type>(<scope>): <简短描述>

<正文说明（可选，中文）>
```

- `type`：`feat`（新功能）/ `fix`（修复）/ `docs`（文档）/ `refactor`（重构）/ `test`（测试）/ `chore`（杂项，如依赖、配置）
- `scope`：`data` / `kg`（知识图谱）/ `agent` / `web` / `docs` 等，可选
- 示例：`feat(data): 新增档案篇目目录 book_toc.json 与溯源标注`

### 2.3 数据文件与密钥

| 类别 | 处理 |
|---|---|
| `data/knowledge_graph/book_toc.json`、`knowledge_graph.json` 等结构化资产 | **入库**（体积小，供双方共用） |
| `data/eval/` 评测集 | 入库 |
| `data/ocr_output/`、`data/index/`（18 部 OCR 文本与索引，体积大） | **不入库**，克隆后从共享位置复制或重建索引 |
| 原始 PDF（405MB） | 不入库，存团队共享盘 |
| `.env` | 不入库，`.env.example` 入库（只放占位符） |

### 2.4 大文件与二进制

- 单文件 > 10MB 的产物不要入库（图谱 JSON、评测结果等小文件例外）。
- 图片/头像等静态资源保持小体积；不要提交截图、临时渲染输出。

---

## 3. Python 代码风格

- 遵循 **PEP 8**；建议使用 `ruff`（`pip install ruff`）检查：`ruff check src/ tests/`。
- 模块顶部写 docstring（中文，说明用途与用法）；函数/类视复杂度写 docstring。
- 类型注解：公开函数建议标注参数与返回类型（`from typing import ...`）。
- 导入顺序：标准库 → 第三方 → 项目内模块（PEP 8 isort 风格）。
- 命名：`snake_case`（函数/变量）、`CamelCase`（类）、`UPPER_CASE`（常量）。
- 字符串统一使用双引号（既有代码约定）；正则中避免引号冲突时可用单引号。
- **新增模块必须有测试**：`tests/` 目录下与模块同名（`test_<module>.py`），用 pytest。

### 3.1 数据/知识图谱代码特别约定

- OCR 错字纠错统一走 `src/knowledge/ocr_fixes.py` 的纠错表（新增错字追加条目即可），不要在业务代码里散落 `replace`。
- 篇目/页码溯源统一走 `src/knowledge/toc_index.py`；不要直接读 xlsx。
- 知识图谱增删实体后运行 `python src/kg/build_graph.py validate` 校验引用完整性。
- 新增实体/关系后运行 `python src/kg/dedupe_entities.py` 检查同名/近名。

---

## 4. 前端 / 脚本约定（B 部分）

- HTML/JS 统一 UTF-8；不要使用内联本机路径（`file:///D:/...`）。
- CDN 资源在 `index.html` 顶部集中声明，便于离线替换。
- PowerShell 脚本（`scripts/*.ps1`）避免硬编码绝对路径，用 `$PSScriptRoot` 推导项目根。

---

## 5. 提交前检查清单（两人通用）

- [ ] `git status`：没有 `.env`、`data/ocr_output`、`data/index`、`__pycache__` 被误提交
- [ ] 代码中无本机绝对路径（搜索 `D:\\`、`C:\\Users\\`）
- [ ] `python -m pytest tests/` 全部通过
- [ ] 新增依赖已同步 `requirements.txt` 与 `requirements-lock.txt`
- [ ] 知识图谱改动后 `build_graph.py validate` 通过
- [ ] 文件保存为 UTF-8（LF 换行由 .gitattributes 统一）
