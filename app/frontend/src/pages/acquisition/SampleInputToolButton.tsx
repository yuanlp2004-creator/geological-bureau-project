import { ClipboardPenLine, Eraser, ListPlus } from 'lucide-react'
import type { ButtonHTMLAttributes } from 'react'

const inputIcons = {
  'input-samples': ClipboardPenLine,
  'insert-sample': ListPlus,
  'clear-samples': Eraser,
}

export function SampleInputToolButton({ icon, label, description, ...props }:
  ButtonHTMLAttributes<HTMLButtonElement> & { icon: keyof typeof inputIcons; label: string; description: string }) {
  const Icon = inputIcons[icon]
  return <button type="button" className="secondary-button inspector-icon-button"
    aria-label={label} title={description} {...props}><Icon size={16} strokeWidth={1.75} aria-hidden="true" /></button>
}
