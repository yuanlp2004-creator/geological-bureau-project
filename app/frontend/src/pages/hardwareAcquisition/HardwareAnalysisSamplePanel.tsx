import { useRef, useState } from 'react'
import { api, type HardwareTask } from '../../api'

export function HardwareAnalysisSamplePanel({ token, task, canSave, onSaved, onToast }: {
  token: string; task: HardwareTask; canSave: boolean; onSaved: () => Promise<void>; onToast: (message: string) => void
}) {
  const [name, setName] = useState(task.sample_name || `转角${task.id}`)
  const [kind, setKind] = useState<'test' | 'standard'>('test')
  const [length, setLength] = useState<12 | 20>(12)
  const [saving, setSaving] = useState(false)
  const inFlight = useRef(false)
  const ready = task.status === 'completed' && !!task.method_id
  return <section className="surface hardware-analysis-sample" aria-label="转角结果保存为分析样品">
    <div className="surface-heading"><h2>分析样品</h2></div>
    {task.analysis_sample ? <p role="status">已保存：{task.analysis_sample.sample_name}。可在“定量分析与慢进”和“谱图查看”中选择。</p> : <>
      <p>{!task.method_id ? '建立任务时绑定已发布方法，完成采集后即可保存分析样品。'
        : !ready ? '完成全部转角采集并确认结果后，可保存分析样品。' : '保存后可在“定量分析与慢进”和“谱图查看”中选择该样品。'}</p>
      {canSave && <form className="hardware-analysis-sample-form" onSubmit={async event => {
        event.preventDefault()
        if (!ready || inFlight.current || !name.trim()) return
        inFlight.current = true; setSaving(true)
        try {
          await api.saveHardwareAnalysisSample(token, task.id, { sample_name: name.trim(), sample_kind: kind, name_length: length })
          await onSaved(); onToast('转角结果已保存为分析样品')
        } catch (error) { onToast(error instanceof Error ? error.message : '保存分析样品失败') }
        finally { inFlight.current = false; setSaving(false) }
      }}>
        <label className="field"><span>正式样号</span><input value={name} required maxLength={length}
          disabled={!ready || saving} onChange={e => setName(e.target.value)} /></label>
        <label className="field"><span>样号长度</span><select value={length} disabled={!ready || saving}
          onChange={e => setLength(Number(e.target.value) as 12 | 20)}><option value={12}>12 位</option><option value={20}>20 位</option></select></label>
        <label className="field"><span>样品类型</span><select value={kind} disabled={!ready || saving}
          onChange={e => setKind(e.target.value as typeof kind)}><option value="test">试样</option><option value="standard">标准样品</option></select></label>
        <button className="primary-button" disabled={!ready || saving || !name.trim()}>{saving ? '保存中…' : '保存为分析样品'}</button>
      </form>}
    </>}
  </section>
}
