import { useRef, useState, type FormEvent } from 'react'
import { ApiError } from '../../api/client'
import { ViewerDialog } from '../spectra/ViewerDialog'
import {
  initialIntensityOutputOptions, requestIntensityOutput, saveIntensityDefaults, saveIntensityFile,
  type IntensityOutputFile, type IntensityOutputOptions,
} from './IntensityOutput'

const outputChoices = [
  ['print_intensity', '打印强度'],
  ['print_to_text', '打印到文本'],
  ['save_intensity', '保存强度'],
  ['save_positions', '保存校正波长'],
] as const

type Props = {
  token: string
  runId: number
  runName: string
  defaults?: IntensityOutputOptions
  canPrint: boolean
  canSaveMethod: boolean
  canExecute: boolean
  onDefaultsSaved: (options: IntensityOutputOptions) => void
  onConfirm: () => void
  onClose: () => void
}

export function AnalysisCalculationDialog({
  token, runId, runName, defaults = initialIntensityOutputOptions, canPrint, canSaveMethod, canExecute,
  onDefaultsSaved, onConfirm, onClose,
}: Props) {
  const [options, setOptions] = useState(() => ({
    ...defaults,
    print_intensity: defaults.print_intensity && canPrint,
    save_positions: defaults.save_positions && canSaveMethod,
  }))
  const [remember, setRemember] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [outputReceived, setOutputReceived] = useState(false)
  const [outcomeUnknown, setOutcomeUnknown] = useState(false)
  const submitting = useRef(false)
  const pendingFiles = useRef<IntensityOutputFile[] | null>(null)

  const close = () => { if (!submitting.current) onClose() }

  const confirm = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (submitting.current || outcomeUnknown) return
    submitting.current = true
    setBusy(true)
    setError('')
    try {
      if (pendingFiles.current === null && Object.values(options).some(Boolean)) {
        try {
          const result = await requestIntensityOutput(token, runId, options, options.print_intensity ? 300_000 : undefined)
          // A print job already goes through the selected printer. Its preview PDF needs no separate save dialog here.
          pendingFiles.current = result.files.filter(file => file.media_type !== 'application/pdf')
          setOutputReceived(true)
        } catch (failure) {
          if ((options.print_intensity || options.save_positions) && failure instanceof ApiError &&
              (failure.code === 'request_outcome_unknown' || failure.status >= 500)) {
            setOutcomeUnknown(true)
          }
          throw failure
        }
      }
      // Keep the receipt so retrying a file save does not print again or make another method draft.
      const files = pendingFiles.current
      while (files?.length) {
        await saveIntensityFile(files[0])
        files.shift()
      }
      if (remember && canExecute) onDefaultsSaved(await saveIntensityDefaults(token, options))
      onConfirm()
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure || '强度输出失败'))
    } finally {
      submitting.current = false
      setBusy(false)
    }
  }

  return (
    <ViewerDialog title="分析计算" onClose={close} closeDisabled={busy}>
      <form className="analysis-calculation-confirmation" onSubmit={confirm} aria-busy={busy}>
        <p>「{runName}」测量已完成。</p>
        <fieldset className="analysis-calculation-options" aria-label="强度输出" disabled={busy || outputReceived || outcomeUnknown}>
          {outputChoices.map(([key, label]) => (
            <label key={key} className="checkbox-row">
              <input
                type="checkbox" checked={options[key]}
                disabled={(key === 'print_intensity' && !canPrint) || (key === 'save_positions' && !canSaveMethod)}
                onChange={event => setOptions({ ...options, [key]: event.target.checked })}
              />
              {label}
            </label>
          ))}
        </fieldset>
        {error && <p className="auth-error" role="alert">{error}</p>}
        <div className="analysis-calculation-footer">
          <label className="checkbox-row">
            <input type="checkbox" checked={remember} disabled={busy || !canExecute || outcomeUnknown}
              onChange={event => setRemember(event.target.checked)} />
            默认
          </label>
          <div className="viewer-dialog-actions">
            <button type="button" className="secondary-button" disabled={busy} onClick={close}>取消</button>
            <button type="submit" className="primary-button" disabled={busy || outcomeUnknown} autoFocus>
              {busy ? '正在处理…' : '确定'}
            </button>
          </div>
        </div>
      </form>
    </ViewerDialog>
  )
}
