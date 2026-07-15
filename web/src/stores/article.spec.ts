import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useArticleStore } from './article'

vi.mock('@/api', async () => {
  const { createApiMock } = await import('./__mocks__/api')
  return createApiMock()
})

import { generateArticle, fetchArticles } from '@/api'

describe('useArticleStore (articles) — new signature', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('loadArticles populates articles', async () => {
    ;(fetchArticles as any).mockResolvedValue([
      { article_id: 'a1', title: 'T', content: 'c', style: 'wechat_mp', news_ids: ['n1'] } as any,
    ])
    const store = useArticleStore()
    await store.loadArticles()
    expect(store.articles).toHaveLength(1)
    expect(store.articles[0].article_id).toBe('a1')
  })

  it('createArticle returns null when newsIds is empty', async () => {
    const store = useArticleStore()
    const res = await store.createArticle([], 'wechat_mp')
    expect(res).toBeNull()
    expect(generateArticle).not.toHaveBeenCalled()
  })

  it('createArticle generates from given newsIds + style and pushes to articles', async () => {
    ;(generateArticle as any).mockResolvedValue({
      article_id: 'a1',
      title: 'My Title',
      content: 'c',
      style: 'xiaohongshu',
      news_ids: ['n1', 'n2'],
    })
    const store = useArticleStore()
    const res = await store.createArticle(['n1', 'n2'], 'xiaohongshu', 'My Title')
    expect(generateArticle).toHaveBeenCalledWith(['n1', 'n2'], 'xiaohongshu', 'My Title')
    expect(res?.article_id).toBe('a1')
    expect(store.articles).toHaveLength(1)
    expect(store.articles[0].style).toBe('xiaohongshu')
  })

  it('addArticle directly appends a constructed article', () => {
    const store = useArticleStore()
    const article = {
      article_id: 'art_stream_1',
      title: 'T',
      content: 'c',
      style: 'wechat_mp',
      news_ids: ['n1'],
    }
    store.addArticle(article)
    expect(store.articles).toHaveLength(1)
    expect(store.articles[0].article_id).toBe('art_stream_1')
  })
})
