import type { CcdLayoutOption, DispersionOption, MethodConditions, SpectralLine } from '../../api/methods'

export type SpectralLineFilters = {
  query: string
  lineType: 'all' | SpectralLine['line_type']
  ccdFilter: 'all' | 'unassigned' | `${number}`
  angleFilter: 'all' | 'undetermined' | `${number}`
  statusFilter: 'all' | 'undetectable' | 'disabled' | 'attention'
}

export const defaultSpectralLineFilters: SpectralLineFilters = {
  query: '', lineType: 'all', ccdFilter: 'all', angleFilter: 'all', statusFilter: 'all'
}

const isUndetectable = (line: SpectralLine) => !line.detectability?.detectable

function matchesQuery(line: SpectralLine, query: string) {
  if (!query) return true
  return line.element.toLowerCase().includes(query) || line.id.toLowerCase().includes(query) ||
    [line.wavelength_nm, line.actual_wavelength_nm].some(value => value != null && (
      String(value).includes(query) || value.toFixed(4).includes(query)
    ))
}

function matchingFilters(line: SpectralLine, filters: SpectralLineFilters, query: string) {
  const ccd = line.detectability?.ccd_index
  const angle = line.detectability?.angle_deg
  return {
    query: matchesQuery(line, query),
    lineType: filters.lineType === 'all' || line.line_type === filters.lineType,
    ccdFilter: filters.ccdFilter === 'all' || (ccd == null ? 'unassigned' : String(ccd)) === filters.ccdFilter,
    angleFilter: filters.angleFilter === 'all' || (angle == null ? 'undetermined' : String(angle)) === filters.angleFilter,
    statusFilter: filters.statusFilter === 'all' ||
      (filters.statusFilter !== 'disabled' && isUndetectable(line)) ||
      (filters.statusFilter !== 'undetectable' && !line.enabled)
  }
}

export function filterSpectralLines(lines: readonly SpectralLine[], filters: SpectralLineFilters) {
  const query = filters.query.trim().toLowerCase()
  return lines.filter(line => Object.values(matchingFilters(line, filters, query)).every(Boolean))
}

export function locateSpectralLine(lines: readonly SpectralLine[], id: string, filters: SpectralLineFilters) {
  const line = lines.find(line => line.id === id)
  if (!line) return null
  const matches = matchingFilters(line, filters, filters.query.trim().toLowerCase())
  const visibleFilters = { ...filters }
  for (const key of Object.keys(matches) as Array<keyof SpectralLineFilters>) {
    if (!matches[key]) Object.assign(visibleFilters, { [key]: defaultSpectralLineFilters[key] })
  }
  return { line, filters: visibleFilters }
}

function wavelengthRange(lines: readonly SpectralLine[]): [number, number] | null {
  if (!lines.length) return null
  const wavelengths = lines.map(line => line.wavelength_nm)
  return [Math.min(...wavelengths), Math.max(...wavelengths)]
}

export function buildBatchPreviewSummary(
  lines: readonly SpectralLine[], visibleLines: readonly SpectralLine[], batchSelectedIds: ReadonlySet<string>
) {
  const selected = lines.filter(line => batchSelectedIds.has(line.id))
  const visibleIds = new Set(visibleLines.map(line => line.id))
  const offList = selected.filter(line => !visibleIds.has(line.id))
  const byType = { baseline: 0, analysis: 0, internal_standard: 0, positioning: 0 }
  for (const line of selected) byType[line.line_type]++
  const enabledCount = selected.filter(line => line.enabled).length
  const undetectableCount = selected.filter(isUndetectable).length
  return {
    totalCount: selected.length,
    offListCount: offList.length,
    byType,
    enabledCount,
    disabledCount: selected.length - enabledCount,
    detectableCount: selected.length - undetectableCount,
    undetectableCount,
    wavelengthRange: wavelengthRange(selected),
    offListElements: [...new Set(offList.map(line => line.element))].sort(),
    offListWavelengthRange: wavelengthRange(offList)
  }
}

export function ccdLabel(layout: CcdLayoutOption | null | undefined, index: number | null) {
  if (index == null) return '未分配 CCD'
  return layout?.ccd_labels[layout.ccd_indices.indexOf(index)] || `CCD${index + 1}`
}

export function lineDetectionReason(line: SpectralLine) {
  return line.detectability?.message || line.detectability?.reason_code
}

export function buildCcdCoverageSummary({ lines, conditions, calibration, ccdLayout }: {
  lines: readonly SpectralLine[]
  conditions: Pick<MethodConditions, 'angle_exposures' | 'selected_ccds'>
  calibration?: DispersionOption | null
  ccdLayout?: CcdLayoutOption | null
}) {
  if (conditions.angle_exposures.length <= 1) {
    const bands = conditions.selected_ccds.map(ccdIndex => {
      const range = calibration?.ccd_ranges.find(item => item.ccd_index === ccdIndex)
      const detected = lines.filter(line => line.detectability?.detectable && line.detectability.ccd_index === ccdIndex)
      return {
        ccdIndex,
        label: ccdLabel(ccdLayout, ccdIndex),
        physicalRange: range ? [range.wavelength_start_nm, range.wavelength_end_nm] as [number, number] : null,
        safeRange: range ? [range.safe_start_nm, range.safe_end_nm] as [number, number] : null,
        missingCalibration: !range,
        detectedCount: detected.length,
        lines: detected
      }
    })
    return { mode: 'single' as const, bands }
  }

  const byAngle = new Map<number, Map<number | null, SpectralLine[]>>()
  const undetermined: Array<{ line: SpectralLine; reason: string }> = []
  for (const line of lines) {
    const detection = line.detectability
    if (!detection?.detectable || detection.angle_deg == null) {
      undetermined.push({ line, reason: lineDetectionReason(line) || '暂无角位信息' })
      continue
    }
    const ccdIndex = detection.ccd_index ?? null
    const ccds = byAngle.get(detection.angle_deg) ?? new Map<number | null, SpectralLine[]>()
    const detected = ccds.get(ccdIndex) ?? []
    detected.push(line)
    ccds.set(ccdIndex, detected)
    byAngle.set(detection.angle_deg, ccds)
  }
  const angles = [...byAngle.entries()].sort(([a], [b]) => a - b).map(([angleDeg, ccds]) => ({
    angleDeg,
    ccds: [...ccds.entries()].sort(([a], [b]) => (a ?? Infinity) - (b ?? Infinity)).map(([ccdIndex, detected]) => ({
      ccdIndex, label: ccdLabel(ccdLayout, ccdIndex), detectedCount: detected.length, lines: detected
    }))
  }))
  return { mode: 'multi' as const, angles, undetermined }
}
