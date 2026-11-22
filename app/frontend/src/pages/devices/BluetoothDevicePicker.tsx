import { useEffect, useId, useRef, useState, type KeyboardEvent } from 'react'
import { ChevronDown, Trash2 } from 'lucide-react'
import type { BluetoothDevice } from '../../api'

const label = (device: BluetoothDevice) => `${device.name}（${device.connected ? '已连接' : device.paired ? '已配对，未连接' : '已记录，未连接'}）`

export function BluetoothDevicePicker({ devices, value, disabled, onChange, onDelete }: {
  devices: BluetoothDevice[]; value: string; disabled: boolean
  onChange: (value: string) => void; onDelete: (device: BluetoothDevice) => Promise<void>
}) {
  const [open, setOpen] = useState(false)
  const [placement, setPlacement] = useState({ above: false, height: 280 })
  const root = useRef<HTMLDivElement>(null), trigger = useRef<HTMLButtonElement>(null)
  const options = useRef<Array<HTMLButtonElement | null>>([])
  const deleting = useRef(false), currentDevices = useRef(devices)
  currentDevices.current = devices
  const popupId = useId()
  const selected = devices.find(item => item.address === value)
  const focus = (index: number) => requestAnimationFrame(() => options.current[Math.max(0, Math.min(index, currentDevices.current.length))]?.focus())
  const close = (restoreFocus = false) => { setOpen(false); if (restoreFocus) trigger.current?.focus() }
  useEffect(() => {
    if (!open) return
    const position = () => {
      const bounds = trigger.current?.getBoundingClientRect()
      if (!bounds) return
      const region = root.current?.closest('.page-scroll-region')?.getBoundingClientRect()
      const above = bounds.top - (region?.top ?? 0) - 8
      const below = (region?.bottom ?? window.innerHeight) - bounds.bottom - 8
      const useAbove = below < 280 && above > below
      setPlacement({ above: useAbove, height: Math.max(80, Math.min(280, useAbove ? above : below)) })
    }
    position()
    const outside = (event: PointerEvent) => { if (!root.current?.contains(event.target as Node)) setOpen(false) }
    document.addEventListener('pointerdown', outside)
    window.addEventListener('resize', position)
    window.addEventListener('scroll', position, true)
    return () => { document.removeEventListener('pointerdown', outside); window.removeEventListener('resize', position); window.removeEventListener('scroll', position, true) }
  }, [open])
  const keyboard = (event: KeyboardEvent, index: number) => {
    if (event.key === 'ArrowDown') { event.preventDefault(); focus(index + 1) }
    else if (event.key === 'ArrowUp') { event.preventDefault(); focus(index - 1) }
    else if (event.key === 'Home') { event.preventDefault(); focus(0) }
    else if (event.key === 'End') { event.preventDefault(); focus(devices.length) }
    else if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); close(true) }
  }
  return <div className="bluetooth-device-picker" ref={root} onBlur={event => {
    if (!deleting.current && !root.current?.contains(event.relatedTarget as Node)) setOpen(false)
  }}>
    <button type="button" className="bluetooth-device-trigger" role="combobox" aria-label="Windows蓝牙设备"
      value={value} aria-haspopup="dialog" aria-expanded={open} aria-controls={popupId} disabled={disabled}
      ref={trigger} onClick={() => setOpen(current => !current)} onKeyDown={event => {
        if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
          event.preventDefault(); setOpen(true)
          const index = devices.findIndex(item => item.address === value)
          focus(index >= 0 ? index + 1 : event.key === 'ArrowUp' ? devices.length : 0)
        } else if (event.key === 'Escape') { event.preventDefault(); close() }
      }}><span>{selected ? label(selected) : '请选择蓝牙设备'}</span><ChevronDown size={16}/></button>
    {open && <div id={popupId} className="bluetooth-device-popup" role="dialog" aria-label="蓝牙设备列表"
      style={{ top: placement.above ? 'auto' : 'calc(100% + 4px)', bottom: placement.above ? 'calc(100% + 4px)' : 'auto', maxHeight: placement.height }}>
      <div className="bluetooth-device-row"><button type="button" className="bluetooth-device-option" disabled={disabled}
        ref={element => { options.current[0] = element }} onKeyDown={event => keyboard(event, 0)}
        onClick={() => { onChange(''); close(true) }}>请选择蓝牙设备</button></div>
      {devices.map((device, index) => <div key={device.address} className={`bluetooth-device-row${device.address === value ? ' selected' : ''}`} data-bluetooth-address={device.address}>
        <button type="button" className="bluetooth-device-option" disabled={disabled} aria-label={`选择 ${device.name}`}
          aria-pressed={device.address === value} ref={element => { options.current[index + 1] = element }}
          onKeyDown={event => {
            if (event.key === 'ArrowRight') { event.preventDefault(); (event.currentTarget.nextElementSibling as HTMLButtonElement)?.focus() }
            else keyboard(event, index + 1)
          }} onClick={() => { onChange(device.address); close(true) }}>{label(device)}</button>
        <button type="button" className="bluetooth-device-delete" title="删除设备" aria-label={`删除 ${device.name}`} disabled={disabled}
          onMouseDown={event => event.preventDefault()} onKeyDown={event => {
            if (event.key === 'ArrowLeft') { event.preventDefault(); options.current[index + 1]?.focus() }
            else keyboard(event, index + 1)
          }} onClick={event => {
            event.stopPropagation(); deleting.current = true
            void onDelete(device).finally(() => requestAnimationFrame(() => {
              deleting.current = false
              if (root.current?.querySelector('[role="dialog"]')) focus(index + 1)
            }))
          }}><Trash2 size={16}/></button>
      </div>)}
    </div>}
  </div>
}
