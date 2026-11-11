<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter, type LocationQuery } from 'vue-router'
import type { AppRead, Resource, ResourceReview } from '@/api/types'
import { useAppQuery, useBackfillMessagesMutation, useResourcesQuery, useReviewsQuery, type ResourceFilters } from '@/api/queries'
import PageHeading from '@/components/shared/PageHeading.vue'
import EmptyState from '@/components/shared/EmptyState.vue'
import QueryError from '@/components/shared/QueryError.vue'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import ResourceFiltersForm from './ResourceFilters.vue'
import ResourceCard from './ResourceCard.vue'

interface ParsedFilters {
  filters: ResourceFilters
  error: string | null
}

function parseFilters(query: LocationQuery, app: AppRead | undefined): ParsedFilters {
  const errors: string[] = []

  function read(key: keyof ResourceFilters, label: string, dict?: Record<string, string>): string {
    const raw = query[key]
    if (raw === undefined || raw === null) return ''
    if (Array.isArray(raw)) {
      errors.push(`筛选条件“${label}”重复出现，仅允许单值查询。`)
      return ''
    }
    if (typeof raw !== 'string') {
      errors.push(`筛选条件“${label}”格式无效。`)
      return ''
    }
    const value = raw.trim()
    if (value === '') return ''
    if (dict && !(value in dict)) {
      errors.push(`筛选条件“${label}”的值“${value}”不在可选范围内。`)
      return ''
    }
    return value
  }

  const filters: ResourceFilters = {
    category: read('category', 'API 类别', app?.categories),
    china_policy: read('china_policy', '中国大陆政策', app?.china_policies),
    status: read('status', '政策核验状态', app?.resource_statuses),
    include_ended: query.include_ended === 'true' || query.include_ended === '1',
  }
  return { filters, error: errors.length ? errors.join(' ') : null }
}

const route = useRoute()
const router = useRouter()

const {
  data: app,
  isPending: appPending,
  error: appError,
  refetch: refetchApp,
} = useAppQuery()

const parsed = computed(() => parseFilters(route.query, app.value))
const applied = computed(() => parsed.value.filters)
const filterError = computed(() => parsed.value.error)
const filtered = computed(() =>
  Boolean(
    applied.value.category ||
      applied.value.china_policy ||
      applied.value.status ||
      applied.value.include_ended,
  ),
)

const {
  data: resourcesData,
  isPending: resourcesPending,
  isError: resourcesFailed,
  error: resourcesError,
  refetch: refetchResources,
} = useResourcesQuery(applied)

const retainedResources = ref<Resource[]>([])
watch(
  resourcesData,
  (data) => {
    if (data !== undefined) retainedResources.value = data
  },
  { immediate: true },
)
const resources = computed(() => resourcesData.value ?? retainedResources.value)

const { data: reviewsData } = useReviewsQuery()
const reviewsById = computed(() => {
  const map = new Map<string, ResourceReview>()
  for (const review of reviewsData.value ?? []) {
    if (review.resource_id) map.set(review.resource_id, review)
  }
  return map
})

const appErrorMessage = computed(() => appError.value?.message ?? '请求失败，请稍后重试。')
const resourcesErrorMessage = computed(
  () => resourcesError.value?.message ?? '请求失败，请稍后重试。',
)

const backfillMutation = useBackfillMessagesMutation()
const backfillPending = backfillMutation.isPending
const backfillError = computed(() => backfillMutation.error.value?.message ?? '')
async function backfillSources(): Promise<void> {
  try {
    const run = await backfillMutation.mutateAsync(undefined)
    await router.push(`/tasks/${run.id}`)
  } catch {
    // 接口错误由 backfillError 呈现。
  }
}

function applyFilters(next: ResourceFilters) {
  const query: Record<string, string> = {}
  if (next.category) query.category = next.category
  if (next.china_policy) query.china_policy = next.china_policy
  if (next.status) query.status = next.status
  if (next.include_ended) query.include_ended = 'true'
  void router.push({ path: '/resources', query })
}

function clearFilters() {
  void router.push({ path: '/resources' })
}
</script>

<template>
  <PageHeading eyebrow="资源库" title="资源库">
    <template #actions>
      <Button type="button" variant="outline" class="h-11" :disabled="backfillPending || Boolean(app?.active_run)" @click="backfillSources">
        {{ backfillPending ? '正在发起…' : '补齐存量消息' }}
      </Button>
    </template>
  </PageHeading>
  <p v-if="backfillError" class="error-message" role="alert">{{ backfillError }}</p>

  <template v-if="appPending">
    <Skeleton class="mb-4 h-44 w-full" />
    <Skeleton class="h-40 w-full" />
  </template>
  <QueryError
    v-else-if="app === undefined"
    :message="appErrorMessage"
    @retry="refetchApp()"
  />
  <template v-else>
    <ResourceFiltersForm
      :app="app"
      :applied="applied"
      :count="resources.length"
      :error="filterError"
      @apply="applyFilters"
      @clear="clearFilters"
    />

    <template v-if="!filterError">
      <Skeleton v-if="resourcesPending" class="h-40 w-full" />
      <QueryError
        v-else-if="resourcesFailed && resources.length === 0"
        :message="resourcesErrorMessage"
        @retry="refetchResources()"
      />
      <template v-else>
        <QueryError
          v-if="resourcesFailed"
          :message="resourcesErrorMessage"
          @retry="refetchResources()"
        />
        <ul v-if="resources.length" class="record-list resource-grid">
          <ResourceCard
            v-for="item in resources"
            :key="item.id ?? `${item.provider}-${item.service}`"
            :resource="item"
            :show-ended="applied.include_ended"
            :review="reviewsById.get(item.id ?? '')"
          />
        </ul>
        <EmptyState
          v-else-if="filtered"
          title="当前筛选下没有资源"
          description="可以清除筛选查看全部资源，或发起收集补充资源库。"
        >
          <template #actions>
            <div class="actions">
              <Button as-child variant="ghost" class="h-11">
                <RouterLink to="/resources">清除筛选</RouterLink>
              </Button>
              <Button as-child variant="ghost" class="h-11">
                <RouterLink to="/tasks#start-task">发起收集任务</RouterLink>
              </Button>
            </div>
          </template>
        </EmptyState>
        <EmptyState
          v-else
          title="资源库尚无记录"
          description="发起首次收集后，这里会保存资源、消息来源与核验历史。"
        >
          <template #actions>
            <div class="actions">
              <Button as-child variant="ghost" class="h-11">
                <RouterLink to="/tasks#start-task">发起收集任务</RouterLink>
              </Button>
            </div>
          </template>
        </EmptyState>
      </template>
    </template>
  </template>
</template>