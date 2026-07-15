import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { KeywordGroup } from '@/api'
import { fetchKeywordStatus, updateKeywordGroups as apiUpdateKeywords } from '@/api'

export const useKeywordStore = defineStore('keyword', () => {
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

  return {
    kwGroups,
    kwLoading,
    loadKeywords,
    saveKeywords,
  }
})
