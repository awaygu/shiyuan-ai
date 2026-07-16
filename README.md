# 识渊 AI · 智能内容工作台

> 基于大语言模型的智能内容创作平台，覆盖「信息获取 → 解读分析 → 知识管理 → 内容生成 → 多平台发布」全链路。

## 功能演示

<video controls width="100%">
  <source src="docs/20260715_184352.mp4" type="video/mp4">
  你的浏览器不支持视频播放。
</video>

---

## 系统架构

```mermaid
graph TB
    subgraph Frontend["🎨 前端层"]
        direction LR
        VUE["Vue 3 + TS"]
        PIN["Pinia"]
        RTR["Vue Router"]
        EL["Element Plus"]
    end

    subgraph API["⚡ API 网关层 (FastAPI)"]
        AGT["/api/agent/*<br/>智能体对话"]
        KB["/api/knowledge/*<br/>知识库管理"]
        NEWS["/api/news/*<br/>新闻采集"]
        PUB["/api/publish/*<br/>内容发布"]
    end

    subgraph Core["🧠 AI 核心层"]
        LG["LangGraph Agent<br/>工具调用 · 短期记忆"]
        RAG["RAG 引擎<br/>查询重写 · 语义检索 · 生成"]
        INT["新闻解读器<br/>多风格分析"]
        IMG["AI 配图生成<br/>qwen-image"]
    end

    subgraph Data["🗄️ 数据层"]
        SQLITE[("SQLite<br/>news_ai.db")]
        FAISS[("FAISS<br/>向量索引")]
        MEM[("agent_memory.db<br/>rag_memory.db")]
        BM25[("BM25<br/>关键词索引")]
    end

    subgraph External["🌐 外部服务"]
        LLM["LLM API<br/>OpenAI 兼容"]
        DS["DashScope<br/>嵌入 · 生图"]
        NN["NewsNow<br/>新闻聚合"]
        SRCH["Kimi / Tavily<br/>联网搜索"]
        PLW["Playwright<br/>浏览器自动化"]
    end

    VUE -->|"SSE 流式 / REST"| API
    API --> Core
    Core --> Data
    Core --> External
    LG --> LLM
    LG --> SRCH
    RAG --> DS
    RAG --> FAISS
    INT --> LLM
    IMG --> DS
    PUB --> PLW
    NEWS --> NN
```

---

## 核心流程

### 智能体对话

```mermaid
sequenceDiagram
    actor U as 用户
    participant F as Vue 前端
    participant A as FastAPI
    participant L as LangGraph Agent
    participant T as 工具调用
    participant M as 短期记忆

    U->>F: 发送消息
    F->>A: POST /api/agent/chat/stream (SSE)
    A->>L: astream_events(messages, config)

    loop Agent 循环
        L->>M: 加载历史消息 (SummarizationMiddleware)
        M-->>L: 压缩后的上下文
        L->>L: LLM 推理
        alt 需要工具调用
            L->>T: 调用工具 (搜索/新闻/知识库)
            T-->>L: 工具结果
        end
    end

    L-->>A: 流式 token
    A-->>F: SSE chunk 事件
    F-->>U: 逐字渲染

    L-->>A: [DONE]
    A->>M: 持久化本轮消息
    A-->>F: conversation_id 事件
```

### RAG 知识库检索

```mermaid
sequenceDiagram
    actor U as 用户
    participant F as Vue 前端
    participant A as FastAPI
    participant R as LangGraph StateGraph
    participant E as DashScope 嵌入
    participant V as FAISS 向量库
    participant L as LLM

    U->>F: 输入问题
    F->>A: POST /api/knowledge/bases/{id}/chat/stream

    A->>R: astream_events(query, kb_id)

    rect rgb(240, 248, 255)
        Note over R: 查询重写 (rewrite_query)
        R->>R: 规则前置过滤<br/>(代词/短句/祈使句检测)
        alt 需要重写
            R->>L: LLM 意图判断 + 代词消解
            L-->>R: 改写后的查询
            R-->>A: SSE rewrite 事件 (原查询 → 新查询)
        end
    end

    rect rgb(255, 248, 240)
        Note over R,V: 语义检索 (retrieve)
        R->>E: embed(rewritten_query)
        E-->>R: 向量
        R->>V: 相似度检索 (top_k)
        V-->>R: 相关文档片段
    end

    rect rgb(240, 255, 240)
        Note over R,L: 生成回答 (generate)
        R->>R: SummarizationMiddleware 压缩历史
        R->>L: SystemMessage(context) + messages + query
        L-->>R: 流式 token
    end

    R-->>A: SSE sources 事件 (引用来源)
    R-->>A: SSE chunk 事件 (逐字输出)
    A-->>F: 流式传输
    F-->>U: 渲染回答 + 引用标注
```

### 新闻采集与解读

```mermaid
sequenceDiagram
    participant S as 定时调度器
    participant C as 爬虫引擎
    participant N as NewsNow / RSS
    participant F as 关键词过滤器
    participant D as SQLite
    participant L as LLM 解读器

    S->>C: 定时触发 (可配置间隔)
    C->>N: 拉取新闻列表
    N-->>C: 新闻数据
    C->>F: 关键词过滤
    F-->>C: 过滤后数据
    C->>D: 去重 + 批量写入

    Note over D: 前端请求解读
    D-->>L: 新闻正文 + 风格参数
    L->>L: 多风格解读<br/>(小红书/公众号/抖音)
    L-->>D: 解读结果 (流式)
```

