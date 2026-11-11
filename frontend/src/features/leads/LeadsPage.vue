<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import type { LeadRead, ReviewAction, RunRead } from '@/api/types'
import {
  useAppQuery,
  useBackfillTranslationMutation,
  useBackfillMessagesMutation,
  useLeadsQuery,
  useRecheckMutation,
  useReviewMutation,
} from '@/api/queries'
import { formatDate, labelFor } from '@/app/presentation'
import PageHeading from '@/components/shared/PageHeading.vue'
import EmptyState from '@/components/shared/EmptyState.vue'
import QueryError from '@/components/shared/QueryError.vue'
import StatusBadge from '@/components/shared/StatusBadge.vue'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'

type RowAction = ReviewAction | 'recheck'

const ACTION_LABELS: Record<ReviewAction, string> = {
  confirm: '确认',
  reject: '驳回',
  ignore: '忽略',
  reopen: '恢复处理',
  favorite: '收藏',
  unfavorite: '取消收藏',
  note: '备注',
}

interface LocalizedText {
  text: string
  original: string
  translated: boolean
}

function localizedText(original: string, translation: string | undefined): LocalizedText {
  const zh = translation?.trim() ?? ''
  if (!zh) return { text: original, original, translated: false }
  return { text: zh, original, translated: true }
}

const { data: app } = useAppQuery()
const router = useRouter()
const {
  data: leadsData,
  isPending: leadsPending,
  isError: leadsFailed,
  error: leadsError,
  refetch: refetchLeads,
} = useLeadsQuery()

const retainedLeads = ref<LeadRead[]>([])
watch(
  leadsData,
  (data) => {
    if (data !== undefined) retainedLeads.value = data
  },
  { immediate: true },
)
const leads = computed(() => leadsData.value ?? retainedLeads.value)
const errorMessage = computed(() => leadsError.value?.message ?? '请求失败，请稍后重试。')

const failureReasonViews = computed(() => {
  const views = new Map<LeadRead, LocalizedText>()
  for (const lead of leads.value) {
    views.set(lead, localizedText(lead.resource.failure_reason, lead.resource.failure_reason_zh))
  }
  return views
})

function failureReasonView(lead: LeadRead): LocalizedText {
  return failureReasonViews.value.get(lead)
    ?? localizedText(lead.resource.failure_reason, lead.resource.failure_reason_zh)
}

const backfillMutation = useBackfillTranslationMutation()
const backfillPending = backfillMutation.isPending
const backfillError = computed(() => backfillMutation.error.value?.message ?? '')

async function runBackfill(): Promise<void> {
  try {
    const run = await backfillMutation.mutateAsync(undefined)
    await router.push(`/tasks/${run.id}`)
  } catch {
    // 失败原因由 backfillError 呈现。
  }
}

const sourceBackfillMutation = useBackfillMessagesMutation()
const sourceBackfillPending = sourceBackfillMutation.isPending
const sourceBackfillError = computed(() => sourceBackfillMutation.error.value?.message ?? '')
async function backfillSources(): Promise<void> {
  try {
    const run = await sourceBackfillMutation.mutateAsync(undefined)
    await router.push(`/tasks/${run.id}`)
  } catch {
    // 由 sourceBackfillError 显示接口返回的原因。
  }
}

const drafts = ref<Record<string, string>>({})
const rowErrors = ref<Record<string, string>>({})
const rowBusy = ref<Record<string, RowAction | undefined>>({})
const recheckResults = ref<Record<string, RunRead>>({})

const activeReviewId = ref('')
const activeRecheckId = ref('')
const reviewMutation = useReviewMutation(() => activeReviewId.value)
const recheckMutation = useRecheckMutation(() => activeRecheckId.value)
const reviewPending = reviewMutation.isPending
const recheckPending = recheckMutation.isPending

function resourceId(lead: LeadRead): string {
  return lead.resource.id ?? ''
}

function stateText(lead: LeadRead): string {
  const label = app.value?.review_states?.[lead.review.state]
  return label ?? lead.review.state
}

function draftFor(lead: LeadRead): string {
  const id = resourceId(lead)
  return drafts.value[id] ?? lead.review.note ?? ''
}

function setDraft(lead: LeadRead, value: string): void {
  drafts.value = { ...drafts.value, [resourceId(lead)]: value }
}

function busyText(lead: LeadRead): string {
  const action = rowBusy.value[resourceId(lead)]
  if (action === 'recheck') return '正在发起按需核验…'
  return action ? `正在提交“${ACTION_LABELS[action]}”…` : ''
}

function onNoteInput(lead: LeadRead, event: Event): void {
  const target = event.target as HTMLTextAreaElement | null
  setDraft(lead, target?.value ?? '')
}

