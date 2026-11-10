<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import type { LeadRead, ReviewAction, RunRead } from '@/api/types'
import {
  useAppQuery,
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

const { data: app } = useAppQuery()
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
  if (action === 'recheck') return '正在发起重查…'
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
  <PageHeading eyebrow="待核实线索" title="待核实线索" />
  <p class="muted">
    人工判断与模型证据分开保存：处理只改变审核状态，不修改官方政策与证据字段；被忽略的资源不再自动重查，也不进入简报。
  </p>

  <Skeleton v-if="leadsPending && leads.length === 0" class="h-52 w-full" />
  <QueryError
    v-else-if="leadsFailed && leads.length === 0"
    :message="errorMessage"
    @retry="refetchLeads()"
  />
  <template v-else>
    <QueryError v-if="leadsFailed" :message="errorMessage" @retry="refetchLeads()" />

    <template v-if="leads.length">
      <p class="muted" role="status">共 {{ leads.length }} 条线索等待人工处理。</p>
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
              <StatusBadge :value="lead.resource.status" :label="labelFor(app, lead.resource.status)" />
              <StatusBadge
                :value="lead.resource.check_status"
                :label="labelFor(app, lead.resource.check_status)"
              />
              <span class="chip">{{ stateText(lead) }}</span>
            </div>
          </div>

          <p v-if="lead.resource.failure_reason" class="reason-body failure preserve-lines">
            失败原因：{{ lead.resource.failure_reason }}
          </p>
          <p class="meta">最近核查：{{ formatDate(lead.resource.last_checked_at) }}</p>
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
              重查这一条
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
            已发起重查任务，<RouterLink :to="`/tasks/${recheckResults[resourceId(lead)].id}`">
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
      title="当前没有待核实的线索。"
      description="新的待核实资源会在自动核查后出现在这里；人工处理过的记录可从资源库查看。"
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
</style>