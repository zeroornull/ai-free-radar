<script setup lang="ts">
import type { CollectedMessage } from '@/api/types'
import { formatDate } from '@/app/presentation'
import SafeExternalLink from './SafeExternalLink.vue'
defineProps<{ items: CollectedMessage['sources'] }>()
const labels: Record<string, string> = { official: '官方页面', community: '社区', github: 'GitHub', search: '搜索结果' }
</script>

<template>
  <ul class="evidence-list">
    <li v-for="(source, index) in items" :key="`${source.url}-${index}`">
      <p><strong>{{ labels[source.source_type] ?? source.source_type }}</strong> · {{ source.access === 'page' ? '页面原文' : '搜索摘要（未读取页面原文）' }}</p>
      <SafeExternalLink :value="source.url" :label="source.title || '查看消息来源'" />
      <blockquote class="preserve-lines">{{ source.excerpt }}</blockquote>
      <p v-if="source.published_at" class="meta">来源发布时间：{{ formatDate(source.published_at) }}</p>
    </li>
  </ul>
</template>
