<template>
  <el-container class="app-container">
    <el-header class="app-header" height="52px">
      <div class="header-left">
        <el-button text @click="$router.push('/')" class="back-btn">
          <el-icon><ArrowLeft /></el-icon> 首页
        </el-button>
        <span class="title">📰 智析 · 新闻解读</span>
      </div>
      <div class="header-right">
        <el-tag type="success" effect="dark" size="small">🟢 运行中</el-tag>
      </div>
    </el-header>

    <el-main class="app-main" :style="store.agentDockedRight ? { paddingRight: store.agentPanelWidth + 'px' } : {}">
      <div class="two-columns" ref="columnsRef">
        <div
          class="column column-left"
          :style="{ width: leftWidth + 'px', flex: 'none' }"
        >
          <NewsList />
        </div>

        <div
          class="resize-handle"
          @mousedown="(e) => startResize(e)"
        ></div>

        <div class="column column-center">
          <NewsDetail />
        </div>
      </div>
    </el-main>

    <FloatingAgent />
  </el-container>
</template>

<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount } from 'vue'
import NewsList from '@/components/NewsList.vue'
import NewsDetail from '@/components/NewsDetail.vue'
import FloatingAgent from '@/components/FloatingAgent.vue'
import { useNewsStore } from '@/stores'

const store = useNewsStore()

const columnsRef = ref<HTMLElement | null>(null)
const leftWidth = ref(360)
const MIN_LEFT = 260

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

onMounted(() => {
  document.addEventListener('mousemove', onMouseMove)
  document.addEventListener('mouseup', onMouseUp)
})

onBeforeUnmount(() => {
  document.removeEventListener('mousemove', onMouseMove)
  document.removeEventListener('mouseup', onMouseUp)
})

onMounted(() => {
  document.addEventListener('mousemove', onMouseMove)
  document.addEventListener('mouseup', onMouseUp)
})

onBeforeUnmount(() => {
  document.removeEventListener('mousemove', onMouseMove)
  document.removeEventListener('mouseup', onMouseUp)
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

.two-columns .resize-handle {
  width: 12px;
  flex-shrink: 0;
  cursor: col-resize;
}
</style>
