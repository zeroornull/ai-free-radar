<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import { ApiError } from '@/api/client'
import type { ReviewAction, RunRead, UserAction } from '@/api/types'
import { useAppQuery, useRecheckMutation, useResourceQuery, useReviewMutation } from '@/api/queries'
import { formatBoolean, formatDate, labelFor } from '@/app/presentation'
import PageHeading from '@/components/shared/PageHeading.vue'
import StatusBadge from '@/components/shared/StatusBadge.vue'
import PolicyChip from '@/components/shared/PolicyChip.vue'
import SafeExternalLink from '@/components/shared/SafeExternalLink.vue'
import FactsList from '@/components/shared/FactsList.vue'
import EvidenceList from '@/components/shared/EvidenceList.vue'
import QueryError from '@/components/shared/QueryError.vue'
import ErrorPage from '@/components/shared/ErrorPage.vue'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import ResourceHistory from './ResourceHistory.vue'

const route = useRoute()
const { data: app } = useAppQuery()

const resourceId = computed(() => {
  const value = route.params.id
  return Array.isArray(value) ? (value[0] ?? '') : (value ?? '')
})

const {
  data: detail,
  isPending: detailPending,
  isError: detailFailed,
  error: detailError,
  refetch: refetchDetail,
} = useResourceQuery(resourceId)

const resource = computed(() => detail.value?.resource)
const history = computed(() => detail.value?.history ?? [])

const isNotFound = computed(
  () => detailError.value instanceof ApiError && detailError.value.status === 404,
)
const errorMessage = computed(() => detailError.value?.message ?? '请求失败，请稍后重试。')
const initialError = computed(() => detailFailed.value && detail.value === undefined)
const backgroundError = computed(() => detailFailed.value && detail.value !== undefined)

const modelsText = computed(() => (resource.value?.models ?? []).join('、') || '未说明')
const headingTitle = computed(() =>
  resource.value ? `${resource.value.provider} · ${resource.value.service}` : '资源详情',
)

const ACTION_LABELS: Record<ReviewAction, string> = {
  confirm: '确认',
  reject: '驳回',
  ignore: '忽略',
  reopen: '恢复处理',
  favorite: '收藏',
  unfavorite: '取消收藏',
  note: '备注',
}

const review = computed(() => detail.value?.review)
const actions = computed(() => detail.value?.actions ?? [])
const noteDraft = ref('')
watch(
  () => detail.value?.review.note,
  (note) => {
    noteDraft.value = note ?? ''
  },
  { immediate: true },
)

const reviewMutation = useReviewMutation(resourceId)
const recheckMutation = useRecheckMutation(resourceId)
const recheckRun = ref<RunRead | null>(null)
const reviewError = computed(() => reviewMutation.error.value?.message ?? '')
const recheckError = computed(() => recheckMutation.error.value?.message ?? '')

function reviewStateLabel(state: string): string {
  return app.value?.review_states?.[state] ?? state
}

function actionLabel(action: UserAction): string {
  return ACTION_LABELS[action.action] ?? action.action
}

function actionResultLabel(actionRecord: UserAction): string {
  const after = actionRecord.after ?? {}
  const parts: string[] = []
  if (typeof after.state === 'string') parts.push(`状态：${reviewStateLabel(after.state)}`)
  if (typeof after.favorite === 'boolean') parts.push(`收藏：${after.favorite ? '是' : '否'}`)
  if (typeof after.note === 'string') {
    parts.push(after.note.trim() ? `备注：${after.note}` : '备注：已清空')
  }
  return parts.join(' · ')
}

async function applyAction(action: ReviewAction): Promise<void> {
  try {
    await reviewMutation.mutateAsync({ action })
  } catch {
    // 失败原因由 Mutation 错误状态呈现。
  }
}

async function toggleFavorite(): Promise<void> {
  await applyAction(review.value?.favorite ? 'unfavorite' : 'favorite')
}

async function saveNote(): Promise<void> {
  try {
    await reviewMutation.mutateAsync({ action: 'note', note: noteDraft.value })
  } catch {
    // 失败原因由 Mutation 错误状态呈现。
  }
}

async function triggerRecheck(): Promise<void> {
  recheckRun.value = null
  try {
    recheckRun.value = await recheckMutation.mutateAsync(undefined)
  } catch {
    // 失败原因由 Mutation 错误状态呈现。
  }
}

