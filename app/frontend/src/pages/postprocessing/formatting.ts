/** 后处理各区域共用的哈希和时间显示格式。 */
export const shortHash = (value: string | null | undefined, length = 12) => value ? `${value.slice(0, length)}…` : '无哈希'

export const formatMeasureTime = (value: string | null | undefined) => {
  if (!value) return '时间未知'
  return value.replace('T', ' ').replace('Z', '').slice(0, 19)
}

