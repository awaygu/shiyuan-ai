import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { NewsItem, StyleType } from '@/types'
import {
  fetchNews,
  refreshNews,
  refreshNewsSource,
  clearNewsContentCache,
  fetchNewsNowPlatforms,
  refreshNewsNow,
  fetchRSSFeeds,
  refreshRSS,
} from '@/api'

export const useNewsStore = defineStore('news', () => {
  const newsItems = ref<NewsItem[]>([])
  const currentSource = ref<string>('cls-telegraph')
  const selectedNewsIds = ref<string[]>([])
  const loading = ref(false)
  const loadingMore = ref(false)
  const currentDetailNews = ref<NewsItem | null>(null)
  const currentStyle = ref<StyleType>('wechat_mp')

  const newsNowPlatforms = ref<Record<string, string>>({})
  const rssFeeds = ref<{ id: string; name: string; url: string; enabled: boolean }[]>([])

  const selectedNews = computed(() =>
    newsItems.value.filter(n => selectedNewsIds.value.includes(n.news_id))
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
      const existingIds = new Set(newsItems.value.map(n => n.news_id))
      const newItems = items.filter(n => !existingIds.has(n.news_id))
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

  async function clearContentCache(source: string) {
    await clearNewsContentCache(source)
    for (const item of newsItems.value) {
      if (item.source === source) {
        item.content = ''
      }
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

  return {
    newsItems,
    currentSource,
    selectedNewsIds,
    loading,
    loadingMore,
    currentDetailNews,
    currentStyle,
    newsNowPlatforms,
    rssFeeds,
    selectedNews,
    sourceCategories,
    loadNews,
    loadMoreNews,
    refreshCurrentSource,
    refreshAllNews,
    toggleSelect,
    clearSelection,
    viewDetail,
    closeDetail,
    loadNewsNowPlatforms,
    refreshNewsNowFeeds,
    clearContentCache,
    loadRSSFeeds,
    refreshRSSFeeds,
  }
})
