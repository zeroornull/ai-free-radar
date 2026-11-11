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

function durationText(run: RunRead): string {
  if (!run.finished_at) return run.status === 'running' ? '运行中' : '未记录'
  const milliseconds = Date.parse(run.finished_at) - Date.parse(run.started_at)
  if (!Number.isFinite(milliseconds) || milliseconds < 0) return '未记录'
  const seconds = Math.floor(milliseconds / 1000)
  return seconds < 60 ? `${seconds} 秒` : `${Math.floor(seconds / 60)} 分 ${seconds % 60} 秒`
}
</script>

<template>
  <div class="run-register">
    <div class="register-head" aria-hidden="true">
      <span>{{ destination === 'briefings' ? '简报 / 任务标识' : '任务标识' }}</span>
      <span>触发</span>
      <span>状态</span>
      <span>范围</span>
      <span>开始时间</span>
      <span>{{ destination === 'briefings' ? '下载' : '时长' }}</span>
    </div>
    <ul class="record-list run-rows">
      <li v-for="run in runs" :key="run.id" class="run-row">
        <component :is="destination === 'briefings' ? 'h2' : 'h3'" class="run-identity">
          <RouterLink :to="`/${destination}/${run.id}`" :aria-label="`查看${destination === 'briefings' ? '简报' : '任务'} ${run.id}`">
            <span v-if="destination === 'briefings'" class="issue-date">{{ formatDate(run.started_at) }} 简报</span>
            <bdi>{{ run.id }}</bdi>
          </RouterLink>
        </component>
        <div class="run-trigger"><span class="sr-only">触发：</span>{{ labelFor(app, run.trigger) }}</div>
        <div class="run-status"><StatusBadge :value="run.status" :label="labelFor(app, run.status)" /></div>
        <div class="run-scope"><span class="sr-only">范围：</span>{{ scopeText(run.scope) }}</div>
        <div class="run-time"><span class="sr-only">开始时间：</span><time :datetime="run.started_at">{{ formatDate(run.started_at) }}</time></div>
        <div class="run-last">
          <template v-if="destination === 'tasks'"><span class="sr-only">时长：</span>{{ durationText(run) }}</template>
          <a v-else-if="run.has_briefing" :href="`/api/briefings/${encodeURIComponent(run.id)}/download`" :aria-label="`下载任务 ${run.id} 的 Markdown 简报`">Markdown</a>
          <span v-else class="muted">尚无简报</span>
        </div>
        <p v-if="run.error" class="failure run-error">{{ run.error }}</p>
      </li>
    </ul>
  </div>
</template>

<style scoped>
.run-register { border-block-start: 1px solid var(--color-text); }
.register-head, .run-row { display: grid; grid-template-columns: minmax(9rem, 1.2fr) 4rem 5rem minmax(12rem, 1.7fr) minmax(8rem, 1fr) 6rem; gap: 1rem; }
.register-head { padding-block: 0.65rem; color: var(--color-text-secondary); font: 500 0.6875rem/1.5 var(--font-ui); }
.run-rows { display: block; margin: 0; }
.run-row { align-items: baseline; padding-block: 1.1rem; border-block-start: 1px solid var(--color-border); min-inline-size: 0; }
.run-row > * { min-inline-size: 0; overflow-wrap: anywhere; }
.run-identity { margin: 0; font: 400 0.75rem/1.6 var(--font-mono); }
.run-identity a { text-decoration-thickness: 1px; text-underline-offset: 0.2em; }
.issue-date { display: block; margin-block-end: 0.3rem; font: 600 1rem/1.45 var(--font-body); }
.run-trigger, .run-time, .run-last { font: 400 0.75rem/1.6 var(--font-ui); }
.run-time { font-variant-numeric: tabular-nums; }
.run-scope { font-size: 0.875rem; line-height: 1.65; }
.run-error { grid-column: 1 / -1; margin: 0; }
@media (max-width: 1099px) {
  .register-head { display: none; }
  .run-row { grid-template-columns: minmax(0, 1fr) auto; gap: 0.5rem 1rem; }
  .run-identity { grid-column: 1; }
  .run-status { grid-column: 2; grid-row: 1; }
  .run-trigger { grid-column: 1; grid-row: 2; }
  .run-scope { grid-column: 1 / -1; }
  .run-time { grid-column: 1; }
  .run-last { grid-column: 2; text-align: end; }
}
@media (max-width: 480px) {
  .run-row { gap: 0.5rem 0.65rem; }
  .run-identity { font-size: 0.6875rem; }
  .run-time, .run-last { font-size: 0.6875rem; }
}
</style>
