import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useNewsStore } from './news'

vi.mock('@/api', async () => {
  const { createApiMock } = await import('./__mocks__/api')
  return createApiMock()
})

describe('useNewsStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('has correct initial state', () => {
    const store = useNewsStore()
    expect(store.newsItems).toEqual([])
    expect(store.currentSource).toBe('cls-telegraph')
    expect(store.selectedNewsIds).toEqual([])
    expect(store.loading).toBe(false)
  })

  it('toggles selected news id', () => {
    const store = useNewsStore()
    store.toggleSelect('n1')
    expect(store.selectedNewsIds).toEqual(['n1'])
    store.toggleSelect('n1')
    expect(store.selectedNewsIds).toEqual([])
  })

  it('clearSelection resets ids', () => {
    const store = useNewsStore()
    store.toggleSelect('n1')
    store.clearSelection()
    expect(store.selectedNewsIds).toEqual([])
  })

  it('selectedNews derives from newsItems and selectedNewsIds', () => {
    const store = useNewsStore()
    store.newsItems = [
      { news_id: 'n1', title: 'T1' },
      { news_id: 'n2', title: 'T2' },
    ] as any
    store.toggleSelect('n1')
    expect(store.selectedNews).toHaveLength(1)
    expect(store.selectedNews[0].news_id).toBe('n1')
  })
})
