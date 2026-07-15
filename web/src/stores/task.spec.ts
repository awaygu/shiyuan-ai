import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useTaskStore } from './task'

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

import { fetchTasks, clearDoneTasks, streamTaskUpdates } from '@/api'
describe('useTaskStore (tasks)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('has correct initial state', () => {
    const store = useTaskStore()
    expect(store.tasks).toEqual([])
    expect(store.showTaskPanel).toBe(false)
    expect(store.runningTaskCount).toBe(0)
  })

  it('loadTasks populates tasks', async () => {
    ;(fetchTasks as any).mockResolvedValue([
      { task_id: 't1', status: 'running', platform: 'wechat_mp', title: 'P' } as any,
    ])
    const store = useTaskStore()
    await store.loadTasks()
    expect(store.tasks).toHaveLength(1)
    expect(store.tasks[0].task_id).toBe('t1')
  })

  it('runningTaskCount counts pending+running only', async () => {
    ;(fetchTasks as any).mockResolvedValue([
      { task_id: 't1', status: 'pending', platform: 'p', title: 'a' } as any,
      { task_id: 't2', status: 'running', platform: 'p', title: 'b' } as any,
      { task_id: 't3', status: 'completed', platform: 'p', title: 'c' } as any,
      { task_id: 't4', status: 'failed', platform: 'p', title: 'd' } as any,
    ])
    const store = useTaskStore()
    await store.loadTasks()
    expect(store.runningTaskCount).toBe(2)
  })

  it('startTaskStream wires streamTaskUpdates once and is idempotent', () => {
    ;(streamTaskUpdates as any).mockImplementation((callbacks: any) => {
      // simulate an incoming update
      callbacks.onTaskUpdate({ task_id: 't1', status: 'running', platform: 'p', title: 'x' } as any)
      return () => {}
    })
    const store = useTaskStore()
    store.startTaskStream()
    store.startTaskStream()
    expect(streamTaskUpdates).toHaveBeenCalledTimes(1)
    expect(store.tasks).toHaveLength(1)
    expect(store.tasks[0].task_id).toBe('t1')
  })

  it('startTaskStream upserts: existing task updated, new task prepended', () => {
    ;(streamTaskUpdates as any).mockImplementation((callbacks: any) => {
      callbacks.onTaskUpdate({ task_id: 't1', status: 'running', platform: 'p', title: 'x' } as any)
      // second update on same id → update in place
      callbacks.onTaskUpdate({
        task_id: 't1',
        status: 'completed',
        platform: 'p',
        title: 'x',
      } as any)
      // new task → prepend
      callbacks.onTaskUpdate({ task_id: 't2', status: 'running', platform: 'p', title: 'y' } as any)
      return () => {}
    })
    const store = useTaskStore()
    store.startTaskStream()
    expect(store.tasks).toHaveLength(2)
    expect(store.tasks[0].task_id).toBe('t2')
    expect(store.tasks[1].task_id).toBe('t1')
    expect(store.tasks[1].status).toBe('completed')
  })

  it('stopTaskStream calls the unsub and is safe when not started', () => {
    const unsub = vi.fn()
    ;(streamTaskUpdates as any).mockReturnValue(unsub)
    const store = useTaskStore()
    store.startTaskStream()
    store.stopTaskStream()
    expect(unsub).toHaveBeenCalledTimes(1)
    // calling again should be a no-op
    store.stopTaskStream()
    expect(unsub).toHaveBeenCalledTimes(1)
  })

  it('toggleTaskPanel opens (starting stream) and closes', () => {
    ;(streamTaskUpdates as any).mockReturnValue(vi.fn())
    const store = useTaskStore()
    expect(store.showTaskPanel).toBe(false)
    store.toggleTaskPanel()
    expect(store.showTaskPanel).toBe(true)
    expect(streamTaskUpdates).toHaveBeenCalledTimes(1)
    store.toggleTaskPanel()
    expect(store.showTaskPanel).toBe(false)
  })

  it('clearDoneTasksAction calls clearDoneTasks and replaces state', async () => {
    ;(clearDoneTasks as any).mockResolvedValue([
      { task_id: 't1', status: 'running', platform: 'p', title: 'a' } as any,
    ])
    const store = useTaskStore()
    await store.clearDoneTasksAction()
    expect(clearDoneTasks).toHaveBeenCalledTimes(1)
    expect(store.tasks).toHaveLength(1)
  })

  it('notifyTaskStarted starts stream, shows panel, and loads tasks', async () => {
    ;(streamTaskUpdates as any).mockReturnValue(vi.fn())
    ;(fetchTasks as any).mockResolvedValue([
      { task_id: 't1', status: 'pending', platform: 'p', title: 'a' } as any,
    ])
    const store = useTaskStore()
    await store.notifyTaskStarted()
    expect(streamTaskUpdates).toHaveBeenCalledTimes(1)
    expect(store.showTaskPanel).toBe(true)
    expect(fetchTasks).toHaveBeenCalledTimes(1)
    expect(store.tasks).toHaveLength(1)
  })

  it('notifyTaskStarted is idempotent on the stream', async () => {
    ;(streamTaskUpdates as any).mockReturnValue(vi.fn())
    ;(fetchTasks as any).mockResolvedValue([])
    const store = useTaskStore()
    await store.notifyTaskStarted()
    await store.notifyTaskStarted()
    expect(streamTaskUpdates).toHaveBeenCalledTimes(1)
  })
})
