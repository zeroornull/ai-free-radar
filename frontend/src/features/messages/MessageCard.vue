<script setup lang="ts">
import { computed } from 'vue'
import { accessModeHint, accessModeLabel, accessModeOf } from '@/api/accessMode'
import type { NewsItem } from '@/api/types'
import { useAppQuery } from '@/api/queries'
import { formatDate, labelFor } from '@/app/presentation'
import PolicyChip from '@/components/shared/PolicyChip.vue'
import SafeExternalLink from '@/components/shared/SafeExternalLink.vue'
import PolicyFacts from '@/components/shared/PolicyFacts.vue'

const props = defineProps<{ item: NewsItem; position: number }>()

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
  feed: '订阅源条目',
  catalog: '目录记录',
}

const categoryLabel = computed(() => labelFor(app.value, props.item.policy.category))
const kindLabel = computed(() => kindLabels[props.item.kind] ?? props.item.kind)
const accessMode = computed(() => accessModeOf(props.item.policy))
const accessModeText = computed(() => accessModeLabel(app.value, props.item.policy))
const accessModeTooltip = computed(() => accessModeHint(props.item.policy))
const ended = computed(() => props.item.ended)

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

const expiryView = computed<LocalizedText>(() => {
  const policy = props.item.policy
  const original = policy.expiry_notes.trim() || '未说明'
  const note = localizedText(original, policy.expiry_notes_zh)
  const date = policy.expires_at ? formatDate(policy.expires_at) : ''
  const noteText = note.text.trim() || '未说明'
  const text = date
    ? noteText === '未说明'
      ? date
      : `${date} · ${noteText}`
    : noteText
  return { text, original, translated: note.translated }
})

