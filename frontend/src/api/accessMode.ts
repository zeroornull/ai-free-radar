import type { AppRead } from './types'

/**
 * Local fallback for `aifreeradar.models.ACCESS_MODE_LABELS`.
 * The app labels payload carries the same mapping; this keeps older payloads readable.
 */
export const ACCESS_MODE_FALLBACK_LABELS: Record<string, string> = {
  api: 'API 可调用',
  product: '产品内额度（非 API）',
  unknown: '入口未核实',
}

export type AccessMode = 'api' | 'product' | 'unknown'

/** Advisory shape: older records (and pre-generation schema) omit `access_mode`. */
export interface AccessModeCarrier {
  access_mode?: string | null
}

export function accessModeOf(policy: AccessModeCarrier | null | undefined): AccessMode {
  const value = policy?.access_mode
  return value === 'api' || value === 'product' ? value : 'unknown'
}

export function accessModeLabel(
  app: AppRead | undefined,
  policy: AccessModeCarrier | null | undefined,
): string {
  const mode = accessModeOf(policy)
  return app?.labels?.[mode] || ACCESS_MODE_FALLBACK_LABELS[mode] || ACCESS_MODE_FALLBACK_LABELS.unknown
}

/** Short explanatory hint; product credits never imply an API surface. */
export function accessModeHint(policy: AccessModeCarrier | null | undefined): string {
  switch (accessModeOf(policy)) {
    case 'api':
      return '通过公开 API 与自助接入使用；是否可调用以来源为准。'
    case 'product':
      return '额度仅在厂商网页、桌面或 Agent 产品内使用，不代表提供可调用的 API。'
    default:
      return '来源未说明领取与使用入口，API 可用性待核实。'
  }
}
