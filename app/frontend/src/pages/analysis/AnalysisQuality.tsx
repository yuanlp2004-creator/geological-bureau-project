import { CheckCircle2, Clock3, RefreshCw, ShieldAlert } from 'lucide-react'
import { api, type AnalysisRun } from '../../api'
import type { AnalysisQcGroup } from '../../api/analysis'
import { useState } from 'react'

// 父页面统一持有草稿、选中项和请求状态。
type PanelProps = {
  selected: AnalysisRun
  busy: boolean
  canQuality: boolean
  mutate: (operation: () => Promise<AnalysisRun>, success: string, continuous?: boolean) => Promise<boolean>
  token: string
  qcGroups: AnalysisQcGroup[]
  qualityDecision: (group: NonNullable<AnalysisRun["quality"]["latest_snapshot"]>["groups"][number], action: "accept" | "exclude" | "restore", lineResultId: number | null, reason: string) => void
}

export function AnalysisQuality({
  selected,
  busy,
  canQuality,
  mutate,
  token,
  qcGroups,
  qualityDecision,
}: PanelProps) {
  const [groupByLine, setGroupByLine] = useState<Record<string, number>>({})
  const context = `${selected.id}-${qcGroups[0]?.line_id ?? ''}`
  const currentGroup = qcGroups.find((group) => group.acquisition_task_id === groupByLine[context])
    ?? qcGroups.find((group) => group.warnings.length && !group.warning_accepted)
    ?? qcGroups[0]
  return (
    <div className="analysis-workspace analysis-quality-panel" aria-label="重复测量质控">
      <div className="surface-heading">
        <div>
          <h3>重复性检查</h3>
        </div>
        <div className="analysis-actions">
          <span
            className={`snapshot-state ${!selected.quality.latest_snapshot ? 'pending' : selected.quality.latest_snapshot.publishable ? 'ready' : 'blocked'}`}
          >
            {!selected.quality.latest_snapshot ? <Clock3 size={14} /> : selected.quality.latest_snapshot.publishable ? <CheckCircle2 size={14} /> : <ShieldAlert size={14} />}
            {selected.quality.latest_snapshot
              ? `${selected.quality.latest_snapshot.publishable ? '可用于拟合' : '存在待复核项'}`
              : '尚未计算'}
          </span>
          <button
            className="secondary-button"
            disabled={busy || !canQuality || selected.status !== 'completed'}
            onClick={() =>
              void mutate(
                () => api.recalculateAnalysisQuality(token, selected.id),
                '重复统计已形成新的不可变质控快照'
              )
            }
          >
            <RefreshCw size={14} />
            重新统计
          </button>
        </div>
      </div>
      {!selected.quality.latest_snapshot && (
        <div className="empty-state compact-empty">
          分析完成后计算平均值、极差、标准差、RSD、ID 和有效次数。
        </div>
      )}
      {qcGroups.length > 0 && <label className="field qc-sample-picker">
        <span>检查样品 · {qcGroups.filter((group) => group.warnings.length && !group.warning_accepted).length} 项待复核</span>
        <select aria-label="重复性检查样品" value={currentGroup?.acquisition_task_id ?? ''} disabled={busy}
          onChange={(event) => setGroupByLine((current) => ({ ...current, [context]: Number(event.target.value) }))}>
          {qcGroups.map((group) => <option key={group.acquisition_task_id} value={group.acquisition_task_id}>
            {group.warnings.length && !group.warning_accepted ? '⚠ ' : ''}{group.sample_name} · {group.warning_accepted ? '已接受' : group.warnings.length ? '待复核' : '正常'}
          </option>)}
        </select>
      </label>}
      <div className="analysis-qc-groups">
        {(currentGroup ? [currentGroup] : []).map((group) => (
          <article
            key={`${group.acquisition_task_id}-${group.line_id}`}
            className={`surface qc-group ${group.warnings.length ? 'warning' : 'ready'}`}
          >
            <header>
              <div>
                <strong>{group.sample_name}</strong>
                <span>
                  {group.element} {group.wavelength_nm.toFixed(3)} nm · {group.repeat_count} 次重复
                </span>
              </div>
              <div className="qc-group-actions">
                <span className={`qc-state ${group.warning_accepted ? 'accepted' : group.warnings.length ? 'warning' : 'ready'}`}>
                  {group.warnings.length && !group.warning_accepted ? <ShieldAlert size={14} /> : <CheckCircle2 size={14} />}
                  {group.warning_accepted ? '已人工接受' : group.warnings.length ? '待复核' : '统计正常'}
                </span>
                {group.warnings.length > 0 && !group.warning_accepted && (
                  <button
                    className="secondary-button"
                    disabled={busy || !canQuality}
                    onClick={() => qualityDecision(group, 'accept', null, '人工复核后接受当前重复性提示')}
                  >
                    接受提示
                  </button>
                )}
              </div>
            </header>
            {group.warnings.length > 0 && (
              <div className="qc-warning-list" role="note" aria-label="重复测量提示">
                <ShieldAlert size={16} />
                <div>
                  {group.warnings.map((warning) => (
                    <p key={warning.code}>{warning.message}</p>
                  ))}
                </div>
              </div>
            )}
            <div className="qc-stat-grid">
              {(
                [
                  ['均值', group.statistics.mean],
                  ['极差', group.statistics.range],
                  ['标准差', group.statistics.stddev],
                  ['RSD %', group.statistics.rsd],
                  ['ID', group.statistics.id],
                  ['有效次数', group.statistics.effective_count]
                ] as Array<[string, number | null]>
              ).map(([label, value]) => (
                <div key={label}>
                  <span>{label}</span>
                  <strong>{value == null ? '—' : label === '有效次数' ? value : value.toFixed(5)}</strong>
                </div>
              ))}
            </div>
            <div className="qc-members">
              <table aria-label={`${group.sample_name}重复测量明细`}>
                <thead>
                  <tr><th>重复测量</th><th>测量值</th><th>状态</th><th>操作</th></tr>
                </thead>
                <tbody>
                  {group.members.map((member) => (
                    <tr key={member.line_result_id} className={member.included ? '' : 'excluded'}>
                      <td>重复 {member.repeat_index + 1}</td>
                      <td className="qc-measurement">{member.value.toFixed(6)}</td>
                      <td><span className={`qc-member-state ${member.included ? 'included' : 'excluded'}`}>{member.included ? '有效' : '已剔除'}</span></td>
                      <td>
                        {member.included ? (
                          <button
                            className="secondary-button"
                            disabled={busy || !canQuality}
                            onClick={() =>
                              qualityDecision(group, 'exclude', member.line_result_id, '重复测量复核后剔除')
                            }
                          >
                            剔除
                          </button>
                        ) : (
                          <button
                            className="secondary-button"
                            disabled={busy || !canQuality}
                            onClick={() =>
                              qualityDecision(group, 'restore', member.line_result_id, '恢复原始重复测量')
                            }
                          >
                            恢复
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </article>
        ))}
      </div>
    </div>
  )
}
