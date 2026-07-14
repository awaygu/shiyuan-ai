"""Global configuration for the news AI system.

Configuration is defined with ``pydantic-settings`` ``BaseSettings`` so that
each value is validated (int/float/bool) and sourced from environment
variables (with the ``.env`` file as a fallback). A single ``settings``
singleton is instantiated at module import time and every historical module
attribute is re-exported at module level, so existing ``from config import X``
imports keep working unchanged.

Order of evaluation matters for tests: ``tests/conftest.py`` calls
``os.environ.setdefault(...)`` *before* importing the app (and thus before
this module is imported). ``load_dotenv()`` below uses ``override=False`` so
those test-injected values win. ``Settings()`` is then instantiated at the
bottom of the module, reading the merged environment.

The ``LANGSMITH_*`` variables are also relied upon by the langsmith SDK via
``os.environ`` directly; ``load_dotenv()`` keeps lifting any ``.env`` values
into ``os.environ`` so that path is preserved (pydantic-settings only fills
typed fields, it does not export back to ``os.environ``).
"""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Lift .env values into os.environ (override=False => real env vars win).
# This must run before Settings() so both the typed fields and any SDK that
# reads os.environ directly (e.g. langsmith) see the same values.
load_dotenv()

_SERVER_DIR = Path(__file__).parent


# ── Settings groups ───────────────────────────────────────────────────────


class LLMSettings(BaseSettings):
    """LLM provider configuration."""

    model_config = SettingsConfigDict(extra="ignore")

    PROVIDER: str = Field("openai", alias="LLM_PROVIDER")
    API_KEY: str = Field("", alias="LLM_API_KEY")
    BASE_URL: str = Field("https://api.deepseek.com", alias="LLM_BASE_URL")
    MODEL: str = Field("deepseek-v4-flash", alias="LLM_MODEL")


class ServerSettings(BaseSettings):
    """HTTP server bind configuration."""

    model_config = SettingsConfigDict(extra="ignore")

    HOST: str = Field("0.0.0.0", alias="HOST")
    PORT: int = Field(8000, alias="PORT")


class CrawlerScheduleSettings(BaseSettings):
    """Crawler intervals, scheduling and keyword filtering."""

    model_config = SettingsConfigDict(extra="ignore")

    CRAWL_INTERVAL: int = Field(1800, alias="CRAWL_INTERVAL")
    SCHEDULE_ENABLED: bool = Field(True, alias="SCHEDULE_ENABLED")
    NEWSNOW_CRAWL_INTERVAL: int = Field(1800, alias="NEWSNOW_CRAWL_INTERVAL")
    RSS_CRAWL_INTERVAL: int = Field(1800, alias="RSS_CRAWL_INTERVAL")
    KEYWORDS_FILE: str = Field(str(_SERVER_DIR / "keywords.txt"), alias="KEYWORDS_FILE")
    KEYWORDS_FILTER_ENABLED: bool = Field(True, alias="KEYWORDS_FILTER_ENABLED")


class PublishingSettings(BaseSettings):
    """Publishing retry, browser automation and WeChat OA configuration."""

    model_config = SettingsConfigDict(extra="ignore")

    PUBLISH_RETRY: int = Field(3, alias="PUBLISH_RETRY")
    COOKIES_DIR: str = Field(str(_SERVER_DIR / "cookies"), alias="COOKIES_DIR")
    PUBLISH_HEADLESS: bool = Field(True, alias="PUBLISH_HEADLESS")
    PUBLISH_TIMEOUT: int = Field(60, alias="PUBLISH_TIMEOUT")
    # 填好表单后等待用户在浏览器窗口手动点发布的超时（秒）
    PUBLISH_MANUAL_TIMEOUT: int = Field(600, alias="PUBLISH_MANUAL_TIMEOUT")
    WECHAT_APP_ID: str = Field("", alias="WECHAT_APP_ID")
    WECHAT_APP_SECRET: str = Field("", alias="WECHAT_APP_SECRET")


class NewsSourcesSettings(BaseSettings):
    """NewsNow API and Jina Reader configuration (source listings are static)."""

    model_config = SettingsConfigDict(extra="ignore")

    NEWSNOW_API_URL: str = Field("https://newsnow.busiyi.world/api/s", alias="NEWSNOW_API_URL")
    JINA_READER_URL: str = Field("https://r.jina.ai", alias="JINA_READER_URL")


