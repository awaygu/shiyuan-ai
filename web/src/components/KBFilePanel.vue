<template>
  <div class="kb-file-panel">
    <div class="panel-header">
      <h3>📁 文件管理</h3>
      <div class="panel-header-right">
        <span class="stat">{{ store.kbDocuments.length }} 文件</span>
        <button class="collapse-btn" title="收起侧栏" @click="$emit('collapse')">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none"><path d="M15 19L8 12L15 5" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>
        </button>
      </div>
    </div>

    <div class="web-search-area">
      <div class="search-input-row">
        <el-input
          v-model="searchQuery"
          placeholder="联网搜索，结果可加入知识库"
          :disabled="searching"
          @keydown.enter="onSearch"
          class="search-input"
        >
          <template #prefix>
            <el-icon><Search /></el-icon>
          </template>
        </el-input>
        <button class="search-btn" :disabled="!searchQuery.trim() || searching" @click="onSearch">
          <el-icon v-if="searching" class="is-loading"><Loading /></el-icon>
          <span v-else>搜索</span>
        </button>
      </div>

      <div v-if="searchResults.length > 0" class="search-results">
        <button
          class="results-collapse-header"
          :class="{ 'has-divider': !resultsCollapsed }"
          @click="toggleResultsCollapsed"
        >
          <span class="collapse-chevron" :class="{ collapsed: resultsCollapsed }">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none"><path d="M6 9L12 15L18 9" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>
          </span>
          <span class="collapse-title">搜索结果</span>
          <span class="collapse-count">{{ searchResults.length }} 条</span>
          <span v-if="resultsCollapsed" class="collapse-summary">已选 {{ selectedResultIds.length }} · 点击展开</span>
        </button>
        <div v-show="!resultsCollapsed" class="results-body">
        <div class="results-toolbar">
          <el-checkbox
            :model-value="selectedResultIds.length === searchResults.length"
            :indeterminate="selectedResultIds.length > 0 && selectedResultIds.length < searchResults.length"
            @change="onSelectAllResults"
          >全选</el-checkbox>
          <span class="results-count">已选 {{ selectedResultIds.length }}/{{ searchResults.length }}</span>
          <button class="ingest-btn" :disabled="selectedResultIds.length === 0 || ingesting" @click="onIngest">
            <el-icon v-if="ingesting" class="is-loading"><Loading /></el-icon>
            <span>{{ ingesting ? '入库中' : `加入知识库 (${selectedResultIds.length})` }}</span>
          </button>
          <button class="clear-results-btn" title="清空搜索结果" @click="clearSearchResults">清空</button>
        </div>

        <div class="result-list">
          <div
            v-for="(r, idx) in searchResults"
            :key="idx"
            class="result-card"
            :class="{ expanded: expandedResultIdx === idx, selected: selectedResultIds.includes(idx) }"
          >
            <el-checkbox
              :model-value="selectedResultIds.includes(idx)"
              @change="toggleResultSelection(idx)"
              class="result-check"
            />
            <div class="result-main">
              <div class="result-title-row">
                <input
                  v-model="r.title"
                  class="result-title-input"
                  placeholder="标题"
                />
                <a v-if="r.url" :href="r.url" target="_blank" rel="noopener" class="result-url" :title="r.url">来源 ↗</a>
              </div>
              <textarea
                v-model="r.content"
                class="result-content-input"
                :rows="expandedResultIdx === idx ? 10 : 5"
                placeholder="内容"
              ></textarea>
              <button class="expand-btn" @click="expandedResultIdx = expandedResultIdx === idx ? -1 : idx">
                {{ expandedResultIdx === idx ? '收起' : '展开编辑' }}
              </button>
            </div>
          </div>
        </div>
        </div>
      </div>
    </div>

    <el-upload
      class="upload-area"
      drag
      multiple
      :auto-upload="true"
      :show-file-list="false"
      :http-request="handleUpload"
      accept=".pdf,.docx,.doc,.txt,.md,.png,.jpg,.jpeg,.gif,.bmp,.webp"
      :disabled="store.kbUploading"
    >
      <div v-if="store.kbUploading" class="upload-loading">
        <el-icon class="is-loading"><Loading /></el-icon>
        <span>正在处理...</span>
      </div>
      <template v-else>
        <el-icon :size="32" color="#a5b4fc"><UploadFilled /></el-icon>
        <div class="upload-text">拖拽文件到此处，或<span class="upload-link">点击上传</span></div>
        <div class="upload-hint">支持 PDF / Word / TXT / Markdown / 图片</div>
      </template>
    </el-upload>

    <el-divider style="margin: 10px 0" />

    <div v-if="store.kbDocuments.length > 0" class="select-bar">
      <el-checkbox
        :model-value="store.kbSelectedDocIds.length === store.kbDocuments.length"
        :indeterminate="store.kbSelectedDocIds.length > 0 && store.kbSelectedDocIds.length < store.kbDocuments.length"
        @change="onSelectAll"
      >全选</el-checkbox>
      <span class="select-count">已选 {{ store.kbSelectedDocIds.length }}/{{ store.kbDocuments.length }}</span>
    </div>

    <div class="doc-list">
      <div v-if="store.kbDocuments.length === 0" class="empty-docs">
        <el-icon :size="32" color="#dcdfe6"><FolderOpened /></el-icon>
        <p>暂无文档，请上传</p>
      </div>
      <div
        v-for="doc in store.kbDocuments"
        :key="doc.doc_id"
        class="doc-card"
        :class="{ selected: store.kbSelectedDocIds.includes(doc.doc_id), expanded: expandedDocId === doc.doc_id }"
      >
        <el-checkbox
          :model-value="store.kbSelectedDocIds.includes(doc.doc_id)"
          @change="store.toggleDocSelection(doc.doc_id)"
          class="doc-check"
        />
        <div class="doc-icon">{{ fileIcon(doc.file_type) }}</div>
        <div class="doc-info" @click="onDocClick(doc)">
          <template v-if="editingDocId === doc.doc_id">
            <el-input
              ref="renameInputRef"
              v-model="editFilename"
              size="small"
              class="rename-input"
              @blur="onSaveRename(doc.doc_id)"
              @keyup.enter="onSaveRename(doc.doc_id)"
              @keyup.escape="editingDocId = ''"
            />
          </template>
          <template v-else>
            <div class="doc-name" :title="doc.filename" @dblclick.stop="startRename(doc.doc_id, doc.filename)">{{ doc.filename }}</div>
          </template>
          <div class="doc-meta">
            <span>{{ formatSize(doc.file_size) }}</span>
          </div>
          <div v-if="expandedDocId === doc.doc_id" class="doc-summary">
            <div v-if="doc.summary" class="summary-text">{{ doc.summary }}</div>
            <div v-else class="summary-empty">暂无概要</div>
          </div>
        </div>
        <el-button
          v-if="editingDocId !== doc.doc_id"
          text
          size="small"
          class="doc-rename-btn"
          @click.stop="startRename(doc.doc_id, doc.filename)"
        >
          <el-icon><Edit /></el-icon>
        </el-button>
        <el-button
          text
          size="small"
          :loading="store.kbDeleting"
          @click.stop="onDelete(doc.doc_id, doc.filename)"
          class="doc-del"
        >
          <el-icon><Delete /></el-icon>
        </el-button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { UploadFilled, Loading, FolderOpened, Delete, Edit, Search } from '@element-plus/icons-vue'
