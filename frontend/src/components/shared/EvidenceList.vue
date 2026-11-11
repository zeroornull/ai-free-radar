<script setup lang="ts">
import type { Evidence } from '@/api/types'
import { useAppQuery } from '@/api/queries'
import { formatDate, labelFor } from '@/app/presentation'
import SafeExternalLink from './SafeExternalLink.vue'

defineProps<{
  items: Evidence[]
}>()

const { data: app } = useAppQuery()
</script>

<template>
  <ul v-if="items.length > 0" class="evidence-list">
    <li v-for="(item, index) in items" :key="item.id ?? index">
      <p>
        <strong>{{ labelFor(app, item.source_type) }}</strong> · 对应事实：<bdi>{{ item.field }}</bdi>
      </p>
      <blockquote>{{ item.quote }}</blockquote>
      <p>
        <SafeExternalLink :value="item.url" label="查看来源" />
        <span class="muted">核查于 {{ formatDate(item.checked_at) }}</span>
      </p>
    </li>
  </ul>
  <p v-else class="muted">
    尚无核验来源。收集到的免费消息只有收集来源，不能替代官方依据，也不能作为已核验政策。
  </p>
</template>
