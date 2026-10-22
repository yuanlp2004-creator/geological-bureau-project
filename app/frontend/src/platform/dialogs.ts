/** Wait for the user's choice in either the browser or the native desktop dialog. */
export async function confirmAction(message: string): Promise<boolean> {
  const invoke = window.__TAURI__?.core?.invoke
  if (!invoke) return window.confirm(message)
  const result = await invoke<string>('plugin:dialog|message', {
    title: 'GeoSpectrum', message, kind: 'warning', buttons: 'OkCancel'
  })
  return result === 'Ok'
}
