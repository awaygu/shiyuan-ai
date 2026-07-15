import { defineStore } from 'pinia'
import { ref } from 'vue'

/** Agent 浮窗的 UI 状态（停靠方向、宽度），与业务数据解耦。 */
export const useAgentUiStore = defineStore('agentUi', () => {
  const agentDockedRight = ref(false)
  const agentPanelWidth = ref(440)

  return {
    agentDockedRight,
    agentPanelWidth,
  }
})
