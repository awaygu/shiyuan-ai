<template>
  <div class="generate-panel">
    <div class="generate-controls">
      <div class="style-row">
        <span class="style-label">风格</span>
        <el-radio-group v-model="currentStyle" size="small">
          <el-radio-button value="xiaohongshu">小红书 ✨</el-radio-button>
          <el-radio-button value="wechat_mp">公众号 📰</el-radio-button>
          <el-radio-button value="douyin">抖音 🎬</el-radio-button>
        </el-radio-group>
      </div>

      <el-input
        v-model="articleTitle"
        placeholder="文章标题（可选，留空自动生成）"
        size="default"
        clearable
        :disabled="generating"
      />

      <el-input
        v-model="userPrompt"
        type="textarea"
        :rows="3"
        placeholder="描述你的生成要求，如：重点分析对散户的影响、用通俗语言解释技术原理..."
        :disabled="generating"
        resize="vertical"
      />

      <el-button
        type="primary"
        :disabled="store.selectedNewsIds.length === 0 || generating"
        :loading="generating"
        style="width: 100%"
        @click="generateArticle"
      >
        <el-icon><MagicStick /></el-icon> {{ generating ? '生成中...' : '生成文章' }}
      </el-button>
    </div>

    <div v-if="generatedContent || generating" class="preview-area">
      <el-divider style="margin: 8px 0" />
      <div v-if="submittedPrompt" class="prompt-block">
        <div class="prompt-header" @click="promptExpanded = !promptExpanded">
          <el-icon size="14"><Document /></el-icon>
          <span>提交的 Prompt</span>
          <el-icon size="12" class="prompt-toggle">
            <component :is="promptExpanded ? 'ArrowUp' : 'ArrowDown'" />
          </el-icon>
        </div>
        <div v-if="promptExpanded" class="prompt-body">{{ submittedPrompt }}</div>
      </div>
      <div class="preview-header">
        <span class="preview-title">{{ articleTitle || 'AI 生成结果' }}</span>
        <el-tag v-if="currentStyle" size="small" :type="getStyleTagType(currentStyle)">
          {{ getStyleLabel(currentStyle) }}
        </el-tag>
      </div>
      <div ref="previewRef" class="preview-content">
        <div v-if="generating && !generatedContent" class="loading-hint">
          ⏳ 正在获取原文并生成中...
        </div>
        <div v-html="renderMarkdown(generatedContent)"></div>
        <span v-if="generating" class="streaming-cursor">▊</span>
      </div>
      <div v-if="generatedContent && !generating" class="preview-actions">
        <el-button type="primary" size="small" @click="addToArticles">
          <el-icon><Plus /></el-icon> 添加到文章列表
        </el-button>
      </div>
    </div>

    <div v-if="!generatedContent && !generating" class="empty-hint">选择新闻后点击"生成文章"</div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, nextTick } from 'vue'
import { ElMessage } from 'element-plus'
import { useNewsStore, useArticleStore } from '@/stores'
import { STYLE_LABELS } from '@/types'
import type { StyleType } from '@/types'
import { streamGenerateArticle } from '@/api'
import { renderSafeMarkdown } from '@/utils/markdown'

const store = useNewsStore()
const articleStore = useArticleStore()
const previewRef = ref<HTMLElement | null>(null)
const generating = ref(false)
const articleTitle = ref('')
const userPrompt = ref('')
const generatedContent = ref('')
const generatedArticleId = ref('')
const submittedPrompt = ref('')
const promptExpanded = ref(false)

const currentStyle = computed({
  get: () => store.currentStyle,
  set: (v: any) => {
    store.currentStyle = v
  },
})

function renderMarkdown(text: string): string {
  return renderSafeMarkdown(text)
}

function getStyleLabel(style: string): string {
  return (STYLE_LABELS as any)[style] ?? style
}

function getStyleTagType(style: string): 'warning' | 'primary' | 'danger' | '' {
  if (style === 'xiaohongshu') return 'warning'
  if (style === 'douyin') return 'danger'
  return 'primary'
}

function scrollToBottom() {
  nextTick(() => {
    if (previewRef.value) {
      previewRef.value.scrollTop = previewRef.value.scrollHeight
    }
  })
}

