<template>
  <div class="kw-settings">
    <div class="kw-header">
      <h3>🔑 关键词过滤</h3>
      <button class="kw-close" title="关闭" @click="emit('close')">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
          <path
            d="M9 5L16 12L9 19"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
            stroke-linejoin="round"
          />
        </svg>
      </button>
    </div>

    <div class="kw-toolbar">
      <span class="kw-summary">{{ totalRules }} 条规则 · {{ groups.length }} 个分组</span>
      <el-button size="small" :icon="Plus" circle title="新增分组" @click="addGroup" />
    </div>

    <div class="kw-body">
      <div v-if="groups.length === 0" class="kw-empty">
        <p>暂无过滤规则</p>
        <p class="kw-empty-hint">添加分组和关键词，只保留匹配的新闻</p>
      </div>

      <div v-for="(group, gi) in groups" :key="gi" class="kw-group">
        <div class="kw-group-header" @click="toggleGroup(gi)">
          <svg
            :class="{ rotated: expandedGroups.has(gi) }"
            width="14"
            height="14"
            viewBox="0 0 24 24"
            fill="none"
          >
            <path
              d="M9 5L16 12L9 19"
              stroke="currentColor"
              stroke-width="2"
              stroke-linecap="round"
              stroke-linejoin="round"
            />
          </svg>
          <template v-if="editingGroupName === gi">
            <el-input
              v-model="editGroupName"
              size="small"
              class="group-name-input"
              @blur="onSaveGroupName(gi)"
              @keyup.enter="onSaveGroupName(gi)"
              @keyup.escape="editingGroupName = -1"
            />
          </template>
          <template v-else>
            <span class="kw-group-name" @dblclick.stop="startEditGroupName(gi, group.name)">{{
              group.name
            }}</span>
          </template>
          <span class="kw-group-count">{{ group.keywords.length }}</span>
          <button class="kw-group-del" title="删除分组" @click.stop="removeGroup(gi)">
            <el-icon><Delete /></el-icon>
          </button>
        </div>

        <div v-if="expandedGroups.has(gi)" class="kw-group-body">
          <div class="kw-tags">
            <span
              v-for="(kw, ki) in group.keywords"
              :key="ki"
              class="kw-tag"
              :class="{ regex: isRegex(kw) }"
            >
              <span class="kw-tag-text">{{ kw }}</span>
              <button class="kw-tag-del" @click="removeKeyword(gi, ki)">×</button>
            </span>
          </div>
          <div class="kw-add-row">
            <el-input
              :model-value="newKeywords[gi] ?? ''"
              size="small"
              placeholder="输入关键词，/正则/ 格式为正则"
              class="kw-add-input"
              @update:model-value="(val: string) => (newKeywords[gi] = val)"
              @keyup.enter="addKeyword(gi)"
            />
            <el-button size="small" type="primary" @click="addKeyword(gi)">添加</el-button>
          </div>
        </div>
      </div>
    </div>

    <div class="kw-footer">
      <el-button type="primary" :loading="store.kwLoading" class="kw-save-btn" @click="onSave">
        保存并生效
      </el-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, nextTick, onMounted } from 'vue'
import { Delete, Plus } from '@element-plus/icons-vue'
import { useKeywordStore } from '@/stores'
import { ElMessage } from 'element-plus'
import type { KeywordGroup } from '@/api'

const emit = defineEmits<{ close: [] }>()

const store = useKeywordStore()

const groups = ref<KeywordGroup[]>([])
const expandedGroups = ref<Set<number>>(new Set())
const editingGroupName = ref(-1)
const editGroupName = ref('')
const newKeywords = ref<Record<number, string>>({})

const totalRules = computed(() => groups.value.reduce((s, g) => s + g.keywords.length, 0))

function isRegex(kw: string): boolean {
  return kw.startsWith('/') && kw.endsWith('/') && kw.length >= 2
}

function toggleGroup(gi: number) {
  const s = new Set(expandedGroups.value)
  if (s.has(gi)) {
    s.delete(gi)
  } else {
    s.add(gi)
  }
  expandedGroups.value = s
}

function addGroup() {
  const name = `分组${groups.value.length + 1}`
  groups.value.push({ name, keywords: [] })
  const gi = groups.value.length - 1
  expandedGroups.value = new Set([...expandedGroups.value, gi])
}

function removeGroup(gi: number) {
  groups.value.splice(gi, 1)
  const s = new Set(expandedGroups.value)
  s.delete(gi)
  expandedGroups.value = new Set([...s].map(i => (i > gi ? i - 1 : i)))
}

function startEditGroupName(gi: number, name: string) {
  editGroupName.value = name
  editingGroupName.value = gi
  nextTick(() => {
    const el = document.querySelector('.group-name-input .el-input__inner') as HTMLElement
    el?.focus()
  })
}

