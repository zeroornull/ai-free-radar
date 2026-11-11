<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink } from 'vue-router'
import type { NewsItem } from '@/api/types'
import { useAppQuery } from '@/api/queries'
import { formatDate, labelFor } from '@/app/presentation'
import PolicyChip from '@/components/shared/PolicyChip.vue'
import SafeExternalLink from '@/components/shared/SafeExternalLink.vue'

const props = defineProps<{ item: NewsItem }>()

interface LocalizedText {
  text: string
  original: string
  translated: boolean
}

function localizedText(original: string, translation: string | undefined): LocalizedText {
  const zh = translation?.trim() ?? ''
  if (!zh) return { text: original, original, translated: false }
  return { text: zh, original, translated: true }
}

const { data: app } = useAppQuery()

const kindLabels: Record<NewsItem['kind'], string> = {
  new: '新消息',
  changed: '有更新',
  expired: '已结束',
  restored: '恢复有效',
}

const sourceTypeLabels: Record<string, string> = {
  official: '官方来源',
  community: '社区来源',
  github: 'GitHub 来源',
  search: '搜索来源',
}

const accessLabels: Record<string, string> = {
  page: '页面内容',
  snippet: '搜索片段',
}

const categoryLabel = computed(() => labelFor(app.value, props.item.policy.category))
const kindLabel = computed(() => kindLabels[props.item.kind] ?? props.item.kind)
const ended = computed(() => props.item.ended || props.item.kind === 'expired')

const titleText = computed(() => localizedText(props.item.title, props.item.title_zh))
const summaryText = computed(() => localizedText(props.item.summary, props.item.summary_zh))
const endReasonText = computed(() => localizedText(props.item.end_reason, props.item.end_reason_zh))

const quotaText = computed(() => {
  const quota = props.item.policy.quota.trim()
  if (!quota || quota === '未说明') return '未说明'
  const unit = props.item.policy.quota_unit.trim()
  return unit && unit !== '未说明' ? `${quota} ${unit}` : quota
})

const quotaView = computed<LocalizedText>(() => {
  const policy = props.item.policy
  const quotaZh = policy.quota_zh.trim()
  const unitZh = policy.quota_unit_zh.trim()
  if (!quotaZh && !unitZh) {
    return { text: quotaText.value, original: quotaText.value, translated: false }
  }
  const quota = quotaZh || policy.quota.trim()
  const unit = unitZh || policy.quota_unit.trim()
  const text = !quota || quota === '未说明'
    ? '未说明'
    : unit && unit !== '未说明'
      ? `${quota} ${unit}`
      : quota
  return { text, original: quotaText.value, translated: true }
})

const claimText = computed(() => {
  const value = props.item.policy.claim_conditions.trim()
  return value || '未说明'
})

const claimView = computed<LocalizedText>(() =>
  localizedText(claimText.value, props.item.policy.claim_conditions_zh),
)

const cardText = computed(() => {
  const required = props.item.policy.payment_method_required
  if (required === true) return '需绑定支付方式（不表示需要付费）'
  if (required === false) return '无需绑定'
  return '未说明'
})

const hasTranslation = computed(() =>
  titleText.value.translated ||
  summaryText.value.translated ||
  quotaView.value.translated ||
  claimView.value.translated ||
  (ended.value && Boolean(props.item.end_reason) && endReasonText.value.translated),
)

const discoveredAt = computed(() => props.item.discovered_at)
const publishedAt = computed(() => props.item.published_at)

const ageText = computed(() => {
  const raw = discoveredAt.value
  if (!raw) return ''
  const date = new Date(raw)
  if (Number.isNaN(date.getTime())) return ''
  const elapsed = Date.now() - date.getTime()
  if (elapsed < 0) return ''
  const hours = Math.floor(elapsed / 3_600_000)
  if (hours < 1) return '发现不到 1 小时'
  if (hours < 24) return `发现于 ${hours} 小时前`
  return `发现于 ${Math.floor(hours / 24)} 天前`
})

function sourceTypeLabel(sourceType: string): string {
  return sourceTypeLabels[sourceType] ?? '来源'
}

function accessLabel(access: string): string {
  return accessLabels[access] ?? '来源内容'
}

function sourceLabel(item: NewsItem['sources'][number]): string {
  return item.title || `查看${sourceTypeLabel(item.source_type)}`
}

function sourceHost(url: string): string {
  try {
    return new URL(url).hostname
  } catch {
    return ''
  }
}
</script>

