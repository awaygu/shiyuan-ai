<template>
  <div class="kb-action-panel">
    <div class="panel-header">
      <h3>✨ 智能生成</h3>
    </div>

    <div class="style-section">
      <div class="section-label">选择风格生成文章</div>

      <button class="style-btn style-xiaohongshu" @click="onGenerate('xiaohongshu')" :disabled="generating || noDocs">
        <span class="style-emoji">✨</span>
        <span class="style-name">小红书</span>
        <span class="style-desc">emoji+口语化</span>
      </button>

      <button class="style-btn style-wechat" @click="onGenerate('wechat_mp')" :disabled="generating || noDocs">
        <span class="style-emoji">📰</span>
        <span class="style-name">公众号</span>
        <span class="style-desc">深度长文</span>
      </button>

      <button class="style-btn style-douyin" @click="onGenerate('douyin')" :disabled="generating || noDocs">
        <span class="style-emoji">🎬</span>
        <span class="style-name">抖音</span>
        <span class="style-desc">短平快口播</span>
      </button>
    </div>

    <el-divider style="margin: 12px 0" />

    <div class="tips-section">
      <div class="section-label">💡 使用提示</div>
      <div class="tip-item">1. 先在左侧上传文档</div>
      <div class="tip-item">2. 在中间对话中提问</div>
      <div class="tip-item">3. 点击上方按钮生成文章</div>
    </div>

    <el-divider style="margin: 12px 0" />

    <div class="stats-section">
      <div class="section-label">📊 知识库统计</div>
      <div class="stat-row">
        <span>文档数</span>
        <span class="stat-val">{{ store.kbDocuments.length }}</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useNewsStore } from '@/stores'
import type { StyleType } from '@/types'

defineProps<{ kbId: string }>()

const store = useNewsStore()
const generating = ref(false)

const noDocs = computed(() => store.kbDocuments.length === 0)

const emit = defineEmits<{
  (e: 'generate', style: StyleType): void
}>()

function onGenerate(style: StyleType) {
  emit('generate', style)
}
</script>

<style scoped>
.kb-action-panel {
  height: 100%;
  display: flex;
  flex-direction: column;
  padding: 16px;
  overflow: hidden;
}

.panel-header {
  margin-bottom: 12px;
}

.panel-header h3 {
  margin: 0;
  font-size: 16px;
}

.section-label {
  font-size: 12px;
  color: #94a3b8;
  margin-bottom: 10px;
  font-weight: 500;
}

.style-section {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.style-btn {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 14px;
  border-radius: 10px;
  border: 1px solid #e2e8f0;
  background: #fff;
  cursor: pointer;
  transition: all 0.2s;
  text-align: left;
  width: 100%;
}

.style-btn:hover:not(:disabled) {
  border-color: #a5b4fc;
  background: #faf5ff;
  box-shadow: 0 2px 8px rgba(99, 102, 241, 0.1);
}

.style-btn:disabled {
  opacity: 0.35;
  cursor: not-allowed;
}

.style-xiaohongshu:hover:not(:disabled) {
  border-color: #fb7185;
  background: #fff1f2;
}

.style-wechat:hover:not(:disabled) {
  border-color: #34d399;
  background: #ecfdf5;
}

.style-douyin:hover:not(:disabled) {
  border-color: #fbbf24;
  background: #fffbeb;
}

.style-emoji {
  font-size: 20px;
  flex-shrink: 0;
}

.style-name {
  font-size: 14px;
  font-weight: 600;
  color: #1e293b;
}

.style-desc {
  font-size: 11px;
  color: #94a3b8;
  margin-left: auto;
}

.tips-section {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.tip-item {
  font-size: 12px;
  color: #64748b;
  line-height: 1.6;
}

.stats-section {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.stat-row {
  display: flex;
  justify-content: space-between;
  font-size: 13px;
  color: #64748b;
}

.stat-val {
  font-weight: 600;
  color: #6366f1;
}
</style>