import { useNewsStore } from '@/stores'
import { ElMessage, ElMessageBox, ElInput } from 'element-plus'
import { ref, nextTick } from 'vue'
import type { KBDoc } from '@/types'
import { webSearchKB, ingestTextToKB, type WebSearchItem } from '@/api'

const props = defineProps<{ kbId: string }>()
defineEmits<{ collapse: [] }>()

const store = useNewsStore()

const editingDocId = ref('')
const editFilename = ref('')
const renameInputRef = ref<InstanceType<typeof ElInput> | null>(null)
const expandedDocId = ref('')

const searchQuery = ref('')
const searching = ref(false)
const ingesting = ref(false)
const searchResults = ref<WebSearchItem[]>([])
const selectedResultIds = ref<number[]>([])
const expandedResultIdx = ref<number>(-1)
const resultsCollapsed = ref(false)

function toggleResultsCollapsed() {
  resultsCollapsed.value = !resultsCollapsed.value
}

async function onSearch() {
  const q = searchQuery.value.trim()
  if (!q || searching.value) return
  searching.value = true
  try {
    const results = await webSearchKB(props.kbId, q)
    if (results.length === 0) {
      ElMessage.info('未搜索到结果')
    }
    searchResults.value = results
    selectedResultIds.value = results.map((_, i) => i)
    expandedResultIdx.value = -1
    resultsCollapsed.value = false
  } catch (e: any) {
    ElMessage.error(`搜索失败：${e.message || '未知错误'}`)
  } finally {
    searching.value = false
  }
}

