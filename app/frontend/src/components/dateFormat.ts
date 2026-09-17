
const configuredTimeZone = () => document.documentElement.dataset.timezone || 'Asia/Shanghai'

const formatDate = (value: string | number | Date, options: Intl.DateTimeFormatOptions) => {
  try {
    return new Intl.DateTimeFormat('zh-CN', { ...options, timeZone: configuredTimeZone() }).format(new Date(value))
  } catch {
    return new Intl.DateTimeFormat('zh-CN', { ...options, timeZone: 'Asia/Shanghai' }).format(new Date(value))
  }
}

export const formatTime = (value: string | number | Date) => formatDate(value, { hour: '2-digit', minute: '2-digit', second: '2-digit' })

export const formatDateTime = (value: string | number | Date) => formatDate(value, {
  year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit',
})
