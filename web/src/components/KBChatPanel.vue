<template>
  <div class="kb-chat-panel">
    <div class="chat-topbar">
      <el-popconfirm
        title="确定清空当前会话记录？"
        confirm-button-text="清空"
        cancel-button-text="取消"
        @confirm="$emit('clear-conv')"
      >
        <template #reference>
          <button class="clear-conv-btn" title="清空会话">
            <el-icon><Delete /></el-icon>
            <span>清空会话</span>
          </button>
        </template>
      </el-popconfirm>
    </div>
    <div ref="messagesRef" class="chat-body">
      <div v-for="(msg, i) in messages" :key="i" class="msg-row" :class="msg.role">
        <div class="msg-avatar">
          <div v-if="msg.role === 'assistant'" class="avatar-ai">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
              <path
                d="M12 2L2 7L12 12L22 7L12 2Z"
                stroke="currentColor"
                stroke-width="2"
                stroke-linecap="round"
                stroke-linejoin="round"
              />
              <path
                d="M2 17L12 22L22 17"
                stroke="currentColor"
                stroke-width="2"
                stroke-linecap="round"
                stroke-linejoin="round"
              />
              <path
                d="M2 12L12 17L22 12"
                stroke="currentColor"
                stroke-width="2"
                stroke-linecap="round"
                stroke-linejoin="round"
              />
            </svg>
          </div>
          <div v-else class="avatar-user">我</div>
        </div>
        <div class="msg-content">
          <div class="msg-bubble" v-html="renderMsgHtml(msg)"></div>
          <div
            v-if="
              msg.role === 'assistant' && !msg.streaming && msg.content && msg.type === 'article'
            "
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

      <div v-if="suggestions.length > 0 && !generating" class="suggestions-area">
        <div class="suggestions-label">推荐提问</div>
        <div class="suggestions-list">
          <button
            v-for="q in suggestions"
            :key="q"
            class="suggestion-btn"
            @click="onClickSuggestion(q)"
          >
            {{ q }}
          </button>
        </div>
      </div>
    </div>

    <div class="chat-footer">
      <div class="input-area">
        <el-input
          v-model="chatMessage"
          type="textarea"
          :autosize="{ minRows: 1, maxRows: 5 }"
          placeholder="输入问题，AI 将检索知识库回答..."
          :disabled="generating"
          class="chat-input"
          @keydown.enter.exact="onInputEnter"
        />
        <button class="send-btn" :disabled="!chatMessage.trim() || generating" @click="sendChat">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
            <path
              d="M5 12H19M19 12L13 6M19 12L13 18"
              stroke="currentColor"
              stroke-width="2"
              stroke-linecap="round"
              stroke-linejoin="round"
            />
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

    <Teleport to="body">
      <div
        v-if="citeTooltip.visible"
        class="cite-tooltip"
        :style="{
          left: citeTooltip.x + 'px',
          top: citeTooltip.y + 'px',
          width: CITE_TIP_WIDTH + 'px',
        }"
        @mouseenter="cancelHideCite"
        @mouseleave="scheduleHideCite"
      >
        <div class="cite-tooltip-title">{{ citeTooltip.tip }}</div>
        <div v-if="citeTooltip.text" class="cite-tooltip-body">{{ citeTooltip.text }}</div>
      </div>
    </Teleport>
  </div>
</template>

<script setup lang="ts">
import { ref, nextTick, watch, onMounted, onBeforeUnmount } from 'vue'
import { ElMessage } from 'element-plus'
import { Delete } from '@element-plus/icons-vue'
import { useKbStore, useTaskStore } from '@/stores'
import { kbStreamChat, fetchKBSuggestions, publishByContent } from '@/api'
import type { KBSource, KBMessage } from '@/types'
import type { ImagePublishOptions } from '@/composables/useWechatPublish'
import { useWechatPublish } from '@/composables/useWechatPublish'
import WechatImageOptionsDialog from '@/components/WechatImageOptionsDialog.vue'
import { renderSafeMarkdown } from '@/utils/markdown'

