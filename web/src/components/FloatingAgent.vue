<template>
  <!-- Bubble button (collapsed) -->
  <div
    v-if="!embedded && !expanded"
    class="agent-bubble"
    :style="props.offsetRight ? { right: (48 + props.offsetRight) + 'px' } : {}"
    @click="openPanel"
  >
    <div class="bubble-inner" @click="openPanel">
      <svg width="28" height="28" viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg">
        <defs>
          <linearGradient id="techGrad1" x1="0" y1="0" x2="48" y2="48" gradientUnits="userSpaceOnUse">
            <stop offset="0%" stop-color="#7c3aed"/>
            <stop offset="50%" stop-color="#8b5cf6"/>
            <stop offset="100%" stop-color="#7c3aed"/>
          </linearGradient>
          <linearGradient id="techGrad2" x1="0" y1="0" x2="48" y2="48" gradientUnits="userSpaceOnUse">
            <stop offset="0%" stop-color="#38bdf8"/>
            <stop offset="100%" stop-color="#a78bfa"/>
          </linearGradient>
          <radialGradient id="coreGlow" cx="24" cy="24" r="9" gradientUnits="userSpaceOnUse">
            <stop offset="0%" stop-color="#7c3aed" stop-opacity="0.95"/>
            <stop offset="50%" stop-color="#8b5cf6" stop-opacity="0.45"/>
            <stop offset="100%" stop-color="#c4b5fd" stop-opacity="0"/>
          </radialGradient>
        </defs>
        <path d="M24 4 L42 14 L42 34 L24 44 L6 34 L6 14 Z" stroke="url(#techGrad1)" stroke-width="1.5" fill="none" opacity="0.55">
          <animateTransform attributeName="transform" type="rotate" from="0 24 24" to="360 24 24" dur="14s" repeatCount="indefinite"/>
        </path>
        <path d="M24 8 L38.5 16.5 L38.5 31.5 L24 40 L9.5 31.5 L9.5 16.5 Z" stroke="url(#techGrad2)" stroke-width="1" fill="none" opacity="0.4">
          <animateTransform attributeName="transform" type="rotate" from="360 24 24" to="0 24 24" dur="11s" repeatCount="indefinite"/>
        </path>
        <circle cx="24" cy="24" r="9" fill="url(#coreGlow)">
          <animate attributeName="r" values="9;10.5;9" dur="3s" repeatCount="indefinite"/>
        </circle>
        <circle cx="24" cy="24" r="4.5" fill="#7c3aed" opacity="0.9">
          <animate attributeName="opacity" values="0.9;0.6;0.9" dur="2.5s" repeatCount="indefinite"/>
        </circle>
        <circle cx="24" cy="24" r="2" fill="#fff" opacity="0.95"/>
        <g stroke="url(#techGrad2)" stroke-width="0.9" opacity="0.55" stroke-linecap="round">
          <line x1="24" y1="15.5" x2="24" y2="12">
            <animate attributeName="opacity" values="0.55;0.2;0.55" dur="3.5s" repeatCount="indefinite"/>
          </line>
          <line x1="31.5" y1="20" x2="34" y2="18">
            <animate attributeName="opacity" values="0.2;0.55;0.2" dur="3.5s" begin="0.6s" repeatCount="indefinite"/>
          </line>
          <line x1="31.5" y1="28" x2="34" y2="30">
            <animate attributeName="opacity" values="0.55;0.2;0.55" dur="3.5s" begin="1.2s" repeatCount="indefinite"/>
          </line>
          <line x1="24" y1="32.5" x2="24" y2="36">
            <animate attributeName="opacity" values="0.2;0.55;0.2" dur="3.5s" begin="1.8s" repeatCount="indefinite"/>
          </line>
          <line x1="16.5" y1="28" x2="14" y2="30">
            <animate attributeName="opacity" values="0.55;0.2;0.55" dur="3.5s" begin="2.4s" repeatCount="indefinite"/>
          </line>
          <line x1="16.5" y1="20" x2="14" y2="18">
            <animate attributeName="opacity" values="0.2;0.55;0.2" dur="3.5s" begin="3s" repeatCount="indefinite"/>
          </line>
        </g>
      </svg>
    </div>
  </div>

  <!-- Chat panel (expanded) -->
  <div
    v-if="embedded || expanded"
    class="agent-panel"
    :class="[{ dragging: isDragging || isResizing, docked: dockedRight, undocking: undocking }, { 'agent-panel-embedded': embedded }]"
    :style="panelStyle"
    ref="panelRef"
  >
    <!-- Draggable header -->
    <div class="panel-header" :class="{ 'panel-header-embedded': embedded }" @mousedown="startDrag">
      <div class="header-left">
        <svg width="20" height="20" viewBox="0 0 48 48" fill="none">
          <path d="M24 8 L38.5 16.5 L38.5 31.5 L24 40 L9.5 31.5 L9.5 16.5 Z" stroke="#a78bfa" stroke-width="1.5" fill="none" opacity="0.6"/>
          <circle cx="24" cy="24" r="7" fill="#ede9fe" opacity="0.8"/>
          <circle cx="24" cy="24" r="3" fill="#7c3aed" opacity="0.85"/>
          <g stroke="#a78bfa" stroke-width="0.8" opacity="0.45" stroke-linecap="round">
            <line x1="24" y1="17" x2="24" y2="14"/>
            <line x1="30" y1="20.5" x2="33" y2="19"/>
            <line x1="30" y1="27.5" x2="33" y2="29"/>
            <line x1="24" y1="31" x2="24" y2="34"/>
            <line x1="18" y1="27.5" x2="15" y2="29"/>
            <line x1="18" y1="20.5" x2="15" y2="19"/>
          </g>
        </svg>
        <span>AI 助手</span>
      </div>
      <div class="header-actions">
        <span class="header-btn" title="历史会话" @mousedown.stop @click.stop="toggleConvList">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
        </span>
        <span class="header-btn" title="新对话" @mousedown.stop @click.stop="startNewConversation">+</span>
        <span v-if="!embedded" class="header-btn" @mousedown.stop @click.stop="closePanel">✕</span>
      </div>
    </div>

    <!-- Conversation list sidebar -->
    <div v-if="showConvList" class="conv-sidebar">
      <div class="conv-sidebar-header">
        <span>历史会话</span>
        <span class="conv-close-btn" @click="showConvList = false">✕</span>
      </div>
      <div class="conv-sidebar-body">
        <div
          v-for="conv in convList"
          :key="conv.id"
          class="conv-item"
          :class="{ active: conv.id === currentConversationId }"
          @click="switchConversation(conv.id)"
        >
          <div class="conv-item-title">{{ conv.title }}</div>
          <div class="conv-item-time">{{ conv.updated_at?.slice(5, 16) }}</div>
          <span class="conv-item-delete" title="删除" @click.stop="deleteConv(conv.id)">✕</span>
        </div>
        <div v-if="convList.length === 0" class="conv-empty">暂无历史会话</div>
      </div>
    </div>

    <!-- Messages -->
    <div class="panel-body" ref="messagesRef">
      <div
        v-for="(msg, i) in messages"
        :key="i"
        class="msg-row"
        :class="msg.role"
      >
        <div class="msg-avatar">
          <div v-if="msg.role === 'assistant'" class="avatar-ai">🤖</div>
          <div v-else class="avatar-user">我</div>
        </div>
        <div class="msg-bubble-wrap">
          <div class="msg-bubble">
            <div v-if="msg.prompt" class="prompt-block">
              <div class="prompt-header" @click="msg.promptExpanded = !msg.promptExpanded">
                <span>Prompt</span>
                <span class="prompt-toggle">{{ msg.promptExpanded ? '▲' : '▼' }}</span>
              </div>
              <div v-if="msg.promptExpanded" class="prompt-body">{{ msg.prompt }}</div>
            </div>
            <div class="msg-content" v-html="renderMsgHtml(msg)"></div>
          </div>
          <!-- Action buttons for completed results -->
          <div
            v-if="msg.role === 'assistant' && !msg.streaming && msg.content"
            class="msg-actions"
          >
            <button class="msg-action-btn" @click="copyContent(msg.content)">📋 复制</button>
            <el-dropdown trigger="click" @command="(p: string) => onPublishCommand(msg, p)">
              <button class="msg-action-btn">📤 发布到 ▾</button>
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
    </div>

    <!-- Footer -->
    <div class="panel-footer">
      <!-- Toolbar row: context tags + action chips -->
      <div class="toolbar">
        <div class="toolbar-left">
          <span v-if="store.currentDetailNews" class="ctx-tag">
            {{ store.currentDetailNews.title?.slice(0, 16) }}{{ (store.currentDetailNews.title?.length || 0) > 16 ? '…' : '' }}
          </span>
          <span v-if="store.selectedNewsIds.length > 0" class="ctx-tag">已选 {{ store.selectedNewsIds.length }} 条</span>
        </div>
        <div class="toolbar-right">
          <button v-if="isNewsPage" :disabled="generating" @click="fetchTrends">热点</button>
          <button v-if="isNewsPage" :disabled="generating" @click="openBriefing">简报</button>
        </div>
      </div>
      <!-- Input area -->
      <div class="input-area">
        <button
          class="web-search-btn"
          :class="{ active: webSearchEnabled }"
          :title="webSearchEnabled ? '联网搜索已开启' : '开启联网搜索'"
          @click="webSearchEnabled = !webSearchEnabled"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="11" cy="11" r="8"/>
            <line x1="21" y1="21" x2="16.65" y2="16.65"/>
          </svg>
        </button>
        <el-input
          v-model="chatMessage"
          type="textarea"
          :autosize="{ minRows: 1, maxRows: 5 }"
          placeholder="输入消息，Enter 发送，Shift+Enter 换行"
          :disabled="generating"
          @keydown.enter.exact="onInputEnter"
          class="chat-input"
        />
        <button class="send-btn" :disabled="!chatMessage.trim() || generating" @click="sendChat">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
            <path d="M5 12H19M19 12L13 6M19 12L13 18" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
          </svg>
        </button>
      </div>
    </div>

    <!-- WeChat AI image options dialog -->
    <WechatImageOptionsDialog
      v-model="imageOptsVisible"
      v-model:generate-cover="imageOpts.generate_cover"
      v-model:generate-inline-images="imageOpts.generate_inline_images"
      @confirm="confirmPublish"
      @cancel="cancelPublish"
    />

    <!-- Snap preview zone -->
    <div
      v-if="isDragging && snapPreview"
      class="snap-preview"
    ></div>

    <!-- Resize handles -->
    <template v-if="!embedded && !dockedRight">
      <div class="resize-handle resize-t" @mousedown.stop="(e) => startResize(e, 't')"></div>
      <div class="resize-handle resize-tl" @mousedown.stop="(e) => startResize(e, 'tl')"></div>
      <div class="resize-handle resize-tr" @mousedown.stop="(e) => startResize(e, 'tr')"></div>
      <div class="resize-handle resize-r" @mousedown.stop="(e) => startResize(e, 'r')"></div>
      <div class="resize-handle resize-b" @mousedown.stop="(e) => startResize(e, 'b')"></div>
      <div class="resize-handle resize-bl" @mousedown.stop="(e) => startResize(e, 'bl')"></div>
      <div class="resize-handle resize-br" @mousedown.stop="(e) => startResize(e, 'br')"></div>
    </template>
    <div v-if="!embedded" class="resize-handle resize-l" @mousedown.stop="(e) => startResize(e, 'l')"></div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, nextTick, onMounted, onBeforeUnmount, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { useRoute } from 'vue-router'
