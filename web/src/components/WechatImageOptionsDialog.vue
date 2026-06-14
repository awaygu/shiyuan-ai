<template>
  <el-dialog
    :model-value="modelValue"
    title="AI 配图选项"
    width="400px"
    :close-on-click-modal="false"
    @update:model-value="emit('update:modelValue', $event)"
    @close="emit('cancel')"
  >
    <div style="margin-bottom:16px">
      <el-switch
        :model-value="generateCover"
        active-text="AI 封面图"
        inactive-text=""
        style="margin-bottom:12px"
        @update:model-value="emit('update:generateCover', $event)"
      />
      <div style="font-size:12px;color:#909399;margin-top:-8px;margin-bottom:12px">
        根据文章主题自动生成封面图（0.5元/张）
      </div>
      <el-switch
        :model-value="generateInlineImages"
        active-text="AI 正文插图"
        inactive-text=""
        @update:model-value="emit('update:generateInlineImages', $event)"
      />
      <div style="font-size:12px;color:#909399;margin-top:-8px">
        为每个章节自动生成配图（耗时较长）
      </div>
    </div>
    <template #footer>
      <el-button @click="emit('cancel')">取消</el-button>
      <el-button type="primary" @click="emit('confirm')">确认发布</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
defineProps<{
  modelValue: boolean
  generateCover: boolean
  generateInlineImages: boolean
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  'update:generateCover': [value: boolean]
  'update:generateInlineImages': [value: boolean]
  'confirm': []
  'cancel': []
}>()
</script>
