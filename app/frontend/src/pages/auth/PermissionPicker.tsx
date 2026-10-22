import { useEffect, useRef } from 'react'
import type { Capability } from '../../api'
import './permissions.css'

const groups: Record<string, string> = {
  settings: '软件设置', 'runtime-events': '运行信息', users: '用户管理', roles: '角色管理', audit: '审计记录',
  methods: '方法与谱线', migration: '旧方法迁移', 'spectrum-migration': '旧谱图迁移',
  'result-migration': '旧结果迁移', spectra: '谱图查看', samples: '样号与样品队列', results: '分析结果',
  devices: '设备调试', dispersion: '色散摄谱与曲线', acquisition: '蒸发与样品摄谱',
  'hardware-acquisition': '自动转角', 'mercury-calibration': '汞灯与光学校准', analysis: '分析与标准曲线',
  postprocessing: '数据后处理', reports: '报告', maintenance: '数据维护', help: '帮助', about: '关于软件'
}
const actions: Record<string, string> = {
  read: '查看', write: '编辑', execute: '执行', export: '导出', print: '打印',
  intervene: '慢进人工干预', quality: '重复性质控', curve: '标准曲线调整'
}
export function permissionGroupLabel(key: string, capabilities: Capability[]): string {
  const prefix = key.split('.')[0]
  return groups[prefix] ?? capabilities.find((item) => item.permissions.includes(key))?.title ?? prefix
}
export function permissionLabel(key: string, capabilities: Capability[]): string {
  const action = key.split('.').slice(1).join('.')
  return `${permissionGroupLabel(key, capabilities)}：${actions[action] ?? action}`
}

function GroupSelection({ label, permissions, selected, onChange }: {
  label: string
  permissions: string[]
  selected: string[]
  onChange: (keys: string[]) => void
}) {
  const input = useRef<HTMLInputElement>(null)
  const count = permissions.filter((key) => selected.includes(key)).length
  useEffect(() => {
    if (input.current) input.current.indeterminate = count > 0 && count < permissions.length
  }, [count, permissions.length])
  return <label className="permission-group-choice">
    <input ref={input} type="checkbox" aria-label={`整组选取：${label}`}
      checked={count === permissions.length} onChange={(event) => onChange(event.target.checked
        ? [...new Set([...selected, ...permissions])]
        : selected.filter((key) => !permissions.includes(key)))} />
    <strong>{label}</strong><small>{count}/{permissions.length}</small>
  </label>
}

export function PermissionPicker({ keys, selected, onChange, capabilities, disabled }: {
  keys: string[]
  selected: string[]
  onChange: (keys: string[]) => void
  capabilities: Capability[]
  disabled: boolean
}) {
  const grouped = new Map<string, string[]>()
  for (const key of keys) {
    const label = permissionGroupLabel(key, capabilities)
    grouped.set(label, [...(grouped.get(label) ?? []), key])
  }
  return <div className="permission-picker" role="group" aria-label="业务权限">
    <p className="field-hint">可整组选取，展开后可单独调整操作。未选中的操作不授权。</p>
    <div className="permission-groups">
      {[...grouped].map(([label, permissions]) => <fieldset className="permission-group" key={label} disabled={disabled}>
        <legend className="visually-hidden">{label}</legend>
        <GroupSelection label={label} permissions={permissions} selected={selected} onChange={onChange} />
        <details className="permission-group-details"><summary>调整细项</summary>
        {permissions.map((key) => <label className="permission-choice" key={key}>
          <input type="checkbox" data-permission-key={key} aria-label={permissionLabel(key, capabilities)}
            checked={selected.includes(key)} onChange={(event) => onChange(event.target.checked
              ? [...new Set([...selected, key])] : selected.filter((value) => value !== key))} />
          <span>{actions[key.split('.').slice(1).join('.')] ?? key.split('.').slice(1).join('.')}</span>
        </label>)}
        </details>
      </fieldset>)}
    </div>
    <small>已选择 {selected.length} 项权限</small>
  </div>
}
