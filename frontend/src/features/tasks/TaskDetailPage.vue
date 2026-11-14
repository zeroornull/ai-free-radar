<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import { ApiError } from '@/api/client'
import { useAppQuery, useTaskQuery } from '@/api/queries'
import { autoRefreshEnabled } from '@/app/refresh'
import { formatDate, labelFor } from '@/app/presentation'
import PageHeading from '@/components/shared/PageHeading.vue'
import FactsList from '@/components/shared/FactsList.vue'
import CollectedMessageList from '@/components/shared/CollectedMessageList.vue'
import SafeExternalLink from '@/components/shared/SafeExternalLink.vue'
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
const messages = computed(() => taskData.value?.messages ?? [])
const changes = computed(() => taskData.value?.changes ?? [])
const traces = computed(() => run.value?.research_traces ?? [])

const STOP_REASON_LABELS: Record<string, string> = {
  gap_resolved: '缺口已补',
  no_new_evidence: '无新证据',
  budget_exhausted: '预算用尽',
  provider_failed: '检索失败',
  duplicate_query: '重复查询',
  pending: '待执行',
}

function stopReasonLabel(reason: string | undefined): string {
  return STOP_REASON_LABELS[reason ?? ''] ?? (reason ?? '未记录')
}

function linkLabel(url: string): string {
  try {
    return `打开 ${new URL(url).hostname}`
  } catch {
    return '打开来源链接'
  }
}

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
  const resourceIds = scope.resource_ids ?? []
  const mode = resourceIds.length
    ? `按需核验 ${resourceIds.length} 个指定资源`
    : '默认收集（不自动核验已有资源）'
  return `${categories} · ${labelFor(app.value, scope.region)} · ${mode}`
})

const downloadHref = computed(() => (run.value ? `/api/briefings/${run.value.id}/download` : ''))