function clearRowError(id: string): void {
  if (!(id in rowErrors.value)) return
  const next = { ...rowErrors.value }
  delete next[id]
  rowErrors.value = next
}

function setRowError(id: string, error: unknown): void {
  rowErrors.value = {
    ...rowErrors.value,
    [id]: error instanceof Error ? error.message : '请求失败，请稍后重试。',
  }
}

function setBusy(id: string, action: RowAction | undefined): void {
  rowBusy.value = { ...rowBusy.value, [id]: action }
}

async function runReview(lead: LeadRead, action: ReviewAction, note?: string): Promise<void> {
  const id = resourceId(lead)
  if (!id) return
  activeReviewId.value = id
  setBusy(id, action)
  clearRowError(id)
  try {
    const result = await reviewMutation.mutateAsync(
      note === undefined ? { action } : { action, note },
    )
    drafts.value = { ...drafts.value, [id]: result.review.note ?? '' }
  } catch (error) {
    setRowError(id, error)
  } finally {
    setBusy(id, undefined)
  }
}

async function saveNote(lead: LeadRead): Promise<void> {
  await runReview(lead, 'note', draftFor(lead))
}

async function toggleFavorite(lead: LeadRead): Promise<void> {
  await runReview(lead, lead.review.favorite ? 'unfavorite' : 'favorite')
}

async function runRecheck(lead: LeadRead): Promise<void> {
  const id = resourceId(lead)
  if (!id) return
  activeRecheckId.value = id
  setBusy(id, 'recheck')
  clearRowError(id)
  try {
    const run = await recheckMutation.mutateAsync(undefined)
    recheckResults.value = { ...recheckResults.value, [id]: run }
  } catch (error) {
    setRowError(id, error)
  } finally {
    setBusy(id, undefined)
  }
}
</script>

