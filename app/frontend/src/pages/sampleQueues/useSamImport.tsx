import { useEffect, useRef, useState } from 'react'
import { ApiError } from '../../api/client'
import type { SamEncoding } from '../../api/sampleQueues'
import { ViewerDialog } from '../spectra/ViewerDialog'

type Difference = { line: number; gb18030: string | null; utf8: string | null }
type Preview = { filename: string; differences: Difference[] }

export function useSamImport() {
  const [preview, setPreview] = useState<Preview | null>(null)
  const pending = useRef<((choice: SamEncoding | null) => void) | null>(null)
  const mounted = useRef(false)
  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
      pending.current?.(null)
      pending.current = null
    }
  }, [])

  const finish = (encoding: SamEncoding | null) => {
    const resolve = pending.current
    pending.current = null
    setPreview(null)
    resolve?.(encoding)
  }

  const importSam = async <T,>(filename: string, submit: (encoding?: SamEncoding) => Promise<T>): Promise<T | null> => {
    try {
      return await submit()
    } catch (error) {
      if (!(error instanceof ApiError) || error.code !== 'sam_encoding_ambiguous') throw error
      const differences = (error.details as { differences?: Difference[] } | undefined)?.differences
      if (!Array.isArray(differences) || !differences.length) throw error
      if (!mounted.current) return null
      const encoding = await new Promise<SamEncoding | null>(resolve => {
        pending.current = resolve
        setPreview({ filename, differences })
      })
      return encoding ? submit(encoding) : null
    }
  }

  const samPreview = preview && <ViewerDialog title="确认 SAM 样号" onClose={() => finish(null)}>
    <div className="sam-encoding-preview">
      <p><strong>{preview.filename}</strong> 有 {preview.differences.length} 行样号读法不同，请选择正确的一列。</p>
      <div className="sam-encoding-differences" tabIndex={0}>
        <table aria-label="不同编码的样号预览">
          <thead><tr><th scope="col">文件行号</th><th scope="col">GB18030</th><th scope="col">UTF-8</th></tr></thead>
          <tbody>{preview.differences.map(row => <tr key={row.line}>
            <th scope="row">{row.line}</th>
            <td>{row.gb18030 ?? '—'}</td><td>{row.utf8 ?? '—'}</td>
          </tr>)}</tbody>
        </table>
      </div>
      <div className="sam-encoding-actions">
        <button type="button" className="secondary-button" onClick={() => finish(null)}>取消</button>
        <button type="button" className="secondary-button" onClick={() => finish('gb18030')}>使用 GB18030</button>
        <button type="button" className="secondary-button" onClick={() => finish('utf-8-sig')}>使用 UTF-8</button>
      </div>
    </div>
  </ViewerDialog>

  return { importSam, samPreview }
}
