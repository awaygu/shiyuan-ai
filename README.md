# 识渊 AI · 智能内容工作台

基于大语言模型的智能内容创作平台，集成新闻AI解读、多知识库RAG检索与多平台内容生成，打造从信息获取到内容发布的完整工作流。

---

## 🛠️ 技术栈

| 分类 | 技术 | 说明 |
|------|------|------|
| **后端** | FastAPI | 高性能 Python Web 框架 |
| **前端** | Vue 3 + TypeScript | 渐进式框架 + 类型安全 |
| **构建** | Vite | 快速构建工具 |
| **UI** | Element Plus | Vue 3 组件库 |
| **状态** | Pinia | Vue 3 状态管理 |
| **路由** | Vue Router | 前端路由 |
| **数据库** | SQLite + aiosqlite | 异步轻量级嵌入式数据库 |
| **AI** | LangChain + OpenAI API | LLM 应用框架 |
| **向量** | FAISS + DashScope | 语义检索 + 文本嵌入 |

---

## 🏗️ 项目结构

```
shiyuan-ai/
├── docker-compose.newsnow.yml  # NewsNow Docker 中台服务配置
├── server/                     # FastAPI 后端服务
│   ├── app.py                 # 主入口 + 应用配置 + NewsNow 健康检查
│   ├── config.py              # 全局配置管理
│   ├── database.py            # SQLite 数据库操作（8张表）
│   ├── prompts.py             # AI 提示词管理
│   ├── keywords.txt           # 关键词过滤列表
│   ├── requirements.txt       # Python 依赖
│   ├── uploads/               # 文件上传目录（按知识库隔离）
│   ├── core/                  # AI 解读核心模块
│   │   ├── interpreter.py     # 新闻解读器
│   │   └── style_manager.py   # 风格管理器
│   ├── sources/               # 新闻来源模块
│   │   ├── base.py            # 爬虫基类（requests + asyncio.to_thread）
│   │   ├── newsnow.py         # NewsNow 统一爬虫（9平台，含 fallback）
│   │   ├── rss.py             # RSS/Atom 爬虫
│   │   └── filter.py          # 内容过滤器
│   ├── rag/                   # RAG 知识库模块
│   │   ├── loader.py          # 文档解析（PDF/DOCX/TXT/MD）
│   │   ├── chunker.py         # 文本分块
│   │   ├── embeddings.py      # DashScope 文本嵌入
│   │   └── vectorstore.py     # FAISS 向量存储（多库隔离）
│   ├── publishers/            # 发布器模块
│   │   ├── xiaohongshu.py     # 小红书发布器
│   │   ├── wechat_mp.py       # 微信公众号发布器
│   │   └── douyin_pub.py      # 抖音发布器
│   └── api/                   # API 路由
│       ├── deps.py            # 依赖注入 + 共享状态
│       ├── news.py            # 新闻接口（含后台刷新）
│       ├── interpret.py       # AI 解读接口
│       ├── knowledge.py       # 知识库 CRUD + RAG 接口
│       ├── agent.py           # 智能体（8工具函数调用）
│       ├── publish.py         # 发布接口
│       ├── schedule.py        # 定时任务接口
│       ├── keywords.py        # 关键词管理
│       └── prompts.py         # 提示词管理
├── web/                        # Vue 3 前端应用
│   ├── src/
│   │   ├── App.vue            # 根组件
│   │   ├── main.ts            # 入口文件
│   │   ├── api/index.ts       # API 请求 + SSE 流式消费
│   │   ├── router/index.ts    # 路由配置
│   │   ├── stores/index.ts    # Pinia 状态管理（非阻塞刷新）
│   │   ├── types/index.ts     # TypeScript 类型定义
│   │   ├── pages/             # 页面
│   │   │   ├── HomeView.vue           # 首页（知识库列表）
│   │   │   ├── NewsView.vue           # 新闻解读
│   │   │   └── KnowledgeBaseView.vue  # 知识库详情
│   │   └── components/        # 组件
│   │       ├── NewsList.vue           # 新闻列表
│   │       ├── NewsDetail.vue         # 新闻详情（正文展示 / iframe）
│   │       ├── FloatingAgent.vue      # 智能体浮窗
│   │       ├── KBFilePanel.vue        # 知识库文件管理
│   │       ├── KBChatPanel.vue        # 知识库 RAG 对话
│   │       └── KBActionPanel.vue      # 智能生成面板
│   └── package.json
└── README.md
```

---

## ✨ 核心功能

