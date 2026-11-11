<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink } from 'vue-router'
import type { Resource, ResourceReview } from '@/api/types'
import { useAppQuery } from '@/api/queries'
import { collectionLabel, hasCollectedSources, policyStatusLabel, labelFor } from '@/app/presentation'
import StatusBadge from '@/components/shared/StatusBadge.vue'
import PolicyChip from '@/components/shared/PolicyChip.vue'
import CollectedMessageList from '@/components/shared/CollectedMessageList.vue'

const props = defineProps<{ resource: Resource; review?: ResourceReview; showEnded?: boolean }>()

const { data: app } = useAppQuery()

const collected = computed(() => props.resource.messages ?? [])
</script>

<template>
  <li class="record resource-card">
    <div class="record-heading">
      <h2>
        <RouterLink :to="`/resources/${resource.id ?? ''}`">
          <bdi>{{ resource.provider }} · {{ resource.service }}</bdi>
        </RouterLink>
      </h2>
      <StatusBadge :value="hasCollectedSources(resource) ? 'success' : 'pending'" :label="collectionLabel(resource)" />
    </div>
    <div class="chips">
      <span class="chip">{{ labelFor(app, resource.category) }}</span>
      <span class="chip">{{ policyStatusLabel(resource.status) }}</span>
      <span class="chip">{{ labelFor(app, resource.free_type) }}</span>
      <PolicyChip :value="resource.china_policy" :label="labelFor(app, resource.china_policy)" />
      <span v-if="review?.favorite" class="chip">收藏</span>
      <span v-if="review?.state === 'confirmed'" class="chip chip--success">已确认</span>
      <span v-if="review?.state === 'ignored'" class="chip chip--warning">已忽略</span>
    </div>
    <p v-if="!hasCollectedSources(resource)" class="meta">可使用“补齐存量消息”恢复或补搜来源。</p>
    <section v-if="collected.length" class="collected-summary">
      <h3>收集到的免费消息</h3>
      <p class="meta">报告与来源未经逐项核验；共 {{ collected.length }} 个活动。</p>
      <CollectedMessageList :items="collected" :show-ended="showEnded" compact />
    </section>
  </li>
</template>