<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import { ApiError, requestBlob } from '@/api/client'
import { useAppQuery, useBriefingQuery } from '@/api/queries'
import { formatDate, labelFor } from '@/app/presentation'
import PageHeading from '@/components/shared/PageHeading.vue'
import QueryError from '@/components/shared/QueryError.vue'
import ErrorPage from '@/components/shared/ErrorPage.vue'
import BriefingContent from './BriefingContent.vue'
import { Button } from '@/components/ui/button'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Skeleton } from '@/components/ui/skeleton'

const route = useRoute()
const { data: app } = useAppQuery()

const briefingId = computed(() => {
  const value = route.params.id
  return Array.isArray(value) ? (value[0] ?? '') : (value ?? '')
})
const {
  data: briefingData,
  isPending: briefingPending,
  isError: briefingFailed,
  error: briefingError,
  refetch: refetchBriefing,
} = useBriefingQuery(briefingId)

const briefing = computed(() => briefingData.value)
const run = computed(() => briefingData.value?.run)

const isNotFound = computed(
  () => briefingError.value instanceof ApiError && briefingError.value.status === 404,
)
const errorMessage = computed(
  () => briefingError.value?.message ?? '请求失败，请稍后重试。',
)
const initialError = computed(() => briefingFailed.value && briefingData.value === undefined)
const backgroundError = computed(() => briefingFailed.value && briefingData.value !== undefined)

const downloading = ref(false)
const downloadError = ref<string | null>(null)
const announcement = ref('')

watch(briefingId, () => {
  downloadError.value = null
  announcement.value = ''
})

async function downloadBriefing(): Promise<void> {
  if (!briefingId.value) return
  downloading.value = true
  downloadError.value = null
  announcement.value = '正在准备下载…'
  let objectUrl: string | null = null
  try {
    const blob = await requestBlob(
      `/api/briefings/${encodeURIComponent(briefingId.value)}/download`,
    )
    objectUrl = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = objectUrl
    anchor.download = `${briefingId.value}.md`
    document.body.append(anchor)
    anchor.click()
    anchor.remove()
    announcement.value = '简报已开始下载。'
  } catch (error) {
    downloadError.value =
      error instanceof ApiError ? error.message : '下载失败，请稍后重试。'
    announcement.value = '简报下载失败。'
  } finally {
    if (objectUrl) {
      const url = objectUrl
      setTimeout(() => URL.revokeObjectURL(url), 1000)
    }
    downloading.value = false
  }
}
</script>

<template>
  <PageHeading title="简报正文" />

  <p class="sr-only" role="status" aria-live="polite">{{ announcement }}</p>

  <Skeleton v-if="briefingPending" class="h-64 w-full" />
  <template v-else-if="initialError">
    <template v-if="isNotFound">
      <RouterLink class="back-link" to="/briefings">返回简报历史</RouterLink>
      <ErrorPage
        title="简报未找到"
        detail="未找到这项简报。请返回简报历史选择已有简报。"
      />
    </template>
    <QueryError v-else :message="errorMessage" @retry="refetchBriefing()" />
  </template>
  <div v-else-if="briefing && run" class="briefing-layout">
    <QueryError
      v-if="backgroundError"
      :message="errorMessage"
      @retry="refetchBriefing()"
    />
    <aside class="actions briefing-tools" aria-label="简报操作">
      <Button :disabled="downloading" @click="downloadBriefing">
        {{ downloading ? '下载中…' : '下载 Markdown' }}
      </Button>
      <Button as-child variant="ghost" class="h-11">
        <RouterLink :to="`/tasks/${run.id}`">查看关联任务</RouterLink>
      </Button>
      <Button as-child variant="ghost" class="h-11">
        <RouterLink to="/briefings">返回简报历史</RouterLink>
      </Button>
    </aside>

    <Alert v-if="downloadError" class="briefing-download-error" variant="destructive">
      <AlertTitle>简报下载失败</AlertTitle>
      <AlertDescription>{{ downloadError }}</AlertDescription>
      <div class="actions">
        <Button variant="outline" class="h-11" :disabled="downloading" @click="downloadBriefing">
          重试下载
        </Button>
      </div>
    </Alert>
    <p class="muted briefing-imprint">
      任务 <bdi>{{ run.id }}</bdi> · {{ labelFor(app, run.trigger) }} ·
      {{ labelFor(app, run.status) }} · <time :datetime="run.started_at">{{ formatDate(run.started_at) }}</time>
    </p>

    <BriefingContent :html="briefing.html" />
  </div>
</template>

<style scoped>
.briefing-layout { display: grid; grid-template-columns: minmax(0, 720px) minmax(10rem, 1fr); column-gap: 2.5rem; align-items: start; }
.briefing-layout > :not(.briefing-tools) { grid-column: 1; min-inline-size: 0; }
.briefing-tools { grid-column: 2; grid-row: 1 / span 4; display: flex; flex-direction: column; align-items: stretch; margin: 0; padding-block: 1rem; border-block-start: 1px solid var(--color-border); }
.briefing-tools :deep(a), .briefing-tools :deep(button) { justify-content: flex-start; }
.briefing-imprint { margin-block: 0 1.75rem; padding-block: 0.85rem; border-block: 1px solid var(--color-border); font: 400 0.6875rem/1.8 var(--font-ui); overflow-wrap: anywhere; }
.briefing-imprint bdi { font-family: var(--font-mono); }
.briefing-download-error { margin-block-end: 1rem; }
@media (max-width: 1099px) {
  .briefing-layout { grid-template-columns: minmax(0, 720px); }
  .briefing-tools { grid-column: 1; grid-row: auto; flex-direction: row; flex-wrap: wrap; gap: 0.5rem; padding-block: 0 1rem; border-block-start: 0; }
}
</style>