import { useNewsStore } from '@/stores'
import { streamAgentChat, publishArticle as apiPublishArticle, publishByContent, fetchTrends as apiFetchTrends, compareSources as apiCompareSources, searchNews as apiSearchNews, streamBriefing, listConversations, getConversationMessages, deleteConversation as apiDeleteConversation } from '@/api'
import type { AgentAction, Conversation } from '@/api'
import type { ImagePublishOptions } from '@/composables/useWechatPublish'
import { useWechatPublish } from '@/composables/useWechatPublish'
import WechatImageOptionsDialog from '@/components/WechatImageOptionsDialog.vue'
import { renderSafeMarkdown } from '@/utils/markdown'

const props = withDefaults(defineProps<{ offsetRight?: number; embedded?: boolean }>(), { offsetRight: 0, embedded: false })
const store = useNewsStore()
const route = useRoute()
const isNewsPage = computed(() => route.name === 'news')
const { imageOptsVisible, imageOpts, needImageOptions, confirmPublish, cancelPublish } = useWechatPublish()

const expanded = ref(false)
const isDragging = ref(false)
const isResizing = ref(false)
const resizeDir = ref<'t' | 'b' | 'l' | 'r' | 'tl' | 'tr' | 'bl' | 'br' | null>(null)
const panelPos = ref({ x: 0, y: 0 })
const panelW = ref(380)
const panelH = ref(620)
const dragOffset = ref({ x: 0, y: 0 })
const resizeStart = ref({ x: 0, y: 0, w: 0, h: 0, px: 0, py: 0 })
const dockedRight = ref(true)
const preDockW = ref(380)
const preDockH = ref(620)
const undocking = ref(false)