const reviewPending = reviewMutation.isPending
const recheckPending = recheckMutation.isPending
</script>

<template>
  <PageHeading eyebrow="资源详情" :title="headingTitle" />
  <RouterLink class="back-link" to="/resources">返回资源库</RouterLink>

  <Skeleton v-if="detailPending" class="h-64 w-full" />
  <ErrorPage
    v-else-if="initialError"
    :title="isNotFound ? '资源未找到' : '资源暂不可用'"
    :detail="isNotFound ? '未找到此资源。请返回资源库选择已有资源。' : errorMessage"
  />
  <template v-else-if="resource">
    <QueryError v-if="backgroundError" :message="errorMessage" @retry="refetchDetail()" />

    <section class="panel" aria-labelledby="resource-policy">
      <h2 id="resource-policy">免费政策与接入信息</h2>
      <div class="chips">
        <StatusBadge :value="resource.status" :label="labelFor(app, resource.status)" />
        <span class="chip">{{ labelFor(app, resource.category) }}</span>
        <span class="chip">{{ labelFor(app, resource.free_type) }}</span>
        <PolicyChip
          :value="resource.china_policy"
          :label="labelFor(app, resource.china_policy)"
        />
      </div>
      <div v-if="resource.check_status !== 'success'" class="notice failure-note">
        <div>
          <strong>本次核查{{ labelFor(app, resource.check_status) }}，结论未获本次更新。</strong>
          <p>{{ resource.failure_reason || '尚无完整核查结果；保留上次已确认结论。' }}</p>
          <p>上次成功核查：{{ formatDate(resource.last_success_at) }}</p>
        </div>
      </div>
      <FactsList>
        <dt>提供商</dt>
        <dd><bdi>{{ resource.provider }}</bdi></dd>
        <dt>具体 API 服务</dt>
        <dd><bdi>{{ resource.service }}</bdi></dd>
        <dt>可用模型</dt>
        <dd>{{ modelsText }}</dd>
        <dt>免费形式</dt>
        <dd>{{ labelFor(app, resource.free_type) }}</dd>
        <dt>免费额度及单位</dt>
        <dd>{{ resource.quota }} {{ resource.quota_unit }}</dd>
        <dt>刷新周期</dt>
        <dd>{{ resource.refresh_cycle }}</dd>
        <dt>限速</dt>
        <dd>{{ resource.rate_limit }}</dd>
        <dt>注册及领取条件</dt>
        <dd>{{ resource.claim_conditions }}</dd>
        <dt>是否要求支付</dt>
        <dd>{{ formatBoolean(resource.payment_required ?? null) }}</dd>
        <dt>是否要求绑定支付方式</dt>
        <dd>{{ formatBoolean(resource.payment_method_required ?? null) }}</dd>
        <dt>到期时间</dt>
        <dd>{{ formatDate(resource.expires_at, '未说明') }}</dd>
        <dt>有效期说明</dt>
        <dd>{{ resource.expiry_notes }}</dd>
        <dt>注册及使用地区限制</dt>
        <dd>{{ resource.region_restrictions }}</dd>
        <dt>中国大陆政策</dt>
        <dd>{{ labelFor(app, resource.china_policy) }}（依据见来源记录）</dd>
        <dt>调用与网络</dt>
        <dd>未实测调用；网络访问未实测</dd>
        <dt>接入入口</dt>
        <dd><SafeExternalLink :value="resource.api_url" label="打开 API 接入入口" /></dd>
        <dt>API 文档</dt>
        <dd><SafeExternalLink :value="resource.docs_url" label="阅读 API 文档" /></dd>
        <dt>本次核查结果</dt>
        <dd>{{ labelFor(app, resource.check_status) }}</dd>
        <dt>最近核查时间</dt>
        <dd>{{ formatDate(resource.last_checked_at) }}</dd>
        <dt>上次成功核查</dt>
        <dd>{{ formatDate(resource.last_success_at) }}</dd>
        <dt>首次发现</dt>
        <dd>{{ formatDate(resource.first_seen_at) }}</dd>
        <dt>已推荐时间</dt>
        <dd>{{ formatDate(resource.recommended_at) }}</dd>
        <dt>最近关联任务</dt>
        <dd>
          <RouterLink v-if="resource.last_task_id" :to="`/tasks/${resource.last_task_id}`">
            查看任务 <bdi>{{ resource.last_task_id }}</bdi>
          </RouterLink>
          <span v-else>尚无关联任务</span>
        </dd>
        <dt>资源标识</dt>
        <dd><bdi>{{ resource.id }}</bdi></dd>
      </FactsList>
    </section>

    <section class="panel" aria-labelledby="resource-review">
      <h2 id="resource-review">人工判断</h2>
      <p class="muted">人工判断不改变官方政策与证据字段。被忽略的资源不再自动重查，也不进入简报。</p>

      <div v-if="review">
        <div class="chips">
          <span class="chip">状态：{{ reviewStateLabel(review.state) }}</span>
          <span class="chip">{{ review.favorite ? '已收藏' : '未收藏' }}</span>
        </div>
        <p class="meta">最近人工处理：{{ formatDate(review.updated_at, '尚无人工处理记录') }}</p>
        <p v-if="review.note" class="meta preserve-lines">当前备注：{{ review.note }}</p>
      </div>

      <div v-if="reviewError" class="error-message" role="alert">
        <strong>判断未保存</strong>
        <p>{{ reviewError }}</p>
      </div>

      <div class="actions">
        <Button type="button" class="h-11" :disabled="reviewPending" @click="applyAction('confirm')">
          确认
        </Button>
        <Button
          type="button"
          variant="outline"
          class="h-11"
          :disabled="reviewPending"
          @click="applyAction('reject')"
        >
          驳回
        </Button>
        <Button
          type="button"
          variant="outline"
          class="h-11"
          :disabled="reviewPending"
          @click="applyAction('ignore')"
        >
          忽略
        </Button>
        <Button
          type="button"
          variant="ghost"
          class="h-11"
          :disabled="reviewPending"
          @click="applyAction('reopen')"
        >
          恢复处理
        </Button>
      </div>

      <div class="actions">
        <Button
          type="button"
          variant="ghost"
          class="h-11"
          :disabled="reviewPending"
          @click="toggleFavorite"
        >
          {{ review?.favorite ? '取消收藏' : '收藏' }}
        </Button>
        <Button
          type="button"
          variant="outline"
          class="h-11"
          :disabled="recheckPending"
          @click="triggerRecheck"
        >
          重查这一条
        </Button>
      </div>
      <p v-if="recheckError" class="error-message" role="alert">{{ recheckError }}</p>
      <p v-if="recheckRun" class="meta" role="status">
        已发起重查任务，<RouterLink :to="`/tasks/${recheckRun.id}`">查看运行状态</RouterLink>。
      </p>

      <form class="review-note-form" @submit.prevent="saveNote">
        <Label for="review-note">人工备注</Label>
        <textarea
          id="review-note"
          v-model="noteDraft"
          class="note-input"
          rows="3"
          maxlength="2000"
          :disabled="reviewPending"
        />
        <p class="form-note">备注仅保存在本机，最多 2000 字，不修改官方政策与证据字段。</p>
        <div class="actions">
          <Button type="submit" variant="outline" class="h-11" :disabled="reviewPending">
            保存备注
          </Button>
        </div>
      </form>

      <h3>操作记录</h3>
      <ol v-if="actions.length" class="history-list">
        <li v-for="record in actions" :key="record.id ?? `${record.action}-${record.created_at}`">
          <p><strong>{{ actionLabel(record) }}</strong> · {{ formatDate(record.created_at) }}</p>
          <p class="meta">{{ actionResultLabel(record) || '无字段变化' }}</p>
        </li>
      </ol>
      <p v-else class="muted">尚无人工处理记录。</p>
    </section>

    <section class="panel">
      <h2>关键事实与来源</h2>
      <p class="muted">官方依据用于确认政策；社区线索仅用于发现，不能单独支持正式推荐。</p>
      <EvidenceList :items="resource.evidence ?? []" />
    </section>

    <ResourceHistory :history="history" />
  </template>
</template>

<style>
.review-note-form {
  margin-block-start: var(--space-2);
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
}
.review-note-form .actions { margin-block: 0; }
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
</style>