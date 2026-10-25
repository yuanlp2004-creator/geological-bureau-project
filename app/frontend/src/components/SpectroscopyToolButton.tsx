import type { ButtonHTMLAttributes } from 'react'
import { SpectroscopyIcon, type SpectroscopyIconName } from './SpectroscopyIcon'

export function SpectroscopyToolButton({ icon, label, description, children, className = '', ...props }:
  ButtonHTMLAttributes<HTMLButtonElement> & { icon: SpectroscopyIconName; label: string; description?: string }) {
  return <button type="button" className={`secondary-button inspector-icon-button ${className}`}
    aria-label={label} title={description ?? label} {...props}><SpectroscopyIcon name={icon} />{children}</button>
}
