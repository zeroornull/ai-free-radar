const FALLBACK_MESSAGE = '请求失败，请稍后重试。'

export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

function assertApiPath(path: string): void {
  if (path !== '/api' && !path.startsWith('/api/')) {
    throw new ApiError(0, '请求必须指向同源 /api 路径。')
  }
}

async function errorDetail(response: Response): Promise<string> {
  let payload: unknown
  try {
    payload = await response.json()
  } catch {
    return FALLBACK_MESSAGE
  }
  if (payload && typeof payload === 'object' && 'detail' in payload) {
    const detail = payload.detail
    if (typeof detail === 'string' && detail.trim() !== '') return detail
  }
  return FALLBACK_MESSAGE
}

async function send(path: string, init?: RequestInit): Promise<Response> {
  assertApiPath(path)
  const headers = new Headers(init?.headers)
  if (!headers.has('Accept')) headers.set('Accept', 'application/json')
  let response: Response
  try {
    response = await fetch(path, {
      ...init,
      headers,
      credentials: 'same-origin',
    })
  } catch {
    throw new ApiError(0, FALLBACK_MESSAGE)
  }
  if (!response.ok) throw new ApiError(response.status, await errorDetail(response))
  return response
}

export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await send(path, init)
  if (response.status === 204) return undefined as unknown as T
  try {
    return (await response.json()) as T
  } catch {
    throw new ApiError(response.status, FALLBACK_MESSAGE)
  }
}

export async function requestBlob(path: string, init?: RequestInit): Promise<Blob> {
  const response = await send(path, init)
  return response.blob()
}