function onSaveGroupName(gi: number) {
  const name = editGroupName.value.trim()
  if (name && groups.value[gi]) {
    groups.value[gi].name = name
  }
  editingGroupName.value = -1
}

function addKeyword(gi: number) {
  const kw = (newKeywords.value[gi] || '').trim()
  if (!kw) return
  if (!groups.value[gi].keywords.includes(kw)) {
    groups.value[gi].keywords.push(kw)
  }
  newKeywords.value[gi] = ''
}

function removeKeyword(gi: number, ki: number) {
  groups.value[gi].keywords.splice(ki, 1)
}

async function onSave() {
  try {
    await store.saveKeywords(groups.value)
    ElMessage.success('关键词规则已保存，下次刷新新闻时生效')
  } catch (e: any) {
    ElMessage.error(`保存失败：${e.message || '未知错误'}`)
  }
}

onMounted(async () => {
  await store.loadKeywords()
  groups.value = store.kwGroups.map(g => ({ ...g, keywords: [...g.keywords] }))
  if (groups.value.length > 0) {
    expandedGroups.value = new Set(groups.value.map((_, i) => i))
  }
})
</script>

<style scoped>
.kw-settings {
  height: 100%;
  display: flex;
  flex-direction: column;
  padding: 16px;
  overflow: hidden;
  background: #fff;
}

.kw-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}

.kw-header h3 {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
  display: flex;
  align-items: center;
  gap: 6px;
}

.kw-close {
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

.kw-close:hover {
  border-color: #a5b4fc;
  color: #6366f1;
  background: #eef2ff;
}

.kw-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
  flex-shrink: 0;
}

.kw-summary {
  font-size: 12px;
  color: #818cf8;
  background: #eef2ff;
  padding: 2px 8px;
  border-radius: 4px;
}

.kw-body {
  flex: 1;
  overflow-y: auto;
}

.kw-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 40px 0;
  color: #c0c4cc;
}

.kw-empty p {
  margin: 0;
  font-size: 13px;
}

.kw-empty-hint {
  font-size: 12px;
  color: #94a3b8;
}

.kw-group {
  margin-bottom: 8px;
  border-radius: 8px;
  border: 1px solid #ebeef5;
  overflow: hidden;
  transition: all 0.15s;
}

.kw-group:hover {
  border-color: #c7d2fe;
  background: #faf5ff;
}

.kw-group-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 12px;
  cursor: pointer;
}

.kw-group-header svg {
  flex-shrink: 0;
  transition: transform 0.2s;
  color: #94a3b8;
}

.kw-group-header svg.rotated {
  transform: rotate(90deg);
}

.kw-group-name {
  font-size: 14px;
  font-weight: 500;
  color: #1e293b;
  cursor: pointer;
}

.kw-group-name:hover {
  color: #6366f1;
}

.group-name-input {
  width: 140px;
}

.kw-group-count {
  font-size: 11px;
  color: #818cf8;
  background: #eef2ff;
  padding: 1px 6px;
  border-radius: 8px;
  margin-left: auto;
}

.kw-group-del {
  background: none;
  border: none;
  cursor: pointer;
  color: #c0c6d0;
  padding: 2px;
  display: flex;
  align-items: center;
  transition: color 0.15s;
}

.kw-group-del:hover {
  color: #f87171;
}

.kw-group-body {
  padding: 8px 12px 12px;
  border-top: 1px solid #f1f5f9;
}

.kw-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 10px;
}

.kw-tag {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 10px;
  border-radius: 6px;
  font-size: 12px;
  background: #f5f6fa;
  color: #475569;
  border: 1px solid #eef0f5;
  transition: all 0.15s;
}

.kw-tag:hover {
  border-color: #c7d2fe;
}

.kw-tag.regex {
  background: #eef2ff;
  color: #4338ca;
  border-color: #c7d2fe;
}

.kw-tag.regex:hover {
  background: #e0e7ff;
}

.kw-tag-text {
  white-space: nowrap;
}

.kw-tag-del {
  background: none;
  border: none;
  cursor: pointer;
  color: #94a3b8;
  font-size: 14px;
  padding: 0;
  line-height: 1;
  transition: color 0.15s;
}

.kw-tag-del:hover {
  color: #ef4444;
}

.kw-add-row {
  display: flex;
  gap: 6px;
}

.kw-add-input {
  flex: 1;
}

.kw-footer {
  flex-shrink: 0;
  padding-top: 12px;
  border-top: 1px solid #eef0f5;
}

.kw-save-btn {
  width: 100%;
  border-radius: 8px;
}
</style>
