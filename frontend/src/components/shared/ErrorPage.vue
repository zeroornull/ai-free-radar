<script setup lang="ts">
import { RouterLink } from 'vue-router'

withDefaults(
  defineProps<{
    title?: string
    detail?: string
  }>(),
  {
    title: '页面暂不可用',
    detail: '未找到此页面，或页面暂时无法打开。',
  },
)
</script>

<template>
  <section class="empty">
    <h2>{{ title }}</h2>
    <p>{{ detail }}</p>
    <div class="actions">
      <RouterLink to="/resources">返回资源库</RouterLink>
      <RouterLink to="/tasks">查看任务历史</RouterLink>
    </div>
  </section>
</template>
