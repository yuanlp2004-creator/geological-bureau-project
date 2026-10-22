import {
  FileText
} from 'lucide-react'

// 父页面统一持有草稿、选中项和请求状态。
type PanelProps = {
  draftName: string
  setDraftName: React.Dispatch<React.SetStateAction<string>>
  canWrite: boolean
  draftDescription: string
  setDraftDescription: React.Dispatch<React.SetStateAction<string>>
}

export function MethodIdentity({
  draftName,
  setDraftName,
  canWrite,
  draftDescription,
  setDraftDescription,
}: PanelProps) {
  return (
    <section className="surface method-section method-identity">
      <div className="surface-heading">
        <div>
          <h2>基本信息</h2>
        </div>
        <FileText size={17} />
      </div>
      <div className="method-field-grid">
        <label className="field">
          <span>方法名称</span>
          <input
            value={draftName}
            onChange={(event) => setDraftName(event.target.value)}
            disabled={!canWrite}
          />
          <small>
            {new TextEncoder().encode(draftName).length} UTF-8 字节；保存时按 GB18030 验证 20 字节边界
          </small>
        </label>
        <label className="field span-2">
          <span>说明</span>
          <textarea
            rows={1}
            value={draftDescription}
            onChange={(event) => setDraftDescription(event.target.value)}
            disabled={!canWrite}
          />
        </label>
      </div>
    </section>
  )
}
