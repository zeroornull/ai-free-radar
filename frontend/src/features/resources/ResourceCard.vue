<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink } from 'vue-router'
import type { Resource, ResourceReview } from '@/api/types'
import { useAppQuery } from '@/api/queries'
import { collectionLabel, hasCollectedSources, policyStatusLabel, formatDate, labelFor } from '@/app/presentation'
import StatusBadge from '@/components/shared/StatusBadge.vue'
import PolicyChip from '@/components/shared/PolicyChip.vue'
import CollectedMessageList from '@/components/shared/CollectedMessageList.vue'

const props = defineProps<{ resource: Resource; review?: ResourceReview; showEnded?: boolean }>()

const { data: app } = useAppQuery()

const collected = computed(() => props.resource.messages ?? [])
const sourceCount = computed(() => new Set(
  collected.value.flatMap((message) => (message.sources ?? [])
    .filter((source) => /^https?:\/\//i.test(source.url))
    .map((source) => source.url)),
).size)
const reviewLabel = computed(() => props.review
  ? app.value?.review_states?.[props.review.state] ?? props.review.state
  : '尚无人工记录')
</script>

<template>
  <li class="resource-index-entry">
    <div class="resource-index-row">
      <div class="resource-identity">
        <p v-if="resource.id" class="resource-registration"><span>登记号</span> <bdi>{{ resource.id }}</bdi></p>
        <h2>
          <RouterLink :to="`/resources/${resource.id ?? ''}`">
            <bdi>{{ resource.provider }} · {{ resource.service }}</bdi>
          </RouterLink>
        </h2>
      </div>
      <dl class="resource-index-facts">
        <div>
          <dt>类别 / 免费形式</dt>
          <dd>{{ labelFor(app, resource.category) }}</dd>
          <dd>{{ labelFor(app, resource.free_type) }}</dd>
        </div>
        <div>
          <dt>收录 / 政策核验</dt>
          <dd><StatusBadge :value="hasCollectedSources(resource) ? 'success' : 'pending'" :label="collectionLabel(resource)" /></dd>
          <dd>{{ policyStatusLabel(resource.status) }}</dd>
        </div>
        <div>
          <dt>来源 / 首次发现</dt>
          <dd>{{ sourceCount }} 个来源链接</dd>
          <dd class="resource-date">{{ formatDate(resource.first_seen_at) }}</dd>
        </div>
        <div>
          <dt>人工状态 / 大陆政策</dt>
          <dd>{{ reviewLabel }}<span v-if="review?.favorite"> · 收藏</span></dd>
          <dd><PolicyChip :value="resource.china_policy" :label="labelFor(app, resource.china_policy)" /></dd>
        </div>
      </dl>
    </div>
    <p v-if="!hasCollectedSources(resource)" class="meta resource-source-note">可使用“补齐存量消息”恢复或补搜来源。</p>
    <details v-if="collected.length" class="resource-collected">
      <summary>收集到的免费消息 · {{ collected.length }} 个活动</summary>
      <div class="resource-collected-content">
        <p class="meta">报告与来源未经逐项核验；共 {{ collected.length }} 个活动。</p>
        <CollectedMessageList :items="collected" :show-ended="showEnded" />
      </div>
    </details>
  </li>
</template>

<style scoped>
.resource-index-entry { min-inline-size: 0; border-block-end: 1px solid var(--color-border); padding-block: 1rem 0.6rem; overflow-wrap: anywhere; }
.resource-index-row { display: grid; grid-template-columns: minmax(12rem, 1.25fr) minmax(0, 3fr); gap: 1.5rem; align-items: start; }
.resource-identity { min-inline-size: 0; }
.resource-registration { margin: 0 0 0.35rem; font-family: var(--font-mono); font-size: 0.625rem; line-height: 1.5; color: var(--color-text-secondary); }
.resource-registration span { font-family: var(--font-ui); margin-inline-end: 0.5rem; }
.resource-identity h2 { margin: 0; font-family: var(--font-body); font-size: 1.125rem; line-height: 1.4; font-weight: 600; }
.resource-identity a { text-decoration-thickness: 1px; text-underline-offset: 0.2em; }
.resource-index-facts { display: grid; grid-template-columns: minmax(0, 0.9fr) minmax(0, 1fr) minmax(0, 1.15fr) minmax(0, 1fr); margin: 0; gap: 1rem; }
.resource-index-facts > div { min-inline-size: 0; padding-inline-start: 0.8rem; border-inline-start: 1px solid var(--color-border); }
.resource-index-facts dt { margin-block-end: 0.3rem; font-family: var(--font-ui); font-size: 0.625rem; line-height: 1.5; font-weight: 500; color: var(--color-text-secondary); }
.resource-index-facts dd { margin: 0; font-size: 0.8125rem; line-height: 1.6; }
.resource-index-facts dd + dd { margin-block-start: 0.2rem; }
.resource-date { font-variant-numeric: tabular-nums; color: var(--color-text-secondary); }
.resource-source-note { margin-block: 0.65rem 0; }
.resource-collected { margin-block-start: 0.45rem; }
.resource-collected > summary { inline-size: fit-content; max-inline-size: 100%; min-block-size: 2rem; padding-block: 0.4rem; font-family: var(--font-ui); font-size: 0.75rem; line-height: 1.6; cursor: pointer; text-decoration: underline; text-underline-offset: 0.2em; }
.resource-collected-content { padding-block: 0.5rem 1rem; border-block-start: 1px solid var(--color-border); }
.resource-collected-content > p { margin-block: 0 1rem; }
@media (max-width: 1099px) {
  .resource-index-row { grid-template-columns: minmax(0, 1fr); gap: 0.85rem; }
  .resource-index-facts { grid-template-columns: repeat(4, minmax(0, 1fr)); }
  .resource-index-facts > div:first-child { padding-inline-start: 0; border-inline-start: 0; }
}
@media (max-width: 599px) {
  .resource-index-facts { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0.9rem; }
  .resource-index-facts > div:nth-child(odd) { padding-inline-start: 0; border-inline-start: 0; }
}
</style>