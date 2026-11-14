<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink } from 'vue-router'
import type { ModelDeployment, Policy, QuotaFact, Resource } from '@/api/types'
import { useResourcesQuery } from '@/api/queries'
import SafeExternalLink from './SafeExternalLink.vue'

const props = defineProps<{ policy: Policy; currentResourceId?: string }>()

const quotaFacts = computed<QuotaFact[]>(() => props.policy.quota_facts ?? [])
const deployments = computed<ModelDeployment[]>(() => props.policy.model_deployments ?? [])
const warnings = computed<string[]>(() => props.policy.fact_warnings ?? [])
const hasFacts = computed(
  () => quotaFacts.value.length > 0 || deployments.value.length > 0 || warnings.value.length > 0,
)

const LIBRARY_FILTERS = { category: '', china_policy: '', status: '' }
const { data: library } = useResourcesQuery(LIBRARY_FILTERS)

const amountFormat = new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 6 })

function amountText(fact: QuotaFact): string {
  if (typeof fact.amount === 'number') return `${amountFormat.format(fact.amount)} ${fact.unit}`
  return fact.value_phrase?.trim() || fact.unit
}

function scopeText(scope: string | undefined): string {
  const value = scope?.trim()
  if (!value || value === 'unspecified') return '未说明作用域'
  return value
}

function modelIdsText(fact: QuotaFact): string {
  return (fact.model_ids ?? []).length ? (fact.model_ids ?? []).join('、') : '未说明'
}

function siblings(baseModel: string): Array<Resource & { id: string }> {
  const target = baseModel.trim().toLowerCase()
  if (!target) return []
  return (library.value ?? []).filter(
    (resource): resource is Resource & { id: string } =>
      Boolean(resource.id) &&
      resource.id !== props.currentResourceId &&
      (resource.models ?? []).some((model) => model.trim().toLowerCase() === target),
  )
}
</script>

<template>
  <section v-if="hasFacts" class="policy-facts" aria-label="可选额度与模型事实">
    <div v-if="warnings.length" class="policy-facts-warning" role="status">
      <strong>部分可选事实已略过</strong>
      <ul>
        <li v-for="warning in warnings" :key="warning" class="preserve-lines">{{ warning }}</li>
      </ul>
    </div>

    <template v-if="quotaFacts.length">
      <h3>额度事实（可选）</h3>
      <ul class="policy-facts-list">
        <li v-for="(fact, index) in quotaFacts" :key="fact.source_url + index">
          <dl class="facts">
            <dt>额度</dt>
            <dd>{{ amountText(fact) }}</dd>
            <dt>周期</dt>
            <dd>{{ fact.period || '未说明' }}</dd>
            <dt>作用域</dt>
            <dd>{{ scopeText(fact.scope) }}</dd>
            <dt>条件</dt>
            <dd>{{ fact.condition || '未说明' }}</dd>
            <dt>适用模型</dt>
            <dd><bdi>{{ modelIdsText(fact) }}</bdi></dd>
            <dt>原文证据</dt>
            <dd>
              <blockquote class="policy-quote preserve-lines">{{ fact.quote }}</blockquote>
              <SafeExternalLink :value="fact.source_url" label="打开额度原文来源" />
            </dd>
          </dl>
        </li>
      </ul>
    </template>

    <template v-if="deployments.length">
      <h3>模型映射（可选）</h3>
      <ul class="policy-facts-list">
        <li v-for="(deployment, index) in deployments" :key="deployment.source_url + index">
          <dl class="facts">
            <dt>提供商</dt>
            <dd><bdi>{{ deployment.provider }}</bdi></dd>
            <dt>部署 ID</dt>
            <dd><bdi>{{ deployment.model_id }}</bdi></dd>
            <dt>基础模型</dt>
            <dd><bdi>{{ deployment.base_model }}</bdi></dd>
            <dt>原文证据</dt>
            <dd>
              <blockquote class="policy-quote preserve-lines">{{ deployment.quote }}</blockquote>
              <SafeExternalLink :value="deployment.source_url" label="打开模型映射原文来源" />
            </dd>
          </dl>
          <p v-if="siblings(deployment.base_model).length" class="meta">
            资源库中同一基础模型的其他平台：
            <RouterLink
              v-for="sibling in siblings(deployment.base_model)"
              :key="sibling.id"
              :to="`/resources/${encodeURIComponent(sibling.id)}`"
            >
              {{ sibling.provider }} · {{ sibling.service }}
            </RouterLink>
          </p>
        </li>
      </ul>
    </template>
  </section>
</template>

<style scoped>
.policy-facts { margin-block-start: 1.25rem; min-inline-size: 0; }
.policy-facts h3 { margin-block: 1.5rem 0.5rem; font: 600 1rem/1.4 var(--font-body); }
.policy-facts h3:first-of-type { margin-block-start: 0.75rem; }
.policy-facts-list { margin: 0; padding: 0; list-style: none; }
.policy-facts-list > li + li { margin-block-start: 1rem; padding-block-start: 0.75rem; border-block-start: 1px solid var(--color-border); }
.policy-facts .facts { margin-block: 0.35rem 0; }
.policy-quote { margin: 0 0 0.35rem; padding-inline-start: 0.75rem; border-inline-start: 1px solid var(--color-border-strong); font: 400 0.875rem/1.55 var(--font-body); color: var(--color-text-secondary); }
.policy-facts .meta a + a::before { content: " · "; color: var(--color-text-tertiary); }
.policy-facts-warning { padding: 0.65rem 0.85rem; margin-block: 0.75rem; border: 1px solid var(--color-warning-border); background: var(--color-warning-bg); color: var(--color-warning); font: 400 0.8125rem/1.6 var(--font-ui); }
.policy-facts-warning ul { margin: 0.25rem 0 0; padding-inline-start: 1.1rem; }
</style>