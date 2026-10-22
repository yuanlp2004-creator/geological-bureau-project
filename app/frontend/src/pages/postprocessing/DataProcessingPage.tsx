import { useEffect, useState } from 'react'
import { ReportsPage } from '../reports/ReportsPage'
import type { ReportSource } from '../reports/ReportBuilder'
import { PostProcessingPage } from './PostProcessingPage'
import { AnalysisIntensityOutput } from './AnalysisIntensityOutput'
import './data-processing.css'

type OutputTab = 'reports' | 'intensity'
type Props = {
  token: string
  page: 'postprocessing' | 'reports'
  initialView: string | null
  permissions: string[]
  reportSource: ReportSource | null
  onReportSourceChange: (source: ReportSource) => void
  onViewChange: (view: OutputTab) => void
  onToast: (message: string) => void
}

export function DataProcessingPage({ token, page, initialView, permissions, reportSource, onReportSourceChange, onViewChange, onToast }: Props) {
  const canReadReports = permissions.includes('reports.read')
  const canReadProcessing = permissions.includes('postprocessing.read')
  const canReadAnalysis = permissions.includes('analysis.read')
  const tabs: Array<{ id: OutputTab; label: string; allowed: boolean }> = [
    { id: 'reports', label: '分析报告', allowed: canReadReports },
    { id: 'intensity', label: '强度数据', allowed: canReadAnalysis }
  ]
  const [actionsTarget, setActionsTarget] = useState<HTMLDivElement | null>(null)
  const [tab, setTab] = useState<OutputTab>('reports')
  const outputTab = tabs.find((item) => item.id === tab && item.allowed)?.id ?? tabs.find((item) => item.allowed)?.id
  useEffect(() => {
    if (initialView === 'reports' || initialView === 'intensity') setTab(initialView)
  }, [initialView])
  const recalculate = page === 'postprocessing'

  return <div className={`page-content data-processing-page refined-page remaining-page${recalculate ? ' data-processing-recalculate' : ''}`} data-testid="data-processing-page">
    {!recalculate && <div className="output-workspace-toolbar"><nav className="postprocessing-view-tabs" role="tablist" aria-label="打印与导出内容">
      {tabs.filter((item) => item.allowed).map((item) => <button key={item.id} id={`output-tab-${item.id}`}
        type="button" role="tab" aria-selected={outputTab === item.id} aria-controls={`output-panel-${item.id}`}
        className={outputTab === item.id ? 'active' : ''} onClick={() => { setTab(item.id); onViewChange(item.id) }}
      >{item.label}</button>)}
    </nav><div ref={setActionsTarget} className="page-file-actions-slot"/></div>}
    {canReadReports && <div id="output-panel-reports" role="tabpanel" aria-labelledby="output-tab-reports"
      style={!recalculate && outputTab === 'reports' ? undefined : { display: 'none' }}>
      <ReportsPage embedded actionsTarget={actionsTarget} actionsActive={!recalculate && outputTab === 'reports'} token={token} canWrite={permissions.includes('reports.write')}
        source={reportSource} onSourceChange={onReportSourceChange}
        canExport={permissions.includes('reports.export')} canReadAnalysis={canReadAnalysis} onToast={onToast} />
    </div>}
    <div id="output-panel-intensity" role={recalculate ? undefined : 'tabpanel'}
      aria-labelledby={recalculate ? undefined : 'output-tab-intensity'}
      style={recalculate || outputTab === 'intensity' ? undefined : { display: 'none' }}>
      {canReadAnalysis && <AnalysisIntensityOutput actionsTarget={actionsTarget} token={token} hidden={recalculate || outputTab !== 'intensity'}
        canPrint={permissions.includes('analysis.print')} onToast={onToast} />}
      {canReadProcessing && <div style={recalculate ? undefined : { display: 'none' }}>
          <PostProcessingPage embedded actionsTarget={actionsTarget} active={recalculate} token={token} view="recalculate"
            canWrite={permissions.includes('postprocessing.write')} canExecute={permissions.includes('postprocessing.execute')}
            canExport={permissions.includes('postprocessing.export')} onToast={onToast} />
        </div>}
    </div>
  </div>
}

