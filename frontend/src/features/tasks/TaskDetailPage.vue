<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import { ApiError } from '@/api/client'
import { useAppQuery, useTaskQuery } from '@/api/queries'
import { autoRefreshEnabled } from '@/app/refresh'
import { formatDate, labelFor } from '@/app/presentation'
import PageHeading from '@/components/shared/PageHeading.vue'
import FactsList from '@/components/shared/FactsList.vue'
import QueryError from '@/components/shared/QueryError.vue'
import ErrorPage from '@/components/shared/ErrorPage.vue'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import RunStats from './RunStats.vue'

const route = useRoute()
const { data: app } = useAppQuery()

const taskId = computed(() => {
  const value = route.params.id
  return Array.isArray(value) ? (value[0] ?? '') : (value ?? '')
})

const {
  data: taskData,
  isPending: taskPending,
  isFetching: taskFetching,
  isError: taskFailed,
  error: taskError,
  refetch: refetchTask,
} = useTaskQuery(taskId)

const run = computed(() => taskData.value?.run)
const changes = computed(() => taskData.value?.changes ?? [])

const isNotFound = computed(
  () => taskError.value instanceof ApiError && taskError.value.status === 404,
)
const errorMessage = computed(() => taskError.value?.message ?? '请求失败，请稍后重试。')
const initialError = computed(() => taskFailed.value && taskData.value === undefined)
const backgroundError = computed(() => taskFailed.value && taskData.value !== undefined)

const scopeText = computed(() => {
  const scope = run.value?.scope
  if (!scope) return ''
  const categories =
    (scope.categories ?? []).map((value) => labelFor(app.value, value)).join('、') || '未设置'
  return `${categories} · ${labelFor(app.value, scope.region)}`
})

const downloadHref = computed(() => (run.value ? `/api/briefings/${run.value.id}/download` : ''))

const runningRefreshText = computed(() => {
  if (!autoRefreshEnabled.value) {
    return '研究正在后台执行。自动刷新已暂停，使用“刷新任务状态”查看进展。'
  }
  if (backgroundError.value) {
    return '研究正在后台执行。自动刷新失败，正在显示上次数据；可手动重试。'
  }
  return '研究正在后台执行。页面每 2 秒自动刷新；也可手动刷新。'
})

const announcement = ref('')
const lastStatus = ref<string | null>(null)

watch(taskId, () => {
  announcement.value = ''
  lastStatus.value = null
})

watch(
  () => taskData.value?.run.status ?? null,
  (next) => {
    const previous = lastStatus.value
    lastStatus.value = next
    if (!next || !previous || next === previous) return
    if (previous === 'running') {
      announcement.value = `任务状态已更新为${labelFor(app.value, next)}。`
    }
  },
)
</script>

<template>
  <PageHeading eyebrow="任务详情" title="任务详情" />
  <RouterLink class="back-link" to="/tasks">返回任务历史</RouterLink>

  <Skeleton v-if="taskPending" class="h-64 w-full" />
  <ErrorPage
    v-else-if="initialError && isNotFound"
    title="任务未找到"
    :detail="errorMessage"
  />
  <QueryError
    v-else-if="initialError"
    :message="errorMessage"
    @retry="refetchTask()"
  />
  <template v-else-if="run">
    <QueryError
      v-if="backgroundError"
      :message="errorMessage"
      @retry="refetchTask()"
    />
    <div class="actions">
      <Button
        variant="outline"
        class="h-11"
        :disabled="taskFetching"
        @click="refetchTask()"
      >
        {{ taskFetching ? '刷新中…' : '刷新任务状态' }}
      </Button>
      <Button v-if="run.has_briefing" as-child variant="ghost" class="h-11">
        <RouterLink :to="`/briefings/${run.id}`">阅读本次简报</RouterLink>
      </Button>
      <Button v-if="run.has_briefing" as="a" :href="downloadHref" class="h-11">
        下载本次 Markdown
      </Button>
    </div>

    <section class="panel">
      <p class="sr-only" role="status" aria-live="polite">{{ announcement }}</p>
      <h2>执行状态：{{ labelFor(app, run.status) }}</h2>
      <p v-if="run.status === 'running'" class="notice">{{ runningRefreshText }}</p>
      <p v-else-if="run.status === 'partial'" class="notice notice--warning">本次仅完成部分研究，已核实结果已保存。下方列出失败原因及未完成事项。</p>
      <p v-else-if="run.status === 'failed'" class="failure">本次任务失败。已有资源结论不会仅因请求失败被判定失效。查看原因后可返回任务页重新发起研究。</p>

      <FactsList>
        <dt>任务标识</dt>
        <dd><bdi>{{ run.id }}</bdi></dd>
        <dt>触发方式</dt>
        <dd>{{ labelFor(app, run.trigger) }}</dd>
        <dt>本次研究范围</dt>
        <dd>{{ scopeText }}</dd>
        <dt>开始时间</dt>
        <dd>{{ formatDate(run.started_at) }}</dd>
        <dt>结束时间</dt>
        <dd>{{ run.finished_at ? formatDate(run.finished_at) : '尚未结束' }}</dd>
        <template v-if="run.schedule_day">
          <dt>计划归属日期</dt>
          <dd>{{ run.schedule_day }}</dd>
        </template>
      </FactsList>

      <h3>本次消耗</h3>
      <RunStats :stats="run.stats" />

      <template v-if="run.error">
        <h3>失败原因</h3>
        <p class="failure preserve-lines">{{ run.error }}</p>
      </template>

      <h3>研究说明与未完成事项</h3>
      <ul v-if="run.notes.length" class="note-list">
        <li v-for="(note, index) in run.notes" :key="index" class="preserve-lines">{{ note }}</li>
      </ul>
      <p v-else class="muted">
        {{
          run.status === 'running'
            ? '研究尚在进行，完成后记录实际范围与未完成事项。'
            : '此任务没有补充说明。资源的核查失败及上次成功时间可在资源详情和简报中查看。'
        }}
      </p>
    </section>

    <section class="panel">
      <h2>本次记录的资源变化</h2>
      <ul v-if="changes.length">
        <li v-for="change in changes" :key="change.id ?? `${change.resource_id}-${change.discovered_at ?? ''}`">
          {{ labelFor(app, change.kind) }} ·
          <RouterLink :to="`/resources/${change.resource_id}`">查看资源 <bdi>{{ change.resource_id }}</bdi></RouterLink>
          · {{ formatDate(change.discovered_at) }}
        </li>
      </ul>
      <p v-else class="muted">
        {{
          run.status === 'running'
            ? '研究进行中，尚无已提交变化。'
            : '本次没有新增或实质政策变化记录。待核实线索、失败及未完成情况以简报和任务说明为准。'
        }}
      </p>
    </section>
  </template>
</template>