async function generateArticle() {
  if (store.selectedNewsIds.length === 0 || generating.value) return
  generating.value = true
  generatedContent.value = ''
  generatedArticleId.value = `art_stream_${Date.now()}`
  submittedPrompt.value = ''
  promptExpanded.value = false

  streamGenerateArticle(
    store.selectedNewsIds,
    store.currentStyle as StyleType,
    {
      onLoading() {
        scrollToBottom()
      },
      onPrompt(prompt) {
        submittedPrompt.value = prompt
        promptExpanded.value = false
      },
      onLimited(message) {
        generatedContent.value = `ℹ️ ${message}`
        generating.value = false
      },
      onChunk(text) {
        generatedContent.value += text
        scrollToBottom()
      },
      onDone() {
        generating.value = false
      },
      onError(err) {
        generatedContent.value += `\n\n❌ 生成失败：${err}`
        generating.value = false
      },
    },
    articleTitle.value || undefined,
    userPrompt.value.trim() || undefined
  )
}

function addToArticles() {
  if (!generatedContent.value) return
  const article = {
    article_id: generatedArticleId.value,
    title: articleTitle.value || 'AI 生成文章',
    content: generatedContent.value,
    style: store.currentStyle,
    news_ids: store.selectedNewsIds,
  }
  articleStore.addArticle(article)
  ElMessage.success('已添加到文章列表')
}
</script>

<style scoped>
.generate-panel {
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.generate-controls {
  display: flex;
  flex-direction: column;
  gap: 10px;
  flex-shrink: 0;
}

.style-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.style-label {
  font-size: 13px;
  color: #606266;
  white-space: nowrap;
}

.prompt-block {
  margin-bottom: 8px;
  border: 1px solid #e4e7ed;
  border-radius: 6px;
  overflow: hidden;
}

.prompt-header {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px 8px;
  background: #fafbfc;
  font-size: 12px;
  color: #909399;
  cursor: pointer;
  user-select: none;
}

.prompt-header:hover {
  background: #f5f7fa;
}

.prompt-toggle {
  margin-left: auto;
}

.prompt-body {
  padding: 8px;
  font-size: 12px;
  color: #606266;
  background: #fafbfc;
  border-top: 1px solid #e4e7ed;
  max-height: 200px;
  overflow-y: auto;
  white-space: pre-wrap;
  word-break: break-all;
  font-family: 'Consolas', 'Monaco', monospace;
  line-height: 1.5;
}

.preview-area {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  min-height: 0;
}

.preview-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}

.preview-title {
  font-weight: 600;
  font-size: 15px;
}

.preview-content {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
  background: #fafbfc;
  border-radius: 8px;
  border: 1px solid #ebeef5;
  font-size: 14px;
  line-height: 1.8;
}

.preview-content :deep(h1),
.preview-content :deep(h2),
.preview-content :deep(h3) {
  margin: 8px 0 4px;
  font-weight: 600;
}
.preview-content :deep(h1) {
  font-size: 18px;
}
.preview-content :deep(h2) {
  font-size: 16px;
}
.preview-content :deep(h3) {
  font-size: 15px;
}
.preview-content :deep(p) {
  margin: 4px 0;
}
.preview-content :deep(ul),
.preview-content :deep(ol) {
  padding-left: 20px;
  margin: 4px 0;
}
.preview-content :deep(li) {
  margin: 2px 0;
}
.preview-content :deep(strong) {
  font-weight: 600;
}
.preview-content :deep(em) {
  font-style: italic;
}
.preview-content :deep(code) {
  background: rgba(0, 0, 0, 0.06);
  padding: 1px 4px;
  border-radius: 3px;
  font-size: 13px;
}
.preview-content :deep(pre) {
  background: rgba(0, 0, 0, 0.06);
  padding: 8px 12px;
  border-radius: 6px;
  overflow-x: auto;
  font-size: 13px;
}
.preview-content :deep(blockquote) {
  border-left: 3px solid #dcdfe6;
  padding-left: 12px;
  color: #606266;
  margin: 4px 0;
}

.loading-hint {
  color: #909399;
  font-size: 13px;
}

.streaming-cursor {
  display: inline;
  animation: blink 0.7s infinite;
  color: #409eff;
  font-weight: bold;
}

@keyframes blink {
  0%,
  50% {
    opacity: 1;
  }
  51%,
  100% {
    opacity: 0;
  }
}

.preview-actions {
  display: flex;
  justify-content: flex-end;
  padding-top: 8px;
  flex-shrink: 0;
}

.empty-hint {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #c0c4cc;
  font-size: 13px;
}
</style>
