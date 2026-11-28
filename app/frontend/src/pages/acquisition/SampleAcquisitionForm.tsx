import { useState, type Dispatch, type FormEvent, type SetStateAction } from 'react'

export type SampleAcquisitionFormProps = {
  canWrite: boolean
  busy: boolean
  taskName: string
  setTaskName: Dispatch<SetStateAction<string>>
  create: (event: FormEvent) => Promise<void>
  formId?: string
  hideSubmit?: boolean
}

export function SampleAcquisitionForm(props: SampleAcquisitionFormProps) {
  const [policy, setPolicy] = useState('stop')
  return <form id={props.formId} className="acquisition-form sample-number-form" onSubmit={props.create}>
    <label className="field">
      <span>样品摄谱编号</span>
      <input autoFocus required maxLength={120} value={props.taskName}
        onChange={event => props.setTaskName(event.target.value)} disabled={!props.canWrite || props.busy} />
    </label>
    <label className="field">
      <span>异常处置</span>
      <select name="anomaly_policy" value={policy} onChange={event => setPolicy(event.target.value)}
        disabled={!props.canWrite || props.busy}>
        <option value="stop">重采耗尽后安全停机</option>
        <option value="manual">重采耗尽后等待人工接管</option>
        <option value="warn">仅告警</option>
      </select>
    </label>
    <label className="field">
      <span>自动重采次数</span>
      <select key={policy === 'warn' ? 'warn' : 'retry'} name="retry_limit" defaultValue={policy === 'warn' ? '0' : '1'}
        disabled={policy === 'warn' || !props.canWrite || props.busy}>
        {[0, 1, 2, 3, 4, 5].map(count => <option key={count} value={count}>{count}</option>)}
      </select>
    </label>
    <p className="field-hint">沿用当前方法、设备参数和预录样号表。</p>
    {!props.hideSubmit && <button type="submit" disabled={!props.canWrite || props.busy || !props.taskName.trim()}>确定</button>}
  </form>
}
