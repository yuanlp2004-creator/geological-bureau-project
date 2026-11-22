import type { FormEvent, Dispatch, SetStateAction } from 'react'
import type { HardwareOptions } from '../../api'
import { AdvancedSettings } from '../../components/AdvancedSettings'
import { NumericInput } from '../../components/NumericInput'
import { ArrowUp, ArrowDown, Plus, Trash2 } from 'lucide-react'

export type ManualTurnDraft = { id: number; angle_deg: number | null; duration_seconds: number }

type Values = { name: string; sampleName: string; methodSelection: string;
  layoutId: string; strategy: 'short_to_long' | 'key_first'; policy: 'retry_then_stop' | 'manual';
  retryLimit: number; sample: string; seed: number; anomalies: string }
type Setters = { [Key in keyof Values as `set${Capitalize<Key>}`]: Dispatch<SetStateAction<Values[Key]>> }
type Props = Values & Setters & { create: (event: FormEvent) => Promise<void>; canWrite: boolean;
  busy: boolean; options: HardwareOptions | null; selectedProfile: HardwareOptions['profiles'][number] | undefined;
  mode: 'automatic' | 'manual'; setMode: (mode: 'automatic' | 'manual') => void;
  manualTurns: ManualTurnDraft[]; setManualTurns: Dispatch<SetStateAction<ManualTurnDraft[]>> }

