<template>
  <div class="kb-container">
    <div class="kb-header">
      <el-button text @click="$router.push('/')" class="back-btn">
        <el-icon><ArrowLeft /></el-icon> 首页
      </el-button>
      <div class="header-info" v-if="store.currentKB">
        <span class="title-icon">{{
          getKbIcon(store.currentKB.name, store.currentKB.description)
        }}</span>
        <template v-if="editingTitle">
          <el-input
            ref="titleInputRef"
            v-model="editName"
            size="small"
            class="title-input"
            @blur="onSaveTitle"
            @keyup.enter="onSaveTitle"
            @keyup.escape="editingTitle = false"
          />
        </template>
        <template v-else>
          <span class="title-text" @dblclick="startEditTitle">{{ store.currentKB.name }}</span>
          <el-icon class="edit-hint" @click="startEditTitle"><Edit /></el-icon>
        </template>
        <span v-if="!editingTitle" class="header-sep">·</span>
        <template v-if="editingDesc">
          <el-input
            ref="descInputRef"
            v-model="editDesc"
            size="small"
            class="desc-input"
            @blur="onSaveDesc"
            @keyup.enter="onSaveDesc"
            @keyup.escape="editingDesc = false"
          />
        </template>
        <template v-else>
          <span class="desc-text" @dblclick="startEditDesc">{{
            store.currentKB.description || '添加描述'
          }}</span>
          <el-icon class="edit-hint" @click="startEditDesc"><Edit /></el-icon>
        </template>
      </div>
      <div class="header-right">
        <el-badge :value="store.runningTaskCount" :hidden="store.runningTaskCount === 0" :max="9">
          <el-button text @click="store.toggleTaskPanel" class="task-btn">
            <el-icon><List /></el-icon> 任务
          </el-button>
        </el-badge>
      </div>
    </div>

    <div class="kb-body">
      <transition name="slide">
        <div v-if="showSidebar" class="kb-sidebar" :style="{ width: sidebarWidth + 'px' }">
          <KBFilePanel :kb-id="kbId" @collapse="showSidebar = false" />
        </div>
      </transition>
      <div
        v-if="showSidebar"
        class="resize-handle resize-handle-left"
        @mousedown="startResize('left', $event)"
      ></div>

      <div class="kb-main">
        <button
          v-if="!showSidebar"
          class="expand-sidebar-btn"
          @click="showSidebar = true"
          title="展开文件管理"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
            <path
              d="M9 5L16 12L9 19"
              stroke="currentColor"
              stroke-width="2"
              stroke-linecap="round"
              stroke-linejoin="round"
            />
          </svg>
        </button>
        <KBChatPanel
          ref="chatPanelRef"
          :kb-id="kbId"
          @clear-conv="onClearConv"
          @generating-change="kbGenerating = $event"
        />
      </div>

      <el-dialog
        v-model="genDialogVisible"
        width="80%"
        top="5vh"
        :close-on-click-modal="false"
        :destroy-on-close="false"
        :show-close="false"
        class="gen-dialog"
        @open="onGenDialogOpen"
        @close="onGenDialogClose"
      >
        <KBGeneratePanel
          ref="generatePanelRef"
          :kb-id="kbId"
          @generating-change="kbGenerating = $event"
          @close="genDialogVisible = false"
        />
      </el-dialog>

      <div
        class="resize-handle resize-handle-right"
        v-if="!actionsCollapsed"
        @mousedown="startResize('right', $event)"
      ></div>
      <div
        class="kb-actions"
        :style="{
          width: (actionsCollapsed ? COLLAPSED_ACTIONS_WIDTH : actionsWidth) + 'px',
          overflow: actionsCollapsed ? 'visible' : 'hidden',
        }"
      >
        <KBActionPanel
          :kb-id="kbId"
          :generating="kbGenerating"
          :collapsed="actionsCollapsed"
          @generate="onGenerate"
          @toggle-collapse="actionsCollapsed = !actionsCollapsed"
        />
      </div>

      <transition name="slide">
        <div v-if="store.showTaskPanel" class="kb-task-panel" :style="{ width: taskWidth + 'px' }">
          <TaskPanel @close="store.showTaskPanel = false" />
        </div>
      </transition>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref, watch, nextTick, onUnmounted } from 'vue'
