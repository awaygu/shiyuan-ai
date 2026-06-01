<template>
  <div class="news-detail">
    <template v-if="news">
      <div class="detail-top">
        <div class="detail-title-row">
          <h2 class="detail-title">{{ news.title }}</h2>
          <el-button text size="small" @click="store.closeDetail()" title="关闭详情">
            <el-icon :size="18"><Close /></el-icon>
          </el-button>
        </div>
        <div class="detail-meta">
          <el-tag size="small" type="info" effect="plain">{{ SOURCE_LABELS[news.source] ?? news.source }}</el-tag>
          <span class="detail-time">{{ formatTime(news.published_at) }}</span>
          <div class="detail-actions">
            <el-button
              :type="isSelected ? 'success' : 'primary'"
              size="small"
              @click="toggleSelect"
            >
              <el-icon><Select /></el-icon>
              {{ isSelected ? '已选中' : '选中解读' }}
            </el-button>
            <el-button v-if="news.url" size="small" @click="openOriginal">
              <el-icon><Link /></el-icon> 新窗口打开
            </el-button>
          </div>
        </div>
        <div v-if="news.summary && news.summary !== news.title" class="detail-summary">
          <el-icon><InfoFilled /></el-icon>
          <span>{{ news.summary }}</span>
        </div>
      </div>

      <div v-if="news.url" class="detail-iframe-wrap">
        <div v-if="iframeLoading" class="iframe-loading">
          <el-icon class="is-loading" :size="24"><Loading /></el-icon>
          <span>正在加载原文...</span>
          <template v-if="iframeSlow">
            <span class="slow-hint">加载较慢，可</span>
            <el-button type="primary" size="small" link @click="openOriginal">新窗口打开</el-button>
          </template>
        </div>
        <div v-if="iframeError" class="iframe-fallback">
          <el-icon :size="48" color="#e6a23c"><Warning /></el-icon>
          <p class="fallback-hint">该网站不允许嵌入显示</p>
          <el-button type="primary" @click="openOriginal">
            <el-icon><Link /></el-icon> 在新窗口中打开
          </el-button>
        </div>
        <iframe
          v-show="!iframeError"
          ref="iframeRef"
          :src="news.url"
          class="detail-iframe"
          sandbox="allow-same-origin allow-scripts allow-popups allow-forms"
          allow="autoplay; fullscreen"
          loading="lazy"
          @load="onIframeLoad"
          @error="onIframeError"
        />
      </div>
      <div v-else class="detail-no-url">
        <el-empty description="暂无原文链接" />
      </div>
    </template>

    <div v-else class="detail-placeholder">
      <el-icon :size="48" color="#dcdfe6"><Document /></el-icon>
      <p>点击左侧新闻查看详情</p>
      <p class="hint">选中的新闻可在右侧进行AI解读或生成文章</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useNewsStore } from '@/stores'
import { SOURCE_LABELS } from '@/types'

const store = useNewsStore()
const news = computed(() => store.currentDetailNews)

const iframeRef = ref<HTMLIFrameElement | null>(null)
const iframeLoading = ref(false)
const iframeError = ref(false)
const iframeSlow = ref(false)
let slowTimer = 0

watch(news, (n) => {
  iframeLoading.value = !!n?.url
  iframeError.value = false
  iframeSlow.value = false
  clearTimeout(slowTimer)
  if (n?.url) {
    slowTimer = window.setTimeout(() => { iframeSlow.value = true }, 10000)
  }
}, { immediate: true })

function onIframeLoad() {
  iframeLoading.value = false
  iframeError.value = false
  iframeSlow.value = false
  clearTimeout(slowTimer)
}

function onIframeError() {
  iframeLoading.value = false
  iframeError.value = true
  iframeSlow.value = false
  clearTimeout(slowTimer)
}

const isSelected = computed(() =>
  news.value ? store.selectedNewsIds.includes(news.value.news_id) : false
)

function toggleSelect() {
  if (news.value) {
    store.toggleSelect(news.value.news_id)
  }
}

function openOriginal() {
  if (news.value?.url) {
    window.open(news.value.url, '_blank')
  }
}

function formatTime(iso: string): string {
  const d = new Date(iso)
  return d.toLocaleString('zh-CN', {
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit',
  })
}
</script>

<style scoped>
.news-detail {
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.detail-top {
  flex-shrink: 0;
}

.detail-title-row {
  display: flex;
  align-items: flex-start;
  gap: 8px;
}

.detail-title {
  flex: 1;
  margin: 0;
  font-size: 18px;
  line-height: 1.4;
}

.detail-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 8px;
}

.detail-time {
  font-size: 13px;
  color: #909399;
}

.detail-actions {
  margin-left: auto;
  display: flex;
  gap: 6px;
}

.detail-summary {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  margin-top: 10px;
  padding: 10px 14px;
  background: #f5f7fa;
  border-radius: 8px;
  font-size: 14px;
  color: #606266;
  line-height: 1.6;
}

.detail-summary .el-icon {
  margin-top: 2px;
  flex-shrink: 0;
  color: #409eff;
}

.detail-iframe-wrap {
  flex: 1;
  border: 1px solid #e4e7ed;
  border-radius: 8px;
  overflow: hidden;
  margin-top: 12px;
  min-height: 0;
  display: flex;
  flex-direction: column;
  position: relative;
}

.detail-iframe {
  width: 100%;
  height: 100%;
  border: none;
  flex: 1;
}

.iframe-loading {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  background: #fff;
  z-index: 1;
  color: #909399;
  font-size: 14px;
  flex-wrap: wrap;
}

.slow-hint {
  color: #e6a23c;
  font-size: 13px;
}

.iframe-fallback {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 16px;
  background: #fafbfc;
}

.fallback-hint {
  font-size: 14px;
  color: #909399;
  margin: 0;
}

.detail-no-url {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-top: 12px;
}

.detail-placeholder {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: #c0c4cc;
}

.detail-placeholder p {
  font-size: 14px;
  margin: 0;
}

.detail-placeholder .hint {
  font-size: 12px;
  color: #dcdfe6;
}
</style>
