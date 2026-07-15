import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useKbStore } from './kb'

vi.mock('@/api', () => ({
  fetchNews: vi.fn(),
  refreshNews: vi.fn(),
  refreshNewsSource: vi.fn(),
  clearNewsContentCache: vi.fn(),
  generateArticle: vi.fn(),
  fetchArticles: vi.fn(),
  publishArticle: vi.fn(),
  fetchPublishLog: vi.fn(),
  fetchNewsNowPlatforms: vi.fn(),
  refreshNewsNow: vi.fn(),
  fetchRSSFeeds: vi.fn(),
  refreshRSS: vi.fn(),
  fetchKBDocuments: vi.fn(),
  uploadDocuments: vi.fn(),
  deleteKBDocument: vi.fn(),
  renameKBDocument: vi.fn(),
  createKnowledgeBase: vi.fn(),
  fetchKnowledgeBases: vi.fn(),
  fetchKnowledgeBase: vi.fn(),
  deleteKnowledgeBase: vi.fn(),
  updateKnowledgeBase: vi.fn(),
  createKBConversation: vi.fn(),
  fetchKBConversations: vi.fn(),
  deleteKBConversation: vi.fn(),
  fetchKBMessages: vi.fn(),
  saveKBMessage: vi.fn(),
  fetchKeywordStatus: vi.fn(),
  updateKeywordGroups: vi.fn(),
  fetchTasks: vi.fn(),
  clearDoneTasks: vi.fn(),
  streamTaskUpdates: vi.fn(),
}))

import {
  fetchKnowledgeBases,
  createKnowledgeBase,
  deleteKnowledgeBase,
  updateKnowledgeBase,
  fetchKnowledgeBase,
  fetchKBDocuments,
  fetchKBConversations,
  createKBConversation,
  deleteKBDocument,
  deleteKBConversation,
} from '@/api'

