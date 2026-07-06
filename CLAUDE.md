# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

识渊 AI 是一个基于大语言模型的内容工作台，覆盖全链路：新闻聚合 → 解读 → 知识库（RAG）→ 文章生成 → 多平台发布。仓库为 monorepo，包含 Python/FastAPI 后端（`server/`）和 Vue 3 + TypeScript 前端（`web/`）。

## 常用命令

### 后端（`server/`）
```bash
cd server
python -m venv venv && source venv/bin/activate    # Windows: .\venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium                         # 发布模块必需
python app.py                                       # 启动 FastAPI（uvicorn, reload），端口 :8000
# 或：python -m uvicorn app:app --host 0.0.0.0 --port 8000 --reload
```
API 文档地址 `http://localhost:8000/docs`。无测试套件——`server/tests/` 为空目录。未配置 lint；`scripts/clear_kb.py` 是破坏性维护脚本（清空所有知识库数据），仅在显式要求时执行。

### 前端（`web/`）
```bash
cd web
npm install
npm run dev       # Vite 开发服务器，端口 :8088，/api 代理到 :8000
npm run build     # vue-tsc --noEmit && vite build（类型检查内嵌于 build）
npm run preview
```
类型检查通过 `npm run build` 中的 `vue-tsc --noEmit` 完成——没有单独的 `typecheck` 脚本。

### Docker（全栈，推荐）
```bash
docker compose up -d                                  # 后端 + 前端 + NewsNow
docker compose logs -f backend
docker compose build && docker compose up -d          # 代码变更后重新构建
docker compose -f docker-compose.newsnow.yml up -d   # 仅单独启动 NewsNow 源
```
服务：`shiyuan-web`（Nginx，8088→80）、`shiyuan-backend`（FastAPI，8000）、`newsnow-local`（新闻聚合，4444 内网）。数据持久化于命名卷 `shiyuan_data`（后端容器内路径 `/app/data`）。

### 本地开发启动脚本
仓库根目录的 `start.bat`（Windows）和 `start.sh`（Linux/Mac）会自动创建 venv、安装依赖、安装 Playwright、安装前端依赖并启动前后端。

## 配置

所有后端配置集中在 `server/config.py`，从 `server/.env` 读取（复制 `server/.env.example`）。必填：`LLM_API_KEY`、`DASHSCOPE_API_KEY`（嵌入 + 生图）。选填：`MOONSHOT_API_KEY`（Kimi 搜索）、`TAVILY_API_KEY`（Tavily 搜索）、`WECHAT_APP_ID/SECRET`（公众号发布 API）。Docker 部署时 `docker-compose.yml` 会覆盖路径，使 `/app/data` 成为唯一持久化卷。

## 架构

### 后端结构（`server/`）
- `app.py` — FastAPI 入口。注册所有路由并执行 `lifespan` 启动流程：等待 NewsNow、初始化数据库、将新闻加载/爬取到内存 store、启动 NewsNow + RSS 爬取循环（由 `SCHEDULE_ENABLED` 控制）。
- `config.py` — 所有可调参数（LLM、爬取间隔、嵌入维度、温度、记忆触发 token 数）。在这里集中修改，不要散落常量。
- `api/` — 按领域拆分的 FastAPI 路由：`agent`（LangGraph agent 对话 + 工具调用）、`knowledge`（知识库 CRUD、上传、RAG 对话/生成）、`news`、`interpret`、`publish`、`schedule`、`keywords`、`prompts`（热重载）、`tasks`（异步任务 SSE）、`conversations`。**`api/deps.py` 是共享状态中枢**——内存中的 `news_store`/`article_store`/`publish_log`、爬虫注册表、锁、`interpreter` 单例、发布器实例、内容抓取辅助函数。路由统一从 `deps` 导入以避免循环依赖。
- `core/` — AI 编排。`agent_graph.py`（通过 `create_agent` + `SummarizationMiddleware` + `AsyncSqliteSaver` 构建 LangGraph agent）、`rag_graph.py`（知识库 RAG StateGraph：`rewrite_query → classify_query → retrieve → generate`）、`interpreter.py`（新闻解读/文章生成）、`style_manager.py`（`PromptManager` 封装 `prompts.py`，支持热重载）、`image_generator.py`（DashScope qwen-image）、`checkpointer.py`（`agent_memory.db` 中的自定义 `conversations`/`messages` 表）。
- `rag/` — `embeddings`（DashScope text-embedding-v4）、`vectorstore`（按知识库分库的 FAISS 索引）、`bm25_index`（jieba 分词的 BM25）、`chunker`、`loader`（PDF/DOCX/TXT/MD/图片 OCR）。检索采用向量 + BM25 命中的 **RRF 融合**。
- `sources/` — `newsnow.py`（爬取 NewsNow 实例，从本地 Docker URL 失败时回退到公共实例）、`rss.py`、`filter.py`（关键词过滤）。
- `publishers/` — 基于 Playwright 的浏览器自动化。`base.py` 定义 `BasePublisher`/`BrowserPublisher` 和 `PublishResult`。实现：`xiaohongshu.py`、`wechat_mp.py`（公众号草稿箱 API，非 Playwright）、`douyin_pub.py`。`image_archive.py` 缓存生成的图片。
- `database.py` — SQLite（`news_ai.db`，aiosqlite，WAL 模式），存储 news/articles/publish_log/知识库表。Schema 迁移使用 try/except 守护的幂等 `ALTER TABLE ... ADD COLUMN`。
- `prompts.py` — 所有系统提示词。在此修改 AI 行为；运行时通过 `POST /api/prompts/reload` 热重载。

