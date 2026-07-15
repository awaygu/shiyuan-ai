import { vi } from 'vitest'

// 共享的 @/api mock 工厂：返回一个完整的 mock 模块对象，所有键均为 vi.fn()。
// 键集合为 5 个 store spec 原有内联 mock 的并集（实际 5 份完全一致）。
// vi.mock('@/api', () => createApiMock()) 会在模块加载前注入此对象。
export function createApiMock() {
  return {
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
  } as unknown as Record<string, ReturnType<typeof vi.fn>>
}
