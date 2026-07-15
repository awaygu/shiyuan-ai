import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { usePublishStore } from './publish'

vi.mock('@/api', async () => {
  const { createApiMock } = await import('./__mocks__/api')
  return createApiMock()
})

import { publishArticle, fetchPublishLog, streamTaskUpdates, fetchTasks } from '@/api'

describe('usePublishStore (publish)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('loadPublishLog populates publishLog', async () => {
    ;(fetchPublishLog as any).mockResolvedValue([
      { article_id: 'a1', platform: 'wechat_mp', success: true, url: 'u', timestamp: 't' } as any,
    ])
    const store = usePublishStore()
    await store.loadPublishLog()
    expect(store.publishLog).toHaveLength(1)
    expect(store.publishLog[0].article_id).toBe('a1')
  })

  it('publish calls publishArticle and returns result', async () => {
    ;(publishArticle as any).mockResolvedValue({
      article_id: 'a1',
      platform: 'xiaohongshu',
      success: true,
      url: 'u',
      timestamp: 't',
    })
    const store = usePublishStore()
    const res = await store.publish('a1', 'xiaohongshu')
    expect(publishArticle).toHaveBeenCalledWith('a1', 'xiaohongshu', undefined)
    expect(res.platform).toBe('xiaohongshu')
  })

  it('publish does NOT trigger task stream/panel (caller owns notifyTaskStarted)', async () => {
    ;(publishArticle as any).mockResolvedValue({
      article_id: 'a1',
      platform: 'xiaohongshu',
      success: true,
      url: 'u',
      timestamp: 't',
    })
    const store = usePublishStore()
    await store.publish('a1', 'xiaohongshu')
    // publish 本身不应触碰任务相关逻辑
    expect(streamTaskUpdates).not.toHaveBeenCalled()
    expect(fetchTasks).not.toHaveBeenCalled()
    expect(store.publishLog).toEqual([])
  })
})
