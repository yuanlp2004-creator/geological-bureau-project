/** Shared HTTP transport, desktop retry and API error conversion. */
import { desktopRuntime } from '../platform/runtime'

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code?: string,
    readonly details?: unknown
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

type TransportInit = RequestInit & { timeoutMs?: number }
type Startup = { controller: AbortController; promise: Promise<Response>; waiters: number }
let backend: { ready: boolean; startup?: Startup } = { ready: false }

export function resetBackendReady() {
  backend.startup?.controller.abort()
  backend = { ready: false }
}

export async function ensureBackendReady(signal?: AbortSignal): Promise<void> {
  const runtime = await desktopRuntime()
  signal?.throwIfAborted()
  const state = backend
  if (!runtime || state.ready) return

  if (!state.startup) {
    const controller = new AbortController()
    state.startup = {
      controller,
      promise: sendRequest('/health', { signal: controller.signal }, true),
      waiters: 0
    }
  }
  const startup = state.startup
  startup.waiters += 1
  let abort: (() => void) | undefined
  try {
    await new Promise<void>((resolve, reject) => {
      abort = () => reject(signal?.reason)
      signal?.addEventListener('abort', abort, { once: true })
      startup.promise.then(() => resolve(), reject)
    })
  } finally {
    if (abort) signal?.removeEventListener('abort', abort)
    startup.waiters -= 1
    if (startup.waiters === 0) {
      state.startup = undefined
      startup.controller.abort()
    }
  }
}

function waitForStartupRetry(signal: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    const done = () => {
      window.clearTimeout(timer)
      signal.removeEventListener('abort', done)
      resolve()
    }
    const timer = window.setTimeout(done, 100)
    signal.addEventListener('abort', done, { once: true })
  })
}

export function requestRaw(path: string, init?: TransportInit): Promise<Response> {
  return sendRequest(path, init)
}

async function sendRequest(path: string, init?: TransportInit, waitForStartup = false): Promise<Response> {
  const state = backend
  const runtime = await desktopRuntime()
  const localBackend = runtime && path.startsWith('/')
  const endpoint = localBackend ? `${runtime.api_base}${path}` : path
  const { timeoutMs = 8000, ...fetchInit } = init ?? {}
  const requestInit = {
    ...fetchInit,
    headers: {
      'Content-Type': 'application/json',
      ...(runtime ? { 'X-GeoSpectrum-Process-Key': runtime.process_key } : {}),
      ...(init?.headers ?? {})
    }
  }
  let response: Response
  const readOnly = ['GET', 'HEAD'].includes((init?.method ?? 'GET').toUpperCase())
  // Only safe reads may wait for sidecar startup. A lost response must never
  // cause a command that may already have committed to be sent again.
  const attempts = waitForStartup ? 80 : 1
  const controller = new AbortController()
  const abort = () => controller.abort(init?.signal?.reason)
  init?.signal?.addEventListener('abort', abort, { once: true })
  if (init?.signal?.aborted) abort()
  const timeout = window.setTimeout(() => controller.abort(new DOMException('请求超时', 'TimeoutError')), timeoutMs)
  try {
    for (let attempt = 1; ; attempt += 1) {
      controller.signal.throwIfAborted()
      try {
        response = await fetch(endpoint, { ...requestInit, signal: controller.signal })
        controller.signal.throwIfAborted()
        if (localBackend) state.ready = true
        break
      } catch (error) {
        if (controller.signal.aborted) throw controller.signal.reason
        if (!readOnly)
          throw new ApiError('未能确认操作结果，请刷新查看当前状态后再决定是否重试', 0, 'request_outcome_unknown')
        if (state.ready || attempt === attempts) throw error
        await waitForStartupRetry(controller.signal)
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
  if (!response.ok) {
    const body = await response.text()
    try {
      const parsed = JSON.parse(body) as { detail?: string | { code?: string; message?: string; details?: unknown } | unknown[] }
      const detail = parsed.detail
      const structured = !Array.isArray(detail) && typeof detail === 'object' && detail ? detail : undefined
      const message = typeof detail === 'string' ? detail : structured?.message
      const code = structured?.code
      throw new ApiError(
        message || (response.status === 422 ? '输入数据无效' : body || `${response.status} ${response.statusText}`),
        response.status,
        code,
        structured?.details
      )
    } catch (error) {
      if (error instanceof SyntaxError)
        throw new ApiError(body || `${response.status} ${response.statusText}`, response.status)
      throw error
    }
  }
  return response
}

export async function request<T>(path: string, init?: TransportInit): Promise<T> {
  const response = await requestRaw(path, init)
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}
