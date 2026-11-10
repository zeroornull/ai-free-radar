<script setup lang="ts">
import { computed } from 'vue'
import type { RunRead } from '@/api/types'
import { useAppQuery, useTasksQuery } from '@/api/queries'
import { autoRefreshEnabled } from '@/app/refresh'
import PageHeading from '@/components/shared/PageHeading.vue'
import RunList from '@/components/shared/RunList.vue'
import EmptyState from '@/components/shared/EmptyState.vue'
import QueryError from '@/components/shared/QueryError.vue'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import ScheduleSummary from './ScheduleSummary.vue'
import StartTaskForm from './StartTaskForm.vue'

const {
  data: app,
  isPending: appPending,
  error: appError,
  refetch: refetchApp,
} = useAppQuery()

const {
  data: tasksData,
  isPending: tasksPending,
  isError: tasksFailed,
  isFetching: tasksFetching,
  error: tasksError,
  refetch: refetchTasks,
} = useTasksQuery()

const tasks = computed<RunRead[]>(() => [...(tasksData.value ?? [])])

const appErrorMessage = computed(() => appError.value?.message ?? '请求失败，请稍后重试。')
const tasksErrorMessage = computed(() => tasksError.value?.message ?? '请求失败，请稍后重试。')

const anyRunning = computed(
  () => tasks.value.some((run) => run.status === 'running') || app.value?.active_run != null,
)

const refreshStatusText = computed(() => {
  if (!autoRefreshEnabled.value) return '自动刷新已暂停。使用“刷新任务状态”手动查看最新结果。'
  if (tasksFailed.value && tasksData.value !== undefined) {
    return '自动刷新失败，正在显示上次数据；可手动重试。'
  }
  if (anyRunning.value) return '任务运行中，页面每 2 秒自动同步任务状态。'
  return '任务状态自动同步中：每 5 秒更新一次。'
})
</script>

<template>
  <PageHeading eyebrow="研究任务" title="研究任务" />

  <template v-if="app">
    <ScheduleSummary :app="app" />
    <StartTaskForm :app="app" />
  </template>
  <template v-else-if="appPending">
    <Skeleton class="mb-4 h-56 w-full" />
    <Skeleton class="h-72 w-full" />
  </template>
  <QueryError
    v-else
    :message="appErrorMessage"
    @retry="refetchApp()"
  />

  <section aria-labelledby="task-history">
    <div class="section-heading">
      <h2 id="task-history">任务历史</h2>
      <Button
        variant="outline"
        class="h-11"
        :disabled="tasksFetching"
        @click="refetchTasks()"
      >
        {{ tasksFetching ? '刷新中…' : '刷新任务状态' }}
      </Button>
    </div>
    <p class="muted" role="status" aria-live="polite">{{ refreshStatusText }}</p>

    <Skeleton v-if="tasksPending" class="h-40 w-full" />
    <QueryError
      v-else-if="tasksFailed && tasksData === undefined"
      :message="tasksErrorMessage"
      @retry="refetchTasks()"
    />
    <template v-else>
      <QueryError
        v-if="tasksFailed"
        :message="tasksErrorMessage"
        @retry="refetchTasks()"
      />
      <RunList v-if="tasks.length" :runs="tasks" destination="tasks" />
      <EmptyState
        v-else
        title="尚无任务记录"
        description="选择上方研究范围后发起首次研究。"
      >
        <template #actions>
          <Button as-child variant="ghost" class="h-11">
            <a href="#start-task">选择首次研究范围</a>
          </Button>
        </template>
      </EmptyState>
    </template>
  </section>
</template>