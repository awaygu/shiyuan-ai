import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { AsyncTask } from '@/types'
import { fetchTasks, clearDoneTasks, streamTaskUpdates } from '@/api'

export const useTaskStore = defineStore('task', () => {
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

  /** 发布/异步任务触发后统一收口：开启任务流、展开面板、刷新任务列表。 */
  async function notifyTaskStarted() {
    startTaskStream()
    showTaskPanel.value = true
    await loadTasks()
  }

  const runningTaskCount = computed(
    () => tasks.value.filter(t => t.status === 'pending' || t.status === 'running').length
  )

  return {
    tasks,
    showTaskPanel,
    loadTasks,
    startTaskStream,
    stopTaskStream,
    clearDoneTasksAction,
    toggleTaskPanel,
    notifyTaskStarted,
    runningTaskCount,
  }
})
