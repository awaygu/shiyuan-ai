"""Global configuration for the news AI system."""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# LLM Configuration
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openai")
LLM_API_KEY = os.getenv("LLM_API_KEY", "sk-your-key-here")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-3.5-turbo")

# Server
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))

# Crawler intervals (seconds)
CRAWL_INTERVAL = int(os.getenv("CRAWL_INTERVAL", "1800"))

SCHEDULE_ENABLED = os.getenv("SCHEDULE_ENABLED", "true").lower() == "true"
NEWSNOW_CRAWL_INTERVAL = int(os.getenv("NEWSNOW_CRAWL_INTERVAL", "1800"))
RSS_CRAWL_INTERVAL = int(os.getenv("RSS_CRAWL_INTERVAL", "1800"))

SCHEDULE_MIN_INTERVAL = 60

KEYWORDS_FILE = os.getenv("KEYWORDS_FILE", str(Path(__file__).parent / "keywords.txt"))
KEYWORDS_FILTER_ENABLED = os.getenv("KEYWORDS_FILTER_ENABLED", "true").lower() == "true"

# Publishing
PUBLISH_RETRY = int(os.getenv("PUBLISH_RETRY", "3"))

# Available news sources (NewsNow + RSS)
NEWS_SOURCES = {
    # NewsNow platforms
    "cls-hot": "财联社热门",
    "cls-telegraph": "财联社电报",
    "wallstreetcn-hot": "华尔街见闻",
    "cankaoxiaoxi": "参考消息",
    "thepaper": "澎湃新闻",
    "toutiao": "今日头条",
    "xueqiu": "雪球",
    "weibo": "微博",
    "douyin": "抖音",
    # RSS feeds
    "hacker-news": "Hacker News",
    "ruanyifeng": "阮一峰的网络日志",
}

NEWSNOW_PLATFORMS = {
    "cls-hot": "财联社热门",
    "cls-telegraph": "财联社电报",
    "wallstreetcn-hot": "华尔街见闻",
    "cankaoxiaoxi": "参考消息",
    "thepaper": "澎湃新闻",
    "toutiao": "今日头条",
    "xueqiu": "雪球",
    "weibo": "微博",
    "douyin": "抖音",
}

NEWSNOW_API_URL = os.getenv("NEWSNOW_API_URL", "https://newsnow.busiyi.world/api/s")

# Jina Reader (free, no API key required)
JINA_READER_URL = os.getenv("JINA_READER_URL", "https://r.jina.ai")

# Publishing platforms
PUBLISH_PLATFORMS = {
    "xiaohongshu": "小红书",
    "wechat_mp": "微信公众号",
    "douyin": "抖音",
}

# WeChat Official Account (certified service account)
WECHAT_APP_ID = os.getenv("WECHAT_APP_ID", "")
WECHAT_APP_SECRET = os.getenv("WECHAT_APP_SECRET", "")

# Browser automation (Playwright)
COOKIES_DIR = os.getenv("COOKIES_DIR", str(Path(__file__).parent / "cookies"))
PUBLISH_HEADLESS = os.getenv("PUBLISH_HEADLESS", "false").lower() == "true"
PUBLISH_TIMEOUT = int(os.getenv("PUBLISH_TIMEOUT", "60"))
# 填好表单后等待用户在浏览器窗口手动点发布的超时（秒）
PUBLISH_MANUAL_TIMEOUT = int(os.getenv("PUBLISH_MANUAL_TIMEOUT", "600"))

# DashScope
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY", "")

# Image Generation
IMAGE_GEN_ENABLED = os.getenv("IMAGE_GEN_ENABLED", "true").lower() == "true"
IMAGE_GEN_MODEL = os.getenv("IMAGE_GEN_MODEL", "qwen-image-2.0-pro")

# CORS
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "*")

# Knowledge Base
KB_CHUNK_SIZE = int(os.getenv("KB_CHUNK_SIZE", "500"))
KB_CHUNK_OVERLAP = int(os.getenv("KB_CHUNK_OVERLAP", "50"))
UPLOAD_DIR = os.getenv("UPLOAD_DIR", str(Path(__file__).parent / "uploads"))
MAX_UPLOAD_SIZE = int(os.getenv("MAX_UPLOAD_SIZE", str(20 * 1024 * 1024)))
KB_EMBEDDING_DIM = int(os.getenv("KB_EMBEDDING_DIM", "1024"))
KB_EMBEDDING_MODEL = os.getenv("KB_EMBEDDING_MODEL", "text-embedding-v4")
KB_VISION_MODEL = os.getenv("KB_VISION_MODEL", "qwen-vl-ocr-latest")
KB_VISION_BASE_URL = os.getenv("KB_VISION_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")

# Web Search
WEB_SEARCH_ENABLED = os.getenv("WEB_SEARCH_ENABLED", "false").lower() == "true"
WEB_SEARCH_ENGINE = os.getenv("WEB_SEARCH_ENGINE", "tavily")  # kimi / tavily
MOONSHOT_API_KEY = os.getenv("MOONSHOT_API_KEY", "")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")

# Memory (Short-term)
MEMORY_DB_PATH = os.getenv("MEMORY_DB_PATH", str(Path(__file__).parent / "data" / "agent_memory.db"))
SUMMARY_MODEL = os.getenv("SUMMARY_MODEL", "deepseek-v4-flash")
SUMMARY_MODEL_BASE_URL = os.getenv("SUMMARY_MODEL_BASE_URL", LLM_BASE_URL)
SUMMARY_MODEL_API_KEY = os.getenv("SUMMARY_MODEL_API_KEY", LLM_API_KEY)
SUMMARY_TRIGGER_TOKENS = int(os.getenv("SUMMARY_TRIGGER_TOKENS", "80000"))
SUMMARY_KEEP_MESSAGES = int(os.getenv("SUMMARY_KEEP_MESSAGES", "10"))

# KB RAG Memory
KB_RAG_SUMMARY_TRIGGER_TOKENS = int(os.getenv("KB_RAG_SUMMARY_TRIGGER_TOKENS", "50000"))
KB_RAG_SUMMARY_KEEP_MESSAGES = int(os.getenv("KB_RAG_SUMMARY_KEEP_MESSAGES", "8"))
KB_RAG_MEMORY_DB_PATH = os.getenv("KB_RAG_MEMORY_DB_PATH", str(Path(__file__).parent / "data" / "rag_memory.db"))

# ── Temperature strategy ────────────────────────────────────────────
# 结构化输出/确定性任务 → 低温
# 分析/创作任务 → 中高温
TEMPERATURE_REWRITE = float(os.getenv("TEMPERATURE_REWRITE", "0.0"))
TEMPERATURE_SUMMARY = float(os.getenv("TEMPERATURE_SUMMARY", "0.3"))
TEMPERATURE_ANALYZE = float(os.getenv("TEMPERATURE_ANALYZE", "0.7"))
TEMPERATURE_GENERATE = float(os.getenv("TEMPERATURE_GENERATE", "0.8"))
TEMPERATURE_CHAT = float(os.getenv("TEMPERATURE_CHAT", "0.7"))

# ── Prompt length guardrails ──────────────────────────────────────
# 各场景系统提示词建议最大字符数（用于日志告警，不强制截断）
MAX_PROMPT_CHARS = {
    "interpret": 4000,
    "chat": 2000,
    "generate": 4000,
    "agent": 4000,
    "kb_rag": 2000,
    "kb_generate": 2000,
}
# RAG 场景下检索内容（知识库片段）最大字符数
MAX_RAG_CONTEXT_CHARS = int(os.getenv("MAX_RAG_CONTEXT_CHARS", "15000"))
