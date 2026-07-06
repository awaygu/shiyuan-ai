<template>
  <div class="kb-gen-panel">
    <div class="gen-topbar">
      <div class="gen-title">
        <el-icon><MagicStick /></el-icon>
        <span>生成文章</span>
      </div>
      <div class="gen-topbar-right">
        <el-popconfirm
          title="确定清空当前生成会话记录？"
          confirm-button-text="清空"
          cancel-button-text="取消"
          @confirm="onClearConv"
        >
          <template #reference>
            <button class="clear-conv-btn" title="清空生成会话" :disabled="generating || preparing">
              <el-icon><Delete /></el-icon>
              <span>清空会话</span>
            </button>
          </template>
        </el-popconfirm>
        <button class="close-btn" title="关闭" @click="closeDialog">
          <el-icon><Close /></el-icon>
        </button>
      </div>
    </div>

    <div class="gen-body" ref="messagesRef">
      <div
        v-for="(msg, i) in messages"
        :key="i"
        class="msg-row"
        :class="msg.role"
      >
        <div class="msg-avatar">
          <div v-if="msg.role === 'assistant'" class="avatar-ai">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none"><path d="M12 2L2 7L12 12L22 7L12 2Z" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/><path d="M2 17L12 22L22 17" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/><path d="M2 12L12 17L22 12" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>
          </div>
          <div v-else class="avatar-user">我</div>
        </div>
        <div class="msg-content">
          <div class="msg-bubble" v-html="renderMsgHtml(msg)"></div>
          <div
            v-if="msg.role === 'assistant' && !msg.streaming && msg.content && msg.type === 'article'"
            class="msg-actions"
          >
            <button class="msg-action-btn" @click="copyContent(msg.content)">复制</button>
            <el-dropdown @command="(p: string) => onPublishCommand(msg.content, p)">
              <button class="msg-action-btn">发布到 ▾</button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="xiaohongshu">小红书</el-dropdown-item>
                  <el-dropdown-item command="wechat_mp">微信公众号</el-dropdown-item>
                  <el-dropdown-item command="douyin">抖音</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </div>
        </div>
      </div>

      <div v-if="messages.length <= 1 && !generating" class="gen-empty">
        <div class="empty-hint">选择风格并输入要求，基于知识库生成文章</div>
      </div>
    </div>

    <div class="gen-footer">
      <div class="gen-input-area">
        <el-select
          v-model="style"
          class="style-select"
          popper-class="kb-gen-style-popper"
          size="default"
        >
          <template #prefix>
            <span class="style-prefix">{{ styleEmoji(style) }}</span>
          </template>
          <el-option label="小红书" value="xiaohongshu">
            <span class="style-option">
              <span class="style-dot" style="--c:#ff2442"></span>
              <span>小红书</span>
            </span>
          </el-option>
          <el-option label="公众号" value="wechat_mp">
            <span class="style-option">
              <span class="style-dot" style="--c:#07c160"></span>
              <span>公众号</span>
            </span>
          </el-option>
          <el-option label="抖音" value="douyin">
            <span class="style-option">
              <span class="style-dot" style="--c:#000000"></span>
              <span>抖音</span>
            </span>
          </el-option>
        </el-select>
        <el-input
          v-model="extraReq"
          type="textarea"
          :autosize="{ minRows: 1, maxRows: 8 }"
          placeholder="输入额外要求（可选，如：聚焦新能源、强调数据对比...）"
          :disabled="generating || preparing"
          class="gen-input"
          @keydown.enter.exact="onInputEnter"
        />
        <button class="send-btn" :disabled="!canSend || generating || preparing" @click="onGenerateClick">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
            <path d="M5 12H19M19 12L13 6M19 12L13 18" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
          </svg>
        </button>
      </div>
    </div>

    <WechatImageOptionsDialog
      v-model="imageOptsVisible"
      v-model:generate-cover="imageOpts.generate_cover"
      v-model:generate-inline-images="imageOpts.generate_inline_images"
      @confirm="confirmPublish"
      @cancel="cancelPublish"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, nextTick, computed } from 'vue'
