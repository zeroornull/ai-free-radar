<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { ApiError } from '@/api/client'
import type {
  Category,
  SourceDefinition,
  SourceEntry,
  SourceRead,
  SourceRule,
  SourceSnapshot,
} from '@/api/types'
import {
  useAppQuery,
  useReplaySourceRulesMutation,
  useSaveSourceMutation,
  useSourceEntriesQuery,
  useSourceSnapshotQuery,
  useSourceSnapshotsQuery,
  useSourcesQuery,
} from '@/api/queries'
import { formatDate } from '@/app/presentation'
import EmptyState from '@/components/shared/EmptyState.vue'
import PageHeading from '@/components/shared/PageHeading.vue'
import QueryError from '@/components/shared/QueryError.vue'
import SafeExternalLink from '@/components/shared/SafeExternalLink.vue'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { NativeSelect, NativeSelectOption } from '@/components/ui/native-select'
import { Skeleton } from '@/components/ui/skeleton'

const ENTRY_PAGE = 50
const SNAPSHOT_PAGE = 20
const MIN_INTERVAL = 60
const MAX_INTERVAL = 31_536_000

interface DraftRule {
  id: string
  field: SourceRule['field']
  pattern: string
  action: SourceRule['action']
  label: string
}

interface Draft {
  id: string
  name: string
  url: string
  kind: SourceDefinition['kind']
  categories: Category[]
  source_type: SourceDefinition['source_type']
  official_domain: string
  enabled: boolean
  interval_seconds: number
  include_selectors: string
  exclude_selectors: string
  ignore_patterns: string
  rules: DraftRule[]
  checked_on: string
  review_reason: string
  reopen_if: string
}

const KIND_LABELS: Record<string, string> = {
  web: '网页',
  feed: '订阅源',
  catalog: '公开目录',
}
const SOURCE_TYPE_LABELS: Record<string, string> = {
  official: '官方来源',
  community: '社区来源',
  github: 'GitHub 来源',
  catalog: '第三方目录',
}
const HEALTH_LABELS: Record<string, string> = {
  never: '尚未检查',
  ok: '最近检查成功',
  error: '最近检查失败',
}
const RULE_FIELD_LABELS: Record<string, string> = {
  title: '标题',
  content: '正文',
  url: '链接',
}
const RULE_ACTION_LABELS: Record<string, string> = {
  tag: '标注',
  deprioritize: '降低优先级',
  review: '标记待审阅',
}

const { data: app } = useAppQuery()
const { data: sources, isPending, isError, error, refetch } = useSourcesQuery()

const expanded = ref<{ id: string; mode: 'entries' | 'edit' } | null>(null)
const activeId = computed(() => expanded.value?.id ?? '')

function idOf(definition: SourceDefinition): string {
  return definition.id ?? ''
}

const entryLimitVisible = ENTRY_PAGE
const entryOffset = ref(0)
const chosenSnapshotId = ref('')
const draft = ref<Draft | null>(null)
const formError = ref('')
const savedNotice = ref('')
const replayNotice = ref('')
const formAlert = ref<HTMLElement | null>(null)

const categoryOptions = computed(() =>
  Object.entries(app.value?.categories ?? {}).map(([value, label]) => ({
    value: value as Category,
    label,
  })),
)

const {
  data: entries,
  isPending: entriesPending,
  isFetching: entriesFetching,
  isError: entriesFailed,
  error: entriesError,
  refetch: refetchEntries,
} = useSourceEntriesQuery(activeId, entryLimitVisible, entryOffset)
const {
  data: snapshots,
  isPending: snapshotsPending,
  isError: snapshotsFailed,
  error: snapshotsError,
  refetch: refetchSnapshots,
} = useSourceSnapshotsQuery(activeId, SNAPSHOT_PAGE)
const {
  data: snapshotDetail,
  isPending: snapshotPending,
  isError: snapshotFailed,
  error: snapshotError,
  refetch: refetchSnapshot,
} = useSourceSnapshotQuery(chosenSnapshotId)

const saveMutation = useSaveSourceMutation()
const replayMutation = useReplaySourceRulesMutation(activeId)

const savedMessage = computed(() => (isError.value ? '' : savedNotice.value))

watch(activeId, () => {
  entryOffset.value = 0
  chosenSnapshotId.value = ''
  replayNotice.value = ''
  savedNotice.value = ''
  formError.value = ''
})

function panelId(kind: string, id: string): string {
  return `${kind}-${id.replace(/[^A-Za-z0-9_-]/g, '-')}`
}

function toggle(id: string, mode: 'entries' | 'edit'): void {
  if (expanded.value?.id === id && expanded.value.mode === mode) {
    expanded.value = null
    return
  }
  const source = sources.value?.find((item) => item.definition.id === id)
  expanded.value = { id, mode }
  if (mode === 'edit' && source) {
    draft.value = draftFrom(source.definition)
  }
}