### 多平台发布

```mermaid
sequenceDiagram
    actor U as 用户
    participant F as Vue 前端
    participant A as FastAPI
    participant P as Playwright 浏览器
    participant PL as 目标平台

    U->>F: 选择文章 + 平台 + 风格
    F->>A: POST /api/publish

    A->>P: 启动浏览器实例
    P->>PL: 加载 Cookie / 扫码登录

    alt 公众号
        P->>PL: API 上传素材 → 创建草稿 → 发布
    else 小红书 / 抖音
        P->>PL: 模拟点击 → 填写内容 → 上传图片 → 发布
    end

    PL-->>P: 发布结果
    P-->>A: 截图 + 状态
    A->>A: 记录发布日志
    A-->>F: 发布成功 + 截图预览
    F-->>U: 展示发布结果
```

---

## 技术栈

| 分类 | 技术 |
|------|------|
| **后端框架** | FastAPI (Python) |
| **前端框架** | Vue 3 + TypeScript + Vite |
| **UI 组件库** | Element Plus |
| **状态管理** | Pinia |
| **AI 框架** | LangChain + LangGraph |
| **向量检索** | FAISS + BM25 |
| **嵌入模型** | DashScope text-embedding |
| **数据库** | SQLite (aiosqlite) |
| **浏览器自动化** | Playwright |
| **联网搜索** | Kimi / Tavily 双引擎 |

---

## 核心功能

| 模块 | 能力 |
|------|------|
| **智能体** | 9 工具函数调用 · 短期记忆 (SummarizationMiddleware) · 联网搜索开关 · 多会话管理 |
| **知识库** | 多库隔离 · PDF/DOCX/TXT/MD 解析 · RAG 语义检索 · 查询重写 · 来源引用 |
| **新闻** | 10+ 平台聚合 · 定时爬取 · 关键词过滤 · AI 多风格解读 · 热门追踪 |
| **文章生成** | 小红书/公众号/抖音三风格 · 知识库素材驱动 · AI 配图 (qwen-image) |
| **发布** | Playwright 自动化 · 小红书 · 公众号 · 抖音 · 发布记录追踪 |
| **定时任务** | 自动爬取 · 异步任务面板 · 后台状态追踪 |

---

## 快速开始

### 环境要求

- **Python** >= 3.10
- **Node.js** >= 18
- **Docker** >= 20.10 + Docker Compose v2（推荐，一键部署全部服务）

### 1. 配置环境变量

```bash
cp server/.env.example server/.env
```

编辑 `.env`，填入必要的 API Key：

| 变量 | 说明 |
|------|------|
| `LLM_API_KEY` | 大模型 API Key（必填） |
| `LLM_BASE_URL` | API 地址，默认 OpenAI |
| `LLM_MODEL` | 模型名，如 `gpt-3.5-turbo` |
| `DASHSCOPE_API_KEY` | 阿里云 DashScope（嵌入 + 生图） |
| `MOONSHOT_API_KEY` | Kimi 联网搜索（可选） |
| `TAVILY_API_KEY` | Tavily 联网搜索（可选） |

### 2. Docker 部署（推荐）

一条命令启动全部服务（后端 + 前端 + NewsNow）：

```bash
docker compose up -d
```

首次启动会自动构建镜像（后端需安装 Playwright Chromium，耗时较长）。

**常用命令：**

```bash
# 查看日志
docker compose logs -f backend

# 停止服务
docker compose down

# 代码变更后重新构建
docker compose build && docker compose up -d
```

**服务架构：**

| 容器 | 说明 | 端口 |
|------|------|------|
| `shiyuan-web` | Nginx 静态文件 + API 反代 + SSE 支持 | 8088 → 80 |
| `shiyuan-backend` | FastAPI + Playwright Chromium | 8000 |
| `newsnow-local` | 新闻聚合服务（Docker 网络内部访问） | 4444 |

数据通过命名卷 `shiyuan_data` 持久化（数据库、上传文件、Cookies），`docker compose down` 不会丢失数据。

> 如仅单独启动 NewsNow 新闻源（本地开发用），可执行 `docker compose -f docker-compose.newsnow.yml up -d`，后端会自动 fallback 到公共实例。

### 3. 本地开发启动

**Windows：**
```powershell
.\start.bat
```

**Linux/Mac：**
```bash
chmod +x start.sh && ./start.sh
```

或手动启动：

**后端：**
```bash
cd server
python -m venv venv
source venv/bin/activate  # Windows: .\venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
python app.py
```

**前端：**
```bash
cd web
npm install
npm run dev
```

### 访问地址

| 服务 | Docker 部署 | 本地开发 |
|------|-------------|----------|
| 前端页面 | `http://localhost:8088` | `http://localhost:8088` |
| 后端 API | `http://localhost:8000` | `http://localhost:8000` |
| API 文档 | `http://localhost:8000/docs` | `http://localhost:8000/docs` |

---

## 许可证

MIT License
