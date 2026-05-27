<template>
  <!-- Bubble button (collapsed) -->
  <div
    v-if="!expanded"
    class="agent-bubble"
    @click="openPanel"
  >
    <el-badge
      :value="store.selectedNewsIds.length"
      :hidden="store.selectedNewsIds.length === 0"
      :max="99"
    >
      <div class="bubble-inner">
        <svg width="26" height="26" viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg">
          <defs>
            <linearGradient id="glow1" x1="0" y1="0" x2="48" y2="48" gradientUnits="userSpaceOnUse">
              <stop offset="0%" stop-color="#7dd3fc"/>
              <stop offset="100%" stop-color="#38bdf8"/>
            </linearGradient>
          </defs>
          <circle cx="24" cy="24" r="20" stroke="url(#glow1)" stroke-width="2" fill="none" opacity="0.7">
            <animateTransform attributeName="transform" type="rotate" from="0 24 24" to="360 24 24" dur="8s" repeatCount="indefinite"/>
          </circle>
          <circle cx="24" cy="24" r="14" stroke="url(#glow1)" stroke-width="1.5" fill="none" opacity="0.5">
            <animateTransform attributeName="transform" type="rotate" from="360 24 24" to="0 24 24" dur="6s" repeatCount="indefinite"/>
          </circle>
          <path d="M24 14 L28 20 L35 21 L30 26 L31 33 L24 30 L17 33 L18 26 L13 21 L20 20 Z" fill="#38bdf8" opacity="0.9"/>
          <circle cx="24" cy="24" r="3" fill="#fff" opacity="0.9">
            <animate attributeName="opacity" values="0.9;0.4;0.9" dur="2s" repeatCount="indefinite"/>
          </circle>
        </svg>
      </div>
    </el-badge>
  </div>

  <!-- Chat panel (expanded) -->
  <div
    v-if="expanded"
    class="agent-panel"
    :style="panelStyle"
    :class="{ dragging: isDragging || isResizing }"
    ref="panelRef"
  >
    <!-- Draggable header -->
    <div class="panel-header" @mousedown="startDrag">
      <div class="header-left">
        <svg width="20" height="20" viewBox="0 0 48 48" fill="none">
          <circle cx="24" cy="24" r="14" stroke="#7dd3fc" stroke-width="2" fill="none" opacity="0.6"/>
          <path d="M24 14 L28 20 L35 21 L30 26 L31 33 L24 30 L17 33 L18 26 L13 21 L20 20 Z" fill="#7dd3fc" opacity="0.8"/>
          <circle cx="24" cy="24" r="3" fill="#fff" opacity="0.8"/>
        </svg>
        <span>AI 助手</span>
      </div>
      <div class="header-actions">
        <span class="header-btn" @click.stop="expanded = false">✕</span>
      </div>
    </div>

    <!-- Context bar + quick actions -->
    <div class="action-bar">
      <div class="action-bar-info">
        <span v-if="store.currentDetailNews" class="context-tag">
          📄 {{ store.currentDetailNews.title?.slice(0, 20) }}{{ (store.currentDetailNews.title?.length || 0) > 20 ? '...' : '' }}
        </span>
        <span v-if="store.selectedNewsIds.length > 0" class="context-tag">
          ✅ 已选 {{ store.selectedNewsIds.length }} 条
        </span>
        <span v-if="!store.currentDetailNews && store.selectedNewsIds.length === 0" class="context-tag hint">
          请先选择新闻
        </span>
      </div>
      <div class="action-bar-btns">
        <button
          class="action-chip"
          :disabled="!store.currentDetailNews || generating"
          @click="quickInterpret"
        >🔍 解读</button>
        <button
          class="action-chip"
          :disabled="store.selectedNewsIds.length === 0 || generating"
          @click="quickGenerate('xiaohongshu')"
        >✨ 小红书</button>
        <button
          class="action-chip"
          :disabled="store.selectedNewsIds.length === 0 || generating"
          @click="quickGenerate('wechat_mp')"
        >📰 公众号</button>
        <button
          class="action-chip"
          :disabled="store.selectedNewsIds.length === 0 || generating"
          @click="quickGenerate('douyin')"
        >🎬 抖音</button>
        <button class="action-chip smart" :disabled="generating" @click="fetchTrends">🔥 热点</button>
        <button class="action-chip smart" :disabled="generating" @click="openBriefing">📋 简报</button>
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
            <div class="msg-content" v-html="renderMarkdown(msg.content)"></div>
            <span v-if="msg.streaming" class="streaming-cursor">▊</span>
          </div>
          <!-- Action buttons for completed article/interpret results -->
          <div
            v-if="msg.role === 'assistant' && !msg.streaming && msg.content && msg.type !== 'chat'"
            class="msg-actions"
          >
            <button class="msg-action-btn" @click="copyContent(msg.content)">📋 复制</button>
            <el-dropdown v-if="msg.type === 'article' && msg.articleId" trigger="click" @command="(p: string) => publishArticle(msg.articleId!, p)">
              <button class="msg-action-btn">📤 发布到 ▾</button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="xiaohongshu">小红书</el-dropdown-item>
                  <el-dropdown-item command="wechat_mp">微信公众号</el-dropdown-item>
                  <el-dropdown-item command="douyin">抖音</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
            <button
              v-if="msg.type === 'article'"
              class="msg-action-btn"
              @click="regenerate(msg)"
            >🔄 重新生成</button>
          </div>
        </div>
      </div>
    </div>

    <!-- Input -->
    <div class="panel-footer">
      <div class="input-row">
        <el-input
          v-model="chatMessage"
          placeholder="随便聊聊，或让我帮你做事..."
          size="default"
          clearable
          :disabled="generating"
          @keyup.enter="sendChat"
          class="chat-input"
        />
        <button
          class="send-btn"
          :disabled="!chatMessage.trim() || generating"
          @click="sendChat"
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
            <path d="M5 12H19M19 12L13 6M19 12L13 18" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
          </svg>
        </button>
      </div>
    </div>

    <!-- Resize handles -->
    <div class="resize-handle resize-r" @mousedown.stop="(e) => startResize(e, 'r')"></div>
    <div class="resize-handle resize-b" @mousedown.stop="(e) => startResize(e, 'b')"></div>
    <div class="resize-handle resize-rb" @mousedown.stop="(e) => startResize(e, 'rb')"></div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, nextTick, onMounted, onBeforeUnmount } from 'vue'