import KBFilePanel from '@/components/KBFilePanel.vue'
import KBChatPanel from '@/components/KBChatPanel.vue'
import KBGeneratePanel from '@/components/KBGeneratePanel.vue'
import KBActionPanel from '@/components/KBActionPanel.vue'
import TaskPanel from '@/components/TaskPanel.vue'
import { useNewsStore } from '@/stores'
import type { StyleType } from '@/types'
import { getKbIcon } from '@/types'
import { ElMessage } from 'element-plus'
import type { InputInstance } from 'element-plus'
import { Edit } from '@element-plus/icons-vue'

const props = defineProps<{ kbId: string }>()
const store = useNewsStore()
const chatPanelRef = ref<InstanceType<typeof KBChatPanel> | null>(null)
const generatePanelRef = ref<InstanceType<typeof KBGeneratePanel> | null>(null)
const showSidebar = ref(true)
const kbGenerating = ref(false)
const genDialogVisible = ref(false)
const pendingGenStyle = ref<StyleType | null>(null)

const sidebarWidth = ref(450)
const actionsWidth = ref(280)
const actionsCollapsed = ref(false)
const COLLAPSED_ACTIONS_WIDTH = 56
const taskWidth = ref(340)
const resizing = ref<'left' | 'right' | null>(null)
const resizeStartX = ref(0)
const resizeStartWidth = ref(0)

function startResize(side: 'left' | 'right', e: MouseEvent) {
  e.preventDefault()
  resizing.value = side
  resizeStartX.value = e.clientX
  resizeStartWidth.value = side === 'left' ? sidebarWidth.value : actionsWidth.value
  document.body.style.cursor = 'col-resize'
  document.body.style.userSelect = 'none'
}

function onMouseMove(e: MouseEvent) {
  if (!resizing.value) return
  const dx = e.clientX - resizeStartX.value
  if (resizing.value === 'left') {
    sidebarWidth.value = Math.max(200, Math.min(600, resizeStartWidth.value + dx))
  } else {
    actionsWidth.value = Math.max(180, Math.min(500, resizeStartWidth.value - dx))
  }
}

function onMouseUp() {
  if (!resizing.value) return
  resizing.value = null
  document.body.style.cursor = ''
  document.body.style.userSelect = ''
}

onMounted(() => {
  window.addEventListener('mousemove', onMouseMove)
  window.addEventListener('mouseup', onMouseUp)
})

onUnmounted(() => {
  window.removeEventListener('mousemove', onMouseMove)
  window.removeEventListener('mouseup', onMouseUp)
})

const editingTitle = ref(false)
const editingDesc = ref(false)
const editName = ref('')
const editDesc = ref('')
const titleInputRef = ref<InputInstance | null>(null)
const descInputRef = ref<InputInstance | null>(null)

function startEditTitle() {
  editName.value = store.currentKB?.name || ''
  editingTitle.value = true
  nextTick(() => titleInputRef.value?.focus())
}

async function onSaveTitle() {
  const name = editName.value.trim()
  if (!name) {
    editingTitle.value = false
    return
  }
  if (name === store.currentKB?.name) {
    editingTitle.value = false
    return
  }
  try {
    await store.updateKB(props.kbId, { name })
    ElMessage.success('标题已更新')
  } catch (e: any) {
    ElMessage.error(`更新失败：${e.message || '未知错误'}`)
  } finally {
    editingTitle.value = false
  }
}

function startEditDesc() {
  editDesc.value = store.currentKB?.description || ''
  editingDesc.value = true
  nextTick(() => descInputRef.value?.focus())
}

async function onSaveDesc() {
  const desc = editDesc.value.trim()
  if (desc === (store.currentKB?.description || '')) {
    editingDesc.value = false
    return
  }
  try {
    await store.updateKB(props.kbId, { description: desc })
    ElMessage.success('描述已更新')
  } catch (e: any) {
    ElMessage.error(`更新失败：${e.message || '未知错误'}`)
  } finally {
    editingDesc.value = false
  }
}

function onGenerate(style: StyleType) {
  pendingGenStyle.value = style
  genDialogVisible.value = true
}

