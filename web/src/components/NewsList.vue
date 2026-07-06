<template>
  <div class="news-list">
    <div class="panel-header">
      <h2>
        <el-icon :size="20"><Collection /></el-icon> 新闻列表
      </h2>
      <div class="header-actions">
        <el-button
          size="small"
          :icon="Refresh"
          :loading="store.loading"
          :disabled="store.loading"
          circle
          @click="onRefresh"
          title="刷新当前来源"
        />
        <el-button size="small" circle @click="emit('toggle-keywords')" title="关键词过滤设置">
          <el-icon><Setting /></el-icon>
        </el-button>
        <el-select
          v-model="sourceFilter"
          placeholder="全部来源"
          size="small"
          style="width: 150px"
          @change="onSourceChange"
        >
          <el-option
            v-for="(label, key) in ALL_SOURCE_OPTIONS"
            :key="key"
            :label="label"
            :value="key"
          />
        </el-select>
      </div>
    </div>

    <el-divider style="margin: 8px 0" />

    <div v-if="store.loading && store.newsItems.length === 0" class="loading-wrap">
      <el-skeleton :rows="6" animated />
    </div>

    <div v-else-if="store.newsItems.length === 0" class="empty-state">
      <el-empty description="暂无新闻" />
    </div>

    <div v-else class="news-scroll">
      <div
        v-for="item in store.newsItems"
        :key="item.news_id"
        class="news-card"
        :class="{ selected: store.selectedNewsIds.includes(item.news_id) }"
      >
        <div class="card-header">
          <el-checkbox
            :model-value="store.selectedNewsIds.includes(item.news_id)"
            @change="() => store.toggleSelect(item.news_id)"
            @click.stop
            size="small"
          />
          <div class="card-clickable" @click="openDetail(item)">
            <div class="card-title">
              <el-tag
                v-if="isVideo(item)"
                size="small"
                type="danger"
                effect="dark"
                class="video-badge"
              >
                <el-icon><VideoCamera /></el-icon>
              </el-tag>
              {{ item.title }}
            </div>
            <div class="card-summary">{{ item.summary }}</div>
            <div class="card-time">{{ formatTime(item.published_at) }}</div>
          </div>
        </div>
      </div>

      <div v-if="store.loadingMore" class="loading-more">
        <el-icon class="is-loading"><Loading /></el-icon>
        <span>正在获取最新数据...</span>
      </div>
      <div v-else class="load-more-hint">下拉到底自动刷新最新数据</div>
      <div ref="sentinelRef" class="scroll-sentinel"></div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { Refresh, Loading, VideoCamera, Setting, Collection } from '@element-plus/icons-vue'
import { useNewsStore } from '@/stores'
import { SOURCE_LABELS, VIDEO_SOURCES } from '@/types'
import type { NewsItem } from '@/types'

const store = useNewsStore()
const emit = defineEmits<{ 'toggle-keywords': [] }>()
const sourceFilter = ref<string>('cls-telegraph')

const sentinelRef = ref<HTMLElement | null>(null)
let observer: IntersectionObserver | null = null

const ALL_SOURCE_OPTIONS: Record<string, string> = { ...SOURCE_LABELS }

function onSourceChange(val: string) {
  store.loadNews(val)
}

function openDetail(item: NewsItem) {
  store.viewDetail(item)
}

function isVideo(item: NewsItem): boolean {
  const mediaType = item.extra?.media_type
  if (mediaType === 'video') return true
  return VIDEO_SOURCES.has(item.source)
}

async function onRefresh() {
  await store.refreshCurrentSource()
}

function setupObserver() {
  if (observer) observer.disconnect()
  observer = new IntersectionObserver(
    entries => {
      if (entries[0].isIntersecting && !store.loadingMore && !store.loading) {
        store.loadMoreNews()
      }
    },
    { rootMargin: '200px' }
  )
  if (sentinelRef.value) {
    observer.observe(sentinelRef.value)
  }
}

function formatTime(iso: string): string {
  const d = new Date(iso)
  return d.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

onMounted(async () => {
  await store.loadNews('cls-telegraph')
  nextTick(() => setupObserver())
})

onBeforeUnmount(() => {
  if (observer) observer.disconnect()
})
</script>

<style scoped>
.news-list {
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 4px;
}

.panel-header h2 {
  margin: 0;
  font-size: 18px;
  display: flex;
  align-items: center;
  gap: 6px;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 6px;
}

.loading-wrap {
  padding: 16px;
}

.empty-state {
  padding: 40px 0;
}

.news-scroll {
  flex: 1;
  overflow-y: auto;
  padding-right: 4px;
}

.news-card {
  padding: 8px;
  margin-bottom: 6px;
  border-radius: 8px;
  border: 1px solid #ebeef5;
  transition: all 0.2s;
}

.news-card.selected {
  border-color: #409eff;
  background: #ecf5ff;
}

.card-header {
  display: flex;
  gap: 8px;
  align-items: flex-start;
}

.card-header .el-checkbox {
  margin-top: 3px;
}

.card-clickable {
  flex: 1;
  cursor: pointer;
  border-radius: 6px;
  transition: background 0.15s;
}

.card-clickable:hover {
  background: #f5f7fa;
}

.news-card.selected .card-clickable:hover {
  background: #d9ecff;
}

.card-top {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}

.card-category {
  font-size: 12px;
  color: #909399;
}

.card-title {
  font-weight: 600;
  font-size: 14px;
  line-height: 1.4;
  margin-bottom: 4px;
  display: flex;
  align-items: center;
  gap: 4px;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.video-badge {
  flex-shrink: 0;
  padding: 0 4px;
  height: 18px;
  line-height: 18px;
}

.video-badge .el-icon {
  font-size: 12px;
}

.card-summary {
  font-size: 12px;
  color: #606266;
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  margin-bottom: 4px;
}

.card-time {
  font-size: 11px;
  color: #c0c4cc;
}

.loading-more {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 12px 0;
  color: #909399;
  font-size: 13px;
}

.load-more-hint {
  text-align: center;
  padding: 12px 0;
  color: #c0c4cc;
  font-size: 12px;
}

.scroll-sentinel {
  height: 1px;
}
</style>
