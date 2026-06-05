<template>
  <div class="publish-panel">
    <el-tabs v-model="activeTab">
      <el-tab-pane label="已生成文章" name="articles">
        <div v-if="store.articles.length === 0" class="empty-state">
          <el-empty description="暂无文章，请先在生成文章标签中生成" />
        </div>

        <div v-else class="article-list">
          <div v-for="art in store.articles" :key="art.article_id" class="article-card">
            <div class="art-title">{{ art.title }}</div>
            <div class="art-meta">
              <el-tag size="small" effect="plain" :type="getStyleTagType(art.style)">
                {{ getStyleLabel(art.style) }}
              </el-tag>
              <span class="art-id">#{{ art.article_id }}</span>
            </div>
            <el-divider style="margin: 6px 0" />
            <div class="art-content-preview" v-html="renderMarkdown(art.content.slice(0, 200) + '...')"></div>

            <div class="art-actions">
              <el-dropdown
                @command="(platform: string) => onPublishCommand(art.article_id, platform)"
              >
                <el-button type="primary" size="small">
                  发布到 <el-icon><ArrowDown /></el-icon>
                </el-button>
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item command="xiaohongshu">
                      <el-icon><ChatDotSquare /></el-icon> 小红书
                    </el-dropdown-item>
                    <el-dropdown-item command="wechat_mp">
                      <el-icon><Message /></el-icon> 微信公众号
                    </el-dropdown-item>
                    <el-dropdown-item command="douyin">
                      <el-icon><VideoCamera /></el-icon> 抖音
                    </el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
            </div>
          </div>
        </div>
      </el-tab-pane>

      <el-tab-pane label="发布记录" name="log">
        <div v-if="store.publishLog.length === 0" class="empty-state">
          <el-empty description="暂无发布记录" />
        </div>

        <el-timeline v-else>
          <el-timeline-item
            v-for="rec in store.publishLog"
            :key="rec.article_id + rec.platform + rec.timestamp"
            :timestamp="formatTime(rec.timestamp)"
            :type="rec.success ? 'success' : 'danger'"
          >
            <div>
              <strong>{{ getPlatformLabel(rec.platform) }}</strong>
              — {{ rec.success ? '✅ 发布成功' : '❌ 发布失败' }}
              <el-link
                v-if="rec.url"
                :href="rec.url"
                target="_blank"
                type="primary"
                style="margin-left: 8px"
              >
                查看
              </el-link>
            </div>
          </el-timeline-item>
        </el-timeline>
      </el-tab-pane>
    </el-tabs>

    <el-dialog v-model="imageOptsVisible" title="AI 配图选项" width="400px" :close-on-click-modal="false">
      <div style="margin-bottom:16px">
        <el-switch v-model="imageOpts.generateCover" active-text="AI 封面图" inactive-text="" style="margin-bottom:12px" />
        <div style="font-size:12px;color:#909399;margin-top:-8px;margin-bottom:12px">根据文章主题自动生成封面图（0.5元/张）</div>
        <el-switch v-model="imageOpts.generateInlineImages" active-text="AI 正文插图" inactive-text="" />
        <div style="font-size:12px;color:#909399;margin-top:-8px">为每个章节自动生成配图（耗时较长）</div>
      </div>
      <template #footer>
        <el-button @click="imageOptsVisible = false">取消</el-button>
        <el-button type="primary" @click="confirmPublishWithImages">确认发布</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, reactive } from 'vue'
import { ElMessage } from 'element-plus'
import { marked } from 'marked'
import { useNewsStore } from '@/stores'
import { STYLE_LABELS, PLATFORM_LABELS } from '@/types'

const store = useNewsStore()
const activeTab = ref('articles')

const imageOptsVisible = ref(false)
const pendingPublishId = ref('')
const pendingPublishPlatform = ref('')
const imageOpts = reactive({
  generateCover: true,
  generateInlineImages: false,
})

function onPublishCommand(articleId: string, platform: string) {
  if (platform === 'wechat_mp') {
    pendingPublishId.value = articleId
    pendingPublishPlatform.value = platform
    imageOpts.generateCover = true
    imageOpts.generateInlineImages = false
    imageOptsVisible.value = true
  } else {
    handlePublish(articleId, platform)
  }
}

async function confirmPublishWithImages() {
  const articleId = pendingPublishId.value
  const platform = pendingPublishPlatform.value
  imageOptsVisible.value = false
  await handlePublish(articleId, platform, {
    generate_cover: imageOpts.generateCover,
    generate_inline_images: imageOpts.generateInlineImages,
  })
}

function getStyleLabel(style: string): string {
  return (STYLE_LABELS as any)[style] ?? style
}

function getStyleTagType(style: string): 'warning' | 'primary' | 'danger' | '' {
  if (style === 'xiaohongshu') return 'warning'
  if (style === 'douyin') return 'danger'
  return 'primary'
}

function getPlatformLabel(platform: string): string {
  return (PLATFORM_LABELS as any)[platform] ?? platform
}

function formatTime(iso: string): string {
  const d = new Date(iso)
  return d.toLocaleString('zh-CN')
}

function renderMarkdown(text: string): string {
  return marked.parse(text, { async: false }) as string
}

async function handlePublish(
  articleId: string,
  platform: string,
  imageOptions?: { generate_cover?: boolean; generate_inline_images?: boolean }
) {
  const label = getPlatformLabel(platform)
  try {
    await store.publish(articleId, platform, imageOptions)
    ElMessage.success(`已提交发布到${label}，请在任务列表中查看进度`)
  } catch (e: any) {
    ElMessage.error(`发布失败：${e.message}`)
  }
}

onMounted(async () => {
  await store.loadArticles()
  await store.loadPublishLog()
})
</script>

<style scoped>
.publish-panel {
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.panel-header h2 {
  margin: 0;
  font-size: 18px;
  display: flex;
  align-items: center;
  gap: 6px;
}

.empty-state {
  padding: 40px 0;
}

.article-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.article-card {
  border: 1px solid #ebeef5;
  border-radius: 8px;
  padding: 12px;
}

.art-title {
  font-weight: 600;
  font-size: 14px;
  margin-bottom: 4px;
  line-height: 1.4;
}

.art-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}

.art-id {
  font-size: 12px;
  color: #c0c4cc;
}

.art-content-preview {
  font-size: 12px;
  color: #606266;
  line-height: 1.6;
  margin-bottom: 8px;
}
.art-content-preview :deep(h1), .art-content-preview :deep(h2), .art-content-preview :deep(h3) {
  margin: 4px 0 2px;
  font-weight: 600;
}
.art-content-preview :deep(p) { margin: 2px 0; }
.art-content-preview :deep(ul), .art-content-preview :deep(ol) { padding-left: 18px; margin: 2px 0; }
.art-content-preview :deep(strong) { font-weight: 600; }
.art-content-preview :deep(em) { font-style: italic; }

.art-actions {
  display: flex;
  justify-content: flex-end;
}
</style>