### 前端结构（`web/src/`）
- `api/index.ts` — 单一 axios 客户端（`baseURL: /api`），封装所有后端端点；所有组件都走这一层。
- `stores/index.ts` — 单个 Pinia store（`useNewsStore`），持有 news、articles、publish log、知识库状态、tasks。文件较大。
- `pages/` — `HomeView`（首页 + 悬浮 agent）、`NewsView`、`KnowledgeBaseView`。
- `components/` — 功能面板：`FloatingAgent`（agent 对话）、`GeneratePanel`、`KBChatPanel`/`KBFilePanel`/`KBGeneratePanel`/`KBActionPanel`、`NewsList`/`NewsDetail`、`PublishPanel`、`TaskPanel`、`KeywordSettings`。
- 路由使用 `createWebHistory`，三条路由（`/`、`/news`、`/kb/:kbId`）。

### 两套 LangGraph 系统（切勿混淆）
1. **Agent**（`core/agent_graph.py`）— `create_agent` + 9+ 工具（刷新/搜索/对比/知识库搜索/联网搜索/生成/解读）。状态通过 `AsyncSqliteSaver` 持久化，`thread_id` = 会话 id。SSE 事件：`conversation_id`、`prompt`、`loading`、`chunk`、`action`、`error`、`[DONE]`。
2. **知识库 RAG**（`core/rag_graph.py`）— 手写 StateGraph，含查询重写（规则前置过滤 → 仅在命中代词/短句时调用 LLM）、意图分类（specific vs. summary，基于规则）、RRF 检索、生成。使用自行实现的 `SummarizationMiddleware`（非 LangChain 自带），以及独立的 `rag_memory.db` checkpointer。仅持久化 `Human`/`AIMessage`——检索到的 context 不入库。

### 约定
- 所有面向用户的字符串和提示词均为中文；注释中英文混用。修改文件时请与该文件已有语言保持一致。
- SSE 响应设置 `X-Accel-Buffering: no`（见 `deps.SSE_HEADERS`），防止 Nginx 缓冲流。
- 前端依赖特定的 SSE 事件结构（`{type, content/action/...}`）；修改 `agent.py`/`knowledge.py` 的流式端点时必须保持该结构。
- SQLite 是唯一的数据存储（无外部数据库）。三个 DB 文件：`news_ai.db`（业务数据）、`data/agent_memory.db`（agent 状态 + 会话）、`data/rag_memory.db`（RAG 状态）。FAISS 索引位于 `uploads/<kb_id>/`。
- Git 提交遵循中文版 Conventional Commits（见 `.trae/rules/git-commit-message.md`）：`<type>(<scope>): <中文 subject>`，祈使语气，≤50 字符。

## 环境要求

Python ≥ 3.10、Node.js ≥ 18、Docker ≥ 20.10 + Compose v2。Windows 下 `app.py` 强制使用 Proactor 事件循环策略，以支持 Playwright 所需的异步子进程。
