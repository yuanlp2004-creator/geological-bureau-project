import { Save } from 'lucide-react'
import { type AcquisitionTask } from '../../api'
import { stateLabel } from './acquisitionView'

// 父页面统一持有草稿、选中项和请求状态。
type PanelProps = {
  canWrite: boolean
  selected: AcquisitionTask
  renameValue: string
  setRenameValue: React.Dispatch<React.SetStateAction<string>>
  rename: () => Promise<void>
  nameLength: 12 | 20
  setNameLength: React.Dispatch<React.SetStateAction<12 | 20>>
  busy: boolean
}

/* 采后名称放在摄谱侧栏；原始数据和名称长度规则保持。 */ export function SampleAcquisitionResults({
  canWrite, selected, renameValue, setRenameValue, rename, nameLength, setNameLength, busy
}: PanelProps) {
  return (
    <details className="acquisition-rename" data-testid="acquisition-rename" onInvalidCapture={(event) => { event.currentTarget.open = true }}>
      <summary><Save size={14} />{selected.task_kind === 'evaporation' ? '实验重命名' : '采集后重命名'}</summary>
      <div className="acquisition-rename-body">
        <div className="rename-form">
          <select aria-label={selected.task_kind === 'evaporation' ? '实验名称长度' : '采集后样号长度'} value={nameLength}
            onChange={/* 选择正式样号长度，不截断草稿。 */ (e) => setNameLength(Number(e.target.value) as 12 | 20)} disabled={!canWrite || busy}>
            <option value={12}>12 位</option><option value={20}>20 位</option>
          </select>
          <input
            value={renameValue}
            onChange={/* 处理样品采集的当前输入或异步响应。 */ (e) => setRenameValue(e.target.value)}
            placeholder={selected.task_kind === 'evaporation' ? '完整采集后输入实验名称' : '完整采集后输入正式样号'}
            disabled={!canWrite || busy || selected.status !== 'completed' || selected.samples.every(/* 已删除样品不可改名。 */ (item) => item.discarded)}
          />
          <button
            className="secondary-button"
            onClick={/* 处理样品采集的当前输入或异步响应。 */ () => void rename()}
            disabled={!canWrite || busy || selected.status !== 'completed' || !renameValue.trim() || selected.samples.every(/* 已删除样品不可改名。 */ (item) => item.discarded)}
          >
            <Save size={15} />
            保存名称
          </button>
        </div>
        <div className={`sample-result-list ${nameLength === 20 ? 'sample-number-columns' : ''}`}>
          {selected.samples.map(
            /* 处理样品采集的当前输入或异步响应。 */ (item) => (
              <div key={item.id}>
                <span className={`task-state-dot ${item.status}`} />
                <strong>{item.sample_name || (selected.task_kind === 'evaporation' ? '未命名实验' : '空样 / 未命名')}</strong>
                <small>
                  {selected.task_kind === 'evaporation' ? '蒸发实验' : item.sample_kind} · {item.discarded ? '已删除 · ' : ''}
                  {item.status === 'completed' ? `${item.bands.length} CCD 均值带` : stateLabel[item.status]}
                </small>
              </div>
            )
          )}
        </div>
      </div>
    </details>
  )
}