function toggleResultSelection(idx: number) {
  const i = selectedResultIds.value.indexOf(idx)
  if (i >= 0) {
    selectedResultIds.value.splice(i, 1)
  } else {
    selectedResultIds.value.push(idx)
  }
}

function onSelectAllResults(val: boolean | string) {
  if (val) {
    selectedResultIds.value = searchResults.value.map((_, i) => i)
  } else {
    selectedResultIds.value = []
  }
}

function clearSearchResults() {
  searchResults.value = []
  selectedResultIds.value = []
  expandedResultIdx.value = -1
  resultsCollapsed.value = false
}

async function onIngest() {
  if (selectedResultIds.value.length === 0 || ingesting.value) return
  const items = selectedResultIds.value
    .map(i => searchResults.value[i])
    .filter((r): r is WebSearchItem => !!r && (!!r.content?.trim() || !!r.title?.trim()))
  if (items.length === 0) {
    ElMessage.warning('所选结果内容为空，无法入库')
    return
  }
  ingesting.value = true
  try {
    const payload = items.map(r => ({
      title: r.title,
      content: r.content,
      url: r.url,
      filename: r.title,
    }))
    const { results, errors } = await ingestTextToKB(props.kbId, payload)
    await store.loadKBDocuments(props.kbId)
    if (results.length > 0) {
      ElMessage.success(`${results.length} 条搜索结果已加入知识库`)
    }
    for (const e of errors) {
      // ingest-text 的错误形如 {title, detail}；upload 的错误形如 {filename, detail}。两者都兼容。
      const name = e.title || e.filename || '某条结果'
      ElMessage.error(`${name} 入库失败：${e.detail || e.error || '未知错误'}`)
    }
    if (errors.length === 0) {
      clearSearchResults()
    }
  } catch (e: any) {
    ElMessage.error(`入库失败：${e.message || '未知错误'}`)
  } finally {
    ingesting.value = false
  }
}

function onDocClick(doc: KBDoc) {
  expandedDocId.value = expandedDocId.value === doc.doc_id ? '' : doc.doc_id
}

function onSelectAll(val: boolean | string) {
  if (val) {
    store.selectAllDocs()
  } else {
    store.deselectAllDocs()
  }
}

function startRename(docId: string, filename: string) {
  editFilename.value = filename
  editingDocId.value = docId
  nextTick(() => renameInputRef.value?.focus())
}

async function onSaveRename(docId: string) {
  const name = editFilename.value.trim()
  if (!name || name === store.kbDocuments.find(d => d.doc_id === docId)?.filename) {
    editingDocId.value = ''
    return
  }
  try {
    await store.renameKBDoc(docId, name)
    ElMessage.success('文件名已更新')
  } catch (e: any) {
    ElMessage.error(`重命名失败：${e.message || '未知错误'}`)
  } finally {
    editingDocId.value = ''
  }
}

const pendingFiles = ref<File[]>([])

async function handleUpload(options: any) {
  const file = options.file as File
  const ext = file.name.split('.').pop()?.toLowerCase()
  const allowed = ['pdf', 'docx', 'doc', 'txt', 'md', 'png', 'jpg', 'jpeg', 'gif', 'bmp', 'webp']
  if (!ext || !allowed.includes(ext)) {
    ElMessage.error(`${file.name} 不支持的文件格式`)
    options.onError(new Error('Unsupported'))
    return
  }
  pendingFiles.value.push(file)
  if (pendingFiles.value.length === 1) {
    setTimeout(flushUploads, 50)
  }
  options.onSuccess({})
}

async function flushUploads() {
  const files = [...pendingFiles.value]
  pendingFiles.value = []
  if (files.length === 0) return
  try {
    const { results, errors } = await store.uploadKBDocs(files)
    if (results.length > 0) {
      ElMessage.success(`${results.length} 个文件上传成功`)
    }
    for (const e of errors) {
      ElMessage.error(`${e.filename} 上传失败：${e.detail}`)
    }
  } catch (e: any) {
    ElMessage.error(`批量上传失败：${e.message || '未知错误'}`)
  }
}

