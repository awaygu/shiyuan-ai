<template>
  <div class="kb-action-panel" :class="{ collapsed: props.collapsed }">
    <!-- 展开状态 -->
    <template v-if="!props.collapsed">
      <div class="panel-header">
        <h3>✨ 智能生成</h3>
        <button class="collapse-btn" title="收起侧边栏" @click="toggleCollapse">
          <el-icon><ArrowRight /></el-icon>
        </button>
      </div>

      <div class="style-section">
        <div class="section-label">选择风格生成文章</div>

        <button
          class="style-btn style-xiaohongshu"
          :disabled="generating || noDocs"
          @click="onGenerate('xiaohongshu')"
        >
          <span class="style-emoji">✨</span>
          <span class="style-name">小红书</span>
          <span class="style-desc">emoji+口语化</span>
        </button>

        <button
          class="style-btn style-wechat"
          :disabled="generating || noDocs"
          @click="onGenerate('wechat_mp')"
        >
          <span class="style-emoji">📰</span>
          <span class="style-name">公众号</span>
          <span class="style-desc">深度长文</span>
        </button>

        <button
          class="style-btn style-douyin"
          :disabled="generating || noDocs"
          @click="onGenerate('douyin')"
        >
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
    </template>

    <!-- 收起状态：垂直按钮条 -->
    <template v-else>
      <button class="expand-btn" title="展开侧边栏" @click="toggleCollapse">
        <el-icon><ArrowLeft /></el-icon>
      </button>

      <div class="vertical-actions">
        <button
          class="vertical-btn style-xiaohongshu"
          data-label="小红书"
          :disabled="generating || noDocs"
          @click="onGenerate('xiaohongshu')"
        >
          <span class="vertical-emoji">✨</span>
        </button>

        <button
          class="vertical-btn style-wechat"
          data-label="公众号"
          :disabled="generating || noDocs"
          @click="onGenerate('wechat_mp')"
        >
          <span class="vertical-emoji">📰</span>
        </button>

        <button
          class="vertical-btn style-douyin"
          data-label="抖音"
          :disabled="generating || noDocs"
          @click="onGenerate('douyin')"
        >
          <span class="vertical-emoji">🎬</span>
        </button>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { ArrowRight, ArrowLeft } from '@element-plus/icons-vue'
import { useNewsStore } from '@/stores'
import type { StyleType } from '@/types'

const props = withDefaults(
  defineProps<{ kbId: string; generating?: boolean; collapsed?: boolean }>(),
  { generating: false, collapsed: false }
)

const store = useNewsStore()

const noDocs = computed(() => store.kbDocuments.length === 0)

const emit = defineEmits<{
  (e: 'generate', style: StyleType): void
  (e: 'toggle-collapse'): void
}>()

function onGenerate(style: StyleType) {
  emit('generate', style)
}

function toggleCollapse() {
  emit('toggle-collapse')
}
</script>

<style scoped>
.kb-action-panel {
  height: 100%;
  display: flex;
  flex-direction: column;
  padding: 16px;
  overflow: hidden;
  background: #fff;
}

.kb-action-panel.collapsed {
  padding: 8px;
  align-items: center;
  gap: 12px;
  overflow: visible;
}

.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}

.panel-header h3 {
  margin: 0;
  font-size: 16px;
}

.collapse-btn,
.expand-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border-radius: 6px;
  border: 1px solid #e2e8f0;
  background: #fff;
  cursor: pointer;
  color: #64748b;
  transition: all 0.2s;
}

.collapse-btn:hover,
.expand-btn:hover {
  border-color: #a5b4fc;
  color: #6366f1;
  background: #f5f7ff;
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

/* 收起状态垂直按钮 */
.vertical-actions {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  flex: 1;
  width: 100%;
}

.vertical-btn {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 6px;
  width: 100%;
  padding: 12px 4px;
  border-radius: 10px;
  border: none;
  background: transparent;
  cursor: pointer;
  transition: all 0.2s;
  position: relative;
}

/* 悬浮 tooltip — 浮在按钮左侧 */
.vertical-btn::after {
  content: attr(data-label);
  position: absolute;
  right: 110%;
  top: 50%;
  transform: translateY(-50%);
  background: #1e293b;
  color: #fff;
  font-size: 12px;
  font-weight: 500;
  padding: 4px 10px;
  border-radius: 6px;
  white-space: nowrap;
  opacity: 0;
  pointer-events: none;
  transition: opacity 0.15s;
  z-index: 100;
}

.vertical-btn::before {
  content: '';
  position: absolute;
  right: calc(110% - 4px);
  top: 50%;
  transform: translateY(-50%);
  border: 5px solid transparent;
  border-right: none;
  border-left-color: #1e293b;
  opacity: 0;
  pointer-events: none;
  transition: opacity 0.15s;
  z-index: 100;
}

.vertical-btn:hover:not(:disabled)::after,
.vertical-btn:hover:not(:disabled)::before {
  opacity: 1;
}

.vertical-btn:hover:not(:disabled) {
  background: #f1f5f9;
}

.vertical-btn:disabled {
  opacity: 0.35;
  cursor: not-allowed;
}

.vertical-emoji {
  font-size: 22px;
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