describe('useKbStore (kb + kb-conversation)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('loadKnowledgeBases populates knowledgeBases', async () => {
    ;(fetchKnowledgeBases as any).mockResolvedValue([{ kb_id: 'kb1', name: 'A', description: '' }])
    const store = useKbStore()
    await store.loadKnowledgeBases()
    expect(store.knowledgeBases).toHaveLength(1)
    expect(store.knowledgeBases[0].kb_id).toBe('kb1')
  })

  it('createKB creates then reloads list', async () => {
    ;(createKnowledgeBase as any).mockResolvedValue({ kb_id: 'kb2', name: 'N', description: 'd' })
    ;(fetchKnowledgeBases as any).mockResolvedValue([{ kb_id: 'kb2', name: 'N', description: 'd' }])
    const store = useKbStore()
    const kb = await store.createKB('N', 'd')
    expect(kb.kb_id).toBe('kb2')
    expect(createKnowledgeBase).toHaveBeenCalledWith('N', 'd')
    expect(store.knowledgeBases).toHaveLength(1)
  })

  it('removeKB deletes then reloads list', async () => {
    ;(deleteKnowledgeBase as any).mockResolvedValue(undefined)
    ;(fetchKnowledgeBases as any).mockResolvedValue([])
    const store = useKbStore()
    await store.removeKB('kb1')
    expect(deleteKnowledgeBase).toHaveBeenCalledWith('kb1')
    expect(store.knowledgeBases).toEqual([])
  })

  it('updateKB updates currentKB when it matches and reloads list', async () => {
    ;(updateKnowledgeBase as any).mockResolvedValue({
      kb_id: 'kb1',
      name: 'new',
      description: 'desc',
    })
    ;(fetchKnowledgeBase as any).mockResolvedValue({
      kb_id: 'kb1',
      name: 'old',
      description: 'old',
    })
    ;(fetchKBDocuments as any).mockResolvedValue({ documents: [], total_chunks: 0 })
    ;(fetchKBConversations as any).mockResolvedValue([])
    const store = useKbStore()
    await store.loadCurrentKB('kb1')
    const updated = await store.updateKB('kb1', { name: 'new' })
    expect(updateKnowledgeBase).toHaveBeenCalledWith('kb1', { name: 'new' })
    expect(updated.name).toBe('new')
    expect(store.currentKB?.name).toBe('new')
  })

  it('loadCurrentKB loads docs+conversations and resets gen conv', async () => {
    ;(fetchKnowledgeBase as any).mockResolvedValue({ kb_id: 'kb1', name: 'K', description: '' })
    ;(fetchKBDocuments as any).mockResolvedValue({
      documents: [
        { doc_id: 'd1', filename: 'a.pdf', file_type: '.pdf', chunk_count: 2 } as any,
        { doc_id: 'd2', filename: 'b.txt', file_type: '.txt', chunk_count: 1 } as any,
      ],
      total_chunks: 3,
    })
    ;(fetchKBConversations as any).mockResolvedValue([
      { conv_id: 'c1', title: '生成文章', kb_id: 'kb1' },
      { conv_id: 'c2', title: '问答', kb_id: 'kb1' },
    ])
    const store = useKbStore()
    await store.loadCurrentKB('kb1')
    expect(store.currentKB?.kb_id).toBe('kb1')
    expect(store.kbDocuments).toHaveLength(2)
    expect(store.kbTotalChunks).toBe(3)
    // 切换 kb 时应选中全部文档
    expect(store.kbSelectedDocIds).toEqual(['d1', 'd2'])
    // 复用已存在的「生成文章」会话
    expect(store.currentGenConvId).toBe('c1')
    expect(store.kbGenMessages).toEqual([])
  })

  it('deleteKBDoc reloads documents', async () => {
    ;(fetchKnowledgeBase as any).mockResolvedValue({ kb_id: 'kb1', name: 'K', description: '' })
    ;(fetchKBDocuments as any)
      .mockResolvedValueOnce({
        documents: [{ doc_id: 'd1', filename: 'a.pdf', file_type: '.pdf', chunk_count: 2 } as any],
        total_chunks: 2,
      })
      .mockResolvedValueOnce({ documents: [], total_chunks: 0 })
    ;(fetchKBConversations as any).mockResolvedValue([])
    ;(deleteKBDocument as any).mockResolvedValue({ deleted: true, doc_id: 'd1', chunks_removed: 2 })
    const store = useKbStore()
    await store.loadCurrentKB('kb1')
    expect(store.kbDocuments).toHaveLength(1)
    await store.deleteKBDoc('d1')
    expect(deleteKBDocument).toHaveBeenCalledWith('kb1', 'd1')
    expect(store.kbDocuments).toEqual([])
  })

  it('createConv creates then sets currentConvId and reloads conversations', async () => {
    ;(fetchKnowledgeBase as any).mockResolvedValue({ kb_id: 'kb1', name: 'K', description: '' })
    ;(fetchKBDocuments as any).mockResolvedValue({ documents: [], total_chunks: 0 })
    ;(fetchKBConversations as any)
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([{ conv_id: 'c9', title: '', kb_id: 'kb1' }])
    ;(createKBConversation as any).mockResolvedValue({ conv_id: 'c9', title: '', kb_id: 'kb1' })
    const store = useKbStore()
    await store.loadCurrentKB('kb1')
    const conv = await store.createConv()
    expect(conv?.conv_id).toBe('c9')
    expect(store.currentConvId).toBe('c9')
    expect(createKBConversation).toHaveBeenCalledWith('kb1', '')
  })

  it('removeConv clears currentConvId when removing the active one', async () => {
    ;(fetchKnowledgeBase as any).mockResolvedValue({ kb_id: 'kb1', name: 'K', description: '' })
    ;(fetchKBDocuments as any).mockResolvedValue({ documents: [], total_chunks: 0 })
    ;(fetchKBConversations as any)
      .mockResolvedValueOnce([{ conv_id: 'c9', title: '', kb_id: 'kb1' }])
      .mockResolvedValueOnce([])
    ;(deleteKBConversation as any).mockResolvedValue(undefined)
    const store = useKbStore()
    await store.loadCurrentKB('kb1')
    store.currentConvId = 'c9'
    await store.removeConv('c9')
    expect(deleteKBConversation).toHaveBeenCalledWith('kb1', 'c9')
    expect(store.currentConvId).toBe('')
  })
})