const SNAP_THRESHOLD = 20

const MIN_W = 340
const MIN_H = 420

watch([dockedRight, panelW], () => {
  store.agentDockedRight = dockedRight.value
  store.agentPanelWidth = panelW.value
})

const messagesRef = ref<HTMLElement | null>(null)
const chatMessage = ref('')
const generating = ref(false)
const webSearchEnabled = ref(false)
const currentConversationId = ref<string | null>(null)
const showConvList = ref(false)
const convList = ref<Conversation[]>([])

interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  streaming?: boolean
  prompt?: string
  promptExpanded?: boolean
  type?: 'chat' | 'interpret' | 'article'
  articleId?: string
  style?: string
  newsIds?: string[]
}

const messages = ref<ChatMessage[]>([
  { role: 'assistant', content: '你好！我可以和你聊天、解读新闻、搜索热点、生成文章，还能帮你执行网站操作。直接说就行！', type: 'chat' },
])

const panelStyle = computed(() => {
  if (props.embedded) {
    return {
      width: '100%',
      height: '100%',
      borderRadius: '0',
    }
  }
  if (dockedRight.value) {
    return {
      right: '24px',
      left: 'auto',
      bottom: '24px',
      top: 'auto',
      width: panelW.value + 'px',
      height: panelH.value + 'px',
      borderRadius: '12px',
    }
  }
  return {
    left: panelPos.value.x + 'px',
    top: panelPos.value.y + 'px',
    width: panelW.value + 'px',
    height: panelH.value + 'px',
  }
})

const snapPreview = computed(() => {
  if (!isDragging.value) return false
  const vx = window.innerWidth
  const rightEdge = panelPos.value.x + panelW.value
  return rightEdge >= vx - SNAP_THRESHOLD
})

function openPanel() {
  expanded.value = true
  dockedRight.value = true
}

function closePanel() {
  expanded.value = false
  dockedRight.value = false
}