import { ElMessage } from 'element-plus'
import { useNewsStore } from '@/stores'
import { streamAgentChat, streamInterpret, streamGenerateArticle, publishArticle as apiPublishArticle, fetchTrends as apiFetchTrends, compareSources as apiCompareSources, searchNews as apiSearchNews, streamBriefing, executeAction } from '@/api'
import type { AgentAction } from '@/api'
import type { StyleType } from '@/types'
import { marked } from 'marked'

const store = useNewsStore()

const expanded = ref(false)
const isDragging = ref(false)
const isResizing = ref(false)
const resizeDir = ref<'r' | 'b' | 'rb' | null>(null)
const panelPos = ref({ x: 0, y: 0 })
const panelW = ref(440)
const panelH = ref(580)
const dragOffset = ref({ x: 0, y: 0 })
const resizeStart = ref({ x: 0, y: 0, w: 0, h: 0, px: 0, py: 0 })

const MIN_W = 340
const MIN_H = 420

const messagesRef = ref<HTMLElement | null>(null)
const chatMessage = ref('')
const generating = ref(false)

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

const panelStyle = computed(() => ({
  left: panelPos.value.x + 'px',
  top: panelPos.value.y + 'px',
  width: panelW.value + 'px',
  height: panelH.value + 'px',
}))

function openPanel() {
  const vx = window.innerWidth
  const vy = window.innerHeight
  panelPos.value = {
    x: vx - panelW.value - 32,
    y: vy - panelH.value - 32,
  }
  expanded.value = true
}

