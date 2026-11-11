<script setup lang="ts">
import { RouterLink } from 'vue-router'
import type { RunRead, Scope } from '@/api/types'
import { useAppQuery } from '@/api/queries'
import { formatDate, labelFor } from '@/app/presentation'
import StatusBadge from './StatusBadge.vue'

defineProps<{
  runs: RunRead[]
  destination: 'tasks' | 'briefings'
}>()

const { data: app } = useAppQuery()

function scopeText(scope: Scope): string {
  const categories = (scope.categories ?? []).map((category) => labelFor(app.value, category))
  const resourceIds = scope.resource_ids ?? []
  const mode = resourceIds.length
    ? `按需核验 ${resourceIds.length} 个资源`
    : '默认收集'
  return `${categories.join('、')} · ${labelFor(app.value, scope.region)} · ${mode}`
}
</script>

<template>
  <ul class="record-list">
    <li v-for="run in runs" :key="run.id" class="record">
      <div class="record-heading">
        <h2>
          <RouterLink :to="`/${destination}/${run.id}`">
            {{ formatDate(run.started_at) }} · {{ labelFor(app, run.trigger)
            }}{{ destination === 'briefings' ? '简报' : '任务' }}
          </RouterLink>
        </h2>
        <StatusBadge :value="run.status" :label="labelFor(app, run.status)" />
      </div>
      <p>{{ scopeText(run.scope) }}</p>
      <p class="meta">任务 <bdi>{{ run.id }}</bdi></p>
      <p v-if="run.error" class="failure">{{ run.error }}</p>
    </li>
  </ul>
</template>
