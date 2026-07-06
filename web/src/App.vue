<template>
  <router-view />
  <FloatingAgent />
</template>

<script setup lang="ts">
import FloatingAgent from '@/components/FloatingAgent.vue'
</script>

<style>
* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

html,
body,
#app {
  height: 100%;
  font-family:
    -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, 'Noto Sans',
    'PingFang SC', 'Microsoft YaHei', sans-serif;
  background: #f0f2f5;
  color: #303133;
}

::-webkit-scrollbar {
  width: 6px;
}
::-webkit-scrollbar-thumb {
  background: #dcdfe6;
  border-radius: 3px;
}
::-webkit-scrollbar-thumb:hover {
  background: #c0c4cc;
}
</style>