async function onGenDialogOpen() {
  const s = pendingGenStyle.value
  pendingGenStyle.value = null
  await generatePanelRef.value?.openDialog(s ?? undefined)
}

function onGenDialogClose() {
  // dialog closed — KBChatPanel remains mounted, no action needed
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
  // 排除「生成文章」会话，避免问答区误选到生成会话（两者物理隔离）
  const chatConvs = store.kbConversations.filter(c => (c.title || '') !== '生成文章')
  if (chatConvs.length > 0) {
    const conv = chatConvs[0]
    store.currentConvId = conv.conv_id
    return
  }
  const conv = await store.createConv()
  store.currentConvId = conv?.conv_id || ''
}

async function initKB(kbId: string) {
  await store.loadCurrentKB(kbId)
  await ensureConv()
  await store.ensureGenConv(kbId)
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

watch(
  () => props.kbId,
  newId => {
    if (newId) {
      initKB(newId)
    }
  }
)
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
  background: #fff;
  border-bottom: 1px solid #eef0f5;
  padding: 0 16px;
  height: 52px;
  flex-shrink: 0;
  gap: 4px;
}

.back-btn {
  font-size: 14px;
  color: #6366f1;
}

.header-info {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  overflow: hidden;
}

.title-icon {
  font-size: 20px;
  flex-shrink: 0;
}

.title-text {
  font-size: 15px;
  font-weight: 600;
  color: #1e293b;
  white-space: nowrap;
  cursor: pointer;
}

.title-text:hover {
  color: #4f46e5;
}

.title-input {
  width: 180px;
}

.header-sep {
  color: #cbd5e1;
  font-size: 13px;
  flex-shrink: 0;
}

.desc-text {
  font-size: 13px;
  color: #94a3b8;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  cursor: pointer;
}

.desc-text:hover {
  color: #4f46e5;
}

.desc-input {
  width: 240px;
}

.edit-hint {
  font-size: 12px;
  color: #c0c6d0;
  cursor: pointer;
  flex-shrink: 0;
  transition: color 0.15s;
}

.edit-hint:hover {
  color: #6366f1;
}

.kb-body {
  flex: 1;
  display: flex;
  overflow: hidden;
}

.expand-sidebar-btn {
  position: absolute;
  left: 0;
  top: 50%;
  transform: translateY(-50%);
  width: 24px;
  height: 56px;
  border: 1px solid #e2e8f0;
  border-left: none;
  border-radius: 0 8px 8px 0;
  background: #fff;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #94a3b8;
  transition: all 0.2s;
  z-index: 10;
  box-shadow: 2px 0 8px rgba(0, 0, 0, 0.04);
}

.expand-sidebar-btn:hover {
  color: #6366f1;
  background: #eef2ff;
  border-color: #a5b4fc;
  width: 28px;
}

.kb-sidebar {
  flex: none;
  background: #fff;
  border-right: 1px solid #eef0f5;
  overflow: hidden;
}

.resize-handle {
  width: 5px;
  flex: none;
  cursor: col-resize;
  background: transparent;
  transition: background 0.15s;
  position: relative;
  z-index: 5;
}

.resize-handle:hover,
.resize-handle:active {
  background: #c7d2fe;
}

.slide-enter-active,
.slide-leave-active {
  transition:
    width 0.25s ease,
    opacity 0.2s ease;
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
  position: relative;
}

.kb-actions {
  flex: none;
  background: #fff;
  border-left: 1px solid #eef0f5;
  overflow: hidden;
}

.kb-task-panel {
  flex: none;
  background: #fff;
  border-left: 1px solid #eef0f5;
  overflow: hidden;
}

.header-right {
  margin-left: auto;
  display: flex;
  align-items: center;
}

.task-btn {
  font-size: 14px;
  color: #6366f1;
}

:deep(.gen-dialog) {
  height: 90vh;
  margin-bottom: 0;
  display: flex;
  flex-direction: column;
}
:deep(.gen-dialog .el-dialog__header) {
  display: none;
}
:deep(.gen-dialog .el-dialog__body) {
  flex: 1;
  height: 100%;
  min-height: 0;
  padding: 0;
  overflow: hidden;
}
</style>