class DashScopeImageSettings(BaseSettings):
    """DashScope embedding/vision key and image generation configuration."""

    model_config = SettingsConfigDict(extra="ignore")

    DASHSCOPE_API_KEY: str = Field("", alias="DASHSCOPE_API_KEY")
    IMAGE_GEN_ENABLED: bool = Field(True, alias="IMAGE_GEN_ENABLED")
    IMAGE_GEN_MODEL: str = Field("qwen-image-2.0-pro", alias="IMAGE_GEN_MODEL")


class CorsSettings(BaseSettings):
    """CORS allowed origins."""

    model_config = SettingsConfigDict(extra="ignore")

    CORS_ORIGINS: str = Field("*", alias="CORS_ORIGINS")


class KnowledgeBaseSettings(BaseSettings):
    """Knowledge base chunking, uploads, embedding and vision configuration."""

    model_config = SettingsConfigDict(extra="ignore")

    KB_CHUNK_SIZE: int = Field(500, alias="KB_CHUNK_SIZE")
    KB_CHUNK_OVERLAP: int = Field(50, alias="KB_CHUNK_OVERLAP")
    UPLOAD_DIR: str = Field(str(_SERVER_DIR / "uploads"), alias="UPLOAD_DIR")
    MAX_UPLOAD_SIZE: int = Field(20 * 1024 * 1024, alias="MAX_UPLOAD_SIZE")
    KB_EMBEDDING_DIM: int = Field(1024, alias="KB_EMBEDDING_DIM")
    KB_EMBEDDING_MODEL: str = Field("text-embedding-v4", alias="KB_EMBEDDING_MODEL")
    KB_VISION_MODEL: str = Field("qwen-vl-ocr-latest", alias="KB_VISION_MODEL")
    KB_VISION_BASE_URL: str = Field(
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
        alias="KB_VISION_BASE_URL",
    )


class WebSearchSettings(BaseSettings):
    """Web search engine toggles and provider keys."""

    model_config = SettingsConfigDict(extra="ignore")

    WEB_SEARCH_ENABLED: bool = Field(False, alias="WEB_SEARCH_ENABLED")
    WEB_SEARCH_ENGINE: str = Field("tavily", alias="WEB_SEARCH_ENGINE")  # kimi / tavily
    MOONSHOT_API_KEY: str = Field("", alias="MOONSHOT_API_KEY")
    TAVILY_API_KEY: str = Field("", alias="TAVILY_API_KEY")


class LangSmithSettings(BaseSettings):
    """LangSmith tracing (optional, off by default).

    Also read directly from os.environ by the langsmith SDK; load_dotenv()
    above keeps that path working when values live only in .env.
    """

    model_config = SettingsConfigDict(extra="ignore")

    LANGSMITH_TRACING: bool = Field(False, alias="LANGSMITH_TRACING")
    LANGSMITH_API_KEY: str = Field("", alias="LANGSMITH_API_KEY")
    LANGSMITH_PROJECT: str = Field("shiyuan-ai", alias="LANGSMITH_PROJECT")
    LANGSMITH_ENDPOINT: str = Field(
        "https://api.smith.langchain.com",
        alias="LANGSMITH_ENDPOINT",
    )


class MemorySettings(BaseSettings):
    """Short-term conversation memory and KB RAG memory configuration.

    Summary model defaults to the main LLM base URL / API key.
    """

    model_config = SettingsConfigDict(extra="ignore")

    MEMORY_DB_PATH: str = Field(
        str(_SERVER_DIR / "data" / "agent_memory.db"),
        alias="MEMORY_DB_PATH",
    )
    SUMMARY_MODEL: str = Field("deepseek-v4-flash", alias="SUMMARY_MODEL")
    SUMMARY_TRIGGER_TOKENS: int = Field(80000, alias="SUMMARY_TRIGGER_TOKENS")
    SUMMARY_KEEP_MESSAGES: int = Field(10, alias="SUMMARY_KEEP_MESSAGES")
    KB_RAG_SUMMARY_TRIGGER_TOKENS: int = Field(
        50000, alias="KB_RAG_SUMMARY_TRIGGER_TOKENS"
    )
    KB_RAG_SUMMARY_KEEP_MESSAGES: int = Field(8, alias="KB_RAG_SUMMARY_KEEP_MESSAGES")
    KB_RAG_MEMORY_DB_PATH: str = Field(
        str(_SERVER_DIR / "data" / "rag_memory.db"),
        alias="KB_RAG_MEMORY_DB_PATH",
    )


