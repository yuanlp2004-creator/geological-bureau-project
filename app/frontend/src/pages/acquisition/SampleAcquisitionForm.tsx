import type { Dispatch, FormEvent, SetStateAction } from 'react'

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
  return <form id={props.formId} className="acquisition-form sample-number-form" onSubmit={props.create}>
    <label className="field">
      <span>样品摄谱编号</span>
      <input autoFocus required maxLength={120} value={props.taskName}
        onChange={event => props.setTaskName(event.target.value)} disabled={!props.canWrite || props.busy} />
    </label>
    <p className="field-hint">沿用当前方法、设备参数和预录样号表。</p>
    {!props.hideSubmit && <button type="submit" disabled={!props.canWrite || props.busy || !props.taskName.trim()}>确定</button>}
  </form>
}
