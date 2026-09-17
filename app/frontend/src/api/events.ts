/** WebSocket URL with the same desktop handshake as HTTP. */
import { desktopRuntime } from '../platform/runtime'

export async function eventSocketUrl(accessToken: string): Promise<string> {
  const runtime = await desktopRuntime()
  const base = runtime ? runtime.api_base.replace(/^http/, 'ws') : `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}`
  const query = new URLSearchParams({ access_token: accessToken })
  if (runtime) query.set('process_key', runtime.process_key)
  return `${base}/ws/events?${query}`
}