export function HardwareAcquisitionForm(props: Props) {
  const disabled = !props.canWrite || props.busy
  const manual = props.mode === 'manual'
  const method = props.options?.methods.find(item => `${item.method_id}-${item.version}` === props.methodSelection)
  const methodTurns = method?.turns ?? []
  const methodPeriod = method?.sampling_period_seconds ?? 1
  const layoutKey = String(method?.ccd_layout_id ?? props.layoutId)
  const methodLayout = props.options?.layouts.find(layout => String(layout.id) === layoutKey || layout.name === layoutKey)
  const move = (index: number, offset: number) => props.setManualTurns(current => {
    const rows = [...current]; [rows[index], rows[index + offset]] = [rows[index + offset], rows[index]]; return rows
  })
  return <form id="hardware-task-form" className="hardware-form" onSubmit={props.create}>
    <fieldset disabled={disabled}>
      <div className="hardware-mode-switch span-2" role="group" aria-label="采集模式">
        <button type="button" aria-pressed={!manual} onClick={() => props.setMode('automatic')}>自动</button>
        <button type="button" aria-pressed={manual} onClick={() => {
          props.setManualTurns(current => current.map(row => row.angle_deg === null ? { ...row,
            angle_deg: methodTurns[0]?.angle_deg ?? null, duration_seconds: Math.max(row.duration_seconds, (methodTurns[0]?.end_frame ?? 1) * methodPeriod) } : row))
          props.setMode('manual')
        }}>手动</button>
      </div>
      <label className="field"><span>任务名称</span><input required maxLength={120} value={props.name}
        onChange={e => props.setName(e.target.value)} /></label>
      <label className="field"><span>样号</span><input maxLength={100} value={props.sampleName}
        onChange={e => props.setSampleName(e.target.value)} /></label>
      <label className="field span-2"><span>采集方法</span><select aria-label="采集方法" required value={props.methodSelection}
        onChange={e => props.setMethodSelection(e.target.value)}>
        <option value="" disabled>请选择已发布方法</option>
        {props.options?.methods.map(method => <option key={`${method.method_id}-${method.version}`} value={`${method.method_id}-${method.version}`}>
          {method.name} · v{method.version}</option>)}
      </select></label>
      {!manual && <label className="field"><span>转角顺序</span><select aria-label="转角顺序" value={props.strategy} onChange={e => props.setStrategy(e.target.value as Values['strategy'])}>
        <option value="short_to_long">短波 → 长波</option><option value="key_first">关键波段优先</option>
      </select></label>}
      {manual && <section className="hardware-manual-plan span-2" aria-label="手动转角计划">
        <p className="field-hint">从方法中选择转角，沿用对应波段、计算区间和谱线计算规则；按表格顺序持续采集，暂停时间不计入。</p>
        {!methodTurns.length && <p className="hardware-alert external" role="status">所选方法未配置转角，请先完善方法。</p>}
        <div className="hardware-manual-scroll"><table><thead><tr><th>顺序</th><th>旋转角度（°）</th><th>采集时长（秒）</th><th>方法计算配置</th><th>操作</th></tr></thead>
          <tbody>{props.manualTurns.map((row, index) => {
            const slot = methodTurns.findIndex(item => item.angle_deg === row.angle_deg)
            const config = methodTurns[slot]
            return <tr key={row.id}><td>{index + 1}</td>
            <td><select aria-label={`手动角度 ${index + 1}`} required value={row.angle_deg ?? ''}
              onChange={event => props.setManualTurns(current => current.map(item => item.id === row.id ? { ...item, angle_deg: Number(event.target.value) } : item))}>
              <option value="" disabled>选择方法转角</option>
              {row.angle_deg !== null && slot < 0 && <option value={row.angle_deg} disabled>{row.angle_deg}°（请重新选择）</option>}
              {methodTurns.map((item, position) => <option key={position} value={item.angle_deg}>{item.angle_deg}° · 第 {position + 1} 组</option>)}
            </select></td>
            <td><NumericInput aria-label={`采集时长 ${index + 1}`} value={row.duration_seconds} min={0.1} max={3600} step="any"
              onValueChange={value => props.setManualTurns(current => current.map(item => item.id === row.id ? { ...item, duration_seconds: value } : item))} /></td>
            <td className="hardware-manual-config">{config ? <><span>第 {slot + 1} 组 · {config.storage_mode === 'full_interval' ? '全区间' : '平均谱图'}</span><small>计算区间：{config.start_frame}–{config.end_frame} 帧</small></> : '请选择对应转角'}</td>
            <td><div className="hardware-row-actions">
              <button type="button" title={`上移转角 ${index + 1}`} disabled={index === 0} onClick={() => move(index, -1)}><ArrowUp size={15} /></button>
              <button type="button" title={`下移转角 ${index + 1}`} disabled={index === props.manualTurns.length - 1} onClick={() => move(index, 1)}><ArrowDown size={15} /></button>
              <button type="button" title={`删除转角 ${index + 1}`} disabled={props.manualTurns.length === 1}
                onClick={() => props.setManualTurns(current => current.filter(item => item.id !== row.id))}><Trash2 size={16} aria-hidden="true" /></button>
            </div></td></tr>})}</tbody></table></div>
        <div className="hardware-manual-footer"><button type="button" className="secondary-button" disabled={props.manualTurns.length >= 300}
          onClick={() => props.setManualTurns(current => [...current, { id: Math.max(0, ...current.map(row => row.id)) + 1, angle_deg: methodTurns[0]?.angle_deg ?? null, duration_seconds: Math.max(10, (methodTurns[0]?.end_frame ?? 1) * methodPeriod) }])}>
          <Plus size={16} aria-hidden="true" />新增转角</button>
          <span>共 {props.manualTurns.length} 个转角 · 总采集 {Number(props.manualTurns.reduce((sum, row) => sum + row.duration_seconds, 0).toFixed(2))} 秒</span></div>
      </section>}
      <AdvancedSettings title="采集与异常设置">
        <div className="advanced-field-grid">
          <label className="field"><span>CCD 布局</span><select value={String(methodLayout?.id ?? layoutKey)} disabled={Boolean(method)} onChange={e => props.setLayoutId(e.target.value)}>
            {props.options?.layouts.map(layout => <option key={String(layout.id)} value={String(layout.id)}>{String(layout.name)}</option>)}
          </select><small>沿用采集方法的 CCD 布局及激发条件</small></label>
          <label className="field"><span>异常处理</span><select value={props.policy} onChange={e => props.setPolicy(e.target.value as Values['policy'])}>
            <option value="retry_then_stop">重采失败后停止</option><option value="manual">重采失败后人工处理</option>
          </select></label>
          <label className="field"><span>重采上限</span><NumericInput min={0} max={5} value={props.retryLimit} onValueChange={props.setRetryLimit} /></label>
        </div>
      </AdvancedSettings>
      {props.selectedProfile?.transport === 'simulator' && <AdvancedSettings title="模拟调试参数">
        <div className="advanced-field-grid">
          <label className="field"><span>模拟帧文件</span><input value={props.sample} onChange={e => props.setSample(e.target.value)} /></label>
          <label className="field"><span>随机种子</span><NumericInput min={0} max={2147483647} value={props.seed} onValueChange={props.setSeed} /></label>
          <label className="field span-2"><span>模拟异常脚本 JSON</span><textarea aria-label="模拟异常脚本 JSON" rows={4} spellCheck={false}
            value={props.anomalies} onChange={e => props.setAnomalies(e.target.value)} /></label>
        </div>
      </AdvancedSettings>}
    </fieldset>
    {props.selectedProfile?.transport === 'serial' && <p className="hardware-alert external" role="status">转角协议尚未接入，此设备暂不可执行采集。</p>}
  </form>
}
