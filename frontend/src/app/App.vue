<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useQueryClient } from '@tanstack/vue-query'
import { RouterView, useRoute } from 'vue-router'
import { useAppQuery, useTasksQuery } from '@/api/queries'
import { autoRefreshEnabled } from '@/app/refresh'
import AppShell from '@/components/shared/AppShell.vue'
import PageHeading from '@/components/shared/PageHeading.vue'
import type { RunRead } from '@/api/types'

const route = useRoute()
const queryClient = useQueryClient()

// The root component owns the only application-wide pollers.
useAppQuery()
const tasksQuery = useTasksQuery({ sync: true })

const completionMessage = ref('')
let knownStatuses: Map<string, RunRead['status']> | null = null
const handledTerminal = new Set<string>()

function recordCompletedTasks(runs: readonly RunRead[]): void {
  const current = new Map(runs.map((run) => [run.id, run.status]))
  if (knownStatuses === null) {
    knownStatuses = current
    return
  }
  const finished: string[] = []
  for (const run of runs) {
    if (run.status === 'running' || handledTerminal.has(run.id)) continue
    const previous = knownStatuses.get(run.id)
    if (previous === undefined || previous === 'running') {
      handledTerminal.add(run.id)
      finished.push(run.id)
    }
  }
  knownStatuses = current
  if (finished.length === 0) return
  completionMessage.value = `任务 ${finished.join('、')} 已完成，消息、资源与简报已更新。`
  void queryClient.invalidateQueries({ queryKey: ['resources'] })
  void queryClient.invalidateQueries({ queryKey: ['messages'] })
  void queryClient.invalidateQueries({ queryKey: ['leads'], exact: true })
  void queryClient.invalidateQueries({ queryKey: ['briefings'] })
  void queryClient.invalidateQueries({ queryKey: ['tasks', 'detail'] })
  void queryClient.invalidateQueries({ queryKey: ['app'], exact: true })
}

watch(() => tasksQuery.data.value, (runs) => {
  if (runs) recordCompletedTasks(runs)
})

function applyDocumentTitle(): void {
  const title = route.meta.title
  document.title = title ? `${title} · AIFreeRadar` : 'AIFreeRadar'
}

async function focusMain(): Promise<void> {
  await nextTick()
  document.getElementById('main')?.focus({ preventScroll: true })
}

watch(() => route.path, () => {
  applyDocumentTitle()
  void focusMain()
})

function refreshActiveQueries(): void {
  if (!autoRefreshEnabled.value) return
  void queryClient.refetchQueries({ type: 'active' })
}

function handleVisibilityChange(): void {
  if (document.visibilityState === 'visible') refreshActiveQueries()
}

watch(autoRefreshEnabled, (enabled) => {
  if (enabled) refreshActiveQueries()
})

onMounted(() => {
  applyDocumentTitle()
  void focusMain()
  document.addEventListener('visibilitychange', handleVisibilityChange)
  window.addEventListener('focus', refreshActiveQueries)
})

onBeforeUnmount(() => {
  document.removeEventListener('visibilitychange', handleVisibilityChange)
  window.removeEventListener('focus', refreshActiveQueries)
})
</script>

<template>
  <AppShell>
    <div role="status" aria-live="polite">{{ completionMessage }}</div>
    <PageHeading v-if="route.name === 'not-found'" eyebrow="系统提示" title="页面不存在" />
    <RouterView />
  </AppShell>
</template>
