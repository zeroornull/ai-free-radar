<script setup lang="ts">
import { computed } from 'vue'
import type { RunRead } from '@/api/types'
import { RouterLink } from 'vue-router'
import { useBriefingsQuery } from '@/api/queries'
import PageHeading from '@/components/shared/PageHeading.vue'
import RunList from '@/components/shared/RunList.vue'
import EmptyState from '@/components/shared/EmptyState.vue'
import QueryError from '@/components/shared/QueryError.vue'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'

const {
  data: briefingsData,
  isPending: briefingsPending,
  isError: briefingsFailed,
  error: briefingsError,
  refetch: refetchBriefings,
} = useBriefingsQuery()

const runs = computed<RunRead[]>(() => [...(briefingsData.value ?? [])])
const errorMessage = computed(
  () => briefingsError.value?.message ?? '请求失败，请稍后重试。',
)
</script>

<template>
  <PageHeading eyebrow="简报历史" title="简报历史" />

  <p class="muted">
    每项任务独立保存 Markdown 简报；同日多次运行分别保留。简报列出初始清单或本次增量，完整记录见资源库。
  </p>

  <Skeleton v-if="briefingsPending" class="h-40 w-full" />
  <QueryError
    v-else-if="briefingsFailed && briefingsData === undefined"
    :message="errorMessage"
    @retry="refetchBriefings()"
  />
  <template v-else>
    <QueryError
      v-if="briefingsFailed"
      :message="errorMessage"
      @retry="refetchBriefings()"
    />
    <RunList v-if="runs.length" :runs="runs" destination="briefings" />
    <EmptyState
      v-else
      title="尚无收集简报"
      description="完成任务后，这里会保留对应的收集简报及 Markdown 下载。"
    >
      <template #actions>
        <Button as-child variant="ghost" class="h-11">
          <RouterLink to="/tasks#start-task">发起首次收集</RouterLink>
        </Button>
      </template>
    </EmptyState>
  </template>
</template>