| 功能 | 说明 |
|------|------|
| **新闻AI解读** | 多源新闻爬取 + LLM 深度解读 + 智能体对话 |
| **多知识库管理** | 创建/删除知识库，每个知识库独立向量索引 |
| **文档上传与解析** | 支持 PDF / DOCX / TXT / MD，自动分块嵌入 |
| **RAG 语义检索** | DashScope 嵌入 + FAISS 向量检索，引用来源 |
| **多风格文章生成** | 小红书 / 公众号 / 抖音三种风格 |
| **会话持久化** | 每个知识库独立会话，对话记录永久保存 |
| **智能体** | 8工具函数调用，自动刷新/搜索/对比/简报 |
| **多平台发布** | 模拟发布到小红书/公众号/抖音 |
| **定时爬取** | 自动定时刷新新闻数据 |

---

## 🚀 快速开始

### 环境要求

- **Python**: >= 3.10
- **Node.js**: >= 18.0
- **Docker**: >= 20.10（用于 NewsNow 中台服务，可选）

### 1. 克隆项目

```bash
git clone <repository-url>
cd news-interpretation
```

### 2. 启动 NewsNow 中台（推荐）

NewsNow 提供本地新闻聚合 API，作为后端爬虫层的数据源。Docker 部署后端自动连接，无需公网依赖。

```bash
# 启动 NewsNow 容器（端口 4444，256M 内存限制）
docker compose -f docker-compose.newsnow.yml up -d

# 验证服务
curl http://localhost:4444/api/s?id=weibo
```

> 若不启动 Docker，爬虫会自动 fallback 到公共实例 `https://newsnow.busiyi.world/api/s`。

### 3. 后端启动

```bash
cd server

# 创建虚拟环境（推荐）
python -m venv venv
# Windows
.\venv\Scripts\activate
# Linux/Mac
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt

# 配置环境变量
cp .env.example .env
# 编辑 .env 配置 LLM_API_KEY、DASHSCOPE_API_KEY 等
# NEWSNOW_API_URL 默认 http://localhost:4444/api/s（本地 Docker）

# 启动服务（自动等待 NewsNow 就绪，最多10秒）
python app.py
```

后端运行在 **http://localhost:8000**，API 文档: http://localhost:8000/docs

### 4. 前端启动

```bash
cd frontend

# 安装依赖
npm install

# 启动开发服务器
npm run dev
```

前端运行在 **http://localhost:5173**

---

## 🔧 配置说明

### 环境变量（server/.env）

```env
# LLM 配置
LLM_API_KEY=your-api-key
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4o-mini

# DashScope 嵌入（知识库必需）
DASHSCOPE_API_KEY=your-dashscope-key

# 服务器配置
HOST=0.0.0.0
PORT=8000

# 爬虫配置
NEWSNOW_API_URL=http://localhost:4444/api/s   # 本地 Docker（推荐）
# NEWSNOW_API_URL=https://newsnow.busiyi.world/api/s  # 公共实例（fallback）
NEWSNOW_CRAWL_INTERVAL=3600
RSS_CRAWL_INTERVAL=1800
SCHEDULE_ENABLED=true

# 文章内容抓取
JINA_READER_URL=https://r.jina.ai
```

### NewsNow Docker 配置

`docker-compose.newsnow.yml` 关键配置：

| 配置项 | 值 | 说明 |
|--------|-----|------|
| 镜像 | `ghcr.io/ourongxing/newsnow:latest` | 官方镜像 |
| 端口 | `4444` | 宿主机映射端口 |
| 内存限制 | `256M` | 容器内存上限 |
| 重启策略 | `unless-stopped` | 自动重启 |
| 数据持久化 | `./newsnow-data:/app/data` | SQLite 缓存不丢失 |

---

## 🔌 API 接口

### 知识库管理

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/knowledge/bases` | 创建知识库 |
| GET | `/api/knowledge/bases` | 获取知识库列表 |
| GET | `/api/knowledge/bases/{kb_id}` | 获取知识库详情 |
| DELETE | `/api/knowledge/bases/{kb_id}` | 删除知识库 |

### 知识库文档

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/knowledge/bases/{kb_id}/upload` | 上传文档 |
| GET | `/api/knowledge/bases/{kb_id}/documents` | 获取文档列表 |
| DELETE | `/api/knowledge/bases/{kb_id}/documents/{doc_id}` | 删除文档 |
| POST | `/api/knowledge/bases/{kb_id}/search` | 语义检索 |

