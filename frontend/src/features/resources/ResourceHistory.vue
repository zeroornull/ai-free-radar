<script setup lang="ts">
import { RouterLink } from 'vue-router'
import type { Change } from '@/api/types'
import { useAppQuery } from '@/api/queries'
import { formatDate, labelFor } from '@/app/presentation'
import EvidenceList from '@/components/shared/EvidenceList.vue'

defineProps<{ history: Change[] }>()

const { data: app } = useAppQuery()

function jsonText(value: unknown): string {
  return JSON.stringify(value ?? null, null, 2)
}
</script>

<template>
  <section class="panel">
    <h2>已核验政策的变化历史</h2>
    <p class="muted">只记录按需核验确认的新增、变化、失效与恢复；收集消息见上方消息动态。</p>
    <ol v-if="history.length" class="history-list">
      <li
        v-for="change in history"
        :key="change.id ?? `${change.resource_id}-${change.discovered_at ?? ''}`"
      >
        <h3>{{ labelFor(app, change.kind) }} · {{ formatDate(change.discovered_at) }}</h3>
        <p>
          <RouterLink :to="`/tasks/${change.task_id}`">查看关联任务</RouterLink>
        </p>
        <details>
          <summary>查看变化前后完整记录</summary>
          <h4>变化前</h4>
          <pre>{{ jsonText(change.before) }}</pre>
          <h4>变化后</h4>
          <pre>{{ jsonText(change.after) }}</pre>
        </details>
        <EvidenceList :items="change.evidence ?? []" />
      </li>
    </ol>
    <p v-else class="muted">尚无已核验的新增、实质政策变化、失效或恢复记录。仅更新时间不会重复推荐。</p>
  </section>
</template>