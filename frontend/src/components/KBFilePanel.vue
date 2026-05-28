<template>
  <div class="kb-file-panel">
    <div class="panel-header">
      <h3>📁 文件管理</h3>
      <span class="stat">{{ store.kbTotalChunks }} 切片</span>
    </div>

    <el-upload
      class="upload-area"
      drag
      :auto-upload="true"
      :show-file-list="false"
      :http-request="handleUpload"
      accept=".pdf,.docx,.doc,.txt,.md"
      :disabled="store.kbUploading"
    >
      <div v-if="store.kbUploading" class="upload-loading">
        <el-icon class="is-loading"><Loading /></el-icon>
        <span>正在处理...</span>
      </div>
      <template v-else>
        <el-icon :size="32" color="#a5b4fc"><UploadFilled /></el-icon>
        <div class="upload-text">拖拽文件到此处，或<span class="upload-link">点击上传</span></div>
        <div class="upload-hint">支持 PDF / Word / TXT</div>
      </template>
    </el-upload>

    <el-divider style="margin: 10px 0" />

    <div class="doc-list">
      <div v-if="store.kbDocuments.length === 0" class="empty-docs">
        <el-icon :size="32" color="#dcdfe6"><FolderOpened /></el-icon>
        <p>暂无文档，请上传</p>
      </div>
      <div
        v-for="doc in store.kbDocuments"
        :key="doc.doc_id"
        class="doc-card"
      >
        <div class="doc-icon">{{ fileIcon(doc.file_type) }}</div>
        <div class="doc-info">
          <div class="doc-name" :title="doc.filename">{{ doc.filename }}</div>
          <div class="doc-meta">
            <span>{{ formatSize(doc.file_size) }}</span>
            <span>{{ doc.chunk_count }} 切片</span>
          </div>
        </div>
        <el-button
          text
          size="small"
          :loading="store.kbDeleting"
          @click="onDelete(doc.doc_id)"
          class="doc-del"
        >
          <el-icon><Delete /></el-icon>
        </el-button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { UploadFilled, Loading, FolderOpened, Delete } from '@element-plus/icons-vue'
import { useNewsStore } from '@/stores'
import { ElMessage } from 'element-plus'

defineProps<{ kbId: string }>()

const store = useNewsStore()

async function handleUpload(options: any) {
  const file = options.file as File
  const ext = file.name.split('.').pop()?.toLowerCase()
  const allowed = ['pdf', 'docx', 'doc', 'txt', 'md']
  if (!ext || !allowed.includes(ext)) {
    ElMessage.error('不支持的文件格式')
    options.onError(new Error('Unsupported'))
    return
  }
  try {
    await store.uploadKBDoc(file)
    ElMessage.success(`${file.name} 上传成功`)
    options.onSuccess({})
  } catch (e: any) {
    ElMessage.error(`上传失败：${e.message || '未知错误'}`)
    options.onError(e)
  }
}

async function onDelete(docId: string) {
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
  align-items: center;
  gap: 10px;
  padding: 10px;
  border-radius: 8px;
  border: 1px solid #ebeef5;
  margin-bottom: 6px;
  transition: all 0.15s;
}

.doc-card:hover {
  border-color: #c7d2fe;
  background: #faf5ff;
}

.doc-icon {
  font-size: 22px;
  flex-shrink: 0;
}

.doc-info {
  flex: 1;
  min-width: 0;
}

.doc-name {
  font-size: 13px;
  font-weight: 500;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
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
</style>