import { ElMessage } from 'element-plus'
import { Delete, MagicStick, Close } from '@element-plus/icons-vue'
import { useNewsStore } from '@/stores'
import { kbStreamGenerate, publishByContent } from '@/api'
import type { StyleType, KBSource, KBMessage } from '@/types'
import type { ImagePublishOptions } from '@/composables/useWechatPublish'
import { useWechatPublish } from '@/composables/useWechatPublish'
import WechatImageOptionsDialog from '@/components/WechatImageOptionsDialog.vue'
import { renderSafeMarkdown } from '@/utils/markdown'

const props = defineProps<{ kbId: string }>()
const emit = defineEmits<{ 'generating-change': [value: boolean]; 'close': [] }>()
const store = useNewsStore()
const { imageOptsVisible, imageOpts, needImageOptions, confirmPublish, cancelPublish } = useWechatPublish()

interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  streaming?: boolean
  type?: 'chat' | 'article'
  sources?: KBSource[]
}

const messages = ref<ChatMessage[]>([])
const messagesRef = ref<HTMLElement | null>(null)
const style = ref<StyleType>('xiaohongshu')
const extraReq = ref('')
const generating = ref(false)
const preparing = ref(false)
const pendingExtraReq = ref('')

const canSend = computed(() => store.kbDocuments.length > 0)

const STYLE_EMOJIS: Record<StyleType, string> = {
  xiaohongshu: '📕',
  wechat_mp: '📰',
  douyin: '🎬',
}
function styleEmoji(s: StyleType): string {
  return STYLE_EMOJIS[s] || '✨'
}

function renderMsgHtml(msg: ChatMessage): string {
  let html = renderSafeMarkdown(msg.content)
  if (msg.streaming) {
    const cursor = '<span class="streaming-cursor">|</span>'
    const lastClose = html.lastIndexOf('</')
    if (lastClose > 0) {
      const tagEnd = html.indexOf('>', lastClose)
      html = html.slice(0, tagEnd) + cursor + html.slice(tagEnd)
    } else {
      html += cursor
    }
  }
  return html
}

function scrollToBottom() {
  nextTick(() => {
    if (messagesRef.value) {
      messagesRef.value.scrollTop = messagesRef.value.scrollHeight
    }
  })
}

function pushUserMessage(text: string) {
  messages.value.push({ role: 'user', content: text, type: 'chat' })
}

function addAssistantMessage(type: ChatMessage['type'] = 'article'): number {
  const msg: ChatMessage = { role: 'assistant', content: '', streaming: true, type }
  messages.value.push(msg)
  return messages.value.length - 1
}

function pushDone(msgIdx: number) {
  const msg = messages.value[msgIdx]
  if (msg) {
    msg.streaming = false
  }
  generating.value = false
  emit('generating-change', false)
  scrollToBottom()
}

function pushError(msgIdx: number, err: string) {
  const msg = messages.value[msgIdx]
  if (msg) {
    msg.content += `\n\n❌ ${err}`
    msg.streaming = false
  } else {
    ElMessage.error(err)
  }
  generating.value = false
  emit('generating-change', false)
  scrollToBottom()
}

function startGenerate(s?: StyleType) {
  if (s) style.value = s
  if (generating.value || preparing.value) return
  if (store.kbDocuments.length === 0) {
    ElMessage.warning('知识库为空，请先上传文档')
    return
  }
  const req = extraReq.value.trim()
  doGenerate(style.value, req)
  // 先把输入暂存到 pendingExtraReq，待流式成功后再清空；
  // 失败时恢复，避免用户丢失输入
  pendingExtraReq.value = req
  extraReq.value = ''
}

function onGenerateClick() {
  startGenerate()
}

function onInputEnter(e: KeyboardEvent) {
  if (e.ctrlKey || e.shiftKey) return
  e.preventDefault()
  startGenerate()
}

