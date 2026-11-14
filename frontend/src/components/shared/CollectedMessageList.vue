<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink } from 'vue-router'
import type { CollectedMessage, NewsItem } from '@/api/types'
import { useAppQuery } from '@/api/queries'
import { formatBoolean, formatDate, labelFor } from '@/app/presentation'
import MessageSources from './MessageSources.vue'
import PolicyFacts from './PolicyFacts.vue'

type MessageItem = CollectedMessage | NewsItem

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

function localizedQuota(policy: MessageItem['policy'] | undefined): LocalizedText {
  const quota = policy?.quota || '未说明'
  const unit = policy?.quota_unit || ''
  const original = unit ? `${quota} ${unit}` : quota
  const quotaZh = policy?.quota_zh?.trim() ?? ''
  const unitZh = policy?.quota_unit_zh?.trim() ?? ''
  if (!quotaZh && !unitZh) return { text: original, original, translated: false }
  return {
    text: [quotaZh || quota, unitZh || unit].filter(Boolean).join(' '),
    original,
    translated: true,
  }
}

interface MessageView {
  item: MessageItem
  kind: string | null
  resourceId: string | null
  sourceTypeText: string
  discoveredAt: string | null
  title: LocalizedText
  summary: LocalizedText
  endReason: LocalizedText
  quota: LocalizedText
  claimConditions: LocalizedText
  refreshCycle: LocalizedText
  rateLimit: LocalizedText
  regionRestrictions: LocalizedText
  expiryNotes: LocalizedText
  hasTranslation: boolean
}

const props = withDefaults(
  defineProps<{
    items: MessageItem[]
    showEnded?: boolean
    compact?: boolean
    linkResources?: boolean
  }>(),
  { showEnded: false, compact: false, linkResources: false },
)

const { data: app } = useAppQuery()

const KIND_LABELS: Record<string, string> = {
  new: '新增',
  changed: '变化',
  expired: '已结束',
  restored: '恢复',
}
const SOURCE_TYPE_LABELS: Record<string, string> = {
  official: '官方页面',
  community: '社区',
  github: 'GitHub',
  search: '搜索摘要',
  catalog: '第三方目录',
}

function kindLabel(value: string): string {
  return KIND_LABELS[value] ?? labelFor(app.value, value)
}

const visible = computed<MessageView[]>(() =>
  props.items
    .filter((item) => props.showEnded || !item.ended)
    .map((item) => {
      const title = localizedText(item.title, item.title_zh)
      const summary = localizedText(item.summary, item.summary_zh)
      const endReason = localizedText(item.end_reason, item.end_reason_zh)
      const quota = localizedQuota(item.policy)
      const claimConditions = localizedText(item.policy?.claim_conditions || '未说明', item.policy?.claim_conditions_zh)
      const refreshCycle = localizedText(item.policy?.refresh_cycle || '未说明', item.policy?.refresh_cycle_zh)
      const rateLimit = localizedText(item.policy?.rate_limit || '未说明', item.policy?.rate_limit_zh)
      const regionRestrictions = localizedText(item.policy?.region_restrictions || '未说明', item.policy?.region_restrictions_zh)
      const expiryNotes = localizedText(item.policy?.expiry_notes || '未说明', item.policy?.expiry_notes_zh)
      const translatedFields = [title, summary, quota, claimConditions]
      if (!props.compact) translatedFields.push(refreshCycle, rateLimit, regionRestrictions, expiryNotes)
      if (item.ended && item.end_reason) translatedFields.push(endReason)
      return {
        item,
        kind: newsKind(item),
        resourceId: newsResourceId(item),
        sourceTypeText: sourceTypes(item),
        discoveredAt: discoveredAt(item),
        title,
        summary,
        endReason,
        quota,
        claimConditions,
        refreshCycle,
        rateLimit,
        regionRestrictions,
        expiryNotes,
        hasTranslation: translatedFields.some((field) => field.translated),
      }
    }),
)

