import assert from 'node:assert/strict'
import test from 'node:test'
import {
  buildBatchPreviewSummary, buildCcdCoverageSummary, defaultSpectralLineFilters, filterSpectralLines, locateSpectralLine
} from '../frontend/src/pages/methods/spectralLineFilters.ts'

const detected = (ccd_index, angle_deg) => ({ detectable: true, ccd_index, angle_deg })
const lines = Object.freeze([
  { id: 'base', line_type: 'baseline', element: 'Fe', wavelength_nm: 250, enabled: true, detectability: detected(0, 0) },
  { id: 'al-a', line_type: 'analysis', element: 'Al', wavelength_nm: 252.737748, actual_wavelength_nm: 252.7398, enabled: true, detectability: detected(0, 17) },
  { id: 'al-b', line_type: 'analysis', element: 'Al', wavelength_nm: 252.737748, enabled: false, detectability: detected(1, 4) },
  { id: 'is', line_type: 'internal_standard', element: 'Ge', wavelength_nm: 270.9626, enabled: true, detectability: detected(1, 4) },
  { id: 'pos', line_type: 'positioning', element: 'Mn', wavelength_nm: 310, enabled: true, detectability: { detectable: false, ccd_index: 0, angle_deg: 4, message: '角位关联有歧义', reason_code: 'ambiguous' } },
  { id: 'far', line_type: 'analysis', element: 'Cu', wavelength_nm: 400, enabled: false, detectability: { detectable: false, reason_code: 'out_of_range' } },
  { id: 'unknown-angle', line_type: 'positioning', element: 'Si', wavelength_nm: 375, enabled: true, detectability: detected(5, null) },
  { id: 'unknown-detection', line_type: 'internal_standard', element: 'Ni', wavelength_nm: 410, enabled: true }
].map(line => Object.freeze({ ...line, detectability: line.detectability && Object.freeze(line.detectability) })))

const filters = overrides => ({ ...defaultSpectralLineFilters, ...overrides })
const ids = records => records.map(line => line.id)
const search = overrides => ids(filterSpectralLines(lines, filters(overrides)))

test('searches elements, IDs and exact or displayed theoretical and actual wavelengths', () => {
  assert.deepEqual(search({ query: '  aL  ' }), ['al-a', 'al-b'])
  assert.deepEqual(search({ query: 'AL-B' }), ['al-b'])
  assert.deepEqual(search({ query: '252.737748' }), ['al-a', 'al-b'])
  assert.deepEqual(search({ query: '252.7377' }), ['al-a', 'al-b'])
  assert.deepEqual(search({ query: '252.7398' }), ['al-a'])
  assert.deepEqual(search({ query: '不存在' }), [])
})

test('combines the four real line types with CCD, angle and status filters', () => {
  assert.deepEqual(search({ query: 'FE', lineType: 'baseline', ccdFilter: '0', angleFilter: '0' }), ['base'])
  assert.deepEqual(search({ query: 'al', lineType: 'analysis', ccdFilter: '1', angleFilter: '4', statusFilter: 'disabled' }), ['al-b'])
  assert.deepEqual(search({ query: 'ge', lineType: 'internal_standard', ccdFilter: '1', angleFilter: '4' }), ['is'])
  assert.deepEqual(search({ query: 'mn', lineType: 'positioning', ccdFilter: '0', angleFilter: '4', statusFilter: 'undetectable' }), ['pos'])
  assert.deepEqual(search({ ccdFilter: 'unassigned', angleFilter: 'undetermined', statusFilter: 'attention' }), ['far', 'unknown-detection'])
  assert.deepEqual(search({ angleFilter: 'undetermined' }), ['far', 'unknown-angle', 'unknown-detection'])
  assert.deepEqual(search({ statusFilter: 'attention' }), ['al-b', 'pos', 'far', 'unknown-detection'])
  assert.deepEqual(search({ statusFilter: 'undetectable' }), ['pos', 'far', 'unknown-detection'])
  assert.deepEqual(search({ statusFilter: 'disabled' }), ['al-b', 'far'])
})

