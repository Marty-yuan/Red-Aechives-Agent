# B 部分功能说明与实现方法

> 本文档记录 Red-Aechives-Agent 项目中“B 部分：Agent、数字人与产品交互”已完成的功能及简要技术实现。
> 更新日期：2026-08-20

## 1. 多智能体编排

### 功能
- 用户问题先经过轻量规则判断，决定走“普通 RAG 问答”还是“复杂智能体规划”。
- 复杂任务由 Planner 生成工具调用计划，Orchestrator 执行工具，最后 LLM 汇总生成自然回答。
- 对路线、村寨对比等任务设置确定性兜底，Planner 失败时仍能生成可用结果。

### 方法
- `PlannerAgent` 使用 DeepSeek OpenAI 兼容接口生成 JSON 规划。
- `OrchestratorAgent` 负责 `Planner -> ToolRegistry -> 最终生成 -> 事实校验` 的串联。
- `ToolRegistry` 提供 `search_archives`、`query_timeline`、`get_village_profile`、`query_knowledge_graph`、`generate_study_route`、`compare_villages`、`estimate_travel` 等工具。

## 2. 红色村寨数字代言人

### 功能
- 每个村寨有独立身份、语言风格和讲解重点。
- 支持三种讲解人格：儿童模式、游客模式、研究者模式。
- 根据当前村寨和用户画像组装 system prompt。

### 方法
- `personas.py` 定义 `BASE_PERSONA`、`PERSONA_MODES`、`VILLAGE_PERSONAS`。
- `build_system_prompt` 把村寨人格、讲解模式和用户偏好合并。

## 3. 地图、时间线与红军战士动画

### 功能
- 地图展示中央红军与红二、六军团两条行军路线。
- 时间线展示关键事件。
- 点击村寨后，红军战士沿路线动画行走到目标地点，而不是瞬移。

### 方法
- 前端使用 Leaflet 地图。
- 村寨坐标、路线、时间线数据集中在 `knowledge.py`。
- 战士行走使用 requestAnimationFrame 沿路线插值。

## 4. 多日研学路线生成

### 功能
- 根据起点、天数、低体力、亲子、美食偏好生成推荐方案和备选方案。
- 每天包含景点、美食、住宿建议、游玩时长、体力消耗。
- 景点、美食、住宿可跳转到小红书搜索链接。
- 通过交通时长和每日容量约束，避免一天内安排无法完成的长途转场。

### 方法
- `generate_study_route` 工具根据村寨坐标和历史路线排序。
- 交通时间使用 Haversine 距离估算，按公路系数换算。
- 低体力方案使用能量值排序；最少车程方案使用贪心最近邻。
- 小红书链接由 `_xhs_search_url` 根据关键词生成。

## 5. 对话内本地攻略链接

### 功能
- 用户问“景点、美食、住宿”等本地旅游问题时，代言人回复会自动附带攻略直达链接。
- 每个推荐提供小红书和抖音两个入口。
- 前端可点击，语音朗读时会自动去掉链接文字。

### 方法
- `rag.py` 中的 `_local_guide_block` 根据问题关键词和当前/指定村寨生成 Markdown 链接。
- 前端 `renderMessageHtml` 将 Markdown 链接渲染为安全超链接。
- `plainTextForSpeech` 在朗读前移除链接语法。

## 6. 村寨对比

### 功能
- 用户同时提到两个村寨并要求比较时，自动展示村寨对比卡片。
- 展示事件、年份、部队、时间线和知识图谱关系。

### 方法
- Orchestrator 检测对比关键词并识别两个村寨。
- `compare_villages` 工具读取村寨档案、时间线和知识图谱，前端渲染对比卡片。

## 7. 事实校验、证据链与 PDF 溯源

### 功能
- 回答后自动运行事实校验，展示可信度和风险点。
- 展示“智能体规划 -> 工具调用 -> 档案证据 -> 事实校验”审计链路。
- 证据可点击查看原始 PDF 对应页面。

### 方法
- `FactCheckerAgent` 调用 DeepSeek 校验回答与证据的一致性。
- `app.py` 提供 `/api/pdf/page`，使用 PyMuPDF 匹配证据文本并返回原 PDF 页面图片。

## 8. 网站真实登录与长期记忆

### 功能
- 支持注册、登录、退出。
- 密码要求至少 6 位且同时包含字母和数字。
- 按用户和村寨保存长期对话历史。
- 用户画像记录讲解人格、最近村寨和最近问题。
- 可删除当前村寨的历史对话。

### 方法
- PostgreSQL 优先，使用 SQLAlchemy；未配置数据库时回退本地 JSON。
- JWT Bearer Token 鉴权，前端保存在 localStorage。
- `memory_store.py` 统一封装用户、画像和对话记忆。

## 9. 语音与村寨头像

### 功能
- 每个村寨有专属头像和声线性别。
- 支持普通话语音、四川话文字风格兜底、关闭声音。
- 四川话真实方言模型方案已整理在 `docs/方言语音接入步骤.md`，当前暂缓。

### 方法
- `tts.py` 优先使用 edge-tts，失败后回退 Windows SAPI 或浏览器语音。
- `knowledge.py` 维护 `VILLAGE_AVATARS` 和 `VILLAGE_GENDERS`。
- 方言方案计划使用 CosyVoice Docker 侧载服务，通过参考音频零样本克隆。

## 10. Web API

### 主要接口
- `/chat`：主对话接口。
- `/api/villages`、`/api/routes`、`/api/timeline`、`/api/knowledge_graph`：地图和知识图谱数据。
- `/api/tts`：文本转语音。
- `/api/auth/*`：注册、登录、退出、当前用户。
- `/api/memory/*`：历史对话、用户画像、讲解模式。
- `/api/pdf/page`：证据 PDF 页面溯源。