const props = defineProps<{ kbId: string }>()
const emit = defineEmits<{ 'clear-conv': []; 'generating-change': [value: boolean] }>()
const store = useKbStore()
const taskStore = useTaskStore()
const { imageOptsVisible, imageOpts, needImageOptions, confirmPublish, cancelPublish } =
  useWechatPublish()

interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  streaming?: boolean
  type?: 'chat' | 'article'
  sources?: KBSource[]
}

const messages = ref<ChatMessage[]>([
  {
    role: 'assistant',
    content: '你好！我可以基于知识库内容回答问题。上传文档后，直接提问即可。',
    type: 'chat',
  },
])

const messagesRef = ref<HTMLElement | null>(null)
const chatMessage = ref('')
const generating = ref(false)
const suggestions = ref<string[]>([])
const loadingSuggestions = ref(false)

watch(generating, val => emit('generating-change', val))

watch(
  () => props.kbId,
  () => {
    loadSuggestions()
  },
  { immediate: true }
)

onMounted(() => {
  window.addEventListener('mouseover', onOverBody)
  window.addEventListener('mouseout', onOutBody)
})
onBeforeUnmount(() => {
  window.removeEventListener('mouseover', onOverBody)
  window.removeEventListener('mouseout', onOutBody)
  if (_citeHideTimer) clearTimeout(_citeHideTimer)
})

function renderMarkdown(text: string): string {
  return renderSafeMarkdown(text)
}

// 将正文中的 [n] 引用编号转换为可悬浮的脚注 sup
function injectCitations(html: string, sources: KBSource[] | undefined): string {
  if (!sources || sources.length === 0) return html
  return html.replace(/\[(\d+)\]/g, (m, numStr: string) => {
    const idx = parseInt(numStr, 10)
    if (idx < 1 || idx > sources.length) return m
    const s = sources[idx - 1]
    const page = s.page ? ` · 第${s.page}页` : ''
    const tip = `${s.filename}${page}`
    return `<sup class="cite-ref" data-tip="${escapeAttr(tip)}" data-text="${escapeAttr(s.preview || '')}">[${idx}]</sup>`
  })
}

function escapeAttr(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/"/g, '&quot;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
}

