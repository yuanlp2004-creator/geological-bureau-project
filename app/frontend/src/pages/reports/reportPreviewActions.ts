export function reportOutputAllowed(status: string, canWrite: boolean, canExport: boolean): boolean {
  return canExport && (status === 'confirmed' || status === 'published' || (status === 'draft' && canWrite))
}

export async function runReportOutput<T>({ status, canWrite, canExport, isCurrent, confirm, output }: {
  status: string
  canWrite: boolean
  canExport: boolean
  isCurrent: () => boolean
  confirm: () => Promise<void>
  output: () => Promise<T>
}): Promise<T | undefined> {
  if (!isCurrent() || !reportOutputAllowed(status, canWrite, canExport)) return
  if (status === 'draft') await confirm()
  if (!isCurrent()) return
  const result = await output()
  return isCurrent() ? result : undefined
}
import type { Report, ReportSummary } from '../../api/reports'

export function reportStatusLabel(status: string): string {
  return ({ draft: '草稿', confirmed: '已确认', published: '已发布' } as Record<string, string>)[status] ?? status
}

export function reportSourceLabel(report: ReportSummary | Report): string {
  if (report.source_run_ids.length) return `${report.source_run_ids.length} 个分析批次`
  // 报告列表只返回摘要。建立报告时，来源只能是分析批次或旧 DAT。
  if (!('model' in report) || report.model.source_kind === 'legacy_dat' || report.model.legacy_sources?.length) return '旧 DAT'
  return '来源未记录'
}

