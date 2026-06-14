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
    <div class="chat-body" ref="messagesRef">
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
          <div v-if="msg.sources && msg.sources.length" class="msg-sources">
            <div
              v-for="(s, si) in msg.sources"
              :key="si"
              class="source-card"
              :class="{ expanded: isSourceExpanded(i, si) }"
            >
              <div class="source-header" @click="toggleSource(i, si)">
                <span class="source-file">{{ s.filename }}</span>
                <span v-if="s.page" class="source-page">P.{{ s.page }}</span>
                <span class="source-score">{{ (s.score * 100).toFixed(0) }}%</span>
                <span class="source-toggle">{{ isSourceExpanded(i, si) ? '收起' : '展开' }}</span>
              </div>
              <div v-if="isSourceExpanded(i, si)" class="source-full">{{ s.text || s.preview }}</div>
              <div v-else class="source-preview">{{ s.preview }}</div>
            </div>
          </div>
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

      <div v-if="suggestions.length > 0 && !generating" class="suggestions-area">
        <div class="suggestions-label">推荐提问</div>
        <div class="suggestions-list">
          <button
            v-for="q in suggestions"
            :key="q"
            class="suggestion-btn"
            @click="onClickSuggestion(q)"
          >{{ q }}</button>
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
          @keydown.enter.exact="onInputEnter"
          class="chat-input"
        />
        <button class="send-btn" :disabled="!chatMessage.trim() || generating" @click="sendChat">
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
import { ref, nextTick, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Delete } from '@element-plus/icons-vue'
import { useNewsStore } from '@/stores'
import { kbStreamChat, kbStreamGenerate, fetchKBSuggestions, publishByContent } from '@/api'
import type { StyleType, KBSource, KBMessage } from '@/types'
import type { ImagePublishOptions } from '@/composables/useWechatPublish'
import { useWechatPublish } from '@/composables/useWechatPublish'
import WechatImageOptionsDialog from '@/components/WechatImageOptionsDialog.vue'
import { marked } from 'marked'

const props = defineProps<{ kbId: string }>()
defineEmits<{ 'clear-conv': [] }>()
const store = useNewsStore()
const { imageOptsVisible, imageOpts, needImageOptions, confirmPublish, cancelPublish } = useWechatPublish()

interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  streaming?: boolean
  type?: 'chat' | 'article'
  sources?: KBSource[]
}

const messages = ref<ChatMessage[]>([
  { role: 'assistant', content: '你好！我可以基于知识库内容回答问题。上传文档后，直接提问即可。', type: 'chat' },
])

const messagesRef = ref<HTMLElement | null>(null)
const chatMessage = ref('')
const generating = ref(false)
const expandedSources = ref<Set<string>>(new Set())
const suggestions = ref<string[]>([])
const loadingSuggestions = ref(false)

watch(() => props.kbId, () => { loadSuggestions() }, { immediate: true })

function sourceKey(msgIdx: number, srcIdx: number): string {
  return `${msgIdx}-${srcIdx}`
}

function isSourceExpanded(msgIdx: number, srcIdx: number): boolean {
  return expandedSources.value.has(sourceKey(msgIdx, srcIdx))
}

function toggleSource(msgIdx: number, srcIdx: number) {
  const key = sourceKey(msgIdx, srcIdx)
  const s = new Set(expandedSources.value)
  if (s.has(key)) {
    s.delete(key)
  } else {
    s.add(key)
  }
  expandedSources.value = s
}

function renderMarkdown(text: string): string {
  return marked.parse(text, { async: false }) as string
}

