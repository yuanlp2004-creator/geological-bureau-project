/** Tauri handshake cache shared by HTTP and WebSocket clients. */
export type DesktopRuntime = { api_base: string; process_key: string }

declare global {
  interface Window {
    __TAURI__?: { core?: { invoke: <T>(command: string, args?: Record<string, unknown>) => Promise<T> } }
  }
}

let desktopRuntimePromise: Promise<DesktopRuntime | null> | null = null

export function desktopRuntime(): Promise<DesktopRuntime | null> {
  // 在 WebView 生命周期内只缓存一次 Tauri 握手结果。
  // 空运行时明确表示使用浏览器开发模式，而不是构造伪造密钥。
  if (!desktopRuntimePromise) {
    const invoke = window.__TAURI__?.core?.invoke
    desktopRuntimePromise = invoke ? invoke<DesktopRuntime>('runtime_config') : Promise.resolve(null)
  }
  return desktopRuntimePromise
}
