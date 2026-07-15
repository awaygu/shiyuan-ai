import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { KnowledgeBase, KBDoc, KBConversation, KBMessage } from '@/types'
import {
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
} from '@/api'

export const useKbStore = defineStore('kb', () => {
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
      return {
        results: [] as any[],
        errors: [{ filename: '', detail: e.message || '上传请求失败' }] as any[],
      }
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

  async function saveConvMessage(
    convId: string,
    role: string,
    content: string,
    type = 'chat',
    sources: any[] = [],
    kbId?: string
  ) {
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
  }
})