function renderMsgHtml(msg: ChatMessage): string {
  let html = renderMarkdown(msg.content)
  if (msg.streaming) {
    const cursor = '<span class="streaming-cursor">▊</span>'
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

  const convId = store.currentConvId
  const docIds = store.kbSelectedDocIds

  if (convId) {
    await store.saveConvMessage(convId, 'user', msg, 'chat')
  }

  kbStreamChat(props.kbId, msg, docIds, {
    onChunk(text) {
      messages.value[msgIdx].content += text
      scrollToBottom()
    },
    onSources(sources) {
      messages.value[msgIdx].sources = sources
    },
    onPrompt() {},
    onDone() {
      pushDone(msgIdx)
    },
    onError(err) {
      pushError(msgIdx, `请求失败：${err}`)
    },
  }, 5, convId)
}

function generateArticle(style: StyleType) {
  if (generating.value) return

  const styleLabels: Record<string, string> = {
    xiaohongshu: '小红书',
    wechat_mp: '公众号',
    douyin: '抖音',
  }

  ElMessageBox.prompt('', `生成${styleLabels[style]}风格文章`, {
    confirmButtonText: '生成',
    cancelButtonText: '取消',
    inputPlaceholder: '输入额外要求（可选，如：聚焦新能源、强调数据对比...）',
    inputType: 'textarea',
    inputAttrs: { rows: 3 },
  }).then(({ value }) => {
    doGenerate(style, value || '')
  }).catch(() => {})
}

function doGenerate(style: StyleType, extraReq: string) {
  const styleLabels: Record<string, string> = {
    xiaohongshu: '小红书',
    wechat_mp: '公众号',
    douyin: '抖音',
  }

  const label = `用${styleLabels[style]}风格生成文章`
  const userMsg = extraReq ? `${label}\n${extraReq}` : label
  pushUserMessage(userMsg)
  generating.value = true

  const msgIdx = addAssistantMessage('article')
  scrollToBottom()

  const convId = store.currentConvId
  const docIds = store.kbSelectedDocIds

  kbStreamGenerate(props.kbId, userMsg, style, {
    onChunk(text) {
      messages.value[msgIdx].content += text
      scrollToBottom()
    },
    onSources(sources) {
      messages.value[msgIdx].sources = sources
    },
    onDone() {
      pushDone(msgIdx)
    },
    onError(err) {
      pushError(msgIdx, `生成失败：${err}`)
    },
  }, docIds, 5, convId)
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
    const res = await publishByContent(title, content, platform, imageOptions)
    store.startTaskStream()
    store.showTaskPanel = true
    await store.loadTasks()
    ElMessage.success(`已提交发布到${label}，请在任务列表中查看进度`)
  } catch (e: any) {
    ElMessage.error(`发布失败：${e.message || '未知错误'}`)
  }
}

function loadHistory(historyMessages: KBMessage[]) {
  messages.value = [
    { role: 'assistant', content: '你好！我可以基于知识库内容回答问题。上传文档后，直接提问即可。', type: 'chat' },
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
    { role: 'assistant', content: '你好！我可以基于知识库内容回答问题。上传文档后，直接提问即可。', type: 'chat' },
  ]
}

defineExpose({ generateArticle, loadHistory, clearMessages, loadSuggestions })
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

.msg-sources {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.source-card {
  background: #fff;
  border: 1px solid #eef0f5;
  border-radius: 8px;
  padding: 8px 12px;
  font-size: 12px;
  transition: border-color 0.15s;
}

.source-card.expanded {
  border-color: #c7d2fe;
}

.source-header {
  display: flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
  user-select: none;
}

.source-header:hover {
  opacity: 0.75;
}

.source-file {
  font-weight: 500;
  color: #6366f1;
  font-size: 12px;
}

.source-page {
  background: #eef2ff;
  color: #6366f1;
  padding: 0 5px;
  border-radius: 3px;
  font-size: 10px;
  font-weight: 600;
}

.source-score {
  color: #94a3b8;
  font-size: 11px;
}

.source-toggle {
  margin-left: auto;
  font-size: 11px;
  color: #a5b4fc;
}

.source-preview {
  color: #64748b;
  line-height: 1.45;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  margin-top: 4px;
}

.source-full {
  color: #334155;
  line-height: 1.65;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 200px;
  overflow-y: auto;
  background: #f8fafc;
  border-radius: 6px;
  padding: 8px 10px;
  margin-top: 6px;
  font-size: 12px;
  border: 1px solid #eef0f5;
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
  0%, 50% { opacity: 1; }
  51%, 100% { opacity: 0; }
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
  transition: border-color 0.15s, box-shadow 0.15s;
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
