import { useEffect, useId, useRef, useState } from 'react'
import { Save } from 'lucide-react'
import { api, type Settings } from '../../api'
import { NumericInput, reportInvalidNumericInput } from '../../components/NumericInput'
import { PageFileActions } from '../../components/PageFileActions'
import { SectionHeading } from '../../components/SectionHeading'

export function SoftwareParameters({ token, settings, canWrite, onSettingsChange, onToast, actionsTarget, active = true }: {
  token: string; settings: Settings; canWrite: boolean; onSettingsChange: (value: Settings) => void
  onToast: (message: string) => void; actionsTarget?: HTMLElement | null; active?: boolean
}) {
  const [draft, setDraft] = useState(settings)
  const [busy, setBusy] = useState(false)
  const dirty = useRef(false)
  const inFlight = useRef(false)
  const form = useRef<HTMLFormElement>(null)
  const formId = useId()
  useEffect(() => { if (!dirty.current) setDraft(settings) }, [settings])
  const change = (next: Settings) => { dirty.current = true; setDraft(next) }
  const save = async () => {
    if (!canWrite || inFlight.current) return
    if (!reportInvalidNumericInput(form.current)) return onToast('请先修正软件参数中的无效数值')
    inFlight.current = true; setBusy(true)
    try {
      const current = await api.settings(token)
      const saved = await api.saveSettings(token, { ...current, analysis: { ...current.analysis,
        dark_round_time_seconds: draft.analysis?.dark_round_time_seconds ?? 8,
        wait_time_ms: draft.analysis?.wait_time_ms ?? 100, look_band: draft.analysis?.look_band ?? true,
        log_analysis: draft.analysis?.log_analysis ?? true },
        display: { ...current.display, screen_width_mm: draft.display.screen_width_mm, screen_resolution_px: draft.display.screen_resolution_px } })
      dirty.current = false; setDraft(saved); onSettingsChange(saved); onToast('软件参数已保存')
    } catch (error) { onToast(error instanceof Error ? error.message : '保存软件参数失败') }
    finally { inFlight.current = false; setBusy(false) }
  }
  return <form id={formId} ref={form} className="surface device-parameter-form" onSubmit={event => { event.preventDefault(); void save() }}>
    <PageFileActions target={actionsTarget} hidden={!active}><button type="submit" form={formId} className="primary-button" disabled={!canWrite || busy}><Save size={15} />保存软件参数</button></PageFileActions>
    <div className="surface-heading"><SectionHeading title="软件参数" /></div>
    <fieldset disabled={!canWrite || busy}>
      <div className="device-parameter-grid">
        <label className="field"><span>空白传输时间（秒）</span><NumericInput min={6} max={20} step={1} value={draft.analysis?.dark_round_time_seconds ?? 8}
          onValueChange={value => change({ ...draft, analysis: { ...draft.analysis, dark_round_time_seconds: value } })} /></label>
        <label className="field"><span>谱带观察等待 (ms)</span><NumericInput min={0} max={5000} value={draft.analysis?.wait_time_ms ?? 100}
          onValueChange={value => change({ ...draft, analysis: { dark_round_time_seconds: 8, ...draft.analysis, wait_time_ms: value } })} /></label>
        <label className="field"><span>屏幕物理宽度 (mm)</span><NumericInput min={254} max={1227.6} value={draft.display.screen_width_mm ?? 409.2}
          onValueChange={value => change({ ...draft, display: { ...draft.display, screen_width_mm: value } })} /></label>
        <label className="field"><span>屏幕水平分辨率 (px)</span><NumericInput min={320} max={16384} value={draft.display.screen_resolution_px ?? 1920}
          onValueChange={value => change({ ...draft, display: { ...draft.display, screen_resolution_px: value } })} /></label>
      </div>
      <p className="settings-effect-note">空白传输时间用于在修改方法采样周期时重新计算空白次数；已有方法保持原次数，也可手动修改。</p>
      <div className="settings-analysis-options">
        <label className="checkbox-row"><input type="checkbox" checked={draft.analysis?.look_band ?? true}
          onChange={event => change({ ...draft, analysis: { dark_round_time_seconds: 8, ...draft.analysis, look_band: event.target.checked } })} />分析时观察谱带</label>
        <label className="checkbox-row"><input type="checkbox" checked={draft.analysis?.log_analysis ?? true}
          onChange={event => change({ ...draft, analysis: { dark_round_time_seconds: 8, ...draft.analysis, log_analysis: event.target.checked } })} />显示分析信息</label>
      </div>
    </fieldset>
  </form>
}