function draftFrom(definition: SourceDefinition): Draft {
  return {
    id: definition.id ?? '',
    name: definition.name ?? '',
    url: definition.url ?? '',
    kind: definition.kind ?? 'web',
    categories: [...(definition.categories ?? [])],
    source_type: definition.source_type ?? 'community',
    official_domain: definition.official_domain ?? '',
    enabled: definition.enabled ?? true,
    interval_seconds: definition.interval_seconds ?? 86_400,
    include_selectors: (definition.include_selectors ?? []).join('\n'),
    exclude_selectors: (definition.exclude_selectors ?? []).join('\n'),
    ignore_patterns: (definition.ignore_patterns ?? []).join('\n'),
    rules: (definition.rules ?? []).map((rule) => ({
      id: rule.id ?? newRuleId(),
      field: rule.field,
      pattern: rule.pattern ?? '',
      action: rule.action ?? 'tag',
      label: rule.label ?? '',
    })),
    checked_on: definition.checked_on ?? '',
    review_reason: definition.review_reason ?? '',
    reopen_if: definition.reopen_if ?? '',
  }
}

function newRuleId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID().replaceAll('-', '')
  }
  return `rule-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`
}

function addRule(): void {
  draft.value?.rules.push({
    id: newRuleId(),
    field: 'title',
    pattern: '',
    action: 'tag',
    label: '',
  })
}

function removeRule(index: number): void {
  draft.value?.rules.splice(index, 1)
}

function setKind(value: unknown): void {
  const target = draft.value
  if (!target) return
  if (value === 'web' || value === 'feed' || value === 'catalog') target.kind = value
}

function setSourceType(value: unknown): void {
  const target = draft.value
  if (!target) return
  if (
    value === 'official' ||
    value === 'community' ||
    value === 'github' ||
    value === 'catalog'
  ) {
    target.source_type = value
  }
}

function setRuleField(index: number, value: unknown): void {
  const rule = draft.value?.rules[index]
  if (!rule) return
  if (value === 'title' || value === 'content' || value === 'url') rule.field = value
}

function setRuleAction(index: number, value: unknown): void {
  const rule = draft.value?.rules[index]
  if (!rule) return
  if (value === 'tag' || value === 'deprioritize' || value === 'review') rule.action = value
}

function lines(value: string): string[] {
  return value
    .split('\n')
    .map((line) => line.trim())
    .filter((line) => line.length > 0)
}

function validRegex(value: string): boolean {
  try {
    new RegExp(value)
    return true
  } catch {
    return false
  }
}

