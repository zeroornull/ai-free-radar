import type { AppRead, Resource } from '@/api/types'

const dateTimeFormatter = new Intl.DateTimeFormat('zh-CN', { timeZoneName: 'shortOffset' })

export function formatDate(value: string | null | undefined, fallback = '尚无记录'): string {
  if (!value) return fallback
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return fallback
  const pad = (part: number): string => String(part).padStart(2, '0')
  const stamp = [
    `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`,
    `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`,
  ].join(' ')
  const zone = dateTimeFormatter
    .formatToParts(date)
    .find((part) => part.type === 'timeZoneName')?.value
  return zone ? `${stamp} ${zone}` : stamp
}

export function formatBoolean(value: boolean | null): string {
  if (typeof value !== 'boolean') return '未说明'
  return value ? '是' : '否'
}

export function labelFor(app: AppRead | undefined, value: string): string {
  if (!value || value === 'unknown') return '未说明'
  if (!app) return value
  return app.labels[value] ?? app.categories[value] ?? value
}

export function hasCollectedSources(resource: Resource): boolean {
  return (resource.messages ?? []).some((message) =>
    (message.sources ?? []).some((source) => /^https?:\/\//i.test(source.url)),
  )
}

export function collectionLabel(resource: Resource): string {
  return hasCollectedSources(resource) ? '已收录' : '历史线索 · 来源待补'
}

export function policyStatusLabel(status: string): string {
  return ({ pending: '未核验', active: '政策已核验', expired: '政策已失效' } as Record<string, string>)[status] ?? status
}