class TemperatureSettings(BaseSettings):
    """Temperature strategy per scenario.

    结构化输出/确定性任务 → 低温；分析/创作任务 → 中高温。
    """

    model_config = SettingsConfigDict(extra="ignore")

    TEMPERATURE_REWRITE: float = Field(0.0, alias="TEMPERATURE_REWRITE")
    TEMPERATURE_SUMMARY: float = Field(0.3, alias="TEMPERATURE_SUMMARY")
    TEMPERATURE_ANALYZE: float = Field(0.7, alias="TEMPERATURE_ANALYZE")
    TEMPERATURE_GENERATE: float = Field(0.8, alias="TEMPERATURE_GENERATE")
    TEMPERATURE_CHAT: float = Field(0.7, alias="TEMPERATURE_CHAT")


class PromptGuardrailsSettings(BaseSettings):
    """Prompt length guardrails (logging warnings, not enforced truncation)."""

    model_config = SettingsConfigDict(extra="ignore")

    MAX_RAG_CONTEXT_CHARS: int = Field(15000, alias="MAX_RAG_CONTEXT_CHARS")


# ── Top-level settings ────────────────────────────────────────────────────


class Settings(BaseSettings):
    """Aggregated application settings.

    Each group is a nested ``BaseSettings`` that reads its own env vars. The
    summary model base URL / API key default to the main LLM values, so they
    are resolved here after the LLM group is populated.
    """

    model_config = SettingsConfigDict(extra="ignore")

    llm: LLMSettings = Field(default_factory=LLMSettings)
    server: ServerSettings = Field(default_factory=ServerSettings)
    crawler_schedule: CrawlerScheduleSettings = Field(default_factory=CrawlerScheduleSettings)
    publishing: PublishingSettings = Field(default_factory=PublishingSettings)
    news_sources: NewsSourcesSettings = Field(default_factory=NewsSourcesSettings)
    dashscope_image: DashScopeImageSettings = Field(default_factory=DashScopeImageSettings)
    cors: CorsSettings = Field(default_factory=CorsSettings)
    knowledge_base: KnowledgeBaseSettings = Field(default_factory=KnowledgeBaseSettings)
    web_search: WebSearchSettings = Field(default_factory=WebSearchSettings)
    langsmith: LangSmithSettings = Field(default_factory=LangSmithSettings)
    memory: MemorySettings = Field(default_factory=MemorySettings)
    temperature: TemperatureSettings = Field(default_factory=TemperatureSettings)
    prompt_guardrails: PromptGuardrailsSettings = Field(default_factory=PromptGuardrailsSettings)

    # Summary model base URL / API key default to the main LLM values.
    SUMMARY_MODEL_BASE_URL: str = Field("", alias="SUMMARY_MODEL_BASE_URL")
    SUMMARY_MODEL_API_KEY: str = Field("", alias="SUMMARY_MODEL_API_KEY")


# ── Static (non-env) configuration ──────────────────────────────────────
# These are constant values that have never been environment-driven; kept as
# plain module-level constants to preserve ``from config import X``.

# Hard lower bound for scheduled crawl intervals (seconds). Not configurable.
SCHEDULE_MIN_INTERVAL = 60

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

# Publishing platforms
PUBLISH_PLATFORMS = {
    "xiaohongshu": "小红书",
    "wechat_mp": "微信公众号",
    "douyin": "抖音",
}

# ── Prompt length guardrails (static) ────────────────────────────────────
# 各场景系统提示词建议最大字符数（用于日志告警，不强制截断）
MAX_PROMPT_CHARS = {
    "interpret": 4000,
    "chat": 2000,
    "generate": 4000,
    "agent": 4000,
    "kb_rag": 2000,
    "kb_generate": 2000,
}


# ── Singleton + module-level re-exports ──────────────────────────────────
# Instantiated at import time. tests/conftest.py sets env vars before
# importing the app, and load_dotenv(override=False) above does not clobber
# them, so the singleton reads the test-injected values correctly.

settings = Settings()


# LLM Configuration
LLM_PROVIDER = settings.llm.PROVIDER
LLM_API_KEY = settings.llm.API_KEY
LLM_BASE_URL = settings.llm.BASE_URL
LLM_MODEL = settings.llm.MODEL

# Server
HOST = settings.server.HOST
PORT = settings.server.PORT

# Crawler intervals (seconds)
CRAWL_INTERVAL = settings.crawler_schedule.CRAWL_INTERVAL
SCHEDULE_ENABLED = settings.crawler_schedule.SCHEDULE_ENABLED
NEWSNOW_CRAWL_INTERVAL = settings.crawler_schedule.NEWSNOW_CRAWL_INTERVAL
RSS_CRAWL_INTERVAL = settings.crawler_schedule.RSS_CRAWL_INTERVAL
KEYWORDS_FILE = settings.crawler_schedule.KEYWORDS_FILE
KEYWORDS_FILTER_ENABLED = settings.crawler_schedule.KEYWORDS_FILTER_ENABLED