function doGenerate(s: StyleType, extraReqText: string) {
  const userMsg = extraReqText
  if (userMsg) {
    pushUserMessage(userMsg)
  }
  generating.value = true
  emit('generating-change', true)
  pendingExtraReq.value = userMsg

  const msgIdx = addAssistantMessage('article')
  scrollToBottom()

  const convId = store.currentGenConvId
  const docIds = store.kbSelectedDocIds

  kbStreamGenerate(props.kbId, userMsg, s, {
    onChunk(text) {
      messages.value[msgIdx].content += text
      scrollToBottom()
    },
    onSources(sources) {
      messages.value[msgIdx].sources = sources
    },
    onDone() {
      pushDone(msgIdx)
      // 生成成功，清空暂存
      pendingExtraReq.value = ''
    },
    onError(err) {
      pushError(msgIdx, `生成失败：${err}`)
      // 失败时恢复用户输入，避免丢失
      extraReq.value = pendingExtraReq.value
      pendingExtraReq.value = ''
    },
  }, docIds, 8, convId)
}

async function onClearConv() {
  if (generating.value || preparing.value) return
  await store.clearGenConv(props.kbId)
  messages.value = []
  ElMessage.success('已清空生成会话')
}

function copyContent(text: string) {
  navigator.clipboard.writeText(text).then(() => {
    ElMessage.success('已复制到剪贴板')
  }).catch(() => {
    ElMessage.error('复制失败')
  })
}

const platformLabels: Record<string, string> = {
  xiaohongshu: '小红书',
  wechat_mp: '微信公众号',
  douyin: '抖音',
}

async function onPublishCommand(content: string, platform: string) {
  if (platform === 'wechat_mp') {
    const imageOptions = await needImageOptions()
    if (imageOptions) {
      await onPublish(content, platform, imageOptions)
    }
  } else {
    await onPublish(content, platform)
  }
}

async function onPublish(content: string, platform: string, imageOptions?: ImagePublishOptions) {
  const label = platformLabels[platform] || platform
  const title = content.split('\n').find(l => l.trim() && !l.trim().startsWith('#'))?.trim()?.slice(0, 30) || '知识库文章'
  try {
    await publishByContent(title, content, platform, imageOptions)
    store.startTaskStream()
    store.showTaskPanel = true
    await store.loadTasks()
    ElMessage.success(`已提交发布到${label}，请在任务列表中查看进度`)
  } catch (e: any) {
    ElMessage.error(`发布失败：${e.message || '未知错误'}`)
  }
}

function loadHistory(historyMessages: KBMessage[]) {
  messages.value = []
  for (const m of historyMessages) {
    messages.value.push({
      role: m.role,
      content: m.content,
      type: m.type as 'chat' | 'article',
      sources: m.sources || [],
    })
  }
  scrollToBottom()
}

async function openDialog(s?: StyleType) {
  if (preparing.value) return
  preparing.value = true
  try {
    if (s) style.value = s
    await store.ensureGenConv(props.kbId)
    await store.loadGenMessages(props.kbId)
    loadHistory(store.kbGenMessages)
  } finally {
    preparing.value = false
  }
}

function closeDialog() {
  emit('close')
}

defineExpose({ startGenerate, loadHistory, openDialog, closeDialog })
</script>

<style scoped>
.kb-gen-panel {
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: #fafbfc;
}

.gen-topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 16px;
  flex-shrink: 0;
  border-bottom: 1px solid #f0f1f5;
}

.gen-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 14px;
  font-weight: 600;
  color: #4f46e5;
}

.gen-topbar-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.close-btn {
  width: 28px;
  height: 28px;
  border-radius: 6px;
  border: 1px solid #e2e8f0;
  background: #fff;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #94a3b8;
  transition: all 0.15s;
}

.close-btn:hover {
  border-color: #fca5a5;
  color: #ef4444;
  background: #fef2f2;
}

.clear-conv-btn {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  border-radius: 6px;
  border: 1px solid #e2e8f0;
  background: #fff;
  cursor: pointer;
  font-size: 12px;
  color: #94a3b8;
  transition: all 0.15s;
}