function renderMsgHtml(msg: ChatMessage): string {
  let html = renderMarkdown(msg.content)
  html = injectCitations(html, msg.sources)
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

// 脚注 tooltip 事件委托 — 锚定到引用编号，悬浮显示，可在 tooltip 上悬停查看长内容
const citeTooltip = ref<{ visible: boolean; x: number; y: number; tip: string; text: string }>({
  visible: false,
  x: 0,
  y: 0,
  tip: '',
  text: '',
})

let _citeHideTimer: number | null = null
function scheduleHideCite() {
  if (_citeHideTimer) clearTimeout(_citeHideTimer)
  _citeHideTimer = window.setTimeout(() => {
    citeTooltip.value.visible = false
  }, 220)
}
function cancelHideCite() {
  if (_citeHideTimer) {
    clearTimeout(_citeHideTimer)
    _citeHideTimer = null
  }
}

const CITE_TIP_WIDTH = 480
const CITE_TIP_MAXH = 240

function showCiteFor(el: HTMLElement) {
  cancelHideCite()
  const rect = el.getBoundingClientRect()
  const tip = el.getAttribute('data-tip') || ''
  const text = el.getAttribute('data-text') || ''
  // 默认放在引用右侧并顶部对齐；右侧放不下则放左侧
  let x = rect.right + 6
  let y = rect.top
  if (x + CITE_TIP_WIDTH > window.innerWidth - 8) {
    x = rect.left - CITE_TIP_WIDTH - 6
  }
  if (x < 8) x = 8
  if (y + CITE_TIP_MAXH > window.innerHeight - 8) {
    y = window.innerHeight - CITE_TIP_MAXH - 8
  }
  if (y < 8) y = 8
  citeTooltip.value = { visible: true, x, y, tip, text }
}

function onOverBody(e: MouseEvent) {
  const target = (e.target as HTMLElement)?.closest?.('.cite-ref') as HTMLElement | null
  if (target) showCiteFor(target)
}

function onOutBody(e: MouseEvent) {
  const target = e.target as HTMLElement | null
  const related = e.relatedTarget as HTMLElement | null
  if (!target || !target.closest?.('.cite-ref')) return
  // 移入 tooltip 本身则保持显示
  if (related && related.closest?.('.cite-tooltip')) return
  scheduleHideCite()
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

function addAssistantMessage(type: ChatMessage['type'] = 'chat'): number {
  const msg: ChatMessage = { role: 'assistant', content: '', streaming: true, type }
  messages.value.push(msg)
  return messages.value.length - 1
}

function pushDone(msgIdx: number) {
  messages.value[msgIdx].streaming = false
  generating.value = false
  scrollToBottom()
  loadSuggestions()
}

function pushError(msgIdx: number, err: string) {
  messages.value[msgIdx].content += `\n\n❌ ${err}`
  messages.value[msgIdx].streaming = false
  generating.value = false
  scrollToBottom()
}

function onInputEnter(e: KeyboardEvent) {
  if (e.ctrlKey || e.shiftKey) return
  e.preventDefault()
  sendChat()
}

async function loadSuggestions() {
  loadingSuggestions.value = true
  try {
    suggestions.value = await fetchKBSuggestions(props.kbId)
  } catch {
    suggestions.value = []
  } finally {
    loadingSuggestions.value = false
  }
}

function onClickSuggestion(q: string) {
  chatMessage.value = q
  sendChat()
}

async function sendChat() {
  const msg = chatMessage.value.trim()
  if (!msg || generating.value) return

  pushUserMessage(msg)
  chatMessage.value = ''
  generating.value = true

  const msgIdx = addAssistantMessage('chat')
  scrollToBottom()

  kbStreamChat(
    props.kbId,
    msg,
    store.kbSelectedDocIds,
    {
      onChunk(text) {
        messages.value[msgIdx].content += text
        scrollToBottom()
      },
      onSources(sources) {
        messages.value[msgIdx].sources = sources as KBSource[]
      },
      onMeta(meta) {
        if (meta.message_type) {
          messages.value[msgIdx].type = meta.message_type
        }
      },
      onLoading(message) {
        messages.value[msgIdx].content = `${message}`
        scrollToBottom()
      },
      onPrompt() {},
      onDone() {
        pushDone(msgIdx)
      },
      onError(err) {
        pushError(msgIdx, `请求失败：${err}`)
      },
    },
    5,
    false,
    store.currentConvId
  )
}

function copyContent(text: string) {
  navigator.clipboard
    .writeText(text)
    .then(() => {
      ElMessage.success('已复制到剪贴板')
    })
    .catch(() => {
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
  const title =
    content
      .split('\n')
      .find(l => l.trim() && !l.trim().startsWith('#'))
      ?.trim()
      ?.slice(0, 30) || '知识库文章'

  try {
    const res = await publishByContent(title, content, platform, imageOptions)
    await taskStore.notifyTaskStarted()
    ElMessage.success(`已提交发布到${label}，请在任务列表中查看进度`)
  } catch (e: any) {
    ElMessage.error(`发布失败：${e.message || '未知错误'}`)
  }
}

function loadHistory(historyMessages: KBMessage[]) {
  messages.value = [
    {
      role: 'assistant',
      content: '你好！我可以基于知识库内容回答问题。上传文档后，直接提问即可。',
      type: 'chat',
    },
  ]
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

function clearMessages() {
  messages.value = [
    {
      role: 'assistant',
      content: '你好！我可以基于知识库内容回答问题。上传文档后，直接提问即可。',
      type: 'chat',
    },
  ]
}

defineExpose({ loadHistory, clearMessages, loadSuggestions })
</script>

<style scoped>
.kb-chat-panel {
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: #fafbfc;
}

.chat-topbar {
  display: flex;
  justify-content: flex-end;
  padding: 8px 16px;
  flex-shrink: 0;
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

.chat-body {
  flex: 1;
  overflow-y: auto;
  padding: 20px 24px;
}

.msg-row {
  display: flex;
  gap: 10px;
  margin-bottom: 20px;
  animation: fadeIn 0.2s ease;
}

@keyframes fadeIn {
  from {
    opacity: 0;
    transform: translateY(4px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
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

.msg-bubble :deep(p) {
  margin: 4px 0;
}
.msg-bubble :deep(p:first-child) {
  margin-top: 0;
}
.msg-bubble :deep(p:last-child) {
  margin-bottom: 0;
}
.msg-bubble :deep(strong) {
  font-weight: 600;
}
.msg-bubble :deep(ol),
.msg-bubble :deep(ul) {
  margin: 6px 0;
  padding-left: 22px;
}
.msg-bubble :deep(li) {
  margin: 3px 0;
  line-height: 1.7;
}
.msg-bubble :deep(h1),
.msg-bubble :deep(h2),
.msg-bubble :deep(h3),
.msg-bubble :deep(h4) {
  margin: 10px 0 6px;
  font-weight: 600;
  color: #1e293b;
}
.msg-bubble :deep(h1) {
  font-size: 18px;
}
.msg-bubble :deep(h2) {
  font-size: 16px;
}
.msg-bubble :deep(h3) {
  font-size: 15px;
}
.msg-bubble :deep(h4) {
  font-size: 14px;
}
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

.msg-row.user .msg-bubble :deep(code) {
  background: rgba(255, 255, 255, 0.15);
  color: #eef2ff;
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
  0%,
  50% {
    opacity: 1;
  }
  51%,
  100% {
    opacity: 0;
  }
}

.suggestions-area {
  padding: 8px 0 16px;
}

.suggestions-label {
  font-size: 12px;
  color: #94a3b8;
  margin-bottom: 8px;
  padding-left: 4px;
}

.suggestions-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.suggestion-btn {
  font-size: 13px;
  padding: 6px 14px;
  border-radius: 18px;
  border: 1px solid #e2e8f0;
  background: #fff;
  color: #475569;
  cursor: pointer;
  transition: all 0.15s;
  text-align: left;
  line-height: 1.4;
}

.suggestion-btn:hover {
  border-color: #a5b4fc;
  color: #4f46e5;
  background: #eef2ff;
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

.chat-footer {
  flex-shrink: 0;
  padding: 12px 16px;
  background: #fafbfc;
  border-top: 1px solid #eef0f5;
}

.input-area {
  display: flex;
  align-items: flex-end;
  gap: 8px;
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 6px 6px 6px 4px;
  transition:
    border-color 0.15s,
    box-shadow 0.15s;
}

.input-area:focus-within {
  border-color: #a5b4fc;
  box-shadow: 0 0 0 3px rgba(129, 140, 248, 0.1);
}

.chat-input {
  flex: 1;
}

.chat-input :deep(.el-textarea__inner) {
  border: none;
  box-shadow: none;
  padding: 6px 10px;
  font-size: 14px;
  line-height: 1.5;
  resize: none;
  background: transparent;
  color: #1e293b;
}

.chat-input :deep(.el-textarea__inner:focus) {
  box-shadow: none;
}

.send-btn {
  width: 34px;
  height: 34px;
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

<style>
/* 引用脚注（v-html 注入，需放在非 scoped 块） */
.cite-ref {
  color: #6366f1;
  font-size: 0.75em;
  font-weight: 600;
  cursor: pointer;
  padding: 0 1px;
  line-height: 1;
  vertical-align: super;
}

.cite-ref:hover {
  color: #4f46e5;
  text-decoration: underline;
}

/* 引用脚注悬浮提示（Teleport 到 body，非 scoped） */
.cite-tooltip {
  position: fixed;
  z-index: 3000;
  background: #ffffff;
  color: #334155;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 16px 24px;
  box-shadow: 0 6px 20px rgba(15, 23, 42, 0.12);
  pointer-events: auto;
  font-size: 16px;
  line-height: 1.6;
  box-sizing: border-box;
}

.cite-tooltip-title {
  font-weight: 600;
  margin-bottom: 6px;
  color: #4f46e5;
}

.cite-tooltip-body {
  color: #475569;
  max-height: 200px;
  overflow-y: auto;
  white-space: pre-wrap;
  word-break: break-all;
}
</style>
