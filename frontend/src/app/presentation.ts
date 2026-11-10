import type { AppRead } from '@/api/types'

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
  if (typeof value !== 'boolean') return '未核实'
  return value ? '是' : '否'
}

export function labelFor(app: AppRead | undefined, value: string): string {
  if (!app) return value
  return app.labels[value] ?? app.categories[value] ?? value
}
