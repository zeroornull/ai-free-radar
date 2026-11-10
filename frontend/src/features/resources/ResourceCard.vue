<script setup lang="ts">
import { RouterLink } from 'vue-router'
import type { Resource, ResourceReview } from '@/api/types'
import { useAppQuery } from '@/api/queries'
import { formatDate, labelFor } from '@/app/presentation'
import StatusBadge from '@/components/shared/StatusBadge.vue'
import PolicyChip from '@/components/shared/PolicyChip.vue'

defineProps<{ resource: Resource; review?: ResourceReview }>()

const { data: app } = useAppQuery()
</script>

<template>
  <li class="record resource-card">
    <div class="record-heading">
      <h2>
        <RouterLink :to="`/resources/${resource.id ?? ''}`">
          <bdi>{{ resource.provider }} · {{ resource.service }}</bdi>
        </RouterLink>
      </h2>
      <StatusBadge :value="resource.status" :label="labelFor(app, resource.status)" />
    </div>
    <div class="chips">
      <span class="chip">{{ labelFor(app, resource.category) }}</span>
      <span class="chip">{{ labelFor(app, resource.free_type) }}</span>
      <PolicyChip :value="resource.china_policy" :label="labelFor(app, resource.china_policy)" />
      <span v-if="review?.favorite" class="chip">收藏</span>
      <span v-if="review?.state === 'confirmed'" class="chip chip--success">已确认</span>
      <span v-if="review?.state === 'ignored'" class="chip chip--warning">已忽略</span>
    </div>
    <dl class="mini-facts">
      <div>
        <dt>免费额度</dt>
        <dd>{{ resource.quota }} {{ resource.quota_unit }}</dd>
      </div>
      <div>
        <dt>刷新周期</dt>
        <dd>{{ resource.refresh_cycle }}</dd>
      </div>
    </dl>
    <p class="meta">
      本次核查：{{ labelFor(app, resource.check_status) }} · 上次成功：{{ formatDate(resource.last_success_at) }}
    </p>
    <details v-if="resource.check_status !== 'success'" class="reason">
      <summary>本次结论未获更新</summary>
      <p class="reason-body failure preserve-lines">
        本次结论未获更新。{{ resource.failure_reason || '本次核查尚未完成；保留上次已确认结论。' }}
      </p>
    </details>
  </li>
</template>