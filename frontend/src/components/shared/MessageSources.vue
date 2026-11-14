<script setup lang="ts">
import type { CollectedMessage } from '@/api/types'
import { formatDate } from '@/app/presentation'
import SafeExternalLink from './SafeExternalLink.vue'
defineProps<{ items: CollectedMessage['sources'] }>()
const labels: Record<string, string> = { official: '官方页面', community: '社区', github: 'GitHub', search: '搜索结果', catalog: '第三方目录' }
const accessLabels: Record<string, string> = { page: '页面原文', snippet: '搜索摘要（未读取页面原文）', feed: '订阅源条目（未抓取文章页面）', catalog: '目录记录（未抓取文章页面）' }
</script>

<template>
  <ul class="evidence-list">
    <li v-for="(source, index) in items" :key="`${source.url}-${index}`">
      <p><strong>{{ labels[source.source_type ?? ''] ?? source.source_type }}</strong> · {{ accessLabels[source.access ?? ''] ?? '来源内容' }}</p>
      <p v-if="source.source_id" class="meta">来源条目：<bdi>{{ source.source_id }}</bdi><template v-if="source.external_id"> · <bdi>{{ source.external_id }}</bdi></template></p>
      <SafeExternalLink :value="source.url" :label="source.title || '查看消息来源'" />
      <blockquote class="preserve-lines">{{ source.excerpt }}</blockquote>
      <p v-if="source.published_at" class="meta">来源发布时间：{{ formatDate(source.published_at) }}</p>
    </li>
  </ul>
</template>
