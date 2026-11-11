<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter, type LocationQuery } from 'vue-router'
import type { AppRead, NewsItem } from '@/api/types'
import { useAppQuery, useMessagesQuery, type MessageFilters } from '@/api/queries'
import { formatDate } from '@/app/presentation'
import PageHeading from '@/components/shared/PageHeading.vue'
import EmptyState from '@/components/shared/EmptyState.vue'
import QueryError from '@/components/shared/QueryError.vue'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import MessageFiltersForm from './MessageFilters.vue'
import MessageCard from './MessageCard.vue'

interface ParsedFilters {
  filters: MessageFilters
  error: string | null
}

function parseFilters(query: LocationQuery, app: AppRead | undefined): ParsedFilters {
  const errors: string[] = []

  function read(key: 'category', label: string, dict?: Record<string, string>): string {
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

  let includeEnded = false
  const rawEnded = query.include_ended
  if (Array.isArray(rawEnded)) {
    errors.push('筛选条件“包含已结束消息”重复出现，仅允许单值查询。')
  } else if (typeof rawEnded === 'string' && rawEnded.trim() !== '') {
    const value = rawEnded.trim().toLowerCase()
    if (value === 'true' || value === '1') includeEnded = true
    else if (value !== 'false' && value !== '0') {
      errors.push('筛选条件“包含已结束消息”只能为 true 或 false。')
    }
  }

  return {
    filters: {
      category: read('category', 'API 类别', app?.categories),
      include_ended: includeEnded,
    },
    error: errors.length ? errors.join(' ') : null,
  }
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
  Boolean(applied.value.category || applied.value.include_ended),
)

const {
  data: messagesData,
  isPending: messagesPending,
  isError: messagesFailed,
  error: messagesError,
  refetch: refetchMessages,
} = useMessagesQuery(applied)

const retainedMessages = ref<NewsItem[]>([])
watch(
  messagesData,
  (data) => {
    if (data !== undefined) retainedMessages.value = data
  },
  { immediate: true },
)
const messages = computed(() => messagesData.value ?? retainedMessages.value)
const currentMessages = computed(() => messages.value.filter((message) => !message.ended))
const endedMessages = computed(() => messages.value.filter((message) => message.ended))
const eventCounts = computed(() => {
  const counts = { new: 0, changed: 0, expired: 0, restored: 0 }
  for (const message of messages.value) counts[message.kind] += 1
  return counts
})
const latestCollection = computed(() => messages.value.reduce((latest, message) => {
  const value = message.discovered_at ?? ''
  return value > latest ? value : latest
}, ''))

const appErrorMessage = computed(() => appError.value?.message ?? '请求失败，请稍后重试。')
const messagesErrorMessage = computed(
  () => messagesError.value?.message ?? '请求失败，请稍后重试。',
)

function applyFilters(next: MessageFilters) {
  const query: Record<string, string> = {}
  if (next.category) query.category = next.category
  if (next.include_ended) query.include_ended = 'true'
  void router.push({ path: '/', query })
}

function clearFilters() {
  void router.push({ path: '/' })
}
</script>

<template>
  <div v-if="messagesData !== undefined || messages.length" class="collection-strip" aria-label="当前消息集合">
    <span v-if="latestCollection">最近收集 <time :datetime="latestCollection">{{ formatDate(latestCollection) }}</time></span>
    <span>当前结果 {{ messages.length }} 条 · 新消息 {{ eventCounts.new }} · 有更新 {{ eventCounts.changed }} · 结束事件 {{ eventCounts.expired }} · 恢复有效 {{ eventCounts.restored }} · 未核验 {{ messages.length }}</span>
  </div>
  <PageHeading title="消息动态" />

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
    <MessageFiltersForm
      :app="app"
      :applied="applied"
      :count="messages.length"
      :error="filterError"
      @apply="applyFilters"
      @clear="clearFilters"
    />

    <template v-if="!filterError">
      <Skeleton v-if="messagesPending && messages.length === 0" class="h-40 w-full" />
      <QueryError
        v-else-if="messagesFailed && messages.length === 0"
        :message="messagesErrorMessage"
        @retry="refetchMessages()"
      />
      <template v-else>
        <QueryError
          v-if="messagesFailed"
          :message="messagesErrorMessage"
          @retry="refetchMessages()"
        />
        <template v-if="messages.length">
          <ol v-if="currentMessages.length" class="record-list message-list" aria-label="当前有效消息">
            <MessageCard
              v-for="(message, index) in currentMessages"
              :key="message.id"
              :item="message"
              :position="index + 1"
            />
          </ol>
          <section v-if="endedMessages.length" class="ended-section" aria-labelledby="ended-heading">
            <div class="ended-heading">
              <h2 id="ended-heading">已结束</h2>
              <p>当前已结束的历史记录 · {{ endedMessages.length }} 条</p>
            </div>
            <ol class="record-list message-list" :start="currentMessages.length + 1" aria-label="当前已结束消息">
              <MessageCard
                v-for="(message, index) in endedMessages"
                :key="message.id"
                :item="message"
                :position="currentMessages.length + index + 1"
              />
            </ol>
          </section>
        </template>
        <EmptyState
          v-else-if="filtered"
          title="没有符合条件的消息"
          description="当前筛选条件下没有消息。清除筛选可查看默认范围内的全部消息。"
        >
          <template #actions>
            <Button variant="ghost" type="button" @click="clearFilters">清除筛选</Button>
          </template>
        </EmptyState>
        <EmptyState
          v-else
          title="还没有消息动态"
          description="研究任务完成收集后，来自官方页面、社区或 GitHub、搜索片段的免费消息会显示在这里。"
        >
          <template #actions>
            <RouterLink class="button" to="/tasks">前往研究任务</RouterLink>
          </template>
        </EmptyState>
      </template>
    </template>
  </template>
</template>

<style scoped>
.collection-strip { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 0.35rem 1.5rem; padding-block: 0.65rem; border-block-end: 1px solid var(--color-border); color: var(--color-text-secondary); font: 400 0.6875rem/1.6 var(--font-mono); font-variant-numeric: tabular-nums; }
.message-list { display: block; margin: 0; padding: 0; list-style: none; }
.ended-section { margin-block-start: 1.75rem; }
.ended-heading { display: flex; flex-wrap: wrap; align-items: baseline; gap: 0.5rem 1rem; padding-block-end: 0.5rem; border-block-end: 1px solid #1b1a17; }
.ended-heading h2 { margin: 0; font: 600 0.875rem/1.5 var(--font-ui); }
.ended-heading p { margin: 0; color: var(--color-text-secondary); font-size: 0.8125rem; }
</style>