function newsKind(item: MessageItem): string | null {
  return 'kind' in item && typeof item.kind === 'string' ? item.kind : null
}

function newsResourceId(item: MessageItem): string | null {
  return 'resource_id' in item && typeof item.resource_id === 'string' ? item.resource_id : null
}

function messageKey(item: MessageItem, index: number): string {
  const id = 'id' in item && typeof item.id === 'string' ? item.id : ''
  return id || `${item.offer_key}-${index}`
}

function discoveredAt(item: MessageItem): string | null {
  return 'discovered_at' in item && typeof item.discovered_at === 'string'
    ? item.discovered_at
    : null
}

function sourceTypes(item: MessageItem): string {
  const types = new Set<string>()
  for (const source of item.sources ?? []) types.add(source.source_type)
  return Array.from(types)
    .map((type) => labelFor(app.value, type) === type ? (SOURCE_TYPE_LABELS[type] ?? type) : labelFor(app.value, type))
    .join('、')
}
</script>

<template>
  <div v-if="visible.length" class="collected-messages">
    <article
      v-for="(view, index) in visible"
      :key="messageKey(view.item, index)"
      class="collected-message"
    >
      <div class="record-heading">
        <h3>{{ view.title.text }}</h3>
        <div class="chips">
          <span v-if="view.kind" class="chip">
            {{ kindLabel(view.kind ?? '') }}
          </span>
          <span v-if="view.item.ended && view.kind !== 'expired'" class="chip chip--warning">
            已结束
          </span>
          <span v-if="view.sourceTypeText" class="chip">{{ view.sourceTypeText }}</span>
          <span v-if="view.item.policy?.payment_method_required === true" class="chip">
            需绑定支付方式
          </span>
        </div>
      </div>
      <details v-if="view.title.translated" class="translation-details">
        <summary>原文</summary>
        <p class="preserve-lines">{{ view.title.original }}</p>
      </details>
      <p class="preserve-lines">{{ view.summary.text }}</p>
      <details v-if="view.summary.translated" class="translation-details">
        <summary>原文</summary>
        <p class="preserve-lines">{{ view.summary.original }}</p>
      </details>
      <p v-if="view.item.ended && view.item.end_reason" class="meta preserve-lines">
        结束说明：{{ view.endReason.text }}
      </p>
      <details
        v-if="view.item.ended && view.item.end_reason && view.endReason.translated"
        class="translation-details"
      >
        <summary>原文</summary>
        <p class="preserve-lines">{{ view.endReason.original }}</p>
      </details>
      <p v-if="view.resourceId && linkResources" class="meta">
        <RouterLink :to="`/resources/${view.resourceId}`">查看关联资源</RouterLink>
        · 发现于 {{ formatDate(view.discoveredAt) }}
      </p>
      <p v-else-if="view.item.published_at" class="meta">
        来源发布时间：{{ formatDate(view.item.published_at) }}
      </p>
      <p v-if="compact" class="meta preserve-lines">
        报告额度：{{ view.quota.text }} ·
        领取条件：{{ view.claimConditions.text }} ·
        到期：{{ formatDate(view.item.policy?.expires_at ?? null, '未说明') }}
      </p>
      <template v-if="compact">
        <details v-if="view.quota.translated" class="translation-details" aria-label="报告额度原文">
          <summary>原文</summary>
          <p class="preserve-lines">{{ view.quota.original }}</p>
        </details>
        <details v-if="view.claimConditions.translated" class="translation-details" aria-label="领取条件原文">
          <summary>原文</summary>
          <p class="preserve-lines">{{ view.claimConditions.original }}</p>
        </details>
      </template>
      <dl v-if="!compact" class="facts">
        <dt>报告免费额度</dt>
        <dd>
          {{ view.quota.text }}
          <details v-if="view.quota.translated" class="translation-details">
            <summary>原文</summary>
            <p class="preserve-lines">{{ view.quota.original }}</p>
          </details>
        </dd>
        <dt>领取条件</dt>
        <dd>
          {{ view.claimConditions.text }}
          <details v-if="view.claimConditions.translated" class="translation-details">
            <summary>原文</summary>
            <p class="preserve-lines">{{ view.claimConditions.original }}</p>
          </details>
        </dd>
        <dt>刷新周期</dt>
        <dd>
          {{ view.refreshCycle.text }}
          <details v-if="view.refreshCycle.translated" class="translation-details">
            <summary>原文</summary>
            <p class="preserve-lines">{{ view.refreshCycle.original }}</p>
          </details>
        </dd>
        <dt>限速</dt>
        <dd>
          {{ view.rateLimit.text }}
          <details v-if="view.rateLimit.translated" class="translation-details">
            <summary>原文</summary>
            <p class="preserve-lines">{{ view.rateLimit.original }}</p>
          </details>
        </dd>
        <dt>绑定支付方式</dt>
        <dd>{{ view.item.policy.payment_method_required == null ? '未说明' : view.item.policy.payment_method_required ? '需要' : '不需要' }}</dd>
        <dt>地区限制</dt>
        <dd>
          {{ view.regionRestrictions.text }}
          <details v-if="view.regionRestrictions.translated" class="translation-details">
            <summary>原文</summary>
            <p class="preserve-lines">{{ view.regionRestrictions.original }}</p>
          </details>
        </dd>
        <dt>中国大陆政策</dt>
        <dd>{{ labelFor(app, view.item.policy.china_policy) }}（来源报告，未实测）</dd>
        <dt>是否要求支付</dt>
        <dd>{{ formatBoolean(view.item.policy?.payment_required ?? null) }}</dd>
        <dt>到期时间</dt>
        <dd>{{ formatDate(view.item.policy?.expires_at ?? null, '未说明') }}</dd>
        <dt>有效期说明</dt>
        <dd>
          {{ view.expiryNotes.text }}
          <details v-if="view.expiryNotes.translated" class="translation-details">
            <summary>原文</summary>
            <p class="preserve-lines">{{ view.expiryNotes.original }}</p>
          </details>
        </dd>
      </dl>
      <PolicyFacts v-if="!compact" :policy="view.item.policy" />
      <p v-if="view.hasTranslation" class="meta translation-note">机器翻译，未经核验</p>
      <p v-if="!compact" class="form-note">
        以上为收集到的报告参数，未经逐项核验；未知条件保留，不视为收集失败。
      </p>
      <details class="reason">
        <summary>查看来源（{{ view.item.sources.length }}）</summary>
        <MessageSources :items="view.item.sources" />
      </details>
    </article>
  </div>
  <p v-else class="muted">
    {{
      items.length
        ? '当前仅收集到已结束的活动；打开“显示历史”可查看。'
        : '尚无收集到的免费消息。收集任务发现消息后会出现在这里。'
    }}
  </p>
</template>

<style scoped>
.collected-messages { display: grid; gap: var(--space-4, 1.5rem); min-inline-size: 0; }
.collected-message { min-inline-size: 0; overflow-wrap: anywhere; }
.collected-message + .collected-message { padding-block-start: var(--space-4, 1.5rem); border-block-start: 1px solid var(--color-control-border); }
.collected-message h3 { margin-block: 0 0.5rem; }
.translation-details { margin-block-start: 0.35rem; border: 1px solid var(--color-border); border-radius: var(--radius-sm); background: var(--color-bg-surface); padding: 0.35rem 0.6rem; }
.translation-details summary { min-block-size: 2rem; padding-block: 0.15rem; color: var(--color-text-secondary); font-size: 0.8125rem; font-weight: 600; }
.translation-details p { margin-block: 0.35rem 0; color: var(--color-text-secondary); font-size: 0.875rem; line-height: 1.55; }
.translation-note { color: var(--color-text-tertiary); }
</style>