function renderMarkdown(text: string): string {
  return marked.parse(text, { async: false }) as string
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

// ── Quick Interpret ──────────────────────────────────────────

function quickInterpret() {
  const news = store.currentDetailNews
  if (!news || generating.value) return

  pushUserMessage(`解读这条新闻：${news.title}`)
  generating.value = true
  const msgIdx = addAssistantMessage('interpret')
  scrollToBottom()

  streamInterpret(news.news_id, 'wechat_mp', {
    onLoading(message) {
      messages.value[msgIdx].content = `⏳ ${message}`
      scrollToBottom()
    },
    onPrompt(prompt) {
      messages.value[msgIdx].prompt = prompt
      messages.value[msgIdx].promptExpanded = false
      scrollToBottom()
    },
    onLimited(message) {
      messages.value[msgIdx].content = `ℹ️ ${message}`
      pushAssistantDone(msgIdx)
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
      pushAssistantError(msgIdx, `请求失败：${err}`)
    },
  })
}

// ── Quick Generate Article ──────────────────────────────────

function quickGenerate(style: StyleType) {
  if (store.selectedNewsIds.length === 0 || generating.value) return

  const styleLabels: Record<string, string> = {
    xiaohongshu: '小红书',
    wechat_mp: '公众号',
    douyin: '抖音',
  }
  pushUserMessage(`用${styleLabels[style] || style}风格生成文章`)
  generating.value = true
  const msgIdx = addAssistantMessage('article')
  scrollToBottom()

  streamGenerateArticle(
    store.selectedNewsIds,
    style,
    {
      onLoading() { scrollToBottom() },
      onPrompt(prompt) {
        messages.value[msgIdx].prompt = prompt
        messages.value[msgIdx].promptExpanded = false
      },
      onMeta(data) {
        if (data.article_id) {
          messages.value[msgIdx].articleId = data.article_id
        }
        messages.value[msgIdx].style = style
        messages.value[msgIdx].newsIds = [...store.selectedNewsIds]
      },
      onLimited(message) {
        messages.value[msgIdx].content = `ℹ️ ${message}`
        pushAssistantDone(msgIdx)
      },
      onChunk(text) {
        messages.value[msgIdx].content += text
        scrollToBottom()
      },
      onDone() {
        pushAssistantDone(msgIdx)
      },
      onError(err) {
        pushAssistantError(msgIdx, `生成失败：${err}`)
      },
    },
  )
}

// ── Regenerate ──────────────────────────────────────────────

function regenerate(msg: ChatMessage) {
  if (!msg.newsIds || msg.newsIds.length === 0 || generating.value) return
  const style = (msg.style || 'wechat_mp') as StyleType
  quickGenerateWithIds(msg.newsIds, style)
}

function quickGenerateWithIds(newsIds: string[], style: StyleType) {
  if (generating.value) return

  const styleLabels: Record<string, string> = {
    xiaohongshu: '小红书',
    wechat_mp: '公众号',
    douyin: '抖音',
  }
  pushUserMessage(`重新生成${styleLabels[style] || style}风格文章`)
  generating.value = true
  const msgIdx = addAssistantMessage('article')
  scrollToBottom()

  streamGenerateArticle(
    newsIds,
    style,
    {
      onLoading() { scrollToBottom() },
      onPrompt(prompt) {
        messages.value[msgIdx].prompt = prompt
        messages.value[msgIdx].promptExpanded = false
      },
      onMeta(data) {
        if (data.article_id) {
          messages.value[msgIdx].articleId = data.article_id
        }
        messages.value[msgIdx].style = style
        messages.value[msgIdx].newsIds = [...newsIds]
      },
      onLimited(message) {
        messages.value[msgIdx].content = `ℹ️ ${message}`
        pushAssistantDone(msgIdx)
      },
      onChunk(text) {
        messages.value[msgIdx].content += text
        scrollToBottom()
      },
      onDone() {
        pushAssistantDone(msgIdx)
      },
      onError(err) {
        pushAssistantError(msgIdx, `生成失败：${err}`)
      },
    },
  )
}

// ── Publish ─────────────────────────────────────────────────

async function publishArticle(articleId: string, platform: string) {
  const platformLabels: Record<string, string> = {
    xiaohongshu: '小红书',
    wechat_mp: '微信公众号',
    douyin: '抖音',
  }
  try {
    await apiPublishArticle(articleId, platform)
    ElMessage.success(`已发布到${platformLabels[platform] || platform}`)
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
  if (act === 'refresh_news') {
    try {
      const res = await executeAction('refresh_news')
      if (res.success) {
        ElMessage.success(`新闻已刷新，共 ${res.total_news} 条`)
        await store.loadNews()
      }
    } catch { ElMessage.error('刷新新闻失败') }
  } else if (act === 'refresh_source') {
    try {
      const src = action.source || store.currentSource
      const res = await executeAction('refresh_source', { source: src })
      if (res.success) {
        ElMessage.success(`${src} 已刷新，新增 ${res.new} 条`)
        await store.loadNews(src)
      }
    } catch { ElMessage.error('刷新源失败') }
  }
}

// ── Chat ────────────────────────────────────────────────────

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
  }, currentNewsId)
}

