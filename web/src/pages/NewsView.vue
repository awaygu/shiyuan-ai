<template>
  <el-container class="app-container">
    <el-header class="app-header" height="52px">
      <div class="header-left">
        <el-button text @click="$router.push('/')" class="back-btn">
          <el-icon><ArrowLeft /></el-icon> 首页
        </el-button>
        <span class="title">📰 识渊 · 新闻解读</span>
      </div>
      <div class="header-right">
        <el-badge :value="store.runningTaskCount" :hidden="store.runningTaskCount === 0" :max="9">
          <el-button text @click="store.toggleTaskPanel" class="task-btn">
            <el-icon><List /></el-icon> 任务
          </el-button>
        </el-badge>
        <el-tag type="success" effect="dark" size="small">🟢 运行中</el-tag>
      </div>
    </el-header>

    <el-main class="app-main">
      <div class="two-columns" ref="columnsRef">
        <div
          class="column column-left"
          :style="{ width: leftWidth + 'px', flex: 'none' }"
        >
          <NewsList @toggle-keywords="showKeywords = !showKeywords" />
        </div>

        <div
          class="resize-handle"
          @mousedown="(e) => startResize(e)"
        ></div>

        <div class="column column-center">
          <NewsDetail />
        </div>

        <div
          v-if="showKeywords"
          class="resize-handle"
          @mousedown="(e) => startKwResize(e)"
        ></div>

        <transition name="slide-right">
          <div v-if="showKeywords" class="column column-kw" :style="{ width: kwWidth + 'px', flex: 'none' }">
            <KeywordSettings @close="showKeywords = false" />
          </div>
        </transition>

        <transition name="slide-right">
          <div v-if="store.showTaskPanel" class="column column-task" :style="{ width: taskWidth + 'px', flex: 'none' }">
            <TaskPanel @close="store.showTaskPanel = false" />
          </div>
        </transition>
      </div>
    </el-main>
  </el-container>
</template>

<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount } from 'vue'
import NewsList from '@/components/NewsList.vue'
import NewsDetail from '@/components/NewsDetail.vue'
import KeywordSettings from '@/components/KeywordSettings.vue'
import TaskPanel from '@/components/TaskPanel.vue'
import { useNewsStore } from '@/stores'

const store = useNewsStore()

const columnsRef = ref<HTMLElement | null>(null)
const leftWidth = ref(360)
const MIN_LEFT = 260

const showKeywords = ref(false)
const kwWidth = ref(320)
const taskWidth = ref(340)

let resizing = false
let startX = 0
let startLeftW = 0

function startResize(e: MouseEvent) {
  e.preventDefault()
  resizing = true
  startX = e.clientX
  startLeftW = leftWidth.value
  document.body.style.cursor = 'col-resize'
  document.body.style.userSelect = 'none'
}

function onMouseMove(e: MouseEvent) {
  if (!resizing) return
  const dx = e.clientX - startX
  const newLeft = startLeftW + dx
  if (newLeft >= MIN_LEFT) {
    leftWidth.value = newLeft
  }
}

function onMouseUp() {
  resizing = false
  document.body.style.cursor = ''
  document.body.style.userSelect = ''
}

let kwResizing = false
let kwStartX = 0
let kwStartW = 0

function startKwResize(e: MouseEvent) {
  e.preventDefault()
  kwResizing = true
  kwStartX = e.clientX
  kwStartW = kwWidth.value
  document.body.style.cursor = 'col-resize'
  document.body.style.userSelect = 'none'
}

function onKwMouseMove(e: MouseEvent) {
  if (!kwResizing) return
  const dx = kwStartX - e.clientX
  kwWidth.value = Math.max(240, Math.min(500, kwStartW + dx))
}

function onKwMouseUp() {
  if (!kwResizing) return
  kwResizing = false
  document.body.style.cursor = ''
  document.body.style.userSelect = ''
}

onMounted(() => {
  document.addEventListener('mousemove', onMouseMove)
  document.addEventListener('mouseup', onMouseUp)
  document.addEventListener('mousemove', onKwMouseMove)
  document.addEventListener('mouseup', onKwMouseUp)
})

onBeforeUnmount(() => {
  document.removeEventListener('mousemove', onMouseMove)
  document.removeEventListener('mouseup', onMouseUp)
  document.removeEventListener('mousemove', onKwMouseMove)
  document.removeEventListener('mouseup', onKwMouseUp)
})
</script>

<style scoped>
.app-container {
  height: 100vh;
  display: flex;
  flex-direction: column;
}

.app-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: #fff;
  border-bottom: 1px solid #e4e7ed;
  padding: 0 20px;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 8px;
}

.back-btn {
  font-size: 14px;
  color: #6366f1;
}

.title {
  font-size: 16px;
  font-weight: 600;
}

.task-btn {
  font-size: 14px;
  color: #6366f1;
}

.app-main {
  flex: 1;
  padding: 12px;
  overflow: hidden;
}

.two-columns {
  display: flex;
  height: 100%;
}

.column {
  background: #fff;
  border-radius: 8px;
  padding: 16px;
  overflow: hidden;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.06);
  flex-shrink: 0;
}

.column-center {
  flex: 1;
  min-width: 0;
}

.column-kw {
  background: #fff;
  border-radius: 8px;
  padding: 0;
  overflow: hidden;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.06);
  margin-left: 4px;
}

.column-task {
  background: #fff;
  border-radius: 8px;
  padding: 0;
  overflow: hidden;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.06);
  margin-left: 4px;
}

.two-columns .resize-handle {
  width: 12px;
  flex-shrink: 0;
  cursor: col-resize;
}

.slide-right-enter-active,
.slide-right-leave-active {
  transition: width 0.25s ease, opacity 0.2s ease;
}

.slide-right-enter-from,
.slide-right-leave-to {
  width: 0;
  opacity: 0;
}
</style>
