import type { ReactNode } from 'react'
import './section-heading.css'

/** Content cards use a compact subtitle; the page owns its decorative main heading. */
export function SectionHeading({ title, description }: { title: ReactNode; description?: ReactNode }) {
  return <div className="section-heading"><h2>{title}</h2>
    {description && <div className="section-heading-description">{description}</div>}
  </div>
}
