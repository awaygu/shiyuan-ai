# 智析 · AI解读与知识库

一站式新闻AI解读、多知识库RAG检索、多风格内容生成的现代化全栈应用。

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
zhixi/
├── backend/                    # FastAPI 后端服务
│   ├── app.py                 # 主入口 + 应用配置
│   ├── config.py              # 全局配置管理
│   ├── database.py            # SQLite 数据库操作（8张表）
│   ├── prompts.py             # AI 提示词管理
│   ├── keywords.txt           # 关键词过滤列表
│   ├── requirements.txt       # Python 依赖
│   ├── uploads/               # 文件上传目录（按知识库隔离）
│   ├── agents/                # AI 解读模块
│   │   ├── interpreter.py     # 新闻解读器
│   │   └── style_manager.py   # 风格管理器
│   ├── crawlers/              # 新闻爬虫模块
│   │   ├── base.py            # 爬虫基类
│   │   ├── newsnow.py         # NewsNow 统一爬虫（9平台）
│   │   ├── rss.py             # RSS/Atom 爬虫
│   │   └── filter.py          # 内容过滤器
│   ├── knowledge/             # 知识库模块
│   │   ├── loader.py          # 文档解析（PDF/DOCX/TXT/MD）
│   │   ├── chunker.py         # 文本分块
│   │   ├── embeddings.py      # DashScope 文本嵌入
│   │   └── vectorstore.py     # FAISS 向量存储（多库隔离）
│   ├── publishers/            # 发布器模块
│   │   ├── xiaohongshu.py     # 小红书发布器
│   │   ├── wechat_mp.py       # 微信公众号发布器
│   │   └── douyin_pub.py      # 抖音发布器
│   └── routers/               # API 路由
│       ├── deps.py            # 依赖注入 + 共享状态
│       ├── news.py            # 新闻接口
│       ├── interpret.py       # AI 解读接口
│       ├── knowledge.py       # 知识库 CRUD + RAG 接口
│       ├── agent.py           # 智能体（8工具函数调用）
│       ├── publish.py         # 发布接口
│       ├── schedule.py        # 定时任务接口
│       ├── keywords.py        # 关键词管理
│       └── prompts.py         # 提示词管理
├── frontend/                   # Vue 3 前端应用
│   ├── src/
│   │   ├── App.vue            # 根组件
│   │   ├── main.ts            # 入口文件
│   │   ├── api/index.ts       # API 请求 + SSE 流式消费
│   │   ├── router/index.ts    # 路由配置
│   │   ├── stores/index.ts    # Pinia 状态管理
│   │   ├── types/index.ts     # TypeScript 类型定义
│   │   ├── views/             # 页面
│   │   │   ├── HomeView.vue           # 首页（知识库列表）
│   │   │   ├── NewsView.vue           # 新闻解读
│   │   │   └── KnowledgeBaseView.vue  # 知识库详情
│   │   └── components/        # 组件
│   │       ├── NewsList.vue           # 新闻列表
│   │       ├── NewsDetail.vue         # 新闻详情
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

### 1. 克隆项目

```bash
git clone <repository-url>
cd news-interpretation
```

### 2. 后端启动

```bash
cd backend

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

# 启动服务
python app.py
```

后端运行在 **http://localhost:8000**，API 文档: http://localhost:8000/docs

### 3. 前端启动

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

### 环境变量（backend/.env）

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
NEWSNOW_CRAWL_INTERVAL=3600
RSS_CRAWL_INTERVAL=1800
SCHEDULE_ENABLED=true
```

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
| GET | `/api/news` | 获取新闻列表 |
| POST | `/api/news/refresh` | 刷新全部新闻 |
| POST | `/api/interpret/stream` | AI 解读（SSE） |
| POST | `/api/chat/stream` | 对话式解读（SSE） |
| POST | `/api/generate_article/stream` | 文章生成（SSE） |
| POST | `/api/agent/chat/stream` | 智能体对话（SSE） |

---

## 🎨 支持风格

| 风格 | 标识符 | 特点 |
|------|--------|------|
| 小红书 | `xiaohongshu` | emoji 丰富、口语化、话题标签 |
| 公众号 | `wechat_mp` | 深度长文、专业分析 |
| 抖音 | `douyin` | 短平快、口播稿 |

---

## 📁 新闻来源

| 来源 | 标识符 |
|------|--------|
| 财联社热门 | `cls-hot` |
| 财联社电报 | `cls-telegraph` |
| 华尔街见闻 | `wallstreetcn-hot` |
| 参考消息 | `cankaoxiaoxi` |
| 澎湃新闻 | `thepaper` |
| 今日头条 | `toutiao` |
| 雪球 | `xueqiu` |
| 微博 | `weibo` |
| 抖音 | `douyin` |
| Hacker News | `hacker-news` |
| 阮一峰的网络日志 | `ruanyifeng` |

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
