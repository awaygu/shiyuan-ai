/** Backend API request wrappers. */

import axios from 'axios'
import type { NewsItem, Article, PublishRecord, StyleType } from '@/types'

const api = axios.create({
  baseURL: '/api',
  timeout: 30000,
})

/** Fetch news with pagination, optionally filtered by source. */
export async function fetchNews(source?: string, offset = 0, limit = 20): Promise<{ total: number; items: NewsItem[] }> {
  const params: Record<string, any> = { offset, limit }
  if (source) params.source = source
  const res = await api.get('/news', { params })
  return res.data
}

/** Re-crawl all news sources and get fresh data */
export async function refreshNews(): Promise<{ total: number; results: Record<string, any> }> {
  const res = await api.post('/news/refresh')
  return res.data
}

/** Refresh a single source (NewsNow platform or RSS feed). */
export async function refreshNewsSource(source: string): Promise<{ source: string; total: number; new: number }> {
  const res = await api.post(`/news/refresh/${encodeURIComponent(source)}`)
  return res.data
}

/** Fetch available sources. */
export async function fetchSources(): Promise<Record<string, string>> {
  const res = await api.get('/sources')
  return res.data.sources
}

// ── NewsNow API ───────────────────────────────────────────────────

/** Fetch NewsNow platforms. */
export async function fetchNewsNowPlatforms(): Promise<Record<string, string>> {
  const res = await api.get('/newsnow/platforms')
  return res.data.platforms
}

/** Refresh all NewsNow platforms. */
export async function refreshNewsNow(): Promise<{ total_new: number; summary: Record<string, any> }> {
  const res = await api.post('/newsnow/refresh')
  return res.data
}

/** Refresh a specific NewsNow platform. */
export async function refreshNewsNowPlatform(platformId: string): Promise<{ platform: string; name: string; total: number; new: number }> {
  const res = await api.post(`/newsnow/refresh/${platformId}`)
  return res.data
}

// ── RSS API ──────────────────────────────────────────────────────

export interface RSSFeed {
  id: string
  name: string
  url: string
  enabled: boolean
}

/** Fetch RSS feeds. */
export async function fetchRSSFeeds(): Promise<RSSFeed[]> {
  const res = await api.get('/rss/feeds')
  return res.data.feeds
}

/** Refresh all RSS feeds. */
export async function refreshRSS(): Promise<{ total_new: number; summary: Record<string, any> }> {
  const res = await api.post('/rss/refresh')
  return res.data
}

// ── AI Interpretation ────────────────────────────────────────────

/** Fetch full article content for a news item (on-demand from original URL). */
export async function fetchNewsContent(newsId: string): Promise<{
  news_id: string
  content: string
  cached: boolean
  source?: string
}> {
  const res = await api.get(`/news/${encodeURIComponent(newsId)}/content`)
  return res.data
}

/** AI-interpret a single news item. */
export async function interpretNews(newsId: string, style: string) {
  const res = await api.post('/interpret', { news_id: newsId, style })
  return res.data
}

/** Chat-style interpretation. */
export async function chatInterpret(message: string, newsIds: string[]) {
  const res = await api.post('/chat', { message, news_ids: newsIds })
  return res.data
}

/** Generate a full article. */
export async function generateArticle(newsIds: string[], style: StyleType, title?: string): Promise<Article> {
  const res = await api.post('/generate_article', { news_ids: newsIds, style, title })
  return res.data
}

/** Get all generated articles. */
export async function fetchArticles(): Promise<Article[]> {
  const res = await api.get('/articles')
  return res.data.items
}

/** Publish an article to a platform. */
export async function publishArticle(articleId: string, platform: string): Promise<PublishRecord> {
  const res = await api.post('/publish', { article_id: articleId, platform })
  return res.data
}

/** Get publish log. */
export async function fetchPublishLog(): Promise<PublishRecord[]> {
  const res = await api.get('/publish_log')
  return res.data.items
}

// ── Streaming (SSE) ──────────────────────────────────────────────

const SSE_BASE_URL = import.meta.env.DEV ? 'http://localhost:8000' : ''

export interface StreamCallbacks {
  onChunk: (text: string) => void
  onDone: () => void
  onError: (error: string) => void
  onLoading?: (message: string) => void
  onPrompt?: (prompt: string) => void
  onLimited?: (message: string) => void
  onMeta?: (data: Record<string, any>) => void
}

async function consumeSSE(path: string, body: Record<string, any>, callbacks: StreamCallbacks) {
  const url = SSE_BASE_URL + path
  try {
    const response = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    if (!response.ok) {
      callbacks.onError(`HTTP ${response.status}`)
      return
    }
    const reader = response.body!.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })

      const parts = buffer.split('\n\n')
      buffer = parts.pop() || ''

      for (const part of parts) {
        const lines = part.split('\n')
        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          const payload = line.slice(6)
          if (payload === '[DONE]') {
            callbacks.onDone()
            return
          }
          try {
            const parsed = JSON.parse(payload)
            if (parsed.type === 'chunk' && parsed.content) {
              callbacks.onChunk(parsed.content)
            } else if (parsed.type === 'prompt' && parsed.content) {
              callbacks.onPrompt?.(parsed.content)
            } else if (parsed.type === 'limited') {
              callbacks.onLimited?.(parsed.message || '内容受限')
            } else if (parsed.type === 'error') {
              callbacks.onError(parsed.message || '处理失败')
            } else if (parsed.type === 'loading') {
              callbacks.onLoading?.(parsed.message || '加载中...')
            } else if (parsed.type === 'meta') {
              callbacks.onMeta?.(parsed)
            } else if (parsed.type === 'done') {
              callbacks.onDone()
              return
            }
          } catch {
            // skip malformed lines
          }
        }
      }
    }
    callbacks.onDone()
  } catch (e: any) {
    callbacks.onError(e.message || 'Stream error')
  }
}