async function onDelete(docId: string, filename: string) {
  try {
    await ElMessageBox.confirm(`确定删除文件「${filename}」？删除后不可恢复。`, '确认删除', { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' })
  } catch {
    return
  }
  try {
    await store.deleteKBDoc(docId)
    ElMessage.success('已删除')
  } catch (e: any) {
    ElMessage.error(`删除失败：${e.message}`)
  }
}

function fileIcon(ext: string): string {
  if (ext === '.pdf') return '📄'
  if (ext === '.docx' || ext === '.doc') return '📝'
  if (['.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp'].includes(ext)) return '🖼️'
  if (ext === '.md') return '📋'
  return '📃'
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / 1024 / 1024).toFixed(1) + ' MB'
}
</script>

<style scoped>
.kb-file-panel {
  height: 100%;
  display: flex;
  flex-direction: column;
  padding: 16px;
  overflow: hidden;
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

.panel-header-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.collapse-btn {
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
  transition: all 0.2s;
}

.collapse-btn:hover {
  border-color: #a5b4fc;
  color: #6366f1;
  background: #eef2ff;
}

.stat {
  font-size: 12px;
  color: #818cf8;
  background: #eef2ff;
  padding: 2px 8px;
  border-radius: 4px;
}

.upload-area {
  width: 100%;
}

.web-search-area {
  margin-bottom: 12px;
  flex-shrink: 0;
}

.search-input-row {
  display: flex;
  gap: 6px;
}

.search-input {
  flex: 1;
}

.search-btn {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  min-width: 64px;
  padding: 0 12px;
  height: 32px;
  border-radius: 8px;
  border: none;
  background: linear-gradient(135deg, #818cf8, #6366f1);
  color: #fff;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.15s;
}

.search-btn:hover:not(:disabled) {
  box-shadow: 0 2px 8px rgba(99, 102, 241, 0.3);
}

.search-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.search-results {
  margin-top: 10px;
  border: 1px solid #e0e7ff;
  border-radius: 8px;
  background: #faf5ff;
  overflow: hidden;
}

.results-collapse-header {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 8px 10px;
  border: none;
  background: #f5f3ff;
  cursor: pointer;
  font-size: 13px;
  color: #4f46e5;
  text-align: left;
  transition: background 0.15s;
}

.results-collapse-header:hover {
  background: #ede9fe;
}

.results-collapse-header.has-divider {
  border-bottom: 1px solid #e0e7ff;
}

.collapse-chevron {
  display: flex;
  align-items: center;
  justify-content: center;
  transition: transform 0.18s;
}

.collapse-chevron.collapsed {
  transform: rotate(-90deg);
}

.collapse-title {
  font-weight: 600;
}

.collapse-count {
  font-size: 12px;
  color: #818cf8;
  background: #eef2ff;
  padding: 1px 8px;
  border-radius: 4px;
}

.collapse-summary {
  margin-left: auto;
  font-size: 12px;
  color: #94a3b8;
  font-weight: 400;
}

.results-toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  background: #f5f3ff;
  border-bottom: 1px solid #e0e7ff;
  flex-wrap: wrap;
}

.results-count {
  font-size: 12px;
  color: #94a3b8;
}

.ingest-btn {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  border-radius: 6px;
  border: none;
  background: #6366f1;
  color: #fff;
  font-size: 12px;
  cursor: pointer;
  transition: all 0.15s;
}

.ingest-btn:hover:not(:disabled) {
  background: #4f46d5;
}

.ingest-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.clear-results-btn {
  padding: 4px 8px;
  border-radius: 6px;
  border: 1px solid #e2e8f0;
  background: #fff;
  color: #94a3b8;
  font-size: 12px;
  cursor: pointer;
  transition: all 0.15s;
}

.clear-results-btn:hover {
  border-color: #fca5a5;
  color: #ef4444;
}

.result-list {
  max-height: 60vh;
  overflow-y: auto;
  padding: 6px;
}

.result-card {
  display: flex;
  gap: 8px;
  padding: 8px;
  border-radius: 6px;
  border: 1px solid #ebeef5;
  background: #fff;
  margin-bottom: 6px;
  transition: all 0.15s;
}

.result-card.selected {
  border-color: #c7d2fe;
  background: #f5f3ff;
}

.result-card:hover {
  border-color: #c7d2fe;
}

.result-check {
  flex-shrink: 0;
  margin-top: 4px;
}

.result-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.result-title-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.result-title-input {
  flex: 1;
  min-width: 0;
  font-size: 13px;
  font-weight: 500;
  color: #1e293b;
  border: none;
  background: transparent;
  outline: none;
  padding: 2px 0;
}

.result-title-input:focus {
  border-bottom: 1px solid #a5b4fc;
}

.result-url {
  flex-shrink: 0;
  font-size: 11px;
  color: #6366f1;
  text-decoration: none;
}

.result-url:hover {
  text-decoration: underline;
}

.result-content-input {
  width: 100%;
  font-size: 12px;
  line-height: 1.5;
  color: #475569;
  border: 1px solid #f1f5f9;
  border-radius: 4px;
  padding: 4px 6px;
  resize: vertical;
  font-family: inherit;
  outline: none;
  background: #fafbfc;
}

.result-content-input:focus {
  border-color: #a5b4fc;
  background: #fff;
}

.expand-btn {
  align-self: flex-start;
  font-size: 11px;
  color: #6366f1;
  background: transparent;
  border: none;
  cursor: pointer;
  padding: 2px 4px;
}

.expand-btn:hover {
  text-decoration: underline;
}


.upload-area :deep(.el-upload-dragger) {
  width: 100%;
  padding: 20px;
  border-radius: 10px;
  border: 2px dashed #ddd6fe;
  background: #faf5ff;
  transition: all 0.2s;
}

.upload-area :deep(.el-upload-dragger:hover) {
  border-color: #a78bfa;
  background: #ede9fe;
}

.upload-loading {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #818cf8;
  font-size: 14px;
}

.upload-text {
  font-size: 13px;
  color: #64748b;
  margin-top: 6px;
}

.upload-link {
  color: #6366f1;
  font-weight: 500;
}

.upload-hint {
  font-size: 12px;
  color: #a5b4fc;
  margin-top: 4px;
}

.select-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
  flex-shrink: 0;
}

.select-bar :deep(.el-checkbox__label) {
  font-size: 13px;
  color: #64748b;
}

.select-count {
  font-size: 12px;
  color: #94a3b8;
  margin-left: auto;
}

.doc-list {
  flex: 1;
  overflow-y: auto;
}

.empty-docs {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 24px 0;
  color: #c0c4cc;
}

.empty-docs p {
  font-size: 13px;
  margin: 0;
}

.doc-card {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 10px;
  border-radius: 8px;
  border: 1px solid #ebeef5;
  margin-bottom: 6px;
  transition: all 0.15s;
}

.doc-card.expanded {
  border-color: #c7d2fe;
  background: #f5f3ff;
}

.doc-card.selected {
  border-color: #c7d2fe;
  background: #f5f3ff;
}

.doc-card:hover {
  border-color: #c7d2fe;
  background: #faf5ff;
}

.doc-check {
  flex-shrink: 0;
}

.doc-icon {
  font-size: 22px;
  flex-shrink: 0;
}

.doc-info {
  flex: 1;
  min-width: 0;
  cursor: pointer;
}

.doc-name {
  font-size: 13px;
  font-weight: 500;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  cursor: pointer;
}

.doc-name:hover {
  color: #6366f1;
}

.rename-input {
  width: 100%;
}

.doc-rename-btn {
  flex-shrink: 0;
  color: #94a3b8;
  opacity: 0;
  transition: opacity 0.15s;
}

.doc-card:hover .doc-rename-btn {
  opacity: 1;
}

.doc-meta {
  display: flex;
  gap: 8px;
  font-size: 11px;
  color: #94a3b8;
  margin-top: 2px;
}

.doc-del {
  flex-shrink: 0;
  color: #f87171;
}

.doc-summary {
  margin-top: 6px;
  padding-top: 6px;
  border-top: 1px dashed #e2e8f0;
}

.doc-summary .summary-text {
  font-size: 12px;
  line-height: 1.6;
  color: #64748b;
  white-space: pre-wrap;
  word-break: break-word;
}

.doc-summary .summary-empty {
  color: #94a3b8;
  font-size: 12px;
}
</style>
