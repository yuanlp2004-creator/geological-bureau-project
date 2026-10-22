export async function copyText(text: string): Promise<void> {
  try {
    if (navigator.clipboard) { await navigator.clipboard.writeText(text); return }
  } catch { /* Use the WebView-compatible selection fallback below. */ }
  const active = document.activeElement as HTMLElement | null
  const area = document.createElement('textarea')
  area.value = text; area.style.position = 'fixed'; area.style.opacity = '0'
  document.body.append(area); area.select()
  const copied = document.execCommand('copy')
  area.remove(); active?.focus()
  if (!copied) throw new Error('当前环境未允许复制，请选择表格内容复制')
}