.clear-conv-btn:hover {
  border-color: #fca5a5;
  color: #ef4444;
  background: #fef2f2;
}

.clear-conv-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.gen-body {
  flex: 1;
  overflow-y: auto;
  padding: 20px 24px;
}

.gen-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 60%;
}

.empty-hint {
  font-size: 14px;
  color: #94a3b8;
}

.msg-row {
  display: flex;
  gap: 10px;
  margin-bottom: 20px;
  animation: fadeIn 0.2s ease;
}

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(4px); }
  to { opacity: 1; transform: translateY(0); }
}

.msg-row.user {
  flex-direction: row-reverse;
}

.msg-avatar {
  flex-shrink: 0;
  padding-top: 2px;
}

.avatar-ai {
  width: 30px;
  height: 30px;
  border-radius: 8px;
  background: linear-gradient(135deg, #eef2ff, #e0e7ff);
  display: flex;
  align-items: center;
  justify-content: center;
  color: #6366f1;
}

.avatar-user {
  width: 30px;
  height: 30px;
  border-radius: 8px;
  background: linear-gradient(135deg, #818cf8, #6366f1);
  color: #fff;
  font-weight: 500;
  font-size: 11px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.msg-content {
  max-width: 80%;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.msg-row.user .msg-content {
  align-items: flex-end;
}

.msg-bubble {
  padding: 12px 18px;
  border-radius: 12px;
  background: #fff;
  border: 1px solid #eef0f5;
  font-size: 14px;
  line-height: 1.7;
  word-break: break-word;
}

.msg-bubble :deep(p) { margin: 4px 0; }
.msg-bubble :deep(p:first-child) { margin-top: 0; }
.msg-bubble :deep(p:last-child) { margin-bottom: 0; }
.msg-bubble :deep(strong) { font-weight: 600; }
.msg-bubble :deep(ol),
.msg-bubble :deep(ul) {
  margin: 6px 0;
  padding-left: 22px;
}
.msg-bubble :deep(li) { margin: 3px 0; line-height: 1.7; }
.msg-bubble :deep(h1),
.msg-bubble :deep(h2),
.msg-bubble :deep(h3),
.msg-bubble :deep(h4) {
  margin: 10px 0 6px;
  font-weight: 600;
  color: #1e293b;
}
.msg-bubble :deep(h1) { font-size: 18px; }
.msg-bubble :deep(h2) { font-size: 16px; }
.msg-bubble :deep(h3) { font-size: 15px; }
.msg-bubble :deep(h4) { font-size: 14px; }
.msg-bubble :deep(hr) {
  border: none;
  border-top: 1px solid #eef0f5;
  margin: 10px 0;
}
.msg-bubble :deep(table) {
  border-collapse: collapse;
  margin: 8px 0;
  font-size: 13px;
}
.msg-bubble :deep(th),
.msg-bubble :deep(td) {
  border: 1px solid #e2e8f0;
  padding: 6px 10px;
  text-align: left;
}
.msg-bubble :deep(th) {
  background: #f5f6fa;
  font-weight: 600;
}
.msg-bubble :deep(code) {
  background: rgba(99, 102, 241, 0.08);
  padding: 1px 5px;
  border-radius: 3px;
  font-size: 13px;
  color: #4338ca;
}
.msg-bubble :deep(pre) {
  background: #f5f6fa;
  padding: 10px 14px;
  border-radius: 8px;
  overflow-x: auto;
  font-size: 13px;
  margin: 6px 0;
}
.msg-bubble :deep(blockquote) {
  border-left: 3px solid #c7d2fe;
  padding-left: 12px;
  color: #64748b;
  margin: 6px 0;
}

.streaming-cursor {
  display: inline;
  animation: blink 0.7s infinite;
  color: #818cf8;
  font-weight: bold;
}

@keyframes blink {
  0%, 50% { opacity: 1; }
  51%, 100% { opacity: 0; }
}

.msg-actions {
  display: flex;
  gap: 4px;
}

.msg-action-btn {
  font-size: 12px;
  padding: 3px 10px;
  border-radius: 6px;
  border: 1px solid #e2e8f0;
  background: #fff;
  color: #64748b;
  cursor: pointer;
  transition: all 0.15s;
}

.msg-action-btn:hover {
  border-color: #a5b4fc;
  color: #6366f1;
  background: #eef2ff;
}

.gen-footer {
  flex-shrink: 0;
  padding: 12px 16px;
  background: #fafbfc;
  border-top: 1px solid #eef0f5;
}

.gen-input-area {
  display: flex;
  align-items: flex-end;
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 0;
  transition: border-color 0.15s, box-shadow 0.15s;
  overflow: hidden;
}

.gen-input-area:focus-within {
  border-color: #a5b4fc;
  box-shadow: 0 0 0 3px rgba(129, 140, 248, 0.1);
}

.style-select {
  flex-shrink:  0;
  width: 88px;
  /* 贴满输入区左侧：上下贴边，右侧用分隔线与输入框分界 */
  align-self: stretch;
}

/* 平台选择框：透明背景、无圆角、贴满容器左侧 */
.style-select :deep(.el-select__wrapper) {
  min-height: 38px;
  height: 100%;
  width: 100%;
  border-radius: 0;
  background: transparent;
  box-shadow: none;
  border: none;
  border-right: 1px solid #eef0f5;
  transition: background 0.15s;
  padding: 0 8px 0 12px;
}

.style-select :deep(.el-select__wrapper:hover) {
  background: #f5f6fa;
}

.style-select :deep(.el-select__wrapper.is-focused) {
  background: #f5f6fa;
  box-shadow: none;
}

.style-select :deep(.el-select__placeholder),
.style-select :deep(.el-select__selected-item) {
  font-size: 14px;
  font-weight: 500;
  color: #1e293b;
}

.style-prefix {
  display: inline-flex;
  align-items: center;
  margin-right: 4px;
  font-size: 15px;
  line-height: 1;
}

/* 下拉项：平台色圆点 + 名称 */
.style-option {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
}

.style-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--c, #94a3b8);
  flex-shrink: 0;
}

.gen-input {
  flex: 1;
}

.gen-input :deep(.el-textarea__inner) {
  border: none;
  box-shadow: none;
  padding: 9px 14px 9px 12px;
  font-size: 14px;
  line-height: 1.5;
  resize: none;
  background: transparent;
  color: #1e293b;
}

.gen-input :deep(.el-textarea__inner:focus) {
  box-shadow: none;
}

.send-btn {
  width: 34px;
  height: 34px;
  margin: 2px 4px 2px 0;
  border-radius: 10px;
  border: none;
  background: linear-gradient(135deg, #818cf8, #6366f1);
  color: #fff;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  transition: all 0.15s;
}

.send-btn:hover:not(:disabled) {
  box-shadow: 0 2px 10px rgba(99, 102, 241, 0.3);
  transform: scale(1.05);
}

.send-btn:disabled {
  opacity: 0.3;
  cursor: not-allowed;
  transform: none;
}
</style>

<!-- 下拉面板 teleport 到 body，需用全局样式 -->
<style>
.kb-gen-style-popper.el-popper {
  border-radius: 10px !important;
  padding: 4px !important;
  border: 1px solid #e2e8f0 !important;
  box-shadow: 0 6px 20px rgba(15, 23, 42, 0.08) !important;
}
.kb-gen-style-popper .el-select-dropdown__item {
  border-radius: 6px;
  padding: 0 10px;
  height: 34px;
  line-height: 34px;
}
.kb-gen-style-popper .el-select-dropdown__item.is-hovering,
.kb-gen-style-popper .el-select-dropdown__item:hover {
  background: #f5f6fa;
}
.kb-gen-style-popper .el-select-dropdown__item.is-selected {
  color: #4f46e5;
  font-weight: 600;
  background: #eef2ff;
}
</style>
