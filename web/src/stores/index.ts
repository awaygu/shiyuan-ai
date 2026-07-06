import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { NewsItem, Article, PublishRecord, StyleType, KBDoc, KnowledgeBase, KBConversation, KBMessage, AsyncTask } from '@/types'
import type { KeywordGroup } from '@/api'
import {
  fetchNews,
  refreshNews,
  refreshNewsSource,
  clearNewsContentCache,
  generateArticle,
  fetchArticles,
  publishArticle,
  fetchPublishLog,
  fetchNewsNowPlatforms,
  refreshNewsNow,
  fetchRSSFeeds,
  refreshRSS,
  fetchKBDocuments,
  uploadDocuments,
  deleteKBDocument,
  renameKBDocument,
  createKnowledgeBase,
  fetchKnowledgeBases,
  fetchKnowledgeBase,
  deleteKnowledgeBase,
  updateKnowledgeBase,
  createKBConversation,
  fetchKBConversations,
  deleteKBConversation,
  fetchKBMessages,
  saveKBMessage,
  fetchKeywordStatus,
  updateKeywordGroups as apiUpdateKeywords,
  fetchTasks,
  clearDoneTasks,
  streamTaskUpdates,
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

  async function publish(articleId: string, platform: string, imageOptions?: { generate_cover?: boolean; generate_inline_images?: boolean }): Promise<PublishRecord & { need_login?: boolean }> {
    const res = await publishArticle(articleId, platform, imageOptions)
    startTaskStream()
    showTaskPanel.value = true
    await loadTasks()
    return res
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

  const agentDockedRight = ref(false)
  const agentPanelWidth = ref(440)

  // ── Keywords ──────────────────────────────────────────────────

  const kwGroups = ref<KeywordGroup[]>([])
  const kwLoading = ref(false)

  async function loadKeywords() {
    kwLoading.value = true
    try {
      const data = await fetchKeywordStatus()
      kwGroups.value = data.groups
    } finally {
      kwLoading.value = false
    }
  }

  async function saveKeywords(groups: KeywordGroup[]) {
    kwLoading.value = true
    try {
      const data = await apiUpdateKeywords(groups)
      kwGroups.value = data.groups
    } finally {
      kwLoading.value = false
    }
  }

  // ── Async Tasks ────────────────────────────────────────────────

  const tasks = ref<AsyncTask[]>([])
  const showTaskPanel = ref(false)
  let _stopTaskStream: (() => void) | null = null

  async function loadTasks() {
    tasks.value = await fetchTasks()
  }

  function startTaskStream() {
    if (_stopTaskStream) return
    _stopTaskStream = streamTaskUpdates({
      onTaskUpdate(taskUpdate) {
        const idx = tasks.value.findIndex(t => t.task_id === taskUpdate.task_id)
        if (idx >= 0) {
          tasks.value[idx] = taskUpdate
        } else {
          tasks.value.unshift(taskUpdate)
        }
      },
      onError() {},
    })
  }

  function stopTaskStream() {
    if (_stopTaskStream) {
      _stopTaskStream()
      _stopTaskStream = null
    }
  }

  async function clearDoneTasksAction() {
    tasks.value = await clearDoneTasks()
  }

  function toggleTaskPanel() {
    showTaskPanel.value = !showTaskPanel.value
    if (showTaskPanel.value) {
      startTaskStream()
    }
  }

  const runningTaskCount = computed(() => tasks.value.filter(t => t.status === 'pending' || t.status === 'running').length)

  // ── Knowledge Base List ────────────────────────────────────────

  const knowledgeBases = ref<KnowledgeBase[]>([])
  const kbLoading = ref(false)

  async function loadKnowledgeBases() {
    kbLoading.value = true
    try {
      knowledgeBases.value = await fetchKnowledgeBases()
    } finally {
      kbLoading.value = false
    }
  }

  async function createKB(name: string, description = ''): Promise<KnowledgeBase> {
    const kb = await createKnowledgeBase(name, description)
    await loadKnowledgeBases()
    return kb
  }

  async function removeKB(kbId: string) {
    await deleteKnowledgeBase(kbId)
    await loadKnowledgeBases()
  }

  async function updateKB(kbId: string, data: { name?: string; description?: string }) {
    const updated = await updateKnowledgeBase(kbId, data)
    if (currentKB.value && currentKB.value.kb_id === kbId) {
      currentKB.value = { ...currentKB.value, ...updated }
    }
    await loadKnowledgeBases()
    return updated
  }

  // ── Current KB State ────────────────────────────────────────────

  const currentKB = ref<KnowledgeBase | null>(null)
  const kbDocuments = ref<KBDoc[]>([])
  const kbTotalChunks = ref(0)
  const kbUploading = ref(false)
  const kbDeleting = ref(false)
  const kbSelectedDocIds = ref<string[]>([])

  const kbConversations = ref<KBConversation[]>([])
  const currentConvId = ref<string>('')

  async function loadCurrentKB(kbId: string) {
    currentKB.value = await fetchKnowledgeBase(kbId)
    await loadKBDocuments(kbId)
    kbSelectedDocIds.value = kbDocuments.value.map(d => d.doc_id)
    await loadKBConversations(kbId)
    // 切换知识库时，生成会话必须重置，否则 currentGenConvId 仍指向旧 KB 的会话
    currentGenConvId.value = ''
    kbGenMessages.value = []
    // 优先复用已存在的「生成文章」会话，避免每次切换都新建
    const existingGen = kbConversations.value.find(c => (c.title || '') === '生成文章')
    if (existingGen) {
      currentGenConvId.value = existingGen.conv_id
    }
  }

  async function loadKBDocuments(kbId?: string) {
    const id = kbId || currentKB.value?.kb_id
    if (!id) return
    const data = await fetchKBDocuments(id)
    kbDocuments.value = data.documents
    kbTotalChunks.value = data.total_chunks
    const newIds = new Set(data.documents.map(d => d.doc_id))
    kbSelectedDocIds.value = kbSelectedDocIds.value.filter(id => newIds.has(id))
    const unselected = data.documents.filter(d => !kbSelectedDocIds.value.includes(d.doc_id))
    if (unselected.length > 0 && kbSelectedDocIds.value.length === 0) {
      kbSelectedDocIds.value = data.documents.map(d => d.doc_id)
    }
  }

  async function uploadKBDocs(files: File[], kbId?: string) {
    const id = kbId || currentKB.value?.kb_id
    if (!id) return { results: [] as any[], errors: [] as any[] }
    kbUploading.value = true
    try {
      const { results, errors } = await uploadDocuments(id, files)
      await loadKBDocuments(id)
      return { results, errors }
    } catch (e: any) {
      return { results: [] as any[], errors: [{ filename: '', detail: e.message || '上传请求失败' }] as any[] }
    } finally {
      kbUploading.value = false
    }
  }

  async function deleteKBDoc(docId: string, kbId?: string) {
    const id = kbId || currentKB.value?.kb_id
    if (!id) return
    kbDeleting.value = true
    try {
      await deleteKBDocument(id, docId)
      await loadKBDocuments(id)
    } finally {
      kbDeleting.value = false
    }
  }

  async function renameKBDoc(docId: string, filename: string, kbId?: string) {
    const id = kbId || currentKB.value?.kb_id
    if (!id) return
    await renameKBDocument(id, docId, filename)
    await loadKBDocuments(id)
  }

  function toggleDocSelection(docId: string) {
    const idx = kbSelectedDocIds.value.indexOf(docId)
    if (idx >= 0) {
      kbSelectedDocIds.value.splice(idx, 1)
    } else {
      kbSelectedDocIds.value.push(docId)
    }
  }

  function selectAllDocs() {
    kbSelectedDocIds.value = kbDocuments.value.map(d => d.doc_id)
  }

  function deselectAllDocs() {
    kbSelectedDocIds.value = []
  }

  async function loadKBConversations(kbId?: string) {
    const id = kbId || currentKB.value?.kb_id
    if (!id) return
    kbConversations.value = await fetchKBConversations(id)
  }

  async function createConv(kbId?: string, title = '') {
    const id = kbId || currentKB.value?.kb_id
    if (!id) return
    const conv = await createKBConversation(id, title)
    await loadKBConversations(id)
    currentConvId.value = conv.conv_id
    return conv
  }

  async function removeConv(convId: string, kbId?: string) {
    const id = kbId || currentKB.value?.kb_id
    if (!id) return
    await deleteKBConversation(id, convId)
    await loadKBConversations(id)
    if (currentConvId.value === convId) {
      currentConvId.value = ''
    }
  }

  async function loadConvMessages(convId: string, kbId?: string): Promise<KBMessage[]> {
    const id = kbId || currentKB.value?.kb_id
    if (!id) return []
    return await fetchKBMessages(id, convId)
  }

  async function saveConvMessage(convId: string, role: string, content: string, type = 'chat', sources: any[] = [], kbId?: string) {
    const id = kbId || currentKB.value?.kb_id
    if (!id) return
    await saveKBMessage(id, convId, role, content, type, sources)
  }

  // ── 独立生成会话（与问答会话物理隔离） ──
  const currentGenConvId = ref<string>('')
  const kbGenMessages = ref<KBMessage[]>([])

  async function ensureGenConv(kbId?: string) {
    const id = kbId || currentKB.value?.kb_id
    if (!id) return
    if (!currentGenConvId.value) {
      // 复用已存在的「生成文章」会话，避免重复创建
      const existing = kbConversations.value.find(c => (c.title || '') === '生成文章')
      if (existing) {
        currentGenConvId.value = existing.conv_id
        return
      }
      const conv = await createKBConversation(id, '生成文章')
      currentGenConvId.value = conv.conv_id
    }
  }

  async function loadGenMessages(kbId?: string) {
    const id = kbId || currentKB.value?.kb_id
    if (!id || !currentGenConvId.value) {
      kbGenMessages.value = []
      return
    }
    kbGenMessages.value = await fetchKBMessages(id, currentGenConvId.value)
  }

  async function clearGenConv(kbId?: string) {
    const id = kbId || currentKB.value?.kb_id
    if (!id || !currentGenConvId.value) return
    const oldConvId = currentGenConvId.value
    await deleteKBConversation(id, oldConvId)
    kbGenMessages.value = []
    const conv = await createKBConversation(id, '生成文章')
    currentGenConvId.value = conv.conv_id
  }

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
    clearContentCache,
    loadRSSFeeds,
    refreshRSSFeeds,
    knowledgeBases,
    kbLoading,
    loadKnowledgeBases,
    createKB,
    removeKB,
    updateKB,
    currentKB,
    kbDocuments,
    kbTotalChunks,
    kbUploading,
    kbDeleting,
    kbConversations,
    currentConvId,
    loadCurrentKB,
    loadKBDocuments,
    uploadKBDocs,
    deleteKBDoc,
    renameKBDoc,
    kbSelectedDocIds,
    toggleDocSelection,
    selectAllDocs,
    deselectAllDocs,
    loadKBConversations,
    createConv,
    removeConv,
    loadConvMessages,
    saveConvMessage,
    currentGenConvId,
    kbGenMessages,
    ensureGenConv,
    loadGenMessages,
    clearGenConv,

    kwGroups,
    kwLoading,
    loadKeywords,
    saveKeywords,

    tasks,
    showTaskPanel,
    loadTasks,
    startTaskStream,
    stopTaskStream,
    clearDoneTasksAction,
    toggleTaskPanel,
    runningTaskCount,
  }
})