<template>
  <PageHeading eyebrow="历史线索" title="历史线索">
    <template #actions>
      <Button type="button" class="h-11" :disabled="sourceBackfillPending || backfillPending || Boolean(app?.active_run)" @click="backfillSources">
        {{ sourceBackfillPending ? '正在发起…' : '补齐存量消息' }}
      </Button>
      <Button
        type="button"
        variant="outline"
        class="h-11"
        :disabled="backfillPending || sourceBackfillPending || Boolean(app?.active_run)"
        @click="runBackfill"
      >
        {{ backfillPending ? '正在发起…' : '回填译文' }}
      </Button>
    </template>
  </PageHeading>
  <p class="muted">
    这里保留尚无可追溯消息来源的历史记录。使用“补齐存量消息”恢复本地来源，并为仍缺来源的记录补搜；补齐后可在资源库查看。
    额度、期限或绑卡条件未说明不影响消息收录。官方政策核验可按需发起，人工判断与收集消息分开保存。
  </p>
  <p v-if="backfillError" class="error-message" role="alert">{{ backfillError }}</p>
  <p v-if="sourceBackfillError" class="error-message" role="alert">{{ sourceBackfillError }}</p>

  <Skeleton v-if="leadsPending && leads.length === 0" class="h-52 w-full" />
  <QueryError
    v-else-if="leadsFailed && leads.length === 0"
    :message="errorMessage"
    @retry="refetchLeads()"
  />
  <template v-else>
    <QueryError v-if="leadsFailed" :message="errorMessage" @retry="refetchLeads()" />

    <template v-if="leads.length">
      <p class="muted" role="status">共 {{ leads.length }} 条历史线索来源待补。</p>
      <ul class="record-list leads-list">
        <li
          v-for="(lead, index) in leads"
          :key="resourceId(lead) || `${lead.resource.provider}-${lead.resource.service}`"
          class="record lead-record"
        >
          <div class="record-heading">
            <h2>
              <RouterLink :to="`/resources/${resourceId(lead)}`">
                <bdi>{{ lead.resource.provider }} · {{ lead.resource.service }}</bdi>
              </RouterLink>
            </h2>
            <div class="chips">
              <span class="chip">{{ labelFor(app, lead.resource.category) }}</span>
              <StatusBadge value="pending" label="来源待补" />
              <span class="chip">{{ stateText(lead) }}</span>
            </div>
          </div>

          <p class="muted">历史线索 · 来源待补</p>
          <details v-if="lead.resource.failure_reason" class="reason">
            <summary>可选：查看历史政策核验说明</summary>
            <p class="reason-body failure preserve-lines">
              按需核验说明：{{ failureReasonView(lead).text }}
            </p>
            <details v-if="failureReasonView(lead).translated" class="translation-details">
              <summary>原文</summary>
              <p class="preserve-lines">{{ failureReasonView(lead).original }}</p>
            </details>
            <p v-if="failureReasonView(lead).translated" class="meta translation-note">
              机器翻译，未经核验
            </p>
          </details>
          <p class="meta">首次发现：{{ formatDate(lead.resource.first_seen_at) }}</p>
          <p v-if="lead.review.note" class="meta preserve-lines">人工备注：{{ lead.review.note }}</p>

          <div class="actions lead-actions">
            <Button
              type="button"
              class="h-11"
              :disabled="reviewPending || Boolean(rowBusy[resourceId(lead)])"
              @click="runReview(lead, 'confirm')"
            >
              确认
            </Button>
            <Button
              type="button"
              variant="outline"
              class="h-11"
              :disabled="reviewPending || Boolean(rowBusy[resourceId(lead)])"
              @click="runReview(lead, 'reject')"
            >
              驳回
            </Button>
            <Button
              type="button"
              variant="outline"
              class="h-11"
              :disabled="reviewPending || Boolean(rowBusy[resourceId(lead)])"
              @click="runReview(lead, 'ignore')"
            >
              忽略
            </Button>
            <Button
              type="button"
              variant="ghost"
              class="h-11"
              :disabled="reviewPending || Boolean(rowBusy[resourceId(lead)])"
              @click="toggleFavorite(lead)"
            >
              {{ lead.review.favorite ? '取消收藏' : '收藏' }}
            </Button>
            <Button
              type="button"
              variant="ghost"
              class="h-11"
              :disabled="recheckPending || Boolean(rowBusy[resourceId(lead)])"
              @click="runRecheck(lead)"
            >
              按需核验
            </Button>
          </div>

          <p v-if="rowBusy[resourceId(lead)]" class="meta" role="status">
            {{ busyText(lead) }}
          </p>
          <p
            v-if="rowErrors[resourceId(lead)]"
            class="error-message"
            role="alert"
          >
            {{ rowErrors[resourceId(lead)] }}
          </p>
          <p
            v-if="recheckResults[resourceId(lead)]"
            class="meta"
            role="status"
          >
            已发起按需核验任务，<RouterLink :to="`/tasks/${recheckResults[resourceId(lead)].id}`">
              查看运行状态
            </RouterLink>。
          </p>

          <form class="note-form" @submit.prevent="saveNote(lead)">
            <Label :for="`lead-note-${index}`">人工备注</Label>
            <textarea
              :id="`lead-note-${index}`"
              class="note-input"
              rows="2"
              maxlength="2000"
              :value="draftFor(lead)"
              :disabled="reviewPending || Boolean(rowBusy[resourceId(lead)])"
              @input="onNoteInput(lead, $event)"
            />
            <div class="actions">
              <Button
                type="submit"
                variant="outline"
                class="h-11"
                :disabled="reviewPending || Boolean(rowBusy[resourceId(lead)])"
              >
                保存备注
              </Button>
            </div>
          </form>
        </li>
      </ul>
    </template>

    <EmptyState
      v-else
      title="当前没有来源待补的历史线索"
      description="有来源的消息已收录到资源库；未说明的条件会随消息保留。"
    >
      <template #actions>
        <div class="actions">
          <Button as-child variant="ghost" class="h-11">
            <RouterLink to="/resources">浏览资源库</RouterLink>
          </Button>
        </div>
      </template>
    </EmptyState>
  </template>
</template>

<style>
.leads-list { gap: var(--space-3); }
.lead-record .lead-actions { margin-block-start: var(--space-2); }
.lead-record .reason-body { margin-block: var(--space-2) 0; }
.note-form {
  margin-block-start: var(--space-2);
  padding-block-start: var(--space-2);
  border-block-start: 1px solid var(--color-border);
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
}
.note-input {
  font: inherit;
  font-size: 1rem;
  inline-size: 100%;
  min-block-size: 2.75rem;
  padding: 0.5rem 0.7rem;
  border: 1px solid var(--color-control-border);
  border-radius: var(--radius-sm);
  color: var(--color-text);
  background-color: var(--color-bg-surface);
  line-height: 1.55;
  resize: vertical;
}
.note-form .actions { margin-block: 0; }
.translation-details { margin-block-start: 0.35rem; border: 1px solid var(--color-border); border-radius: var(--radius-sm); background: var(--color-bg-surface); padding: 0.35rem 0.6rem; }
.translation-details summary { min-block-size: 2rem; padding-block: 0.15rem; color: var(--color-text-secondary); font-size: 0.8125rem; font-weight: 600; }
.translation-details p { margin-block: 0.35rem 0; color: var(--color-text-secondary); font-size: 0.875rem; line-height: 1.55; }
.translation-note { color: var(--color-text-tertiary); }
</style>