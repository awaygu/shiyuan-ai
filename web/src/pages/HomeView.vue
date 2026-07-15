<template>
  <div class="home">
    <div class="home-header">
      <span class="logo">📚</span>
      <h1>识渊 · AI解读与知识库</h1>
    </div>
    <div class="cards-grid">
      <div class="entry-card card-new" @click="showCreateDialog = true">
        <div class="card-plus">+</div>
        <div class="card-new-text">新建知识库</div>
      </div>
      <div class="entry-card card-fixed" @click="$router.push('/news')">
        <div class="card-icon">📰</div>
        <h2>新闻解读</h2>
        <p class="card-desc">爬取实时新闻，AI深度解读</p>
        <ul class="card-features">
          <li>多源新闻爬取</li>
          <li>AI 深度解读</li>
          <li>多平台一键发布</li>
        </ul>
        <div class="card-arrow">→</div>
      </div>
      <div
        v-for="kb in store.knowledgeBases"
        :key="kb.kb_id"
        class="entry-card card-kb"
        @click="$router.push(`/kb/${kb.kb_id}`)"
      >
        <div class="card-icon">{{ getKbIcon(kb.name, kb.description) }}</div>
        <h2>{{ kb.name }}</h2>
        <p v-if="kb.description" class="card-desc">{{ kb.description }}</p>
        <div class="kb-stats">
          <span>{{ kb.doc_count ?? 0 }} 文档</span>
        </div>
        <div class="kb-card-actions">
          <span class="kb-time">{{ formatTime(kb.created_at) }}</span>
          <el-button text size="small" class="kb-del-btn" @click.stop="onDelete(kb.kb_id, kb.name)">
            <el-icon><Delete /></el-icon>
          </el-button>
        </div>
      </div>
    </div>

    <el-dialog
      v-model="showCreateDialog"
      title="新建知识库"
      width="420px"
      :close-on-click-modal="false"
    >
      <el-form label-position="top">
        <el-form-item label="名称">
          <el-input v-model="newKBName" placeholder="请输入知识库名称" maxlength="50" />
        </el-form-item>
        <el-form-item label="描述（选填）">
          <el-input
            v-model="newKBDesc"
            type="textarea"
            :rows="3"
            placeholder="简短描述知识库用途"
            maxlength="200"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreateDialog = false">取消</el-button>
        <el-button
          type="primary"
          :disabled="!newKBName.trim()"
          :loading="creating"
          @click="onCreate"
          >创建</el-button
        >
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Delete } from '@element-plus/icons-vue'
import { useKbStore } from '@/stores'
import { getKbIcon } from '@/types'
import { ElMessage, ElMessageBox } from 'element-plus'

const store = useKbStore()
const router = useRouter()

const showCreateDialog = ref(false)
const newKBName = ref('')
const newKBDesc = ref('')
const creating = ref(false)

onMounted(() => {
  store.loadKnowledgeBases()
})

async function onCreate() {
  if (!newKBName.value.trim()) return
  creating.value = true
  try {
    const kb = await store.createKB(newKBName.value.trim(), newKBDesc.value.trim())
    showCreateDialog.value = false
    newKBName.value = ''
    newKBDesc.value = ''
    ElMessage.success('知识库创建成功')
    router.push(`/kb/${kb.kb_id}`)
  } catch (e: any) {
    ElMessage.error(`创建失败：${e.message || '未知错误'}`)
  } finally {
    creating.value = false
  }
}

async function onDelete(kbId: string, name: string) {
  try {
    await ElMessageBox.confirm(`确定删除知识库「${name}」？所有文档和对话将被删除。`, '删除确认', {
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      type: 'warning',
    })
    await store.removeKB(kbId)
    ElMessage.success('已删除')
  } catch {}
}

function formatTime(t: string): string {
  if (!t) return ''
  try {
    return new Date(t).toLocaleDateString('zh-CN')
  } catch {
    return t
  }
}
</script>

