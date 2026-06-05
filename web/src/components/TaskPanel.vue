<template>
  <div class="task-panel">
    <div class="task-panel-header">
      <span class="task-panel-title">任务列表</span>
      <button class="task-close-btn" @click="$emit('close')">
        <el-icon><Close /></el-icon>
      </button>
    </div>

    <div v-if="tasks.length === 0" class="task-empty">
      <el-empty description="暂无任务" :image-size="48" />
    </div>

    <div v-else class="task-list">
      <div v-for="task in tasks" :key="task.task_id" class="task-card" :class="task.status">
        <div class="task-card-header">
          <span class="task-platform">{{ platformLabel(task.platform) }}</span>
          <el-tag size="small" :type="statusTagType(task.status)" effect="dark">
            <el-icon v-if="task.status === 'running'" class="is-loading"><Loading /></el-icon>
            {{ statusLabel(task.status) }}
          </el-tag>
        </div>
        <div class="task-card-title">{{ task.title }}</div>
        <div v-if="task.status === 'running' && task.progress" class="task-card-progress">
          <el-icon class="is-loading" style="margin-right:4px"><Loading /></el-icon>
          {{ task.progress }}
        </div>
        <div v-if="task.status === 'completed'" class="task-card-result success">
          发布成功
        </div>
        <div v-if="task.status === 'failed' && task.error" class="task-card-result failed">
          {{ task.error }}
        </div>
      </div>
    </div>

    <div v-if="hasDone" class="task-footer">
      <el-button size="small" text @click="store.clearDoneTasksAction()">清除已完成</el-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useNewsStore } from '@/stores'

const store = useNewsStore()
defineEmits<{ 'close': []; 'clear-done': [] }>()

const tasks = computed(() => store.tasks)

function platformLabel(platform: string): string {
  const map: Record<string, string> = { xiaohongshu: '小红书', wechat_mp: '微信公众号', douyin: '抖音' }
  return map[platform] || platform
}

function statusLabel(status: string): string {
  const map: Record<string, string> = { pending: '等待中', running: '进行中', completed: '成功', failed: '失败' }
  return map[status] || status
}

function statusTagType(status: string): 'info' | 'primary' | 'success' | 'danger' {
  const map: Record<string, any> = { pending: 'info', running: 'primary', completed: 'success', failed: 'danger' }
  return map[status] || 'info'
}

const hasDone = computed(() => {
  return tasks.value.some(t => t.status === 'completed' || t.status === 'failed')
})
</script>

<style scoped>
.task-panel {
  height: 100%;
  display: flex;
  flex-direction: column;
  background: #fff;
  overflow: hidden;
}

.task-panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid #ebeef5;
}

.task-panel-title {
  font-weight: 600;
  font-size: 14px;
}

.task-close-btn {
  background: none;
  border: none;
  cursor: pointer;
  color: #909399;
  padding: 4px;
}

.task-close-btn:hover {
  color: #409eff;
}

.task-empty {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
}

.task-list {
  flex: 1;
  overflow-y: auto;
  padding: 8px 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.task-card {
  border: 1px solid #ebeef5;
  border-radius: 8px;
  padding: 10px 12px;
  transition: border-color 0.2s;
}

.task-card.running {
  border-color: #409eff;
  background: #ecf5ff;
}

.task-card.failed {
  border-color: #f56c6c;
  background: #fef0f0;
}

.task-card.completed {
  border-color: #67c23a;
  background: #f0f9eb;
}

.task-card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 4px;
}

.task-platform {
  font-size: 12px;
  color: #606266;
  font-weight: 500;
}

.task-card-title {
  font-size: 13px;
  color: #303133;
  font-weight: 600;
  line-height: 1.4;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.task-card-progress {
  font-size: 12px;
  color: #409eff;
  margin-top: 4px;
  display: flex;
  align-items: center;
}

.task-card-result {
  font-size: 12px;
  margin-top: 4px;
}

.task-card-result.success {
  color: #67c23a;
}

.task-card-result.failed {
  color: #f56c6c;
}

.task-footer {
  padding: 8px 12px;
  border-top: 1px solid #ebeef5;
  text-align: center;
}
</style>
