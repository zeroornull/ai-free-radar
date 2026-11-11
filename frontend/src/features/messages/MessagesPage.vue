<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter, type LocationQuery } from 'vue-router'
import type { AppRead, NewsItem } from '@/api/types'
import { useAppQuery, useMessagesQuery, type MessageFilters } from '@/api/queries'
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
  <PageHeading eyebrow="消息动态" title="消息动态" />

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
        <ul v-if="messages.length" class="record-list message-list">
          <MessageCard
            v-for="message in messages"
            :key="message.id"
            :item="message"
          />
        </ul>
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