<style scoped>
.home {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  background: #f5f6fa;
  padding: 40px 0 60px;
}

.home-header {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 0 56px 36px;
}

.home-header .logo {
  font-size: 30px;
}

.home-header h1 {
  font-size: 20px;
  font-weight: 600;
  color: #1e293b;
  letter-spacing: 0.5px;
}

.cards-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 18px;
  padding: 0 56px;
}

.entry-card {
  padding: 24px 22px;
  background: #fff;
  border-radius: 12px;
  border: 1px solid #eef0f5;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.03);
  cursor: pointer;
  transition: all 0.2s ease;
  position: relative;
  overflow: hidden;
}

.entry-card:hover {
  transform: translateY(-3px);
  box-shadow: 0 6px 20px rgba(99, 102, 241, 0.1);
  border-color: #c7d2fe;
}

.entry-card::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 3px;
  background: linear-gradient(90deg, #a5b4fc, #818cf8);
  opacity: 0;
  transition: opacity 0.2s;
}

.entry-card:hover::before {
  opacity: 1;
}

.card-new {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  border: 2px dashed #ddd6fe;
  background: transparent;
  min-height: 200px;
}

.card-new:hover {
  border-color: #a5b4fc;
  background: rgba(129, 140, 248, 0.04);
  box-shadow: 0 6px 20px rgba(99, 102, 241, 0.08);
  transform: translateY(-3px);
}

.card-new::before {
  display: none;
}

.card-plus {
  width: 48px;
  height: 48px;
  border-radius: 50%;
  background: #eef2ff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 24px;
  font-weight: 400;
  color: #818cf8;
  line-height: 1;
  transition: all 0.2s;
}

.card-new:hover .card-plus {
  background: #ddd6fe;
  color: #6366f1;
}

.card-new-text {
  font-size: 13px;
  color: #818cf8;
  margin-top: 12px;
  font-weight: 500;
}

.card-icon {
  font-size: 32px;
  margin-bottom: 14px;
}

.entry-card h2 {
  font-size: 16px;
  font-weight: 600;
  color: #1e293b;
  margin: 0 0 8px;
}

.card-desc {
  font-size: 13px;
  color: #64748b;
  margin: 0 0 14px;
  line-height: 1.55;
}

.card-features {
  list-style: none;
  padding: 0;
  margin: 0 0 4px;
}

.card-features li {
  font-size: 12px;
  color: #94a3b8;
  padding: 3px 0 3px 16px;
  position: relative;
}

.card-features li::before {
  content: '';
  position: absolute;
  left: 0;
  top: 50%;
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: #c7d2fe;
  transform: translateY(-50%);
}

.card-arrow {
  position: absolute;
  right: 18px;
  bottom: 18px;
  font-size: 16px;
  color: #d4d8e8;
  transition: all 0.2s;
}

.entry-card:hover .card-arrow {
  color: #818cf8;
  transform: translateX(3px);
}

.card-kb {
  display: flex;
  flex-direction: column;
  min-height: 200px;
}

.card-kb h2 {
  margin-bottom: 6px;
}

.card-kb .card-desc {
  flex: 1;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  margin-bottom: 14px;
}

.kb-stats {
  display: flex;
  gap: 12px;
  margin-bottom: 12px;
}

.kb-stats span {
  font-size: 11px;
  color: #94a3b8;
  background: #f5f6fa;
  padding: 2px 8px;
  border-radius: 4px;
}

.kb-card-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: auto;
  padding-top: 10px;
  border-top: 1px solid #f1f2f6;
}

.kb-time {
  font-size: 11px;
  color: #b0b8c9;
}

.kb-del-btn {
  color: #e0b4b4;
  opacity: 0;
  transition: all 0.15s;
  padding: 2px 4px;
}

.kb-del-btn:hover {
  color: #ef4444 !important;
}

.card-kb:hover .kb-del-btn {
  opacity: 1;
}
</style>