/** Stream chat interpretation. */
export function streamChat(message: string, newsIds: string[], callbacks: StreamCallbacks) {
  return consumeSSE('/api/chat/stream', { message, news_ids: newsIds }, callbacks)
}

/** Stream article generation. */
export function streamGenerateArticle(newsIds: string[], style: StyleType, callbacks: StreamCallbacks, title?: string, prompt?: string) {
  return consumeSSE('/api/generate_article/stream', { news_ids: newsIds, style, title, prompt }, callbacks)
}

/** Stream single news interpretation. */
export function streamInterpret(newsId: string, style: string, callbacks: StreamCallbacks) {
  return consumeSSE('/api/interpret/stream', { news_id: newsId, style }, callbacks)
}

// ── Agent Smart APIs ───────────────────────────────────────────

export interface TrendItem {
  keyword: string
  count: number
  source_count: number
  related_news: { news_id: string; title: string; source: string; url: string }[]
}

/** Get trending topics. */
export async function fetchTrends(topN = 10): Promise<{ trends: TrendItem[]; total_news: number }> {
  const res = await api.get('/agent/trends', { params: { top_n: topN } })
  return res.data
}

/** Compare coverage across sources. */
export async function compareSources(keyword: string, sources?: string[]): Promise<{
  keyword: string
  comparison: string
  matched_count: number
  sources: string[]
}> {
  const res = await api.post('/agent/compare', { keyword, sources })
  return res.data
}

/** Search news by keyword. */
export async function searchNews(q: string, source?: string, limit = 20): Promise<{
  keyword: string
  total: number
  items: NewsItem[]
}> {
  const params: Record<string, any> = { q, limit }
  if (source) params.source = source
  const res = await api.get('/agent/search', { params })
  return res.data
}

/** Stream daily briefing. */
export function streamBriefing(callbacks: StreamCallbacks) {
  return consumeSSE('/api/agent/briefing/stream', {}, callbacks)
}

// ── Agent Chat & Actions ──────────────────────────────────────

export interface AgentAction {
  action: string
  source?: string
  keyword?: string
  style?: string
}

export interface AgentStreamCallbacks extends StreamCallbacks {
  onAction?: (action: AgentAction) => void
  onLoadingDone?: () => void
}

/** Stream agent chat (general chat with action detection). */
export function streamAgentChat(message: string, newsIds: string[], callbacks: AgentStreamCallbacks, currentNewsId?: string) {
  const body: Record<string, any> = { message, news_ids: newsIds }
  if (currentNewsId) body.current_news_id = currentNewsId
  return consumeAgentSSE('/api/agent/chat/stream', body, callbacks)
}

async function consumeAgentSSE(path: string, body: Record<string, any>, callbacks: AgentStreamCallbacks) {
  const url = SSE_BASE_URL + path
  try {
    const response = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    if (!response.ok) {
      callbacks.onError(`HTTP ${response.status}`)
      return
    }
    const reader = response.body!.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })

      const parts = buffer.split('\n\n')
      buffer = parts.pop() || ''

      for (const part of parts) {
        const lines = part.split('\n')
        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          const payload = line.slice(6)
          if (payload === '[DONE]') {
            callbacks.onDone()
            return
          }
          try {
            const parsed = JSON.parse(payload)
            if (parsed.type === 'chunk' && parsed.content) {
              callbacks.onChunk(parsed.content)
            } else if (parsed.type === 'action' && parsed.action) {
              callbacks.onAction?.(parsed.action)
            } else if (parsed.type === 'prompt' && parsed.content) {
              callbacks.onPrompt?.(parsed.content)
            } else if (parsed.type === 'limited') {
              callbacks.onLimited?.(parsed.message || '内容受限')
            } else if (parsed.type === 'error') {
              callbacks.onError(parsed.message || '处理失败')
            } else if (parsed.type === 'loading') {
              callbacks.onLoading?.(parsed.message || '加载中...')
            } else if (parsed.type === 'loading_done') {
              callbacks.onLoadingDone?.()
            } else if (parsed.type === 'meta') {
              callbacks.onMeta?.(parsed)
            } else if (parsed.type === 'done') {
              callbacks.onDone()
              return
            }
          } catch {
            // skip
          }
        }
      }
    }
    callbacks.onDone()
  } catch (e: any) {
    callbacks.onError(e.message || 'Stream error')
  }
}

/** Execute a site action. */
export async function executeAction(action: string, params?: Record<string, any>): Promise<Record<string, any>> {
  const body: Record<string, any> = { action, ...params }
  const res = await api.post('/agent/execute', body)
  return res.data
}
