import { AppIcon } from '../../components/AppIcon'
import { type About } from '../../api'

export function AboutPage({ about }: { about: About | null }) {
  return (
    <div className="page-content about-page refined-page remaining-page" data-testid="about-software">
      <section className="surface about-software-card">
        <div className="product-lockup">
          <AppIcon className="product-mark" size={48} />
          <h2>{about?.display_name ?? 'GeoSpectrum'}</h2>
        </div>
        <dl className="about-software-details">
          <div><dt>版本</dt><dd>{about?.version ?? '—'}</dd></div>
          <div><dt>版权</dt><dd>{about?.copyright ?? '—'}</dd></div>
        </dl>
      </section>
    </div>
  )
}
