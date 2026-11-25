import { ChevronRight } from 'lucide-react'
import type { SpectralLine } from '../../api'
import type { buildCcdCoverageSummary } from './spectralLineFilters'

type Coverage = ReturnType<typeof buildCcdCoverageSummary>
type Range = [number, number]

function rangeText([start, end]: Range) {
  return `${start.toFixed(4)}–${end.toFixed(4)} nm`
}

function rangePosition([start, end]: Range, min: number, span: number) {
  return { left: `${(start - min) / span * 100}%`, width: `${(end - start) / span * 100}%` }
}

function LineLink({ line, onLocate }: { line: SpectralLine; onLocate: (id: string) => void }) {
  return <button type="button" onClick={() => onLocate(line.id)} title="在谱线清单中定位">
    {line.element} {line.wavelength_nm.toFixed(4)} nm
  </button>
}

export function SpectralCcdCoverage({ coverage, onLocate }: { coverage: Coverage; onLocate: (id: string) => void }) {
  const physicalRanges = coverage.mode === 'single'
    ? coverage.bands.flatMap(band => band.physicalRange ? [band.physicalRange] : []) : []
  const min = Math.min(...physicalRanges.map(([start]) => start))
  const span = Math.max(...physicalRanges.map(([, end]) => end)) - min
  return (
    <details className="spectral-ccd-coverage-bar" data-testid="spectral-ccd-coverage">
      <summary>
        <ChevronRight size={15} aria-hidden="true" />
        <strong>CCD 波段覆盖</strong>
        <span>{coverage.mode === 'single'
          ? `${coverage.bands.length} 个 CCD${coverage.bands.some(band => band.missingCalibration) ? ' · 有 CCD 缺标定' : ''}`
          : `${coverage.angles.length} 个已检出角位 · 未确定角位 ${coverage.undetermined.length} 条`}</span>
      </summary>
      <div className="spectral-coverage-groups">
        {coverage.mode === 'single' ? (
          coverage.bands.length === 0 ? <p>方法未选择 CCD</p> : coverage.bands.map(band => (
            <section className="spectral-coverage-group" key={band.ccdIndex}>
              <h3>{band.label} <small>已检出 {band.detectedCount} 条</small></h3>
              {band.missingCalibration && <p className="spectral-coverage-warning">缺标定</p>}
              {band.physicalRange && band.safeRange && (
                <>
                  {span > 0 && <div className="spectral-coverage-track" aria-hidden="true">
                    <span className="physical" style={rangePosition(band.physicalRange, min, span)} />
                    <span className="safe" style={rangePosition(band.safeRange, min, span)} />
                  </div>}
                  <div className="spectral-coverage-range"><span>物理范围</span> {rangeText(band.physicalRange)}</div>
                  <div className="spectral-coverage-range"><span>安全范围</span> {rangeText(band.safeRange)}</div>
                </>
              )}
              <div className="spectral-coverage-links">
                {band.lines.map(line => <LineLink key={line.id} line={line} onLocate={onLocate} />)}
              </div>
            </section>
          ))
        ) : (
          <>
            {coverage.angles.map(angle => (
              <section className="spectral-coverage-group" key={angle.angleDeg}>
                <h3>{angle.angleDeg}°</h3>
                {angle.ccds.map(ccd => (
                  <div className="spectral-coverage-angle-ccd" key={ccd.ccdIndex ?? 'unassigned'}>
                    <strong>{ccd.label} <small>已检出 {ccd.detectedCount} 条</small></strong>
                    <div className="spectral-coverage-links">
                      {ccd.lines.map(line => <LineLink key={line.id} line={line} onLocate={onLocate} />)}
                    </div>
                  </div>
                ))}
              </section>
            ))}
            <section className="spectral-coverage-group spectral-coverage-undetermined">
              <h3>未确定角位 <small>{coverage.undetermined.length} 条</small></h3>
              {coverage.undetermined.length === 0 && <p>无未确定角位的谱线</p>}
              <ul className="spectral-coverage-links">
                {coverage.undetermined.map(({ line, reason }) => (
                  <li key={line.id}><LineLink line={line} onLocate={onLocate} /><span>{reason}</span></li>
                ))}
              </ul>
            </section>
          </>
        )}
      </div>
    </details>
  )
}