// ── Drag ────────────────────────────────────────────────────

function startDrag(e: MouseEvent) {
  e.preventDefault()
  isDragging.value = true
  dragOffset.value = {
    x: e.clientX - panelPos.value.x,
    y: e.clientY - panelPos.value.y,
  }
  document.body.style.cursor = 'move'
  document.body.style.userSelect = 'none'
}

// ── Resize ──────────────────────────────────────────────────

function startResize(e: MouseEvent, dir: 'r' | 'b' | 'rb') {
  e.preventDefault()
  isResizing.value = true
  resizeDir.value = dir
  resizeStart.value = {
    x: e.clientX,
    y: e.clientY,
    w: panelW.value,
    h: panelH.value,
    px: panelPos.value.x,
    py: panelPos.value.y,
  }
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
    if (dir === 'r' || dir === 'rb') {
      panelW.value = Math.max(MIN_W, resizeStart.value.w + dx)
    }
    if (dir === 'b' || dir === 'rb') {
      panelH.value = Math.max(MIN_H, resizeStart.value.h + dy)
    }
    const vx = window.innerWidth
    const vy = window.innerHeight
    if (resizeStart.value.px + panelW.value > vx) {
      panelPos.value.x = vx - panelW.value
    }
    if (resizeStart.value.py + panelH.value > vy) {
      panelPos.value.y = vy - panelH.value
    }
  }
}

