-- 0001_initial.sql
-- 初始 schema：8 个业务表。使用 CREATE TABLE IF NOT EXISTS 保证幂等。
-- 与原 database.py init_db() 的 schema 等价，唯一差异是把 source_url
-- 提升进 kb_documents 的 CREATE TABLE（原仅靠 ALTER ADD COLUMN 存在，是隐患）。
-- 3 个原 try/except ALTER（page / kb_id / summary）不再写入，因为对应
-- 列已在 CREATE TABLE 里定义。

CREATE TABLE IF NOT EXISTS news (
    news_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    summary TEXT,
    content TEXT,
    source TEXT,
    url TEXT,
    published_at TEXT,
    extra TEXT
);

CREATE TABLE IF NOT EXISTS articles (
    article_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    content TEXT,
    style TEXT,
    news_ids TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS publish_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    article_id TEXT,
    platform TEXT,
    success INTEGER,
    url TEXT,
    timestamp TEXT,
    extra TEXT
);

CREATE TABLE IF NOT EXISTS kb_documents (
    doc_id TEXT PRIMARY KEY,
    kb_id TEXT NOT NULL DEFAULT 'default',
    filename TEXT NOT NULL,
    file_type TEXT,
    chunk_count INTEGER DEFAULT 0,
    file_size INTEGER DEFAULT 0,
    upload_time TEXT DEFAULT (datetime('now')),
    status TEXT DEFAULT 'ready',
    summary TEXT DEFAULT '',
    source_url TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS kb_chunks (
    chunk_id TEXT PRIMARY KEY,
    doc_id TEXT NOT NULL,
    chunk_index INTEGER DEFAULT 0,
    page INTEGER DEFAULT 0,
    text TEXT NOT NULL,
    FOREIGN KEY (doc_id) REFERENCES kb_documents(doc_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS knowledge_bases (
    kb_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT DEFAULT '',
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS kb_conversations (
    conv_id TEXT PRIMARY KEY,
    kb_id TEXT NOT NULL,
    title TEXT DEFAULT '',
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (kb_id) REFERENCES knowledge_bases(kb_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS kb_messages (
    msg_id TEXT PRIMARY KEY,
    conv_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT DEFAULT '',
    type TEXT DEFAULT 'chat',
    sources TEXT DEFAULT '',
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (conv_id) REFERENCES kb_conversations(conv_id) ON DELETE CASCADE
);
