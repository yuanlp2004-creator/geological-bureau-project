import { useEffect, useRef } from 'react'
import type { Capability } from '../../api'
import { isAvailablePermission, isCompatibilityPermission, selectablePermissions } from './permissionChoices'
import './permissions.css'

const groups: Record<string, string> = {
  settings: '分析与屏幕参数', 'runtime-events': '运行信息', users: '用户管理', roles: '角色管理', audit: '审计记录',
  methods: '方法与谱线', migration: '旧方法迁移', 'spectrum-migration': '旧谱图迁移',
  'result-migration': '旧结果迁移', spectra: '谱图查看', samples: '样号与样品队列', results: '历史分析结果',
  devices: '设备调试', dispersion: '色散摄谱与曲线', acquisition: '蒸发与样品摄谱',
  'hardware-acquisition': '历史转角任务', 'mercury-calibration': '历史汞灯校准', analysis: '分析与标准曲线',
  postprocessing: '数据后处理', reports: '报告', maintenance: '数据维护', help: '帮助', about: '关于软件',
  activation: '软件激活', support: '模块远程诊断'
}

const actions: Record<string, string> = {
  read: '查看', write: '编辑', execute: '执行', export: '导出', print: '打印',
  intervene: '慢进人工干预', quality: '重复性质控', curve: '标准曲线调整'
}
const permissionActions: Record<string, string> = {
  'methods.write': '新增、编辑与删除',
  'analysis.execute': '测量与分析',
  'dispersion.execute': '执行色散摄谱',
  'acquisition.execute': '执行样品与蒸发摄谱',
  'hardware-acquisition.execute': '转存已确认的分析样品',
  'activation.manage': '查看状态与导入授权',
  'support.manage': '开启与结束诊断共享'
}

function permissionAction(key: string): string {
  const action = key.split('.').slice(1).join('.')
  return permissionActions[key] ?? actions[action] ?? action
}
export function permissionGroupLabel(key: string, capabilities: Capability[]): string {
  const prefix = key.split('.')[0]
  return groups[prefix] ?? capabilities.find((item) => item.permissions.includes(key))?.title ?? prefix
}
export function permissionLabel(key: string, capabilities: Capability[]): string {
  return `${permissionGroupLabel(key, capabilities)}：${permissionAction(key)}${isAvailablePermission(key) ? '' : '（已退役）'}`
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

export function PermissionPicker({ keys, selected, retainedKeys = [], onChange, capabilities, disabled }: {
  keys: string[]
  selected: string[]
  retainedKeys?: string[]
  onChange: (keys: string[]) => void
  capabilities: Capability[]
  disabled: boolean
}) {
  const grouped = new Map<string, string[]>()
  const compatible = new Map<string, string[]>()
  for (const key of selectablePermissions(keys, [...retainedKeys, ...selected])) {
    const target = isCompatibilityPermission(key) ? compatible : grouped
    const label = permissionGroupLabel(key, capabilities)
    target.set(label, [...(target.get(label) ?? []), key])
  }
  const renderGroups = (group: Map<string, string[]>) => <div className="permission-groups">
      {[...group].map(([label, permissions]) => <fieldset className="permission-group" key={label} disabled={disabled}>
        <legend className="visually-hidden">{label}</legend>
        <GroupSelection label={label} permissions={permissions} selected={selected} onChange={onChange} />
        <details className="permission-group-details"><summary>调整细项</summary>
        {permissions.map((key) => <label className="permission-choice" key={key}>
          <input type="checkbox" data-permission-key={key} aria-label={permissionLabel(key, capabilities)} title={key}
            checked={selected.includes(key)} onChange={(event) => onChange(event.target.checked
              ? [...new Set([...selected, key])] : selected.filter((value) => value !== key))} />
          <span>{permissionAction(key)}{!isAvailablePermission(key) && '（已退役）'}</span>
        </label>)}
        </details>
      </fieldset>)}
    </div>
  return <div className="permission-picker" role="group" aria-label="业务权限">
    <p className="field-hint">可整组选取，展开后可单独调整操作。未选中的操作不授权。</p>
    {renderGroups(grouped)}
    {compatible.size > 0 && <div role="group" aria-label="历史兼容权限">
      <p className="field-hint">历史兼容权限</p>
      {renderGroups(compatible)}
    </div>}
    <small>已选择 {selected.length} 项权限</small>
  </div>
}
