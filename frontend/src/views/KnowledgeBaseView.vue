<template>
  <div class="kb-container">
    <div class="kb-header">
      <div class="header-left">
        <el-button text @click="$router.push('/')" class="back-btn">
          <el-icon><ArrowLeft /></el-icon> 首页
        </el-button>
        <div class="header-title">
          <span class="title-icon">📚</span>
          <span class="title-text">{{ store.currentKB?.name || '知识库' }}</span>
        </div>
      </div>
      <div class="header-right">
        <el-popconfirm
          title="确定清空当前会话记录？"
          confirm-button-text="清空"
          cancel-button-text="取消"
          @confirm="onClearConv"
        >
          <template #reference>
            <button class="header-action-btn" title="清空会话">
              <el-icon><Delete /></el-icon>
              <span>清空会话</span>
            </button>
          </template>
        </el-popconfirm>
        <button class="toggle-sidebar-btn" :class="{ active: showSidebar }" @click="showSidebar = !showSidebar">
          <el-icon><FolderOpened /></el-icon>
        </button>
      </div>
    </div>

    <div class="kb-body">
      <transition name="slide">
        <div v-if="showSidebar" class="kb-sidebar">
          <KBFilePanel :kb-id="kbId" />
        </div>
      </transition>

      <div class="kb-main">
        <KBChatPanel ref="chatPanelRef" :kb-id="kbId" />
      </div>

      <div class="kb-actions">
        <KBActionPanel :kb-id="kbId" @generate="onGenerate" />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import KBFilePanel from '@/components/KBFilePanel.vue'
import KBChatPanel from '@/components/KBChatPanel.vue'
import KBActionPanel from '@/components/KBActionPanel.vue'
import { useNewsStore } from '@/stores'
import type { StyleType } from '@/types'
import { FolderOpened, Delete } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'

const props = defineProps<{ kbId: string }>()
const store = useNewsStore()
const chatPanelRef = ref<InstanceType<typeof KBChatPanel> | null>(null)
const showSidebar = ref(true)

function onGenerate(style: StyleType) {
  chatPanelRef.value?.generateArticle(style)
}

async function onClearConv() {
  const convId = store.currentConvId
  if (!convId) return
  await store.removeConv(convId)
  chatPanelRef.value?.clearMessages()
  await ensureConv()
  ElMessage.success('会话已清空')
}

async function ensureConv() {
  if (store.kbConversations.length > 0) {
    const conv = store.kbConversations[0]
    store.currentConvId = conv.conv_id
    return
  }
  const conv = await store.createConv()
  store.currentConvId = conv.conv_id
}

async function initKB(kbId: string) {
  await store.loadCurrentKB(kbId)
  await ensureConv()
  if (store.currentConvId) {
    const messages = await store.loadConvMessages(store.currentConvId)
    chatPanelRef.value?.loadHistory(messages)
  } else {
    chatPanelRef.value?.clearMessages()
  }
}

onMounted(() => {
  initKB(props.kbId)
})

watch(() => props.kbId, (newId) => {
  if (newId) {
    initKB(newId)
  }
})
</script>

<style scoped>
.kb-container {
  height: 100vh;
  display: flex;
  flex-direction: column;
  background: #f5f6fa;
}

.kb-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: #fff;
  border-bottom: 1px solid #eef0f5;
  padding: 0 16px;
  height: 52px;
  flex-shrink: 0;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 6px;
}

.back-btn {
  font-size: 14px;
  color: #6366f1;
}

.header-title {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-left: 4px;
}

.title-icon {
  font-size: 18px;
}

.title-text {
  font-size: 15px;
  font-weight: 600;
  color: #1e293b;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 10px;
}

.header-action-btn {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  border-radius: 6px;
  border: 1px solid #e2e8f0;
  background: #fff;
  cursor: pointer;
  font-size: 13px;
  color: #64748b;
  transition: all 0.15s;
}

.header-action-btn:hover {
  border-color: #fca5a5;
  color: #ef4444;
  background: #fef2f2;
}

.toggle-sidebar-btn {
  width: 32px;
  height: 32px;
  border-radius: 8px;
  border: 1px solid #e2e8f0;
  background: #fff;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #94a3b8;
  transition: all 0.2s;
}

.toggle-sidebar-btn:hover,
.toggle-sidebar-btn.active {
  border-color: #a5b4fc;
  color: #6366f1;
  background: #eef2ff;
}

.kb-body {
  flex: 1;
  display: flex;
  overflow: hidden;
}

.kb-sidebar {
  width: 320px;
  flex: none;
  background: #fff;
  border-right: 1px solid #eef0f5;
  overflow: hidden;
}

.slide-enter-active,
.slide-leave-active {
  transition: width 0.25s ease, opacity 0.2s ease;
}

.slide-enter-from,
.slide-leave-to {
  width: 0;
  opacity: 0;
}

.kb-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}

.kb-actions {
  width: 280px;
  flex: none;
  background: #fff;
  border-left: 1px solid #eef0f5;
  overflow: hidden;
}
</style>
