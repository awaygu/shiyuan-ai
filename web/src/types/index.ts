/** TypeScript type definitions for the News AI system. */

export interface NewsItem {
  news_id: string
  title: string
  summary: string
  content: string
  source: string
  url: string
  published_at: string
  extra: Record<string, any>
}

export interface Article {
  article_id: string
  title: string
  content: string
  style: string
  news_ids: string[]
}

export interface PublishRecord {
  article_id: string
  platform: string
  success: boolean
  url: string
  timestamp: string
  extra: Record<string, any>
}

export type StyleType = 'xiaohongshu' | 'wechat_mp' | 'douyin'

export const STYLE_LABELS: Record<StyleType, string> = {
  xiaohongshu: '小红书风格 ✨',
  wechat_mp: '公众号风格 📰',
  douyin: '抖音风格 🎬',
}

export const SOURCE_LABELS: Record<string, string> = {
  'cls-hot': '财联社热门',
  'cls-telegraph': '财联社电报',
  'wallstreetcn-hot': '华尔街见闻',
  cankaoxiaoxi: '参考消息',
  thepaper: '澎湃新闻',
  toutiao: '今日头条',
  xueqiu: '雪球',
  weibo: '微博',
  douyin: '抖音',
  'hacker-news': 'Hacker News',
  ruanyifeng: '阮一峰的网络日志',
}

export const VIDEO_SOURCES = new Set(['douyin'])

// 已知不支持 iframe 嵌入的源，直接显示"新窗口打开"
export const NO_IFRAME_SOURCES = new Set([
  'weibo', // 微博：X-Frame-Options
  'toutiao', // 今日头条：CSP 限制
  'thepaper', // 澎湃新闻：X-Frame-Options
  'cankaoxiaoxi', // 参考消息：不允许嵌入
])

export const PLATFORM_LABELS: Record<string, string> = {
  xiaohongshu: '小红书',
  wechat_mp: '微信公众号',
  douyin: '抖音',
}

// ── Knowledge Base ────────────────────────────────────────────

const KB_ICON_MAP: [RegExp, string][] = [
  [/(新闻|资讯|报|媒体|news)/i, '📰'],
  [/(法|法律|律|条款|法典|law)/i, '⚖️'],
  [/(医|药|健康|病理|临床|med)/i, '🏥'],
  [/(金融|经济|投资|股票|基金|财|fin)/i, '💰'],
  [/(科技|技术|编程|代码|开发|dev|tech)/i, '🚀'],
  [/(教育|学习|课程|教学|培训|edu)/i, '🎓'],
  [/(历史|史料|年代|史|history)/i, '📜'],
  [/(文|文学|小说|诗歌|写作|lit)/i, '✍️'],
  [/(商|商业|企业|管理|marketing|biz)/i, '📊'],
  [/(设|设计|艺术|创意|art|design)/i, '🎨'],
  [/(音乐|乐|music)/i, '🎵'],
  [/(电影|影视|视频|video|film)/i, '🎬'],
  [/(旅行|旅游|出行|地理|travel)/i, '🌍'],
  [/(美食|饮食|烹饪|厨|food|cook)/i, '🍳'],
  [/(体育|运动|健身|sport|fitness)/i, '⚽'],
  [/(心理|情绪|psy)/i, '🧠'],
  [/(数据|统计|数据分析|data|stat)/i, '📈'],
  [/(安全|安防|网络|sec)/i, '🔒'],
  [/(人|人物|传记|bio)/i, '👤'],
  [/(自然|生态|环境|环保|nat)/i, '🌿'],
]

export function getKbIcon(name: string, description?: string): string {
  const text = `${name} ${description ?? ''}`
  for (const [re, icon] of KB_ICON_MAP) {
    if (re.test(text)) return icon
  }
  return '📚'
}

export interface KnowledgeBase {
  kb_id: string
  name: string
  description: string
  created_at: string
  updated_at: string
  doc_count?: number
  total_chunks?: number
  conversation_count?: number
}

export interface KBDoc {
  doc_id: string
  kb_id: string
  filename: string
  file_type: string
  chunk_count: number
  file_size: number
  upload_time: string
  status: string
  summary: string
}

export interface KBSearchResult {
  chunk_id: number
  doc_id: string
  filename: string
  page: number
  text: string
  preview: string
  score: number
}

export interface KBSource {
  filename: string
  page: number
  score: number
  preview: string
  text?: string
}

export interface KBConversation {
  conv_id: string
  kb_id: string
  title: string
  created_at: string
}

export interface KBMessage {
  msg_id: string
  conv_id: string
  role: 'user' | 'assistant'
  content: string
  type: 'chat' | 'article'
  sources: KBSource[]
  created_at: string
}

export interface AsyncTask {
  task_id: string
  task_type: string
  platform: string
  title: string
  status: 'pending' | 'running' | 'completed' | 'failed'
  progress: string
  created_at: string
  updated_at: string
  result?: Record<string, any>
  error?: string
  need_login?: boolean
}
