import type { SelectHTMLAttributes } from 'react'
import { SpectroscopyIcon } from './SpectroscopyIcon'

/** FmView.TbSelCcd: the CCD grid icon and its adjacent dropdown arrow. */
export function LegacyCcdPicker({ children, title, ...props }: SelectHTMLAttributes<HTMLSelectElement>) {
  return <label className="legacy-ccd-picker" title={title}>
    <SpectroscopyIcon name="select-ccd" /><span className="legacy-ccd-arrow" aria-hidden="true" />
    <select {...props} title={title}>{children}</select>
  </label>
}
