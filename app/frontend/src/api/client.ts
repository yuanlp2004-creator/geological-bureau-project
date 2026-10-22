/** Shared HTTP transport, desktop retry and API error conversion. */
import { desktopRuntime } from '../platform/runtime'

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code?: string
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

export async function requestRaw(path: string, init?: RequestInit & { timeoutMs?: number }): Promise<Response> {
  const runtime = await desktopRuntime()
  const endpoint = runtime && path.startsWith('/') ? `${runtime.api_base}${path}` : path
  const { timeoutMs = 8000, ...fetchInit } = init ?? {}
  const requestInit = {
    ...fetchInit,
    headers: {
      'Content-Type': 'application/json',
      ...(runtime ? { 'X-GeoSpectrum-Process-Key': runtime.process_key } : {}),
      ...(init?.headers ?? {})
    }
  }
  let response: Response | null = null
  let lastError: unknown = null
  const readOnly = ['GET', 'HEAD'].includes((init?.method ?? 'GET').toUpperCase())
  // Only safe reads may wait for sidecar startup. A lost response must never
  // cause a command that may already have committed to be sent again.
  const attempts = runtime && readOnly ? 80 : 1
  const controller = new AbortController()
  const abort = () => controller.abort(init?.signal?.reason)
  init?.signal?.addEventListener('abort', abort, { once: true })
  if (init?.signal?.aborted) abort()
  const timeout = window.setTimeout(() => controller.abort(new DOMException('请求超时', 'TimeoutError')), timeoutMs)
  try {
    for (let attempt = 0; attempt < attempts; attempt += 1) {
      controller.signal.throwIfAborted()
      try {
        response = await fetch(endpoint, { ...requestInit, signal: controller.signal })
        break
      } catch (error) {
        lastError = error
        if (controller.signal.aborted) throw controller.signal.reason
        if (!readOnly)
          throw new ApiError('未能确认操作结果，请刷新查看当前状态后再决定是否重试', 0, 'request_outcome_unknown')
        if (attempt + 1 < attempts) await new Promise((resolve) => window.setTimeout(resolve, 100))
      }
    }
  } catch (error) {
    if (!readOnly && controller.signal.reason?.name === 'TimeoutError') {
      throw new ApiError('操作等待超时，结果尚未确认，请刷新查看当前状态', 0, 'request_outcome_unknown')
    }
    throw error
  } finally {
    window.clearTimeout(timeout)
    init?.signal?.removeEventListener('abort', abort)
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
      throw new ApiError(
        message || (response.status === 422 ? '输入数据无效' : body || `${response.status} ${response.statusText}`),
        response.status,
        code
      )
    } catch (error) {
      if (error instanceof SyntaxError)
        throw new ApiError(body || `${response.status} ${response.statusText}`, response.status)
      throw error
    }
  }
  return response
}

export async function request<T>(path: string, init?: RequestInit & { timeoutMs?: number }): Promise<T> {
  const response = await requestRaw(path, init)
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}