const runningRefreshText = computed(() => {
  if (!autoRefreshEnabled.value) {
    return '任务正在后台执行。自动刷新已暂停，使用“刷新任务状态”查看进展。'
  }
  if (backgroundError.value) {
    return '任务正在后台执行。自动刷新失败，正在显示上次数据；可手动重试。'
  }
  return '任务正在后台执行。页面每 2 秒自动刷新；也可手动刷新。'
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
  <PageHeading title="任务详情" />
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
  <article v-else-if="run" class="task-article" aria-label="任务运行记录">
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

    <section class="task-chapter" aria-labelledby="run-status-heading">
      <p class="sr-only" role="status" aria-live="polite">{{ announcement }}</p>
      <h2 id="run-status-heading">执行状态：{{ labelFor(app, run.status) }}</h2>
      <p v-if="run.status === 'running'" class="notice">{{ runningRefreshText }}</p>
      <p v-else-if="run.status === 'partial'" class="notice notice--warning">本次仅完成部分，已收集结果已保存。下方列出失败原因及未完成事项。</p>
      <p v-else-if="run.status === 'failed'" class="failure">本次任务失败。已有资源结论不会仅因请求失败被判定失效。查看原因后可返回任务页重新发起。</p>

      <FactsList>
        <dt>任务标识</dt>
        <dd><bdi>{{ run.id }}</bdi></dd>
        <dt>触发方式</dt>
        <dd>{{ labelFor(app, run.trigger) }}</dd>
        <dt>本次收集范围</dt>
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
    </section>

    <section class="task-chapter" aria-labelledby="run-consumption-heading">
      <h2 id="run-consumption-heading">本次消耗</h2>
      <RunStats :stats="run.stats" />
    </section>

    <section v-if="traces.length" class="task-chapter" aria-labelledby="run-traces-heading">
      <h2 id="run-traces-heading">补搜轨迹</h2>
      <p class="muted">
        首轮观察到的免费或试用线索触发一层补搜，与主流程共用本任务的检索及抓取预算；停止原因说明该次补搜为何结束。
      </p>
      <ol class="trace-list">
        <li v-for="trace in traces" :key="`${trace.gap_id}-${trace.observed_at}`">
          <FactsList>
            <dt>类别</dt>
            <dd>{{ labelFor(app, trace.category) }}</dd>
            <dt>补搜查询</dt>
            <dd><bdi>{{ trace.query }}</bdi></dd>
            <dt>补搜目的</dt>
            <dd>{{ trace.goal }}</dd>
            <dt>停止原因</dt>
            <dd>{{ stopReasonLabel(trace.stop_reason) }}</dd>
            <dt>检索次数</dt>
            <dd>{{ trace.search_calls }}</dd>
            <dt>触发页面</dt>
            <dd><SafeExternalLink :value="trace.trigger_url" label="打开触发补搜的页面" /></dd>
            <template v-if="(trace.result_urls ?? []).length">
              <dt>检索返回链接</dt>
              <dd class="trace-links">
                <SafeExternalLink
                  v-for="url in trace.result_urls ?? []"
                  :key="`result-${url}`"
                  :value="url"
                  :label="linkLabel(url)"
                />
              </dd>
            </template>
            <template v-if="(trace.new_evidence_urls ?? []).length">
              <dt>新增证据链接</dt>
              <dd class="trace-links">
                <SafeExternalLink
                  v-for="url in trace.new_evidence_urls ?? []"
                  :key="`new-${url}`"
                  :value="url"
                  :label="linkLabel(url)"
                />
              </dd>
            </template>
            <template v-if="(trace.source_ids ?? []).length">
              <dt>相关来源</dt>
              <dd><bdi>{{ (trace.source_ids ?? []).join('、') }}</bdi></dd>
            </template>
            <dt>记录时间</dt>
            <dd>{{ formatDate(trace.observed_at) }}</dd>
          </FactsList>
        </li>
      </ol>
    </section>

    <section v-if="run.error" class="task-chapter task-chapter--failure" aria-labelledby="run-failure-heading">
      <h2 id="run-failure-heading">失败原因</h2>
      <p class="failure preserve-lines">{{ run.error }}</p>
    </section>

    <section class="task-chapter" aria-labelledby="run-notes-heading">
      <h2 id="run-notes-heading">任务说明与未完成事项</h2>
      <ul v-if="run.notes.length" class="note-list">
        <li v-for="(note, index) in run.notes" :key="index" class="preserve-lines">{{ note }}</li>
      </ul>
      <p v-else class="muted">
        {{
          run.status === 'running'
            ? '任务尚在进行，完成后记录实际范围与未完成事项。'
            : '此任务没有补充说明。资源的核验失败及上次成功时间可在资源详情和简报中查看。'
        }}
      </p>
    </section>

    <section class="task-chapter" aria-labelledby="run-messages-heading">
      <h2 id="run-messages-heading">本次收集到的消息</h2>
      <CollectedMessageList :items="messages" :show-ended="true" :link-resources="true" />
    </section>

    <section class="task-chapter" aria-labelledby="run-changes-heading">
      <h2 id="run-changes-heading">本次记录的资源变化</h2>
      <ul v-if="changes.length" class="change-register">
        <li v-for="change in changes" :key="change.id ?? `${change.resource_id}-${change.discovered_at ?? ''}`">
          {{ labelFor(app, change.kind) }} ·
          <RouterLink :to="`/resources/${change.resource_id}`">查看资源 <bdi>{{ change.resource_id }}</bdi></RouterLink>
          · {{ formatDate(change.discovered_at) }}
        </li>
      </ul>
      <p v-else class="muted">
        {{
          run.status === 'running'
            ? '任务进行中，尚无已提交变化。'
            : '本次没有新增或实质政策变化记录。待核验线索、失败及未完成情况以简报和任务说明为准。'
        }}
      </p>
    </section>
  </article>
</template>

<style scoped>
.task-article { min-inline-size: 0; }
.task-article > .actions { padding-block: 1rem; margin-block: 0 0.5rem; }
.task-chapter { margin-block: 1.5rem 0; padding-block-start: 1rem; border-block-start: 1px solid var(--color-border); }
.task-chapter > h2 { margin-block: 0 1rem; font: 600 1.25rem/1.4 var(--font-body); }
.task-chapter--failure { border-block-start-color: var(--color-error); }
.task-chapter :deep(.facts dd bdi) { font-family: var(--font-mono); font-size: 0.8125rem; overflow-wrap: anywhere; }
.change-register { list-style: none; margin: 0; padding: 0; }
.change-register > li { padding-block: 0.85rem; border-block-end: 1px solid var(--color-border); font-size: 0.875rem; overflow-wrap: anywhere; }
.task-chapter > .note-list { max-inline-size: 75ch; }
.trace-list { margin: 0; padding: 0; list-style: none; }
.trace-list > li { padding-block: 1rem; border-block-end: 1px solid var(--color-border); }
.trace-list > li:first-child { padding-block-start: 0.25rem; }
.trace-list :deep(.facts) { margin-block: 0.35rem 0; }
.trace-list :deep(.trace-links) { display: flex; flex-direction: column; gap: 0.2rem; }
.trace-list :deep(.trace-links a) { overflow-wrap: anywhere; }
@media (max-width: 480px) {
  .task-article > .actions { align-items: stretch; }
  .task-article > .actions :deep(a), .task-article > .actions :deep(button) { flex: 1 1 auto; }
}
</style>