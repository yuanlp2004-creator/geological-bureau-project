/** Shared HTTP transport, desktop retry and API error conversion. */
import { desktopRuntime } from '../platform/runtime'

export class ApiError extends Error {
  constructor(message: string, readonly status: number, readonly code?: string) {
    super(message)
    this.name = 'ApiError'
  }
}

export async function requestRaw(path: string, init?: RequestInit): Promise<Response> {
  const runtime = await desktopRuntime()
  const endpoint = runtime && path.startsWith('/') ? `${runtime.api_base}${path}` : path
  const requestInit = {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(runtime ? { 'X-GeoSpectrum-Process-Key': runtime.process_key } : {}), ...(init?.headers ?? {}) },
  }
  let response: Response | null = null
  let lastError: unknown = null
  // WebView 可能先于刚启动的 sidecar 就绪，因此只在桌面模式重试；
  // 浏览器开发模式应立即暴露连接错误。
  const attempts = runtime ? 80 : 1
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    try {
      response = await fetch(endpoint, requestInit)
      break
    } catch (error) {
      lastError = error
      if (attempt + 1 < attempts) await new Promise((resolve) => window.setTimeout(resolve, 100))
    }
  }
  if (!response) throw lastError instanceof Error ? lastError : new Error('本地服务启动超时')
  if (!response.ok) {
    const body = await response.text()
    try {
      const parsed = JSON.parse(body) as { detail?: string | { code?: string; message?: string } | unknown[] }
      const detail = parsed.detail
      const structured = !Array.isArray(detail) && typeof detail === 'object' && detail ? detail : undefined
      const message = typeof detail === 'string' ? detail : structured?.message
      const code = structured?.code
      throw new ApiError(message || (response.status === 422 ? '输入数据无效' : body || `${response.status} ${response.statusText}`), response.status, code)
    } catch (error) {
      if (error instanceof SyntaxError) throw new ApiError(body || `${response.status} ${response.statusText}`, response.status)
      throw error
    }
  }
  return response
}

export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await requestRaw(path, init)
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}