function validateDraft(value: Draft): string[] {
  const problems: string[] = []
  if (!value.name.trim()) problems.push('填写来源名称。')
  const url = value.url.trim()
  let parsed: URL | null = null
  try {
    parsed = new URL(url)
  } catch {
    parsed = null
  }
  if (
    !parsed ||
    (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') ||
    parsed.username ||
    parsed.password ||
    /[\u0000-\u0020\\]/u.test(url)
  ) {
    problems.push('来源地址必须是无凭据的公开 HTTP(S) 链接。')
  }
  if (
    !Number.isInteger(value.interval_seconds) ||
    value.interval_seconds < MIN_INTERVAL ||
    value.interval_seconds > MAX_INTERVAL
  ) {
    problems.push(`轮询间隔需为 ${MIN_INTERVAL} 到 ${MAX_INTERVAL} 秒之间的整数。`)
  }
  if (!value.categories.length) problems.push('至少选择一个适用类别。')
  for (const pattern of lines(value.ignore_patterns)) {
    if (!validRegex(pattern)) problems.push(`忽略模式不是有效正则：${pattern}`)
  }
  for (const rule of value.rules) {
    const label = rule.label.trim() || rule.pattern.trim() || '未命名规则'
    if (!rule.label.trim()) problems.push(`规则“${label}”缺少标签。`)
    if (!rule.pattern.trim() || !validRegex(rule.pattern)) {
      problems.push(`规则“${label}”的表达式无效。`)
    }
    if (!rule.id.trim()) problems.push(`规则“${label}”缺少标识，请删除后重新添加。`)
  }
  return problems
}

function toDefinition(value: Draft): SourceDefinition {
  return {
    id: value.id,
    name: value.name.trim(),
    url: value.url.trim(),
    kind: value.kind,
    categories: [...value.categories],
    source_type: value.source_type,
    official_domain: value.official_domain.trim(),
    enabled: value.enabled,
    interval_seconds: value.interval_seconds,
    include_selectors: lines(value.include_selectors),
    exclude_selectors: lines(value.exclude_selectors),
    ignore_patterns: lines(value.ignore_patterns),
    rules: value.rules.map((rule) => ({
      id: rule.id,
      field: rule.field,
      pattern: rule.pattern.trim(),
      action: rule.action,
      label: rule.label.trim(),
    })),
    checked_on: value.checked_on || null,
    review_reason: value.review_reason.trim(),
    reopen_if: value.reopen_if.trim(),
  }
}

async function save(): Promise<void> {
  if (!draft.value) return
  const problems = validateDraft(draft.value)
  if (problems.length) {
    formError.value = problems.join(' ')
    savedNotice.value = ''
    await nextTick()
    formAlert.value?.focus()
    return
  }
  formError.value = ''
  try {
    const saved = await saveMutation.mutateAsync(toDefinition(draft.value))
    draft.value = draftFrom(saved.definition)
    savedNotice.value = '来源定义已保存到本机。保存不会访问网络；需要收集时请发起手动研究任务。'
  } catch (caught) {
    savedNotice.value = ''
    formError.value =
      caught instanceof Error ? caught.message : '来源定义未能保存，请检查输入后重试。'
    await nextTick()
    formAlert.value?.focus()
  }
}

async function replayRules(): Promise<void> {
  replayNotice.value = ''
  try {
    const updated = await replayMutation.mutateAsync()
    replayNotice.value = `已重新应用规则：${updated.length} 条原始条目的标注与优先级已更新，未访问网络。`
  } catch (caught) {
    replayNotice.value = caught instanceof Error ? caught.message : '规则重放失败，请稍后重试。'
  }
}

function kindLabel(kind: string | undefined): string {
  return KIND_LABELS[kind ?? ''] ?? '来源'
}

function sourceTypeLabel(value: string | undefined): string {
  return SOURCE_TYPE_LABELS[value ?? ''] ?? (value ?? '来源')
}

function healthLabel(status: string): string {
  return HEALTH_LABELS[status] ?? status
}

function accessNote(kind: string): string {
  if (kind === 'feed') return '订阅源条目保留来源原始记录，不抓取文章页面原文。'
  if (kind === 'catalog') return '公开目录记录只作为线索，不构成官方政策核验依据。'
  return '网页来源保存原始与正文快照，按包含与排除选择器提取。'
}

function stateOf(source: SourceRead) {
  return source.state ?? null
}

function entryCount(source: SourceRead): string {
  const state = stateOf(source)
  if (!state) return '尚无条目记录'
  return `${state.entry_count ?? 0} 条原始条目`
}

function ruleMatches(entry: SourceEntry): string {
  return (entry.rule_matches ?? [])
    .map(
      (match) =>
        `${RULE_FIELD_LABELS[match.field] ?? match.field} · ${RULE_ACTION_LABELS[match.action] ?? match.action} · ${match.label}`,
    )
    .join('；')
}

function shortHash(value: string | undefined): string {
  return (value ?? '').slice(0, 12) || '未记录'
}

function snapshotLabel(snapshot: SourceSnapshot): string {
  return snapshot.previous_id ? '变更版本' : '首个基线'
}

function intervalText(definition: SourceDefinition): string {
  const seconds = definition.interval_seconds ?? 86_400
  return `${seconds} 秒`
}

function nextPage(): void {
  entryOffset.value += ENTRY_PAGE
}

function previousPage(): void {
  entryOffset.value = Math.max(0, entryOffset.value - ENTRY_PAGE)
}

function retrySources(): void {
  void refetch()
}
function retryEntries(): void {
  void refetchEntries()
}

function retrySnapshots(): void {
  void refetchSnapshots()
}

function retrySnapshot(): void {
  void refetchSnapshot()
}

const entriesErrorMessage = computed(() => entriesError.value?.message ?? '原始条目暂不可用。')
const snapshotsErrorMessage = computed(
  () => snapshotsError.value?.message ?? '网页版本暂不可用。',
)
const snapshotErrorMessage = computed(
  () => snapshotError.value?.message ?? '网页版本详情暂不可用。',
)
const snapshotMissing = computed(
  () => snapshotError.value instanceof ApiError && snapshotError.value.status === 404,
)
</script>

<template>
  <PageHeading title="来源管理" />

  <p class="muted source-intro">
    来源定义、原始条目与网页版本保存在本机数据库。保存定义或重放规则不会访问网络；收集由现有手动研究任务执行，共用研究锁与检索预算。
  </p>
  <div class="actions source-actions">
    <Button as-child variant="outline" class="h-11">
      <RouterLink to="/tasks">发起手动研究任务</RouterLink>
    </Button>
  </div>

  <Skeleton v-if="isPending" class="h-64 w-full" />
  <QueryError v-else-if="isError" :message="error?.message ?? '来源列表暂不可用。'" @retry="retrySources()" />

  <template v-else>
    <EmptyState
      v-if="!sources?.length"
      title="尚未配置来源"
      description="在 config.toml 或设置中加入公开网页、订阅源或公开目录后，来源会出现在这里。保存定义不会访问网络。"
    />

    <ol v-else class="record-list source-register">
      <li
        v-for="source in sources ?? []"
        :key="idOf(source.definition)"
        class="record source-record"
      >
        <div class="source-record-head">
          <h2>{{ source.definition.name }}</h2>
          <div class="chips">
            <span class="chip">{{ kindLabel(source.definition.kind) }}</span>
            <span class="chip">{{ sourceTypeLabel(source.definition.source_type) }}</span>
            <span class="chip" :class="{ 'chip--warning': stateOf(source)?.status === 'error' }">
              {{ healthLabel(stateOf(source)?.status ?? 'never') }}
            </span>
            <span v-if="source.definition.enabled === false" class="chip chip--warning">已停用</span>
          </div>
        </div>

        <p class="meta source-url">
          <SafeExternalLink :value="source.definition.url" label="打开来源地址" />
        </p>
        <p class="meta">
          {{ entryCount(source) }} · 轮询间隔 {{ intervalText(source.definition) }}
          <template v-if="stateOf(source)?.last_checked_at">
            · 最近检查 {{ formatDate(stateOf(source)?.last_checked_at) }}
          </template>
          <template v-if="stateOf(source)?.last_success_at">
            · 最近成功 {{ formatDate(stateOf(source)?.last_success_at) }}
          </template>
        </p>
        <p v-if="stateOf(source)?.next_check_at" class="meta">
          下次计划检查 {{ formatDate(stateOf(source)?.next_check_at) }}（仅在手动或定时研究任务运行时执行）
        </p>
        <p v-if="stateOf(source)?.etag || stateOf(source)?.last_modified" class="meta">
          条件请求标识：<bdi>{{ stateOf(source)?.etag || '未记录 ETag' }}</bdi> ·
          <bdi>{{ stateOf(source)?.last_modified || '未记录 Last-Modified' }}</bdi>
        </p>
        <p v-if="stateOf(source)?.error" class="error-message" role="alert">
          最近检查错误：{{ stateOf(source)?.error }}
        </p>
        <p v-if="stateOf(source)?.coverage_warning" class="notice notice--warning">
          {{ stateOf(source)?.coverage_warning }}
        </p>
        <p v-if="source.definition.review_reason" class="meta">
          人工审阅理由：{{ source.definition.review_reason }}
        </p>
        <p v-if="source.definition.reopen_if" class="meta">
          重启条件：{{ source.definition.reopen_if }}
        </p>
        <p class="meta">{{ accessNote(source.definition.kind ?? 'web') }}</p>

        <div class="actions">
          <Button
            variant="outline"
            class="h-11"
            :aria-expanded="expanded?.id === idOf(source.definition) && expanded?.mode === 'entries'"
            :aria-controls="panelId('entries', idOf(source.definition))"
            @click="toggle(idOf(source.definition), 'entries')"
          >
            查看原始条目与版本
          </Button>
          <Button
            variant="outline"
            class="h-11"
            :aria-expanded="expanded?.id === idOf(source.definition) && expanded?.mode === 'edit'"
            :aria-controls="panelId('form', idOf(source.definition))"
            @click="toggle(idOf(source.definition), 'edit')"
          >
            编辑来源定义
          </Button>
        </div>

        <section
          v-if="expanded?.id === idOf(source.definition) && expanded?.mode === 'entries'"
          :id="panelId('entries', idOf(source.definition))"
          class="source-panel"
          :aria-label="`${source.definition.name} 的原始条目与网页版本`"
        >
          <p v-if="replayNotice" class="meta" role="status">{{ replayNotice }}</p>
          <div class="actions">
            <Button
              variant="ghost"
              class="h-11"
              :disabled="replayMutation.isPending.value"
              @click="replayRules()"
            >
              {{ replayMutation.isPending.value ? '重放中…' : '重放软规则（不访问网络）' }}
            </Button>
          </div>

          <h3>原始条目</h3>
          <Skeleton v-if="entriesPending" class="h-40 w-full" />
          <QueryError
            v-else-if="entriesFailed && !entries?.length"
            :message="entriesErrorMessage"
            @retry="retryEntries()"
          />
          <EmptyState
            v-else-if="!entries?.length"
            title="尚无原始条目"
            description="运行一次手动研究任务后会保存来源条目。扩展、目录或模型处理失败时，原始条目仍会独立保留。"
          />
          <template v-else>
            <ol class="source-entries">
              <li
                v-for="entry in entries ?? []"
                :key="entry.id ?? `${entry.source_id}-${entry.external_id}`"
                class="source-entry"
              >
                <h4>
                  <SafeExternalLink :value="entry.url" :label="entry.title || '查看来源条目'" />
                </h4>
                <div class="chips">
                  <span class="badge">优先级 {{ entry.priority ?? 0 }}</span>
                  <span class="badge">第 {{ entry.revision ?? 1 }} 版</span>
                  <span class="badge">{{ shortHash(entry.content_hash) }}</span>
                  <span v-if="entry.needs_review" class="badge badge--warning">待审阅</span>
                </div>
                <p class="meta">
                  来源身份：<bdi>{{ entry.source_id }}</bdi> · 条目 <bdi>{{ entry.external_id }}</bdi>
                </p>
                <p class="meta">
                  发现 <time :datetime="entry.first_seen_at">{{ formatDate(entry.first_seen_at) }}</time>
                  · 最近 <time :datetime="entry.last_seen_at">{{ formatDate(entry.last_seen_at) }}</time>
                  <template v-if="entry.published_at">
                    · 来源发布时间 {{ formatDate(entry.published_at) }}
                  </template>
                </p>
                <p v-if="entry.rule_matches?.length" class="meta">
                  命中原因：{{ ruleMatches(entry) }}
                </p>
                <details class="entry-content">
                  <summary>正文与原始记录</summary>
                  <p class="preserve-lines">{{ entry.content || '来源未提供正文。' }}</p>
                  <details class="raw-disclosure">
                    <summary>原始内容</summary>
                    <pre class="raw-block">{{ entry.raw_content || '未保存原始内容。' }}</pre>
                  </details>
                </details>
              </li>
            </ol>
            <div class="actions">
              <Button
                variant="ghost"
                class="h-11"
                :disabled="entryOffset === 0 || entriesFetching"
                @click="previousPage()"
              >
                上一页
              </Button>
              <span class="meta">第 {{ Math.floor(entryOffset / ENTRY_PAGE) + 1 }} 页</span>
              <Button
                variant="ghost"
                class="h-11"
                :disabled="(entries?.length ?? 0) < ENTRY_PAGE || entriesFetching"
                @click="nextPage()"
              >
                下一页
              </Button>
            </div>
          </template>

          <h3>网页版本与差异</h3>
          <p class="muted">
            版本按抓取时间保留，原始内容与正文均不可覆盖；首个版本作为基线，后续版本显示与前一版本的正文及链接差异。
          </p>
          <Skeleton v-if="snapshotsPending" class="h-32 w-full" />
          <QueryError
            v-else-if="snapshotsFailed"
            :message="snapshotsErrorMessage"
            @retry="retrySnapshots()"
          />
          <EmptyState
            v-else-if="!snapshots?.length"
            title="尚无网页版本"
            description="来源第一次成功抓取后会保存基线版本。"
          />
          <ul v-else class="snapshot-list">
            <li v-for="snapshot in snapshots ?? []" :key="snapshot.id ?? shortHash(snapshot.fetched_at)">
              <p>
                <strong>{{ snapshotLabel(snapshot) }}</strong>
                · <span class="meta">版本 <bdi>{{ snapshot.id }}</bdi></span>
              </p>
              <p class="meta">
                抓取 {{ formatDate(snapshot.fetched_at) }}
                <template v-if="snapshot.previous_id">
                  · 前一版本 <bdi>{{ snapshot.previous_id }}</bdi>
                </template>
                · 配置指纹 <bdi>{{ shortHash(snapshot.config_hash) }}</bdi>
              </p>
              <div class="actions">
                <Button
                  variant="ghost"
                  class="h-11"
                  :aria-expanded="chosenSnapshotId === snapshot.id"
                  @click="chosenSnapshotId = chosenSnapshotId === snapshot.id ? '' : (snapshot.id ?? '')"
                >
                  {{ chosenSnapshotId === snapshot.id ? '收起版本详情' : '查看版本详情' }}
                </Button>
              </div>
            </li>
          </ul>

          <section v-if="chosenSnapshotId" class="snapshot-detail" aria-label="网页版本详情">
            <Skeleton v-if="snapshotPending" class="h-40 w-full" />
            <p v-else-if="snapshotMissing" class="muted">未找到此网页版本。请选择一个仍在列表中的版本。</p>
            <QueryError
              v-else-if="snapshotFailed"
              :message="snapshotErrorMessage"
              @retry="retrySnapshot()"
            />
            <template v-else-if="snapshotDetail">
              <h4>{{ snapshotDetail.previous_id ? '变更版本' : '首个基线' }}</h4>
              <dl class="facts">
                <dt>版本标识</dt>
                <dd><bdi>{{ snapshotDetail.id }}</bdi></dd>
                <dt>抓取时间</dt>
                <dd>{{ formatDate(snapshotDetail.fetched_at) }}</dd>
                <dt>前一版本</dt>
                <dd><bdi>{{ snapshotDetail.previous_id || '无（首个基线）' }}</bdi></dd>
                <dt>内容类型</dt>
                <dd>{{ snapshotDetail.content_type || '未说明' }}</dd>
                <dt>正文差异</dt>
                <dd>
                  <pre class="diff-block">{{ snapshotDetail.text_diff || '正文无差异。' }}</pre>
                </dd>
                <dt>新增链接</dt>
                <dd class="link-list">
                  <SafeExternalLink
                    v-for="link in snapshotDetail.added_links ?? []"
                    :key="`added-${link}`"
                    :value="link"
                    label="打开新增链接"
                  />
                  <span v-if="!(snapshotDetail.added_links ?? []).length">无</span>
                </dd>
                <dt>移除链接</dt>
                <dd class="link-list">
                  <SafeExternalLink
                    v-for="link in snapshotDetail.removed_links ?? []"
                    :key="`removed-${link}`"
                    :value="link"
                    label="打开已移除链接"
                  />
                  <span v-if="!(snapshotDetail.removed_links ?? []).length">无</span>
                </dd>
                <dt>原始内容</dt>
                <dd>
                  <details class="raw-disclosure">
                    <summary>展开原始内容</summary>
                    <pre class="raw-block">{{ snapshotDetail.raw_content }}</pre>
                  </details>
                </dd>
              </dl>
            </template>
          </section>
        </section>

        <section
          v-if="expanded?.id === idOf(source.definition) && expanded?.mode === 'edit' && draft"
          :id="panelId('form', idOf(source.definition))"
          class="source-panel source-form"
          :aria-label="`${source.definition.name} 的来源定义`"
        >
          <h3>来源定义</h3>
          <p class="muted">
            保存只写入本机定义，不访问网络。停用或修改审阅理由后可重新打开继续编辑。
          </p>

          <div v-if="formError" ref="formAlert" class="error-message" role="alert" tabindex="-1">
            {{ formError }}
          </div>
          <p v-if="savedMessage" class="notice notice--success" role="status">{{ savedMessage }}</p>

          <form class="source-form-grid" @submit.prevent="save">
            <div class="field">
              <Label :for="panelId('name', draft.id)">来源名称</Label>
              <input
                :id="panelId('name', draft.id)"
                v-model="draft.name"
                class="control"
                type="text"
                maxlength="200"
                required
              >
            </div>
            <div class="field">
              <Label :for="panelId('kind', draft.id)">来源类型</Label>
              <NativeSelect
                :id="panelId('kind', draft.id)"
                :model-value="draft.kind"
                class="control"
                @update:model-value="setKind($event)"
              >
                <NativeSelectOption value="web">网页</NativeSelectOption>
                <NativeSelectOption value="feed">订阅源（RSS / Atom / JSON Feed）</NativeSelectOption>
                <NativeSelectOption value="catalog">公开模型目录</NativeSelectOption>
              </NativeSelect>
            </div>
            <div class="field field--wide">
              <Label :for="panelId('url', draft.id)">公开地址</Label>
              <input
                :id="panelId('url', draft.id)"
                v-model="draft.url"
                class="control"
                type="url"
                inputmode="url"
                autocomplete="off"
                required
              >
              <p class="form-note">只接受无凭据的 HTTP(S) 公开地址；实际抓取时仍会校验 DNS 与跳转。</p>
            </div>
            <div class="field">
              <Label :for="panelId('source-type', draft.id)">来源身份</Label>
              <NativeSelect
                :id="panelId('source-type', draft.id)"
                :model-value="draft.source_type"
                class="control"
                @update:model-value="setSourceType($event)"
              >
                <NativeSelectOption value="official">官方来源</NativeSelectOption>
                <NativeSelectOption value="community">社区来源</NativeSelectOption>
                <NativeSelectOption value="github">GitHub 来源</NativeSelectOption>
                <NativeSelectOption value="catalog">第三方目录</NativeSelectOption>
              </NativeSelect>
            </div>
            <div class="field">
              <Label :for="panelId('official-domain', draft.id)">官方域名（可选）</Label>
              <input
                :id="panelId('official-domain', draft.id)"
                v-model="draft.official_domain"
                class="control"
                type="text"
                autocomplete="off"
              >
            </div>
            <div class="field">
              <Label :for="panelId('interval', draft.id)">轮询间隔（秒）</Label>
              <input
                :id="panelId('interval', draft.id)"
                v-model.number="draft.interval_seconds"
                class="control"
                type="number"
                :min="MIN_INTERVAL"
                :max="MAX_INTERVAL"
                step="60"
                inputmode="numeric"
                required
              >
            </div>
            <div class="field">
              <Label :for="panelId('checked-on', draft.id)">审阅日期</Label>
              <input
                :id="panelId('checked-on', draft.id)"
                v-model="draft.checked_on"
                class="control control--date"
                type="date"
              >
            </div>
            <div class="field field--full">
              <span :id="panelId('categories', draft.id)" class="field-legend">适用类别</span>
              <div class="category-grid" role="group" :aria-labelledby="panelId('categories', draft.id)">
                <label v-for="option in categoryOptions" :key="option.value" class="check-option">
                  <input v-model="draft.categories" type="checkbox" :value="option.value">
                  {{ option.label }}
                </label>
              </div>
            </div>
            <div class="field field--full">
              <label class="check-option">
                <input v-model="draft.enabled" type="checkbox">
                启用此来源（停用后保留已收集条目与版本）
              </label>
            </div>
            <div class="field">
              <Label :for="panelId('include', draft.id)">包含选择器（每行一个）</Label>
              <textarea
                :id="panelId('include', draft.id)"
                v-model="draft.include_selectors"
                class="control"
                rows="4"
                spellcheck="false"
              />
              <p class="form-note">留空时读取整页正文。选择器服务端校验，匹配失败按健康错误记录，不删除旧条目。</p>
            </div>
            <div class="field">
              <Label :for="panelId('exclude', draft.id)">排除选择器（每行一个）</Label>
              <textarea
                :id="panelId('exclude', draft.id)"
                v-model="draft.exclude_selectors"
                class="control"
                rows="4"
                spellcheck="false"
              />
            </div>
            <div class="field field--full">
              <Label :for="panelId('ignore', draft.id)">忽略模式（正则，每行一个）</Label>
              <textarea
                :id="panelId('ignore', draft.id)"
                v-model="draft.ignore_patterns"
                class="control"
                rows="3"
                spellcheck="false"
              />
              <p class="form-note">忽略模式只影响归一化正文与版本差异，原始内容始终保留。</p>
            </div>
            <div class="field field--full">
              <span :id="panelId('rules', draft.id)" class="field-legend">软规则</span>
              <p :id="panelId('rules-hint', draft.id)" class="form-note">规则只标注或调整原始条目优先级，不丢弃条目，也不改变内容版本。</p>
              <div v-if="draft.rules.length" class="rule-list">
                <div v-for="(rule, index) in draft.rules" :key="rule.id" class="rule-row">
                  <div class="field">
                    <Label :for="panelId(`rule-label-${index}`, draft.id)">标签</Label>
                    <input
                      :id="panelId(`rule-label-${index}`, draft.id)"
                      v-model="rule.label"
                      class="control"
                      type="text"
                      maxlength="120"
                    >
                  </div>
                  <div class="field">
                    <Label :for="panelId(`rule-field-${index}`, draft.id)">检查字段</Label>
                    <NativeSelect
                      :id="panelId(`rule-field-${index}`, draft.id)"
                      :model-value="rule.field"
                      class="control"
                      @update:model-value="setRuleField(index, $event)"
                    >
                      <NativeSelectOption value="title">标题</NativeSelectOption>
                      <NativeSelectOption value="content">正文</NativeSelectOption>
                      <NativeSelectOption value="url">链接</NativeSelectOption>
                    </NativeSelect>
                  </div>
                  <div class="field">
                    <Label :for="panelId(`rule-pattern-${index}`, draft.id)">表达式</Label>
                    <input
                      :id="panelId(`rule-pattern-${index}`, draft.id)"
                      v-model="rule.pattern"
                      class="control"
                      type="text"
                      maxlength="1000"
                      spellcheck="false"
                    >
                  </div>
                  <div class="field">
                    <Label :for="panelId(`rule-action-${index}`, draft.id)">动作</Label>
                    <NativeSelect
                      :id="panelId(`rule-action-${index}`, draft.id)"
                      :model-value="rule.action"
                      class="control"
                      @update:model-value="setRuleAction(index, $event)"
                    >
                      <NativeSelectOption value="tag">标注</NativeSelectOption>
                      <NativeSelectOption value="deprioritize">降低优先级</NativeSelectOption>
                      <NativeSelectOption value="review">标记待审阅</NativeSelectOption>
                    </NativeSelect>
                  </div>
                  <Button
                    variant="ghost"
                    class="h-11 rule-remove"
                    type="button"
                    @click="removeRule(index)"
                  >
                    删除规则
                  </Button>
                </div>
              </div>
              <div class="actions">
                <Button variant="outline" class="h-11" type="button" @click="addRule()">
                  添加软规则
                </Button>
              </div>
            </div>
            <div class="field field--full">
              <Label :for="panelId('review-reason', draft.id)">人工审阅理由</Label>
              <textarea
                :id="panelId('review-reason', draft.id)"
                v-model="draft.review_reason"
                class="control"
                rows="2"
              />
            </div>
            <div class="field field--full">
              <Label :for="panelId('reopen-if', draft.id)">重启条件</Label>
              <textarea
                :id="panelId('reopen-if', draft.id)"
                v-model="draft.reopen_if"
                class="control"
                rows="2"
              />
            </div>
            <div class="field field--full form-actions">
              <Button type="submit" class="h-11" :disabled="saveMutation.isPending.value">
                {{ saveMutation.isPending.value ? '保存中…' : '保存来源定义' }}
              </Button>
              <p class="form-note">保存不会触发网络请求或研究任务。</p>
            </div>
          </form>
        </section>
      </li>
    </ol>
  </template>
</template>

<style scoped>
.source-intro { max-inline-size: 75ch; }
.source-actions { margin-block: 0.75rem 1.25rem; }
.source-register { margin-block-start: 0.5rem; }
.source-record { padding-block: 1.25rem; }
.source-record-head { display: flex; flex-wrap: wrap; align-items: baseline; justify-content: space-between; gap: 0.5rem 1.5rem; }
.source-record-head h2 { font: 600 1.375rem/1.35 var(--font-body); min-inline-size: 0; overflow-wrap: anywhere; }
.source-record h3 { margin-block: 1.75rem 0.6rem; font: 600 1.125rem/1.4 var(--font-body); }
.source-record h4 { margin-block: 0; font: 600 1rem/1.45 var(--font-body); overflow-wrap: anywhere; }
.source-url { overflow-wrap: anywhere; }
.source-panel { margin-block-start: 1rem; padding-block-start: 1rem; border-block-start: 1px solid var(--color-border); min-inline-size: 0; }
.source-entries { margin: 0; padding: 0; list-style: none; }
.source-entry { padding-block: 1rem; border-block-end: 1px solid var(--color-border); min-inline-size: 0; overflow-wrap: anywhere; }
.source-entry + .source-entry { margin-block-start: 0; }
.entry-content { margin-block-start: 0.5rem; }
.entry-content > summary, .raw-disclosure > summary { min-block-size: 2.4rem; padding-block: 0.35rem; font: 500 0.8125rem/1.5 var(--font-ui); cursor: pointer; }
.entry-content p { max-inline-size: 75ch; }
.raw-block, .diff-block { margin: 0.35rem 0 0; padding: 0.75rem; max-block-size: 28rem; overflow: auto; border: 1px solid var(--color-border); background: var(--color-bg-subtle); font: 400 0.75rem/1.55 var(--font-mono); white-space: pre-wrap; overflow-wrap: anywhere; }
.diff-block { max-block-size: 22rem; }
.snapshot-list { margin: 0.5rem 0 0; padding: 0; list-style: none; }
.snapshot-list > li { padding-block: 0.85rem; border-block-end: 1px solid var(--color-border); }
.snapshot-list p { margin-block: 0 0.25rem; }
.snapshot-detail { margin-block-start: 1rem; padding-block-start: 0.75rem; border-block-start: 1px solid var(--color-border); }
.link-list { display: flex; flex-direction: column; gap: 0.25rem; }
.link-list a { overflow-wrap: anywhere; }
.source-form-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 1.25rem 1.5rem; margin-block-start: 1.25rem; }
.field { display: flex; flex-direction: column; gap: 0.3rem; min-inline-size: 0; }
.field--wide, .field--full { grid-column: 1 / -1; }
.field-legend { font: 500 0.8125rem/1.5 var(--font-ui); }
.control { inline-size: 100%; min-block-size: 2.75rem; padding: 0.45rem 0.7rem; border: 1px solid var(--color-control-border); border-radius: 0; color: var(--color-text); background-color: var(--color-bg-surface); font: 400 0.875rem/1.5 var(--font-ui); }
textarea.control { min-block-size: 5.5rem; line-height: 1.55; resize: vertical; }
.control--date { max-inline-size: 14rem; }
.category-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 0 1rem; }
.rule-list { display: grid; gap: 0.85rem; margin-block: 0.35rem 0.5rem; }
.rule-row { display: grid; grid-template-columns: minmax(8rem, 1fr) repeat(3, minmax(7rem, 1fr)) auto; gap: 0.75rem; align-items: end; padding-block: 0.75rem; border-block-start: 1px solid var(--color-border); }
.rule-remove { align-self: end; }
.form-actions { align-items: center; flex-wrap: wrap; margin-block-start: 0.25rem; padding-block-start: 1rem; border-block-start: 1px solid var(--color-text); }
@media (max-width: 1099px) {
  .rule-row { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .rule-remove { justify-self: start; }
}
@media (max-width: 699px) {
  .source-form-grid { grid-template-columns: minmax(0, 1fr); }
  .category-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .rule-row { grid-template-columns: minmax(0, 1fr); }
}
</style>