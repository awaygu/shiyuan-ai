import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { NewsItem, Article, PublishRecord, StyleType } from '@/types'
import {
  fetchNews,
  refreshNews,
  refreshNewsSource,
  generateArticle,
  fetchArticles,
  publishArticle,
  fetchPublishLog,
  fetchNewsNowPlatforms,
  refreshNewsNow,
  fetchRSSFeeds,
  refreshRSS,
} from '@/api'

export const useNewsStore = defineStore('news', () => {
  const newsItems = ref<NewsItem[]>([])
  const currentSource = ref<string>('cls-telegraph')
  const selectedNewsIds = ref<string[]>([])
  const articles = ref<Article[]>([])
  const publishLog = ref<PublishRecord[]>([])
  const loading = ref(false)
  const loadingMore = ref(false)
  const currentDetailNews = ref<NewsItem | null>(null)
  const currentStyle = ref<StyleType>('wechat_mp')

  const newsNowPlatforms = ref<Record<string, string>>({})
  const rssFeeds = ref<{ id: string; name: string; url: string; enabled: boolean }[]>([])

  const selectedNews = computed(() =>
    newsItems.value.filter((n) => selectedNewsIds.value.includes(n.news_id))
  )

  const sourceCategories = computed(() => {
    const map = new Map<string, NewsItem[]>()
    for (const item of newsItems.value) {
      const list = map.get(item.source) ?? []
      list.push(item)
      map.set(item.source, list)
    }
    return map
  })

  async function loadNews(source?: string) {
    loading.value = true
    try {
      const src = source ?? currentSource.value
      if (source !== undefined) currentSource.value = source
      await refreshNewsSource(currentSource.value)
      const { items } = await fetchNews(currentSource.value, 0, 100)
      newsItems.value = items
    } finally {
      loading.value = false
    }
  }

  async function loadMoreNews() {
    if (loadingMore.value || loading.value) return
    loadingMore.value = true
    try {
      await refreshNewsSource(currentSource.value)
      const { items } = await fetchNews(currentSource.value, 0, 100)
      const existingIds = new Set(newsItems.value.map((n) => n.news_id))
      const newItems = items.filter((n) => !existingIds.has(n.news_id))
      if (newItems.length > 0) {
        newsItems.value.push(...newItems)
      }
    } finally {
      loadingMore.value = false
    }
  }

  async function refreshCurrentSource() {
    loading.value = true
    try {
      await refreshNewsSource(currentSource.value)
      const { items } = await fetchNews(currentSource.value, 0, 100)
      newsItems.value = items
    } finally {
      loading.value = false
    }
  }

  async function refreshAllNews() {
    loading.value = true
    try {
      await refreshNews()
      const { items } = await fetchNews(currentSource.value, 0, 100)
      newsItems.value = items
    } finally {
      loading.value = false
    }
  }

  function toggleSelect(newsId: string) {
    const idx = selectedNewsIds.value.indexOf(newsId)
    if (idx >= 0) {
      selectedNewsIds.value.splice(idx, 1)
    } else {
      selectedNewsIds.value.push(newsId)
    }
  }

  function clearSelection() {
    selectedNewsIds.value = []
  }

  function viewDetail(news: NewsItem) {
    currentDetailNews.value = news
  }

  function closeDetail() {
    currentDetailNews.value = null
  }

  async function createArticle(title?: string): Promise<Article | null> {
    if (selectedNewsIds.value.length === 0) return null
    loading.value = true
    try {
      const article = await generateArticle(selectedNewsIds.value, currentStyle.value, title)
      articles.value.push(article)
      return article
    } finally {
      loading.value = false
    }
  }

  async function publish(articleId: string, platform: string): Promise<PublishRecord> {
    const record = await publishArticle(articleId, platform)
    publishLog.value.push(record)
    return record
  }

  async function loadArticles() {
    articles.value = await fetchArticles()
  }

  async function loadPublishLog() {
    publishLog.value = await fetchPublishLog()
  }

  async function loadNewsNowPlatforms() {
    newsNowPlatforms.value = await fetchNewsNowPlatforms()
  }

  async function refreshNewsNowFeeds() {
    loading.value = true
    try {
      await refreshNewsNow()
      const { items } = await fetchNews(currentSource.value, 0, 100)
      newsItems.value = items
    } finally {
      loading.value = false
    }
  }

  async function loadRSSFeeds() {
    rssFeeds.value = await fetchRSSFeeds()
  }

  async function refreshRSSFeeds() {
    loading.value = true
    try {
      await refreshRSS()
      const { items } = await fetchNews(currentSource.value, 0, 100)
      newsItems.value = items
    } finally {
      loading.value = false
    }
  }

  const agentDockedRight = ref(false)
  const agentPanelWidth = ref(440)

  return {
    newsItems,
    currentSource,
    selectedNewsIds,
    articles,
    publishLog,
    loading,
    loadingMore,
    currentDetailNews,
    currentStyle,
    newsNowPlatforms,
    rssFeeds,
    selectedNews,
    sourceCategories,
    agentDockedRight,
    agentPanelWidth,
    loadNews,
    loadMoreNews,
    refreshCurrentSource,
    refreshAllNews,
    toggleSelect,
    clearSelection,
    viewDetail,
    closeDetail,
    createArticle,
    publish,
    loadArticles,
    loadPublishLog,
    loadNewsNowPlatforms,
    refreshNewsNowFeeds,
    loadRSSFeeds,
    refreshRSSFeeds,
  }
})