test('batch preview counts only checked IDs, includes hidden selections and performs no writes', t => {
  const request = t.mock.method(globalThis, 'fetch', () => { throw new Error('Batch preview attempted a request') })
  const before = structuredClone(lines)
  const selectedId = 'is'
  const batchSelectedIds = new Set(['base', 'al-b', 'pos', 'unknown-detection', 'removed'])
  assert.equal(batchSelectedIds.has(selectedId), false)
  const visible = filterSpectralLines(lines, filters({ ccdFilter: '1', angleFilter: '4' }))
  assert.ok(ids(visible).includes(selectedId))
  assert.deepEqual(buildBatchPreviewSummary(lines, visible, batchSelectedIds), {
    totalCount: 4,
    offListCount: 3,
    byType: { baseline: 1, analysis: 1, internal_standard: 1, positioning: 1 },
    enabledCount: 3,
    disabledCount: 1,
    detectableCount: 2,
    undetectableCount: 2,
    wavelengthRange: [250, 410],
    offListElements: ['Fe', 'Mn', 'Ni'],
    offListWavelengthRange: [250, 410]
  })
  const cleared = buildBatchPreviewSummary(lines, visible, new Set())
  assert.equal(cleared.totalCount, 0)
  assert.equal(cleared.wavelengthRange, null)
  assert.equal(cleared.offListWavelengthRange, null)
  const partiallyVisible = buildBatchPreviewSummary(lines, visible, new Set(['al-b', 'pos']))
  assert.deepEqual(partiallyVisible.wavelengthRange, [252.737748, 310])
  assert.deepEqual(partiallyVisible.offListWavelengthRange, [310, 310])
  assert.deepEqual([...batchSelectedIds], ['base', 'al-b', 'pos', 'unknown-detection', 'removed'])
  assert.deepEqual(lines, before)
  assert.equal(request.mock.callCount(), 0)
})

const layout = { ccd_indices: [5, 0, 1], ccd_labels: ['长波 CCD', '中央 CCD', '短波 CCD'] }
const calibration = { ccd_ranges: [
  { ccd_index: 0, wavelength_start_nm: 228, wavelength_end_nm: 280, safe_start_nm: 230, safe_end_nm: 278 },
  { ccd_index: 1, wavelength_start_nm: 240, wavelength_end_nm: 300, safe_start_nm: 242, safe_end_nm: 297 }
] }

test('single angle coverage uses selected CCD labels, physical/safe bands and explicit missing calibration', () => {
  const getCoverage = angle_exposures => buildCcdCoverageSummary({
    lines, conditions: { selected_ccds: [0, 5], angle_exposures }, calibration, ccdLayout: layout
  })
  const result = getCoverage([{ angle_deg: 0 }])
  assert.equal(result.mode, 'single')
  assert.deepEqual(result.bands.map(band => ({ ...band, lines: ids(band.lines) })), [
    { ccdIndex: 0, label: '中央 CCD', physicalRange: [228, 280], safeRange: [230, 278], missingCalibration: false, detectedCount: 2, lines: ['base', 'al-a'] },
    { ccdIndex: 5, label: '长波 CCD', physicalRange: null, safeRange: null, missingCalibration: true, detectedCount: 1, lines: ['unknown-angle'] }
  ])
  assert.deepEqual(getCoverage([]), result)
})

test('multi-angle coverage groups actual angles, keeps unresolved reasons, and never guesses nearby angles', () => {
  const result = buildCcdCoverageSummary({
    lines, conditions: { selected_ccds: [0, 1, 5], angle_exposures: [{ angle_deg: 4 }, { angle_deg: 16 }] }, calibration, ccdLayout: layout
  })
  assert.equal(result.mode, 'multi')
  assert.deepEqual(result.angles.map(({ angleDeg, ccds }) => [angleDeg, ccds.map(ccd => [ccd.label, ccd.detectedCount, ids(ccd.lines)])]), [
    [0, [['中央 CCD', 1, ['base']]]],
    [4, [['短波 CCD', 2, ['al-b', 'is']]]],
    [17, [['中央 CCD', 1, ['al-a']]]]
  ])
  assert.deepEqual(result.undetermined.map(({ line, reason }) => [line.id, reason]), [
    ['pos', '角位关联有歧义'], ['far', 'out_of_range'], ['unknown-angle', '暂无角位信息'], ['unknown-detection', '暂无角位信息']
  ])
})

test('locates exact ID after sorting and resets only filters that hide that row', () => {
  const previous = filters({ query: 'Al', lineType: 'analysis', ccdFilter: '1', angleFilter: '4', statusFilter: 'disabled' })
  const reordered = [...lines].reverse()
  const filtered = filterSpectralLines(reordered, previous)
  assert.deepEqual(ids(filtered), ['al-b'])
  assert.equal(locateSpectralLine(filtered, 'al-a', previous), null)
  const located = locateSpectralLine(reordered, 'al-a', previous)
  assert.equal(located.line, lines[1])
  assert.deepEqual(located.filters, filters({ query: 'Al', lineType: 'analysis' }))
  assert.equal(filterSpectralLines(reordered, located.filters).find(line => line.id === 'al-a'), lines[1])
  assert.equal(previous.angleFilter, '4')
  assert.deepEqual(locateSpectralLine(reordered, 'al-b', previous).filters, previous)
  assert.equal(locateSpectralLine(reordered, 'unknown', previous), null)
})