# Publishing
PUBLISH_RETRY = settings.publishing.PUBLISH_RETRY
COOKIES_DIR = settings.publishing.COOKIES_DIR
PUBLISH_HEADLESS = settings.publishing.PUBLISH_HEADLESS
PUBLISH_TIMEOUT = settings.publishing.PUBLISH_TIMEOUT
PUBLISH_MANUAL_TIMEOUT = settings.publishing.PUBLISH_MANUAL_TIMEOUT
WECHAT_APP_ID = settings.publishing.WECHAT_APP_ID
WECHAT_APP_SECRET = settings.publishing.WECHAT_APP_SECRET

# News sources
NEWSNOW_API_URL = settings.news_sources.NEWSNOW_API_URL
JINA_READER_URL = settings.news_sources.JINA_READER_URL

# DashScope / Image Generation
DASHSCOPE_API_KEY = settings.dashscope_image.DASHSCOPE_API_KEY
IMAGE_GEN_ENABLED = settings.dashscope_image.IMAGE_GEN_ENABLED
IMAGE_GEN_MODEL = settings.dashscope_image.IMAGE_GEN_MODEL

# CORS
CORS_ORIGINS = settings.cors.CORS_ORIGINS

# Knowledge Base
KB_CHUNK_SIZE = settings.knowledge_base.KB_CHUNK_SIZE
KB_CHUNK_OVERLAP = settings.knowledge_base.KB_CHUNK_OVERLAP
UPLOAD_DIR = settings.knowledge_base.UPLOAD_DIR
MAX_UPLOAD_SIZE = settings.knowledge_base.MAX_UPLOAD_SIZE
KB_EMBEDDING_DIM = settings.knowledge_base.KB_EMBEDDING_DIM
KB_EMBEDDING_MODEL = settings.knowledge_base.KB_EMBEDDING_MODEL
KB_VISION_MODEL = settings.knowledge_base.KB_VISION_MODEL
KB_VISION_BASE_URL = settings.knowledge_base.KB_VISION_BASE_URL

# Web Search
WEB_SEARCH_ENABLED = settings.web_search.WEB_SEARCH_ENABLED
WEB_SEARCH_ENGINE = settings.web_search.WEB_SEARCH_ENGINE
MOONSHOT_API_KEY = settings.web_search.MOONSHOT_API_KEY
TAVILY_API_KEY = settings.web_search.TAVILY_API_KEY

# LangSmith Tracing (optional, off by default)
LANGSMITH_TRACING = settings.langsmith.LANGSMITH_TRACING
LANGSMITH_API_KEY = settings.langsmith.LANGSMITH_API_KEY
LANGSMITH_PROJECT = settings.langsmith.LANGSMITH_PROJECT
LANGSMITH_ENDPOINT = settings.langsmith.LANGSMITH_ENDPOINT

# Memory (Short-term)
MEMORY_DB_PATH = settings.memory.MEMORY_DB_PATH
SUMMARY_MODEL = settings.memory.SUMMARY_MODEL
SUMMARY_MODEL_BASE_URL = settings.SUMMARY_MODEL_BASE_URL or LLM_BASE_URL
SUMMARY_MODEL_API_KEY = settings.SUMMARY_MODEL_API_KEY or LLM_API_KEY
SUMMARY_TRIGGER_TOKENS = settings.memory.SUMMARY_TRIGGER_TOKENS
SUMMARY_KEEP_MESSAGES = settings.memory.SUMMARY_KEEP_MESSAGES

# KB RAG Memory
KB_RAG_SUMMARY_TRIGGER_TOKENS = settings.memory.KB_RAG_SUMMARY_TRIGGER_TOKENS
KB_RAG_SUMMARY_KEEP_MESSAGES = settings.memory.KB_RAG_SUMMARY_KEEP_MESSAGES
KB_RAG_MEMORY_DB_PATH = settings.memory.KB_RAG_MEMORY_DB_PATH

# Temperature strategy
TEMPERATURE_REWRITE = settings.temperature.TEMPERATURE_REWRITE
TEMPERATURE_SUMMARY = settings.temperature.TEMPERATURE_SUMMARY
TEMPERATURE_ANALYZE = settings.temperature.TEMPERATURE_ANALYZE
TEMPERATURE_GENERATE = settings.temperature.TEMPERATURE_GENERATE
TEMPERATURE_CHAT = settings.temperature.TEMPERATURE_CHAT

# Prompt guardrails
MAX_RAG_CONTEXT_CHARS = settings.prompt_guardrails.MAX_RAG_CONTEXT_CHARS