<template>
  <li class="record message-card">
    <div class="record-heading">
      <h2><bdi>{{ titleText.text }}</bdi></h2>
      <span class="badge">未核验消息</span>
    </div>
    <details v-if="titleText.translated" class="translation-details">
      <summary>原文</summary>
      <p class="preserve-lines">{{ titleText.original }}</p>
    </details>
    <div class="chips">
      <span class="chip">{{ categoryLabel }}</span>
      <PolicyChip
        :value="item.policy.china_policy"
        :label="labelFor(app, item.policy.china_policy)"
      />
      <span class="chip">{{ kindLabel }}</span>
      <span v-if="ended" class="chip chip--danger">当前已结束</span>
    </div>
    <p class="message-summary">{{ summaryText.text }}</p>
    <details v-if="summaryText.translated" class="translation-details">
      <summary>原文</summary>
      <p class="preserve-lines">{{ summaryText.original }}</p>
    </details>
    <dl class="mini-facts">
      <div>
        <dt>免费额度</dt>
        <dd>
          {{ quotaView.text }}
          <details v-if="quotaView.translated" class="translation-details">
            <summary>原文</summary>
            <p class="preserve-lines">{{ quotaView.original }}</p>
          </details>
        </dd>
      </div>
      <div>
        <dt>申请条件</dt>
        <dd>
          {{ claimView.text }}
          <details v-if="claimView.translated" class="translation-details">
            <summary>原文</summary>
            <p class="preserve-lines">{{ claimView.original }}</p>
          </details>
        </dd>
      </div>
      <div>
        <dt>绑定支付方式</dt>
        <dd>{{ cardText }}</dd>
      </div>
    </dl>
    <p v-if="ended && item.end_reason" class="meta">结束说明：{{ endReasonText.text }}</p>
    <details v-if="ended && item.end_reason && endReasonText.translated" class="translation-details">
      <summary>原文</summary>
      <p class="preserve-lines">{{ endReasonText.original }}</p>
    </details>
    <p v-if="hasTranslation" class="meta translation-note">机器翻译，未经核验</p>
    <section class="source-section" aria-label="消息来源">
      <h3 class="source-heading">来源（{{ item.sources.length }}）</h3>
      <ul class="source-list">
        <li v-for="(source, index) in item.sources" :key="`${item.id}-${index}`" class="source">
          <div class="source-head">
            <SafeExternalLink :value="source.url" :label="sourceLabel(source)" />
            <span class="source-badges">
              <span class="badge">{{ sourceTypeLabel(source.source_type) }}</span>
              <span class="badge">{{ accessLabel(source.access) }}</span>
            </span>
          </div>
          <p v-if="sourceHost(source.url)" class="source-host">{{ sourceHost(source.url) }}</p>
          <p class="source-excerpt">{{ source.excerpt }}</p>
          <p v-if="source.access === 'snippet'" class="meta">
            以上为搜索或来源片段，并非页面全文引用。
          </p>
          <p v-if="source.published_at" class="meta">
            来源发布时间：<time :datetime="source.published_at">{{ formatDate(source.published_at) }}</time>
          </p>
        </li>
      </ul>
    </section>
    <p class="meta">
      <template v-if="publishedAt">
        发布时间：<time :datetime="publishedAt">{{ formatDate(publishedAt) }}</time>
      </template>
      <template v-else>
        发现时间：<time :datetime="discoveredAt">{{ formatDate(discoveredAt) }}</time>
        （来源未说明发布时间）
      </template>
      <span v-if="ageText"> · {{ ageText }}</span>
    </p>
    <div class="actions">
      <RouterLink
        class="button"
        :to="`/resources/${encodeURIComponent(item.resource_id)}`"
        :aria-label="`查看资源详情：${titleText.text}`"
      >
        查看资源详情
      </RouterLink>
    </div>
  </li>
</template>

<style scoped>
.translation-details { margin-block-start: 0.35rem; border: 1px solid var(--color-border); border-radius: var(--radius-sm); background: var(--color-bg-surface); padding: 0.35rem 0.6rem; }
.translation-details summary { min-block-size: 2rem; padding-block: 0.15rem; color: var(--color-text-secondary); font-size: 0.8125rem; font-weight: 600; }
.translation-details p { margin-block: 0.35rem 0; color: var(--color-text-secondary); font-size: 0.875rem; font-weight: 400; line-height: 1.55; }
.translation-note { color: var(--color-text-tertiary); }
</style>