### 知识库对话

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/knowledge/bases/{kb_id}/conversations` | 创建会话 |
| GET | `/api/knowledge/bases/{kb_id}/conversations` | 获取会话列表 |
| DELETE | `/api/knowledge/bases/{kb_id}/conversations/{conv_id}` | 删除会话 |
| GET | `/api/knowledge/bases/{kb_id}/conversations/{conv_id}/messages` | 获取会话消息 |
| POST | `/api/knowledge/bases/{kb_id}/chat/stream` | RAG 对话（SSE 流式） |
| POST | `/api/knowledge/bases/{kb_id}/generate/stream` | RAG 文章生成（SSE 流式） |

### 新闻与解读

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/news` | 获取新闻列表（分页 + 按源筛选） |
| POST | `/api/news/refresh` | 刷新全部新闻（同步） |
| POST | `/api/news/refresh/{source}` | 刷新单源新闻（后台异步，立即返回） |
| GET | `/api/news/{news_id}/content` | 获取新闻正文（后端抓取 + Jina Reader） |
| POST | `/api/interpret/stream` | AI 解读（SSE） |
| POST | `/api/chat/stream` | 对话式解读（SSE） |
| POST | `/api/generate_article/stream` | 文章生成（SSE） |
| POST | `/api/agent/chat/stream` | 智能体对话（SSE） |

### NewsNow 平台

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/newsnow/platforms` | 获取可用平台列表 |
| POST | `/api/newsnow/refresh` | 刷新全部平台（同步） |
| POST | `/api/newsnow/refresh/{platform_id}` | 刷新单平台（后台异步） |

---

## 🎨 支持风格

| 风格 | 标识符 | 特点 |
|------|--------|------|
| 小红书 | `xiaohongshu` | emoji 丰富、口语化、话题标签 |
| 公众号 | `wechat_mp` | 深度长文、专业分析 |
| 抖音 | `douyin` | 短平快、口播稿 |

---

## 📁 新闻来源

### NewsNow 平台（通过 Docker 中台聚合）

| 来源 | 标识符 | 别名 |
|------|--------|------|
| 财联社热门 | `cls-hot` | `cls_hot` |
| 财联社电报 | `cls-telegraph` | `cls_telegraph` |
| 华尔街见闻 | `wallstreetcn-hot` | `wallstreet` |
| 参考消息 | `cankaoxiaoxi` | `cankao` |
| 澎湃新闻 | `thepaper` | `pengpai` |
| 今日头条 | `toutiao` | `toutiao` |
| 雪球 | `xueqiu` | `xueqiu` |
| 微博 | `weibo` | `weibo` |
| 抖音 | `douyin` | `douyin`（视频） |

### RSS 源

| 来源 | 标识符 |
|------|--------|
| Hacker News | `hacker-news` |
| 阮一峰的网络日志 | `ruanyifeng` |

### 爬虫架构

```
前端 loadNews() ──fire-and-forget──▶ POST /api/news/refresh/{source}
        │                                      │
        │                              asyncio.create_task()
        │                              (_bg_crawl_and_save)
        │                                      │
        ├──等待2s──▶ GET /api/news          ┌───┴───┐
        │                              本地 Docker   公共实例
        │                              :4444/api/s  (fallback)
        │                                  │
        │                              NewsNow 响应
        │                                  │
        └──────── 解析 + 去重 + 入库 ◀─────┘
```

**关键设计：**
- 单源刷新为后台异步任务，API 立即返回 `{"status": "refreshing"}`，前端不阻塞
- 主 API 失败自动 fallback 到公共实例
- 爬虫层使用 `requests`（httpx 与 NewsNow Nitro 服务器不兼容）
- 双层缓存：NewsNow SQLite（最新快照）+ 后端 SQLite（历史持久化）

---

## 🗄️ 数据库设计

| 表名 | 说明 |
|------|------|
| `news` | 新闻数据 |
| `articles` | 生成的文章 |
| `publish_log` | 发布记录 |
| `knowledge_bases` | 知识库 |
| `kb_documents` | 知识库文档（关联 kb_id） |
| `kb_chunks` | 文档分块 |
| `kb_conversations` | 知识库会话 |
| `kb_messages` | 会话消息 |

---

## 📝 更新日志

### v2.1.0
- NewsNow Docker 中台：本地部署替代公网 API，端口 4444
- 爬虫层 httpx → requests：解决与 Nitro 服务器 502 兼容性问题
- 自动 fallback：主 API 失败自动切换到公共实例
- 单源刷新非阻塞：`POST /api/news/refresh/{source}` 后台异步执行
- 正文内容展示：优先后端抓取正文，纯文本渲染替代 iframe（避免 sandbox 报错）
- JS 渲染源标记：`toutiao`、`cankaoxiaoxi` 标记为动态加载，提示新窗口打开
- 后端启动健康检查：自动等待 NewsNow 就绪（最多 10 秒）

### v2.0.0
- 多知识库支持：独立创建、独立向量索引、独立会话
- RAG 对话：语义检索 + 来源引用
- 会话持久化：对话记录永久保存
- 智能体：8工具函数调用

### v1.0.0
- 多源新闻爬取
- AI 多风格解读
- 多平台发布模拟
- SQLite 数据持久化

---

## 📄 许可证

MIT License
