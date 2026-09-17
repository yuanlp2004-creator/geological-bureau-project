/** Native file commands and the browser download fallback. */
export async function selectLegacyDirectory(): Promise<string | null> {
  const invoke = window.__TAURI__?.core?.invoke
  if (!invoke) throw new Error('浏览器模式请填写一次旧版目录，再点击检测目录；桌面版支持直接选择文件夹。')
  return invoke<string | null>('select_legacy_directory')
}

const exportContentType = (fileName: string): string => {
  const extension = fileName.toLocaleLowerCase().split('.').pop()
  if (extension === 'pdf') return 'application/pdf'
  if (extension === 'csv') return 'text/csv'
  return 'text/plain'
}

export async function saveFile(blob: Blob, fileName: string): Promise<string | null> {
  // 桌面写盘必须经过 Rust 校验边界；只有浏览器开发模式使用对象 URL 下载。
  // 各功能页面不得另行实现第三套保存路径。
  const invoke = window.__TAURI__?.core?.invoke
  if (invoke) {
    const bytes = Array.from(new Uint8Array(await blob.arrayBuffer()))
    return invoke<string | null>('save_export_file', { fileName, contentType: exportContentType(fileName), bytes })
  }
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = fileName
  document.body.append(anchor)
  anchor.click()
  anchor.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 0)
  return fileName
}

export const savePdfFile = saveFile