const hasTranslation = computed(() =>
  titleText.value.translated ||
  summaryText.value.translated ||
  quotaView.value.translated ||
  claimView.value.translated ||
  expiryView.value.translated ||
  (Boolean(props.item.end_reason) && endReasonText.value.translated),
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
const summaryLong = computed(() => summaryText.value.text.length > 88)
const claimLong = computed(() => claimView.value.text.length > 56)
const primarySource = computed(() => props.item.sources[0])
const extraSourceCount = computed(() => Math.max(props.item.sources.length - 1, 0))

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
  <li class="record message-card" :class="{ 'message-card--ended': ended }">
    <span class="message-position" aria-label="列表位置">{{ String(position).padStart(2, '0') }}</span>
    <div class="message-body">
    <div class="record-heading">
      <h2><bdi>{{ titleText.text }}</bdi></h2>
      <details v-if="titleText.translated" class="translation-details">
        <summary>原文</summary>
        <p class="preserve-lines">{{ titleText.original }}</p>
      </details>
    </div>
    <details v-if="summaryLong" class="summary-details">
      <summary>
        <span class="summary-clip">{{ summaryText.text }}</span>
        <span class="summary-toggle"><span class="disclosure-closed">全文</span><span class="disclosure-open">收起全文</span></span>
      </summary>
      <p class="summary-full">{{ summaryText.text }}</p>
      <p v-if="summaryText.translated" class="translation-full">原文：{{ summaryText.original }}</p>
    </details>
    <div v-else class="message-summary">
      {{ summaryText.text }}
      <details v-if="summaryText.translated" class="translation-details">
        <summary>原文</summary>
        <p class="preserve-lines">{{ summaryText.original }}</p>
      </details>
    </div>
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
      <div class="fact-claim">
        <dt>申请条件</dt>
        <dd>
          <details v-if="claimLong" class="claim-details">
            <summary>
              <span class="claim-clip">{{ claimView.text }}</span>
              <span class="fact-toggle"><span class="disclosure-closed">全文</span><span class="disclosure-open">收起全文</span></span>
            </summary>
            <p class="fact-full">{{ claimView.text }}</p>
            <p v-if="claimView.translated" class="translation-full">原文：{{ claimView.original }}</p>
          </details>
          <template v-else>
            {{ claimView.text }}
            <details v-if="claimView.translated" class="translation-details">
              <summary>原文</summary>
              <p class="preserve-lines">{{ claimView.original }}</p>
            </details>
          </template>
        </dd>
      </div>
      <div>
        <dt>绑定支付方式</dt>
        <dd>{{ cardText }}</dd>
      </div>
      <div>
        <dt>期限</dt>
        <dd>
          {{ expiryView.text }}
          <details v-if="expiryView.translated" class="translation-details">
            <summary>原文</summary>
            <p class="preserve-lines">{{ expiryView.original }}</p>
          </details>
        </dd>
      </div>
    </dl>
    <PolicyFacts :policy="item.policy" />
    <div v-if="item.end_reason" class="meta">
      {{ ended ? '结束说明' : '结束事件说明' }}：{{ endReasonText.text }}
      <details v-if="endReasonText.translated" class="translation-details">
        <summary>原文</summary>
        <p class="preserve-lines">{{ endReasonText.original }}</p>
      </details>
    </div>
    <div class="citation-strip" aria-label="消息引文">
      <span class="citation-meta">{{ categoryLabel }}</span>
      <PolicyChip
        class="citation-meta"
        :value="item.policy.china_policy"
        :label="labelFor(app, item.policy.china_policy)"
      />
      <span
        class="badge access-mode-badge"
        :class="`access-mode-badge--${accessMode}`"
        :title="accessModeTooltip"
      >{{ accessModeText }}</span>
      <span v-if="primarySource" class="citation-source">
        <SafeExternalLink
          :value="primarySource.url"
          :label="sourceHost(primarySource.url) || sourceLabel(primarySource)"
        />
        <span> · {{ sourceTypeLabel(primarySource.source_type) }} · {{ accessLabel(primarySource.access) }}</span>
      </span>
      <span v-if="extraSourceCount" class="citation-meta">等 {{ item.sources.length }} 个来源</span>
      <span v-if="discoveredAt">收集 <time :datetime="discoveredAt">{{ formatDate(discoveredAt) }}</time></span>
      <RouterLink :to="`/resources/${encodeURIComponent(item.resource_id)}`" :aria-label="`查看资源详情：${titleText.text}`">查看资源详情</RouterLink>
      <span v-if="hasTranslation" class="citation-meta">机器翻译，未经核验</span>
    </div>
    <details class="source-section">
      <summary class="source-heading">来源详情与证据（{{ item.sources.length }}）</summary>
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
          <p v-if="source.source_id" class="meta">
            来源条目：<bdi>{{ source.source_id }}</bdi>
            <template v-if="source.external_id"> · <bdi>{{ source.external_id }}</bdi></template>
          </p>
          <p v-else-if="source.access === 'feed' || source.access === 'catalog'" class="meta">
            该来源为{{ accessLabel(source.access) }}，未抓取文章页面原文。
          </p>
          <p v-if="source.access === 'snippet'" class="meta">
            以上为搜索或来源片段，并非页面全文引用。
          </p>
          <p v-if="source.published_at" class="meta">
            来源发布时间：<time :datetime="source.published_at">{{ formatDate(source.published_at) }}</time>
          </p>
        </li>
      </ul>
      <p class="meta source-time">
        <template v-if="publishedAt">
          发布时间：<time :datetime="publishedAt">{{ formatDate(publishedAt) }}</time>
        </template>
        <template v-else>
          发现时间：<time :datetime="discoveredAt">{{ formatDate(discoveredAt) }}</time>
          （来源未说明发布时间）
        </template>
        <span v-if="ageText"> · {{ ageText }}</span>
      </p>
    </details>
    </div>
    <aside class="message-state" aria-label="事件与核验状态" :class="{ 'message-state--changed': item.kind === 'changed' || item.kind === 'expired' }">
      <span>{{ kindLabel }}</span>
      <span class="message-unverified">未核验消息</span>
      <span v-if="ended && item.kind !== 'expired'" class="message-ended">当前已结束</span>
    </aside>
  </li>
</template>

<style scoped>
.message-card { display: grid; grid-template-columns: 2.5rem minmax(0, 1fr) 7rem; gap: 1rem; padding: 0.65rem 0; border-block-end: 1px solid var(--color-border); }
.message-position { padding-block-start: 0.2rem; color: #8c2f39; font: 500 0.9375rem/1.5 var(--font-mono); font-variant-numeric: tabular-nums; }
.message-body { min-inline-size: 0; }
.message-card .record-heading { display: flex; flex-wrap: wrap; align-items: baseline; justify-content: flex-start; gap: 0 0.35rem; margin: 0; }
.message-card .record-heading .translation-details[open] { flex-basis: 100%; }
.message-card h2 { margin: 0; font: 600 1.125rem/1.4 var(--font-body); overflow-wrap: anywhere; }
.message-card .citation-meta { margin: 0; }
.citation-strip :deep(.chip) { border: 0; padding: 0; background: none; border-radius: 0; font: inherit; letter-spacing: inherit; text-transform: none; }
.message-summary { margin-block: 0.2rem 0; font: 400 0.875rem/1.55 var(--font-body); overflow-wrap: anywhere; }
.message-card .mini-facts { display: flex; flex-wrap: wrap; gap: 0.2rem 1.25rem; margin-block: 0.35rem; }
.message-card .mini-facts > div { display: flex; align-items: baseline; gap: 0.5rem; min-inline-size: 0; padding: 0; border: 0; background: transparent; border-radius: 0; }
.message-card .mini-facts dt { flex-shrink: 0; font: 500 0.6875rem/1.6 var(--font-ui); color: var(--color-text-secondary); }
.message-card .mini-facts dd { min-inline-size: 0; margin: 0; font-size: 0.8125rem; overflow-wrap: anywhere; }
.message-card .fact-claim { flex: 1 1 18rem; max-inline-size: 32rem; }
.summary-details summary, .claim-details summary { display: flex; gap: 0.4rem; align-items: flex-end; cursor: pointer; list-style: none; }
.summary-details summary::-webkit-details-marker, .claim-details summary::-webkit-details-marker { display: none; }
.disclosure-open { display: none; }
.summary-details[open] .summary-clip, .claim-details[open] .claim-clip, details[open] > summary .disclosure-closed { display: none; }
details[open] > summary .disclosure-open { display: inline; }
.summary-clip { display: -webkit-box; -webkit-box-orient: vertical; -webkit-line-clamp: 2; overflow: hidden; flex: 1; font: 400 0.875rem/1.55 var(--font-body); }
.claim-clip { display: -webkit-box; -webkit-box-orient: vertical; -webkit-line-clamp: 1; overflow: hidden; flex: 1; font-size: 0.8125rem; }
.summary-toggle, .fact-toggle { flex-shrink: 0; color: var(--color-text-secondary); font: 400 0.6875rem/1.5 var(--font-mono); text-decoration: underline; text-underline-offset: 0.2em; }
.summary-full, .fact-full { margin-block: 0.25rem 0; font: 400 0.875rem/1.55 var(--font-body); overflow-wrap: anywhere; }
.translation-full { margin-block: 0.2rem 0; color: var(--color-text-secondary); font-size: 0.875rem; line-height: 1.55; overflow-wrap: anywhere; }
.citation-strip { display: flex; flex-wrap: wrap; align-items: baseline; gap: 0.2rem 1rem; margin-block-start: 0.3rem; color: var(--color-text-secondary); font: 400 0.6875rem/1.5 var(--font-mono); overflow-wrap: anywhere; }
.citation-source { min-inline-size: 0; }
.access-mode-badge { flex-shrink: 0; font-family: var(--font-ui); }
.access-mode-badge--api { color: var(--color-success); border-color: var(--color-success-border); }
.access-mode-badge--product { color: var(--color-warning); border-color: var(--color-warning-border); }
.access-mode-badge--unknown { color: var(--color-text-secondary); }
.citation-strip a { text-decoration: underline; text-underline-offset: 0.2em; }
.message-state { display: flex; flex-direction: column; gap: 0.35rem; align-items: flex-end; padding-block-start: 0.25rem; font: 600 0.75rem/1.5 var(--font-ui); }
.message-state--changed, .message-card--ended .message-state { color: #8c2f39; }
.message-unverified { color: var(--color-text-secondary); font-size: 0.6875rem; font-weight: 400; }
.message-ended { color: #8c2f39; font-size: 0.6875rem; }
.message-card--ended h2 { color: var(--color-text-secondary); }
.message-card .source-section { margin-block-start: 0.1rem; padding-block-start: 0; border-block-start: 0; }
.source-heading { cursor: pointer; margin: 0; padding-block: 0.1rem; font: 400 0.6875rem/1.5 var(--font-mono); color: var(--color-text-secondary); }
.message-card .source-list { margin-block-start: 0.65rem; }
.message-card .meta { margin-block: 0.35rem; font-size: 0.75rem; }
.message-card .source-time { margin-block: 0.45rem 0; }
.translation-details { display: inline-block; vertical-align: baseline; margin-inline-start: 0.35rem; max-inline-size: 100%; }
.translation-details summary { display: inline; cursor: pointer; color: var(--color-text-secondary); font: 400 0.6875rem/1.5 var(--font-mono); }
.translation-details p { display: block; margin-block: 0.25rem 0; color: var(--color-text-secondary); font-size: 0.875rem; font-weight: 400; line-height: 1.55; overflow-wrap: anywhere; }
@media (max-width: 1099px) {
  .message-card { grid-template-columns: 2rem minmax(0, 1fr); gap: 0.5rem 0.75rem; }
  .message-state { grid-column: 2; grid-row: 1; flex-direction: row; flex-wrap: wrap; align-items: baseline; gap: 0.75rem; padding: 0; }
  .message-body { grid-column: 2; }
  .message-position { grid-row: 1 / span 2; }
}
@media (max-width: 599px) {
  .message-card { grid-template-columns: 1.5rem minmax(0, 1fr); }
  .message-card .mini-facts { flex-direction: column; }
  .message-card .mini-facts > div { display: block; }
  .message-card .fact-claim { flex: none; max-inline-size: none; }
  .message-card .fact-claim dd { display: block; }
  .message-card .mini-facts dt { display: inline; margin-inline-end: 0.5rem; }
  .message-card .mini-facts dd { display: inline; }
}
</style>