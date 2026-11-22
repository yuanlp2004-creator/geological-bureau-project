import type { DevicePort, DeviceProfile } from '../../api'

export function connectionValue(profile: DeviceProfile | null | undefined): string {
  return profile ? profile.transport === 'serial' ? `COM${profile.port}` : 'simulator' : ''
}

export function ConnectionPortSelect({ value, ports, savedPorts, disabled, label = '通讯口', onChange }: {
  value: string; ports: DevicePort[]; savedPorts: number[]; disabled: boolean; label?: string
  onChange: (value: string) => void
}) {
  const numbers = [...new Set([...ports.map(port => port.port), ...savedPorts])].sort((a, b) => a - b)
  return <label className="field legacy-parameter-row"><span>通讯口</span>
    <select aria-label={label} value={value} disabled={disabled} onChange={event => onChange(event.target.value)}>
      <option value="">请选择通讯口</option>
      {numbers.map(number => {
        const port = ports.find(item => item.port === number)
        return <option key={number} value={`COM${number}`}>COM{number}{port
          ? ` · ${port.is_bluetooth ? '蓝牙串口 · ' : ''}${port.description}` : '（系统未列出）'}</option>
      })}
    </select>
  </label>
}