function onMouseUp() {
  if (isDragging.value) {
    isDragging.value = false
    document.body.style.cursor = ''
  }
  if (isResizing.value) {
    isResizing.value = false
    resizeDir.value = null
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
  bottom: 32px;
  right: 32px;
  z-index: 2100;
  cursor: pointer;
}

.bubble-inner {
  width: 60px;
  height: 60px;
  border-radius: 50%;
  background: linear-gradient(135deg, #0c1629, #1a2744);
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow:
    0 0 16px rgba(56, 189, 248, 0.35),
    0 0 32px rgba(56, 189, 248, 0.15),
    inset 0 0 12px rgba(56, 189, 248, 0.1);
  transition: transform 0.2s, box-shadow 0.2s;
}

.bubble-inner:hover {
  transform: scale(1.08);
  box-shadow:
    0 0 24px rgba(56, 189, 248, 0.5),
    0 0 48px rgba(56, 189, 248, 0.2),
    inset 0 0 16px rgba(56, 189, 248, 0.15);
}

.agent-panel {
  position: fixed;
  z-index: 2000;
  display: flex;
  flex-direction: column;
  border-radius: 12px;
  background: #fff;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.18);
  overflow: hidden;
  transition: opacity 0.2s;
}

.agent-panel.dragging {
  transition: none;
  user-select: none;
}

.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 48px;
  padding: 0 16px;
  background: linear-gradient(135deg, #0c1629, #1a2744);
  color: #e0f2fe;
  cursor: move;
  flex-shrink: 0;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 15px;
  font-weight: 600;
}

.header-actions {
  display: flex;
  gap: 8px;
}

.header-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border-radius: 50%;
  font-size: 14px;
  color: #94a3b8;
  cursor: pointer;
  transition: all 0.15s;
}

.header-btn:hover {
  background: rgba(148, 163, 184, 0.2);
  color: #e2e8f0;
}

/* ── Action Bar ─────────────────────────────────────────────── */

.action-bar {
  flex-shrink: 0;
  padding: 10px 14px;
  border-bottom: 1px solid #f0f2f5;
  background: #fafbfc;
}

.action-bar-info {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 8px;
  flex-wrap: wrap;
}

.context-tag {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  font-size: 12px;
  color: #606266;
  background: #fff;
  border: 1px solid #e4e7ed;
  border-radius: 4px;
  padding: 3px 8px;
  line-height: 1.4;
  max-width: 180px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.context-tag.hint {
  color: #c0c4cc;
  border-color: #ebeef5;
}

.action-bar-btns {
  display: flex;
  gap: 5px;
  flex-wrap: wrap;
}

.action-chip {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  font-size: 13px;
  padding: 4px 10px;
  border-radius: 6px;
  border: 1px solid #dcdfe6;
  background: #fff;
  color: #606266;
  cursor: pointer;
  transition: all 0.15s;
  white-space: nowrap;
}

.action-chip:hover:not(:disabled) {
  border-color: #409eff;
  color: #409eff;
  background: #ecf5ff;
}

.action-chip:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.action-chip.smart {
  border-color: #e6a23c;
  color: #e6a23c;
}

.action-chip.smart:hover:not(:disabled) {
  border-color: #e6a23c;
  background: #fdf6ec;
  color: #cf8e17;
}

/* ── Messages ──────────────────────────────────────────────── */

.panel-body {
  flex: 1;
  overflow-y: auto;
  padding: 14px 16px;
  min-height: 0;
  background: #fafbfc;
}

.msg-row {
  display: flex;
  gap: 10px;
  margin-bottom: 16px;
}

.msg-row.user {
  flex-direction: row-reverse;
}

.msg-avatar {
  flex-shrink: 0;
}

.avatar-ai,
.avatar-user {
  width: 34px;
  height: 34px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 15px;
}

.avatar-ai {
  background: #ecf5ff;
}

.avatar-user {
  background: #409eff;
  color: #fff;
  font-weight: 600;
  font-size: 13px;
}

.msg-bubble-wrap {
  max-width: 80%;
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.msg-row.user .msg-bubble-wrap {
  align-items: flex-end;
}

.msg-bubble {
  padding: 10px 14px;
  border-radius: 12px;
  background: #fff;
  font-size: 14px;
  line-height: 1.7;
  word-break: break-word;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.06);
}

.msg-row.user .msg-bubble {
  background: #409eff;
  color: #fff;
}

.prompt-block {
  margin-bottom: 8px;
  border: 1px solid #ebeef5;
  border-radius: 6px;
  overflow: hidden;
}

.prompt-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 5px 10px;
  background: #fafbfc;
  font-size: 12px;
  color: #909399;
  cursor: pointer;
}

.prompt-body {
  padding: 8px 10px;
  font-size: 12px;
  color: #606266;
  background: #fafbfc;
  border-top: 1px solid #ebeef5;
  max-height: 140px;
  overflow-y: auto;
  white-space: pre-wrap;
  word-break: break-all;
  font-family: Consolas, Monaco, monospace;
  line-height: 1.5;
}

.msg-content :deep(h1),
.msg-content :deep(h2),
.msg-content :deep(h3) {
  margin: 8px 0 4px;
  font-weight: 600;
}

.msg-content :deep(h1) { font-size: 18px; }
.msg-content :deep(h2) { font-size: 17px; }
.msg-content :deep(h3) { font-size: 16px; }
.msg-content :deep(p) { margin: 4px 0; }
.msg-content :deep(ul),
.msg-content :deep(ol) { padding-left: 20px; margin: 4px 0; }
.msg-content :deep(li) { margin: 2px 0; }
.msg-content :deep(strong) { font-weight: 600; }
.msg-content :deep(em) { font-style: italic; }
.msg-content :deep(code) {
  background: rgba(0, 0, 0, 0.06);
  padding: 2px 5px;
  border-radius: 3px;
  font-size: 13px;
}
.msg-content :deep(pre) {
  background: rgba(0, 0, 0, 0.06);
  padding: 8px 12px;
  border-radius: 6px;
  overflow-x: auto;
  font-size: 13px;
}
.msg-content :deep(blockquote) {
  border-left: 3px solid #dcdfe6;
  padding-left: 12px;
  color: #606266;
  margin: 4px 0;
}

.msg-row.user .msg-content :deep(code) {
  background: rgba(255, 255, 255, 0.2);
}

.streaming-cursor {
  display: inline;
  animation: blink 0.7s infinite;
  color: #409eff;
  font-weight: bold;
}

@keyframes blink {
  0%, 50% { opacity: 1; }
  51%, 100% { opacity: 0; }
}

/* ── Message Actions ───────────────────────────────────────── */

.msg-actions {
  display: flex;
  gap: 5px;
  flex-wrap: wrap;
}

.msg-action-btn {
  font-size: 12px;
  padding: 3px 10px;
  border-radius: 6px;
  border: 1px solid #e4e7ed;
  background: #fff;
  color: #606266;
  cursor: pointer;
  transition: all 0.15s;
  white-space: nowrap;
}

.msg-action-btn:hover {
  border-color: #409eff;
  color: #409eff;
  background: #ecf5ff;
}

/* ── Footer ────────────────────────────────────────────────── */

.panel-footer {
  flex-shrink: 0;
  padding: 12px 16px;
  border-top: 1px solid #ebeef5;
  background: #fff;
}

.input-row {
  display: flex;
  gap: 8px;
  align-items: center;
}

.chat-input {
  flex: 1;
}

.chat-input :deep(.el-input__wrapper) {
  border-radius: 8px;
  box-shadow: 0 0 0 1px #dcdfe6 inset;
  padding: 4px 12px;
  font-size: 14px;
}

.chat-input :deep(.el-input__wrapper:hover) {
  box-shadow: 0 0 0 1px #c0c4cc inset;
}

.chat-input :deep(.el-input__wrapper.is-focus) {
  box-shadow: 0 0 0 1px #409eff inset;
}

.send-btn {
  width: 40px;
  height: 40px;
  border-radius: 10px;
  border: none;
  background: linear-gradient(135deg, #409eff, #337ecc);
  color: #fff;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  transition: all 0.2s;
  box-shadow: 0 2px 8px rgba(64, 158, 255, 0.3);
}

.send-btn:hover:not(:disabled) {
  background: linear-gradient(135deg, #66b1ff, #409eff);
  box-shadow: 0 4px 12px rgba(64, 158, 255, 0.4);
  transform: translateY(-1px);
}

.send-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
  box-shadow: none;
}

.send-btn:active:not(:disabled) {
  transform: translateY(0);
}

/* ── Resize Handles ────────────────────────────────────────── */

.resize-handle {
  position: absolute;
  z-index: 10;
}

.resize-r {
  top: 0;
  right: 0;
  width: 8px;
  height: 100%;
  cursor: e-resize;
}

.resize-r:hover,
.resize-r:active {
  background: linear-gradient(to right, transparent, rgba(64, 158, 255, 0.15));
}

.resize-b {
  bottom: 0;
  left: 0;
  width: 100%;
  height: 8px;
  cursor: s-resize;
}

.resize-b:hover,
.resize-b:active {
  background: linear-gradient(to bottom, transparent, rgba(64, 158, 255, 0.15));
}

.resize-rb {
  right: 0;
  bottom: 0;
  width: 16px;
  height: 16px;
  cursor: se-resize;
}

.resize-rb::after {
  content: '';
  position: absolute;
  right: 4px;
  bottom: 4px;
  width: 10px;
  height: 10px;
  border-right: 2px solid #b0b8c4;
  border-bottom: 2px solid #b0b8c4;
  border-radius: 0 0 2px 0;
  opacity: 0.5;
  transition: opacity 0.15s;
}

.resize-rb:hover::after,
.resize-rb:active::after {
  opacity: 1;
  border-color: #409eff;
}
</style>
