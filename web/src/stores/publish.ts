import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { PublishRecord } from '@/types'
import { publishArticle, fetchPublishLog } from '@/api'

export const usePublishStore = defineStore('publish', () => {
  const publishLog = ref<PublishRecord[]>([])

  async function publish(
    articleId: string,
    platform: string,
    imageOptions?: { generate_cover?: boolean; generate_inline_images?: boolean }
  ): Promise<PublishRecord & { need_login?: boolean }> {
    // 任务流由调用方在发布后通过 useTaskStore().notifyTaskStarted() 触发，
    // 避免跨 store 调用耦合。
    return await publishArticle(articleId, platform, imageOptions)
  }

  async function loadPublishLog() {
    publishLog.value = await fetchPublishLog()
  }

  return {
    publishLog,
    publish,
    loadPublishLog,
  }
})