function renderMarkdown(text: string): string {
  return renderSafeMarkdown(text)
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

function addAssistantMessage(type: ChatMessage['type'] = 'chat'): number {
  const msg: ChatMessage = { role: 'assistant', content: '', streaming: true, type }
  messages.value.push(msg)
  return messages.value.length - 1
}

function pushUserMessage(text: string) {
  messages.value.push({ role: 'user', content: text, type: 'chat' })
}

function pushAssistantDone(msgIdx: number) {
  messages.value[msgIdx].streaming = false
  generating.value = false
  scrollToBottom()
}

function pushAssistantError(msgIdx: number, err: string) {
  messages.value[msgIdx].content += `\n\n❌ ${err}`
  messages.value[msgIdx].streaming = false
  generating.value = false
  scrollToBottom()
}

// ── Publish ─────────────────────────────────────────────────

async function onPublishCommand(msg: ChatMessage, platform: string) {
  if (platform === 'wechat_mp') {
    const imageOptions = await needImageOptions()
    if (imageOptions) {
      await doPublish(msg, platform, imageOptions)
    }
  } else {
    await doPublish(msg, platform)
  }
}

async function doPublish(msg: ChatMessage, platform: string, imageOptions?: ImagePublishOptions) {
  const platformLabels: Record<string, string> = {
    xiaohongshu: '小红书',
    wechat_mp: '微信公众号',
    douyin: '抖音',
  }
  try {
    if (msg.articleId) {
      await apiPublishArticle(msg.articleId, platform, imageOptions ? { generate_cover: imageOptions.generate_cover, generate_inline_images: imageOptions.generate_inline_images } : undefined)
    } else {
      const title = msg.content.split('\n').find(l => l.trim() && !l.trim().startsWith('#'))?.trim()?.slice(0, 30) || 'AI 生成内容'
      await publishByContent(title, msg.content, platform, imageOptions)
    }
    store.startTaskStream()
    store.showTaskPanel = true
    await store.loadTasks()
    ElMessage.success(`已提交发布到${platformLabels[platform] || platform}，请在任务列表中查看进度`)
  } catch (e: any) {
    ElMessage.error(`发布失败：${e.message}`)
  }
}

// ── Copy ────────────────────────────────────────────────────

function copyContent(text: string) {
  navigator.clipboard.writeText(text).then(() => {
    ElMessage.success('已复制到剪贴板')
  }).catch(() => {
    ElMessage.error('复制失败')
  })
}

// ── Smart: Trends ──────────────────────────────────────────

async function fetchTrends() {
  if (generating.value) return

  pushUserMessage('今天有什么热点？')
  generating.value = true
  const msgIdx = addAssistantMessage('chat')
  scrollToBottom()

  try {
    const data = await apiFetchTrends(10)
    if (!data.trends.length) {
      messages.value[msgIdx].content = '当前没有新闻数据，请先爬取新闻。'
      pushAssistantDone(msgIdx)
      return
    }

    let text = `📊 **今日热点 Top ${data.trends.length}**（共 ${data.total_news} 条新闻）\n\n`
    for (const t of data.trends) {
      const sources = t.source_count > 1 ? ` (${t.source_count} 个源)` : ''
      text += `- **${t.keyword}** — 出现 ${t.count} 次${sources}\n`
      for (const n of t.related_news.slice(0, 3)) {
        text += `  - ${n.title}\n`
      }
    }
    text += '\n> 点击热点关键词，可以输入"对比 [关键词]"查看多源差异分析。'
    messages.value[msgIdx].content = text
    pushAssistantDone(msgIdx)
  } catch (e: any) {
    pushAssistantError(msgIdx, `获取热点失败：${e.message}`)
  }
}

// ── Smart: Briefing ────────────────────────────────────────

function openBriefing() {
  if (generating.value) return

  pushUserMessage('生成今日要闻简报')
  generating.value = true
  const msgIdx = addAssistantMessage('chat')
  scrollToBottom()

  streamBriefing({
    onLoading(message) {
      messages.value[msgIdx].content = `⏳ ${message}`
      scrollToBottom()
    },
    onChunk(text) {
      if (messages.value[msgIdx].content.startsWith('⏳')) {
        messages.value[msgIdx].content = ''
      }
      messages.value[msgIdx].content += text
      scrollToBottom()
    },
    onDone() {
      pushAssistantDone(msgIdx)
    },
    onError(err) {
      pushAssistantError(msgIdx, `生成简报失败：${err}`)
    },
  })
}

// ── Smart: Chat with command detection ─────────────────────

const CMD_PATTERNS: [RegExp, (match: RegExpMatchArray) => void][] = [
  [/^\/热点$/, () => fetchTrends()],
  [/^\/简报$/, () => openBriefing()],
  [/^对比\s+(.+)/, (m) => doCompare(m[1].trim())],
  [/^搜索\s+(.+)/, (m) => doSearch(m[1].trim())],
]

async function doCompare(keyword: string) {
  pushUserMessage(`对比不同媒体对「${keyword}」的报道`)
  generating.value = true
  const msgIdx = addAssistantMessage('chat')
  scrollToBottom()

  try {
    const data = await apiCompareSources(keyword)
    messages.value[msgIdx].content = data.comparison
    pushAssistantDone(msgIdx)
  } catch (e: any) {
    pushAssistantError(msgIdx, `对比分析失败：${e.message}`)
  }
}

async function doSearch(keyword: string) {
  pushUserMessage(`搜索：${keyword}`)
  generating.value = true
  const msgIdx = addAssistantMessage('chat')
  scrollToBottom()

  try {
    const data = await apiSearchNews(keyword)
    if (!data.total) {
      messages.value[msgIdx].content = `没有找到与「${keyword}」相关的新闻。`
      pushAssistantDone(msgIdx)
      return
    }

    let text = `🔍 搜索「${keyword}」— 找到 ${data.total} 条\n\n`
    for (const n of data.items.slice(0, 10)) {
      text += `- **${n.title}** (${n.source})\n`
    }
    if (data.total > 10) {
      text += `\n> 还有 ${data.total - 10} 条结果...`
    }
    messages.value[msgIdx].content = text
    pushAssistantDone(msgIdx)
  } catch (e: any) {
    pushAssistantError(msgIdx, `搜索失败：${e.message}`)
  }
}

// ── Handle agent action ──────────────────────────────────────

async function handleAction(action: AgentAction) {
  generating.value = false
  const act = action.action
  try {
    if (act === 'refresh_news') {
      await store.loadNews()
      ElMessage.success('新闻已刷新')
    } else if (act === 'refresh_source') {
      const src = action.source || store.currentSource
      await store.loadNews(src)
      ElMessage.success(`${src} 已刷新`)
    } else if (act === 'generate_article') {
      // 将 article_id 存储到最后一条 assistant 消息，以便发布
      const lastAssistantIdx = [...messages.value].map((m, i) => ({ m, i })).filter(x => x.m.role === 'assistant').pop()?.i
      if (lastAssistantIdx !== undefined && action.article_id) {
        messages.value[lastAssistantIdx].articleId = action.article_id
      }
    } else {
      console.warn('未处理的工具类型:', act)
    }
  } catch (error) {
    console.error('工具执行失败:', error)
    ElMessage.error(`操作失败: ${error instanceof Error ? error.message : '未知错误'}`)
  }
}

// ── Chat ────────────────────────────────────────────────────

function startNewConversation() {
  currentConversationId.value = null
  showConvList.value = false
  messages.value = [
    { role: 'assistant', content: '你好！我可以和你聊天、解读新闻、搜索热点、生成文章，还能帮你执行网站操作。直接说就行！', type: 'chat' },
  ]
}

async function toggleConvList() {
  showConvList.value = !showConvList.value
  if (showConvList.value) {
    await loadConvList()
  }
}

async function loadConvList() {
  try {
    const data = await listConversations(50)
    convList.value = data.items
  } catch {
    convList.value = []
  }
}

async function switchConversation(convId: string) {
  if (convId === currentConversationId.value) {
    showConvList.value = false
    return
  }
  try {
    const data = await getConversationMessages(convId)
    currentConversationId.value = convId
    showConvList.value = false
    // Rebuild messages from history
    const loaded: ChatMessage[] = []
    for (const msg of data.messages) {
      if (msg.role === 'user' || msg.role === 'assistant') {
        loaded.push({ role: msg.role, content: msg.content, type: 'chat' })
      }
    }
    messages.value = loaded.length > 0
      ? loaded
      : [{ role: 'assistant', content: '你好！我可以和你聊天、解读新闻、搜索热点、生成文章，还能帮你执行网站操作。直接说就行！', type: 'chat' }]
    scrollToBottom()
  } catch (e: any) {
    ElMessage.error('加载会话失败')
  }
}

async function deleteConv(convId: string) {
  try {
    await apiDeleteConversation(convId)
    if (convId === currentConversationId.value) {
      startNewConversation()
    }
    await loadConvList()
  } catch {
    ElMessage.error('删除失败')
  }
}

function onInputEnter(e: KeyboardEvent) {
  if (e.ctrlKey || e.shiftKey) return
  e.preventDefault()
  sendChat()
}

async function sendChat() {
  const msg = chatMessage.value.trim()
  if (!msg || generating.value) return

  for (const [pattern, handler] of CMD_PATTERNS) {
    const match = msg.match(pattern)
    if (match) {
      chatMessage.value = ''
      handler(match)
      return
    }
  }

  pushUserMessage(msg)
  chatMessage.value = ''
  generating.value = true

  const msgIdx = addAssistantMessage('chat')
  scrollToBottom()

  const currentNewsId = store.currentDetailNews?.news_id
  const newsIds = store.selectedNewsIds.length > 0 ? store.selectedNewsIds : (currentNewsId ? [currentNewsId] : [])

  let currentMsgIdx = msgIdx
  let isLoading = false
  let pendingActions: AgentAction[] = []

  streamAgentChat(msg, newsIds, {
    onPrompt(prompt) {
      messages.value[currentMsgIdx].prompt = prompt
      messages.value[currentMsgIdx].promptExpanded = false
    },
    onLoading(message) {
      isLoading = true
      messages.value[currentMsgIdx].content = `⏳ ${message}`
      scrollToBottom()
    },
    onLoadingDone() {
      isLoading = false
      if (messages.value[currentMsgIdx].content.startsWith('⏳')) {
        messages.value[currentMsgIdx].content = ''
      }
    },
    onChunk(text) {
      if (isLoading) {
        isLoading = false
        messages.value[currentMsgIdx].content = ''
      }
      messages.value[currentMsgIdx].content += text
      scrollToBottom()
    },
    onAction(action) {
      pendingActions.push(action)
    },
    onConversationId(id) {
      currentConversationId.value = id
    },
    onDone() {
      const content = messages.value[currentMsgIdx].content.trim()
      if (!content || content.startsWith('⏳')) {
        messages.value.splice(currentMsgIdx, 1)
      } else {
        pushAssistantDone(currentMsgIdx)
      }
      generating.value = false
      for (const action of pendingActions) {
        handleAction(action)
      }
      pendingActions = []
    },
    onError(err) {
      pushAssistantError(currentMsgIdx, `请求失败：${err}`)
    },
  }, currentNewsId, webSearchEnabled.value, currentConversationId.value ?? undefined)
}

// ── Drag ────────────────────────────────────────────────────

function startDrag(e: MouseEvent) {
  if (props.embedded) return
  e.preventDefault()
  if (dockedRight.value) {
    preDockW.value = panelW.value
    preDockH.value = panelH.value
    const vx = window.innerWidth
    const vy = window.innerHeight
    panelPos.value = { x: vx - panelW.value - 24, y: vy - panelH.value - 24 }
    dockedRight.value = false
  }
  isDragging.value = true
  dragOffset.value = {
    x: e.clientX - panelPos.value.x,
    y: e.clientY - panelPos.value.y,
  }
  document.body.style.cursor = 'move'
  document.body.style.userSelect = 'none'
}

// ── Resize ──────────────────────────────────────────────────

function startResize(e: MouseEvent, dir: 't' | 'b' | 'l' | 'r' | 'tl' | 'tr' | 'bl' | 'br') {
  if (props.embedded) return
  e.preventDefault()
  e.stopPropagation()
  isResizing.value = true
  resizeDir.value = dir
  let actualPx = panelPos.value.x
  let actualPy = panelPos.value.y
  if (dockedRight.value) {
    actualPx = window.innerWidth - panelW.value - 24
    actualPy = window.innerHeight - panelH.value - 24
  }
  resizeStart.value = {
    x: e.clientX,
    y: e.clientY,
    w: panelW.value,
    h: panelH.value,
    px: actualPx,
    py: actualPy,
  }
  const cursors: Record<string, string> = {
    t: 'n-resize', b: 's-resize', l: 'w-resize', r: 'e-resize',
    tl: 'nw-resize', tr: 'ne-resize', bl: 'sw-resize', br: 'se-resize',
  }
  document.body.style.cursor = cursors[dir] || 'default'
  document.body.style.userSelect = 'none'
}

function onMouseMove(e: MouseEvent) {
  if (isDragging.value) {
    const vx = window.innerWidth
    const vy = window.innerHeight
    let nx = e.clientX - dragOffset.value.x
    let ny = e.clientY - dragOffset.value.y
    nx = Math.max(0, Math.min(vx - panelW.value, nx))
    ny = Math.max(0, Math.min(vy - panelH.value, ny))
    panelPos.value = { x: nx, y: ny }
  } else if (isResizing.value) {
    const dx = e.clientX - resizeStart.value.x
    const dy = e.clientY - resizeStart.value.y
    const dir = resizeDir.value
    if (!dir) return

    if (dockedRight.value) {
      let newW = resizeStart.value.w
      let newH = resizeStart.value.h
      if (dir === 'l' || dir === 'tl' || dir === 'bl') {
        newW = Math.max(MIN_W, resizeStart.value.w - dx)
      }
      if (dir === 'r' || dir === 'tr' || dir === 'br') {
        newW = Math.max(MIN_W, resizeStart.value.w + dx)
      }
      if (dir === 't' || dir === 'tl' || dir === 'tr') {
        newH = Math.max(MIN_H, resizeStart.value.h - dy)
      }
      if (dir === 'b' || dir === 'bl' || dir === 'br') {
        newH = Math.max(MIN_H, resizeStart.value.h + dy)
      }
      const vx = window.innerWidth
      const vy = window.innerHeight
      newW = Math.min(newW, vx - 24)
      newH = Math.min(newH, vy - 24)
      panelW.value = Math.max(MIN_W, newW)
      panelH.value = Math.max(MIN_H, newH)
      return
    }

    let newW = resizeStart.value.w
    let newH = resizeStart.value.h
    let newX = resizeStart.value.px
    let newY = resizeStart.value.py

    if (dir === 'r' || dir === 'tr' || dir === 'br') {
      newW = Math.max(MIN_W, resizeStart.value.w + dx)
    }
    if (dir === 'l' || dir === 'tl' || dir === 'bl') {
      newW = Math.max(MIN_W, resizeStart.value.w - dx)
      newX = resizeStart.value.px + resizeStart.value.w - newW
    }
    if (dir === 'b' || dir === 'bl' || dir === 'br') {
      newH = Math.max(MIN_H, resizeStart.value.h + dy)
    }
    if (dir === 't' || dir === 'tl' || dir === 'tr') {
      newH = Math.max(MIN_H, resizeStart.value.h - dy)
      newY = resizeStart.value.py + resizeStart.value.h - newH
    }

    const vx = window.innerWidth
    const vy = window.innerHeight
    if (newX < 0) { newW += newX; newX = 0 }
    if (newY < 0) { newH += newY; newY = 0 }
    if (newX + newW > vx) newW = vx - newX
    if (newY + newH > vy) newH = vy - newY

    panelW.value = Math.max(MIN_W, newW)
    panelH.value = Math.max(MIN_H, newH)
    panelPos.value = { x: newX, y: newY }
  }
}

function onMouseUp() {
  if (isDragging.value) {
    isDragging.value = false
    document.body.style.cursor = ''
    const vx = window.innerWidth
    const rightEdge = panelPos.value.x + panelW.value
    if (rightEdge >= vx - SNAP_THRESHOLD) {
      preDockW.value = panelW.value
      preDockH.value = panelH.value
      dockedRight.value = true
    }
  }
  if (isResizing.value) {
    isResizing.value = false
    resizeDir.value = null
    document.body.style.cursor = ''
  }
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
</script>

<style scoped>
.agent-bubble {
  position: fixed;
  bottom: 48px;
  right: 48px;
  z-index: 2100;
  cursor: pointer;
}

.bubble-inner {
  width: 56px;
  height: 56px;
  border-radius: 18px;
  background: linear-gradient(135deg, #ede9fe 0%, #dbeafe 50%, #ede9fe 100%);
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 3px 16px rgba(139, 92, 246, 0.3), 0 1px 4px rgba(59, 130, 246, 0.15);
  transition: transform 0.25s, box-shadow 0.25s;
  border: 2px solid rgba(167, 139, 250, 0.35);
  position: relative;
}

.bubble-inner::before {
  content: '';
  position: absolute;
  inset: -3px;
  border-radius: 21px;
  background: conic-gradient(from 0deg, #a78bfa, #7dd3fc, #c4b5fd, #7dd3fc, #a78bfa);
  opacity: 0;
  transition: opacity 0.3s;
  z-index: -1;
  animation: borderSpin 6s linear infinite;
}

@keyframes borderSpin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.bubble-inner:hover {
  transform: scale(1.08);
  box-shadow: 0 6px 28px rgba(139, 92, 246, 0.4), 0 2px 8px rgba(59, 130, 246, 0.2);
}

.bubble-inner:hover::before {
  opacity: 0.55;
}

.bubble-inner::before {
  content: '';
  position: absolute;
  inset: -2px;
  border-radius: 18px;
  background: conic-gradient(from 0deg, #06b6d4, #8b5cf6, #06b6d4);
  opacity: 0;
  transition: opacity 0.3s;
  z-index: -1;
  animation: borderSpin 4s linear infinite;
}

@keyframes borderSpin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.bubble-inner:hover {
  transform: scale(1.08);
  box-shadow: 0 6px 24px rgba(196, 181, 253, 0.45), 0 2px 8px rgba(186, 230, 253, 0.3);
}

.bubble-inner:hover::before {
  opacity: 0.6;
}

.agent-panel {
  position: fixed;
  z-index: 2000;
  display: flex;
  flex-direction: column;
  border-radius: 14px;
  background: #fff;
  box-shadow: 0 8px 40px rgba(0, 0, 0, 0.08), 0 0 0 1px rgba(99, 102, 241, 0.06);
  overflow: hidden;
  transition: left 0.25s ease, top 0.25s ease, width 0.25s ease, height 0.25s ease, border-radius 0.25s ease;
}

.agent-panel.dragging {
  user-select: none;
  transition: none;
}

.agent-panel.undocking {
  transition: left 0.3s ease, top 0.3s ease, width 0.3s ease, height 0.3s ease, border-radius 0.3s ease;
}

.snap-preview {
  position: fixed;
  right: 0;
  top: 0;
  width: 4px;
  height: 100vh;
  background: linear-gradient(135deg, #3b82f6, #6366f1);
  opacity: 0.5;
  z-index: 1999;
  pointer-events: none;
  border-radius: 0 0 0 2px;
}

.agent-panel.agent-panel-embedded {
  position: relative;
  border-radius: 0;
  box-shadow: none;
  border-left: 1px solid #e0e7ff;
  transition: none;
}

.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 48px;
  padding: 0 16px;
  background: #fff;
  border-bottom: 1px solid #eef0f5;
  cursor: move;
  flex-shrink: 0;
}

.panel-header-embedded {
  cursor: default;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 15px;
  font-weight: 600;
  color: #1e293b;
}

.header-actions {
  display: flex;
  gap: 4px;
}

.header-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border-radius: 6px;
  font-size: 13px;
  color: #94a3b8;
  cursor: pointer;
  transition: all 0.15s;
}

.header-btn:hover {
  background: #eef2ff;
  color: #6366f1;
}

.panel-body {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
  min-height: 0;
  background: #f8fafc;
}

.msg-row {
  display: flex;
  gap: 8px;
  margin-bottom: 14px;
}

.msg-row.user {
  flex-direction: row-reverse;
}

.msg-avatar {
  flex-shrink: 0;
}

.avatar-ai,
.avatar-user {
  width: 28px;
  height: 28px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
}

.avatar-ai {
  background: #eff6ff;
  color: #6366f1;
}

.avatar-user {
  background: linear-gradient(135deg, #3b82f6, #6366f1);
  color: #fff;
  font-weight: 500;
  font-size: 11px;
}

.msg-bubble-wrap {
  max-width: 85%;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.msg-row.user .msg-bubble-wrap {
  align-items: flex-end;
}

.msg-bubble {
  padding: 8px 12px;
  border-radius: 10px;
  background: #fff;
  font-size: 13.5px;
  line-height: 1.65;
  word-break: break-word;
}

.msg-row.user .msg-bubble {
  background: linear-gradient(135deg, #3b82f6, #6366f1);
  color: #fff;
}

.prompt-block {
  margin-bottom: 6px;
  border-radius: 6px;
  overflow: hidden;
  background: #f8fafc;
  border: 1px solid #e0e7ff;
}

.prompt-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 4px 10px;
  font-size: 11px;
  color: #818cf8;
  cursor: pointer;
}

.prompt-header:hover {
  background: #eef2ff;
}

.prompt-toggle {
  font-size: 9px;
}

.prompt-body {
  padding: 8px 10px;
  font-size: 11px;
  color: #64748b;
  border-top: 1px solid #e0e7ff;
  max-height: 500px;
  overflow-y: auto;
  white-space: pre-wrap;
  word-break: break-all;
  font-family: 'SF Mono', Consolas, monospace;
  line-height: 1.5;
}

.msg-content :deep(h1),
.msg-content :deep(h2),
.msg-content :deep(h3) {
  margin: 6px 0 3px;
  font-weight: 600;
  color: #1e293b;
}
.msg-content :deep(h1) { font-size: 17px; }
.msg-content :deep(h2) { font-size: 15px; }
.msg-content :deep(h3) { font-size: 14px; }
.msg-content :deep(p) { margin: 3px 0; }
.msg-content :deep(ul),
.msg-content :deep(ol) { padding-left: 18px; margin: 3px 0; }
.msg-content :deep(li) { margin: 1px 0; }
.msg-content :deep(strong) { font-weight: 600; color: #1e293b; }
.msg-content :deep(em) { font-style: italic; }
.msg-content :deep(code) {
  background: #eef2ff;
  padding: 1px 5px;
  border-radius: 3px;
  font-size: 12.5px;
  color: #4338ca;
}
.msg-content :deep(pre) {
  background: #f1f5f9;
  padding: 8px 12px;
  border-radius: 6px;
  overflow-x: auto;
  font-size: 12.5px;
}
.msg-content :deep(blockquote) {
  border-left: 2px solid #a5b4fc;
  padding-left: 10px;
  color: #64748b;
  margin: 3px 0;
}

.msg-row.user .msg-content :deep(code) {
  background: rgba(255, 255, 255, 0.15);
}

.streaming-cursor {
  display: inline;
  animation: blink 0.7s infinite;
  color: #6366f1;
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
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 4px;
  border: 1px solid #e0e7ff;
  background: #fff;
  color: #6366f1;
  cursor: pointer;
  transition: all 0.15s;
}

.msg-action-btn:hover {
  border-color: #818cf8;
  color: #4f46e5;
  background: #eef2ff;
}

.panel-footer {
  flex-shrink: 0;
  background: #fff;
  border-top: 1px solid #e0e7ff;
  padding: 8px 12px 12px;
}

.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  margin-bottom: 8px;
  min-height: 24px;
}

.toolbar-left {
  display: flex;
  align-items: center;
  gap: 4px;
  overflow: hidden;
}

.ctx-tag {
  font-size: 11px;
  color: #818cf8;
  background: #eef2ff;
  border: 1px solid #e0e7ff;
  border-radius: 4px;
  padding: 2px 6px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 120px;
}

.toolbar-right {
  display: flex;
  align-items: center;
  gap: 2px;
  flex-shrink: 0;
}

.toolbar-right button {
  font-size: 11.5px;
  padding: 3px 8px;
  border-radius: 4px;
  border: none;
  background: transparent;
  color: #64748b;
  cursor: pointer;
  transition: all 0.15s;
  white-space: nowrap;
}

.toolbar-right button:hover:not(:disabled) {
  background: #eef2ff;
  color: #4f46e5;
}

.toolbar-right button:disabled {
  opacity: 0.3;
  cursor: not-allowed;
}

.input-area {
  display: flex;
  align-items: flex-end;
  gap: 6px;
  background: #f8fafc;
  border: 1px solid #e0e7ff;
  border-radius: 10px;
  padding: 4px 4px 4px 2px;
  transition: border-color 0.15s, box-shadow 0.15s;
}

.web-search-btn {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border: none;
  border-radius: 8px;
  background: transparent;
  color: #94a3b8;
  cursor: pointer;
  transition: all 0.15s;
  align-self: flex-end;
  margin-bottom: 2px;
}

.web-search-btn:hover {
  background: #e0e7ff;
  color: #6366f1;
}

.web-search-btn.active {
  background: #6366f1;
  color: #fff;
}

.web-search-btn.active:hover {
  background: #4f46e5;
}

.input-area:focus-within {
  border-color: #818cf8;
  box-shadow: 0 0 0 2px rgba(129, 140, 248, 0.12);
}

.chat-input {
  flex: 1;
}

.chat-input :deep(.el-textarea__inner) {
  border: none;
  box-shadow: none;
  padding: 6px 10px;
  font-size: 13.5px;
  line-height: 1.5;
  resize: none;
  background: transparent;
  color: #1e293b;
}

.chat-input :deep(.el-textarea__inner:focus) {
  box-shadow: none;
}

.send-btn {
  width: 32px;
  height: 32px;
  border-radius: 8px;
  border: none;
  background: linear-gradient(135deg, #3b82f6, #6366f1);
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
}

.send-btn:disabled {
  opacity: 0.25;
  cursor: not-allowed;
}

.resize-handle {
  position: absolute;
  z-index: 15;
}

.resize-t {
  top: -3px;
  left: 14px;
  right: 14px;
  height: 8px;
  cursor: n-resize;
}

.resize-b {
  bottom: -3px;
  left: 14px;
  right: 14px;
  height: 8px;
  cursor: s-resize;
}

.resize-l {
  top: 14px;
  left: -3px;
  bottom: 14px;
  width: 8px;
  cursor: w-resize;
}

.resize-r {
  top: 14px;
  right: -3px;
  bottom: 14px;
  width: 8px;
  cursor: e-resize;
}

.resize-tl {
  top: -3px;
  left: -3px;
  width: 14px;
  height: 14px;
  cursor: nw-resize;
}

.resize-tr {
  top: -3px;
  right: -3px;
  width: 14px;
  height: 14px;
  cursor: ne-resize;
}

.resize-bl {
  bottom: -3px;
  left: -3px;
  width: 14px;
  height: 14px;
  cursor: sw-resize;
}

.resize-br {
  bottom: -3px;
  right: -3px;
  width: 14px;
  height: 14px;
  cursor: se-resize;
}

/* ── Conversation sidebar ──────────────────────────── */
.conv-sidebar {
  position: absolute;
  top: 48px;
  left: 0;
  bottom: 0;
  width: 220px;
  background: #f8f9fb;
  border-right: 1px solid #e5e7eb;
  z-index: 10;
  display: flex;
  flex-direction: column;
  animation: slideIn 0.2s ease;
}

@keyframes slideIn {
  from { transform: translateX(-100%); opacity: 0; }
  to { transform: translateX(0); opacity: 1; }
}

.conv-sidebar-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 12px;
  font-size: 13px;
  font-weight: 600;
  color: #374151;
  border-bottom: 1px solid #e5e7eb;
}

.conv-close-btn {
  cursor: pointer;
  color: #9ca3af;
  font-size: 12px;
}
.conv-close-btn:hover { color: #6b7280; }

.conv-sidebar-body {
  flex: 1;
  overflow-y: auto;
  padding: 4px 0;
}

.conv-item {
  display: flex;
  align-items: center;
  padding: 8px 12px;
  cursor: pointer;
  transition: background 0.15s;
  position: relative;
}
.conv-item:hover { background: #eef2ff; }
.conv-item.active { background: #e0e7ff; }

.conv-item-title {
  flex: 1;
  font-size: 12px;
  color: #374151;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.conv-item-time {
  font-size: 10px;
  color: #9ca3af;
  margin-left: 6px;
  flex-shrink: 0;
}

.conv-item-delete {
  display: none;
  margin-left: 4px;
  font-size: 10px;
  color: #9ca3af;
  cursor: pointer;
  flex-shrink: 0;
}
.conv-item:hover .conv-item-delete { display: inline; }
.conv-item-delete:hover { color: #ef4444; }

.conv-empty {
  text-align: center;
  color: #9ca3af;
  font-size: 12px;
  padding: 24px 0;
}
</style>
