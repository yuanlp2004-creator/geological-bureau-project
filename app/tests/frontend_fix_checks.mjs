import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import path from 'node:path'

export async function checkFixes(page, checks) {
  await page.evaluate(async () => {
    const React = (await import('/node_modules/.vite/deps/react.js')).default
    const { createRoot } = (await import('/node_modules/.vite/deps/react-dom_client.js')).default
    const { api } = await import('/src/api/index.ts')
    const host = document.createElement('div')
    host.id = 'fix-checks'
    host.style.cssText = 'position:fixed;inset:0;background:white;z-index:999999;overflow:auto'
    document.body.append(host)
    const root = createRoot(host),
      originals = { ...api },
      token = sessionStorage.getItem('geospectrum.token')
    window.__fix = { React, root, host, api, originals, token, toasts: [], pending: [] }
    const { AnalysisPage } = await import('/src/pages/analysis/AnalysisPage.tsx')
    const base = {
      status: 'draft',
      samples: [],
      line_results: [],
      quality: { latest_snapshot: null, decisions: [] },
      curves: { lines: [], results: [], merges: [], actions: [], print_jobs: [] },
      input_sha256: 'hash',
      method_name: 'method',
      method_version: 1,
      calculation_profile: 'modern_v1',
      messages: []
    }
    const a = { ...base, id: 9001, name: 'FIX-A' },
      b = { ...base, id: 9002, name: 'FIX-B' }
    window.__fix.a = a
    window.__fix.b = b
    api.analysisRuns = async () => [a, b]
    api.analysisOptions = async () => ({ profiles: [], samples: [], method_versions: [] })
    api.analysisRun = async (_t, id) => (id === a.id ? a : b)
    root.render(
      React.createElement(AnalysisPage, {
        token,
        initialView: 'raw',
        onViewChange: () => {},
        canExecute: true,
        canIntervene: true,
        canQuality: true,
        canCurve: true,
        canPrint: true,
        onToast: (m) => window.__fix.toasts.push(m)
      })
    )
  })
  const host = page.locator('#fix-checks')
  await host.locator('.analysis-detail h2').filter({ hasText: 'FIX-A' }).waitFor()
  await page.evaluate(() => {
    const r = window.__fix
    r.api.analysisRun = (_t, id) => new Promise((resolve, reject) => r.pending.push({ id, resolve, reject }))
  })
  await host.locator('.analysis-run-list button').filter({ hasText: 'FIX-A' }).click()
  await host.locator('.analysis-run-list button').filter({ hasText: 'FIX-B' }).click()
  await page.evaluate(() => {
    const r = window.__fix
    r.pending[1].resolve(r.b)
    r.pending[0].resolve(r.a)
  })
  await host.locator('.analysis-detail h2').filter({ hasText: 'FIX-B' }).waitFor()
  await host.locator('.analysis-run-list button').filter({ hasText: 'FIX-A' }).click()
  await host.locator('.analysis-run-list button').filter({ hasText: 'FIX-B' }).click()
  await host.locator('.analysis-run-list button').filter({ hasText: 'FIX-A' }).click()
  await page.evaluate(() => {
    const r = window.__fix
    r.pending[4].resolve({ ...r.a, name: 'FIX-A-current' })
    r.pending[2].resolve({ ...r.a, name: 'STALE-A' })
    r.pending[3].reject(new Error('OLD-ERROR'))
  })
  await host.locator('.analysis-detail h2').filter({ hasText: 'FIX-A-current' }).waitFor()
  assert.equal(await page.evaluate(() => window.__fix.toasts.includes('OLD-ERROR')), false)
  await page.evaluate(() => {
    const r = window.__fix
    r.steps = 0
    r.api.startAnalysisRun = async () => ({ ...r.a, status: 'running', slow_mode: false })
    r.api.stepAnalysisRun = async () => ({
      ...r.a,
      status: ++r.steps === 3 ? 'completed' : 'running',
      slow_mode: false
    })
  })
  await host.getByRole('button', { name: '开始', exact: true }).click()
  await host.locator('.analysis-status').filter({ hasText: '已完成' }).waitFor()
  assert.equal(await page.evaluate(() => window.__fix.steps), 3)
  checks.push('FIX-07/GAP-03: analysis A/B and A/B/A response ownership, old errors, sequential non-slow completion')
  await page.evaluate(() => {
    const r = window.__fix
    r.steps = 0
    r.api.analysisRun = async () => r.a
    r.api.startAnalysisRun = async () => ({ ...r.a, status: 'running', slow_mode: true })
  })
  await host.locator('.analysis-run-list button').filter({ hasText: 'FIX-A' }).click()
  await host.getByRole('button', { name: '开始', exact: true }).click()
  await host.getByRole('button', { name: '推进一条谱线', exact: true }).waitFor()
  assert.equal(await page.evaluate(() => window.__fix.steps), 0)
  await page.evaluate(() => {
    const r = window.__fix
    r.api.analysisRun = () => new Promise((_resolve, reject) => (r.unmountedReject = reject))
  })
  await host.locator('.analysis-run-list button').filter({ hasText: 'FIX-B' }).click()
  await page.evaluate(() => window.__fix.root.render(null))
  await host.locator('.analysis-page').waitFor({ state: 'detached' })
  await page.evaluate(() => window.__fix.unmountedReject(new Error('UNMOUNTED-ERROR')))
  assert.equal(await page.evaluate(() => window.__fix.toasts.includes('UNMOUNTED-ERROR')), false)
  checks.push('FIX-07/GAP-03: slow mode does not auto-step; rejected request after unmount cannot display an old error')

  await page.evaluate(async () => {
    const r = window.__fix
    r.root.render(null)
    Object.assign(r.api, r.originals)
    const { DispersionPage } = await import('/src/pages/dispersion/DispersionPage.tsx')
    r.da = await r.api.createDispersionTask(r.token, {
      name: 'FIX-DISP-A',
      frame_count: 10,
      dark_frame_count: 1,
      pre_excitation_seconds: 0
    })
    r.db = await r.api.createDispersionTask(r.token, {
      name: 'FIX-DISP-B',
      frame_count: 10,
      dark_frame_count: 1,
      pre_excitation_seconds: 0
    })
    r.root.render(
      r.React.createElement(DispersionPage, {
        token: r.token,
        canWrite: true,
        canExecute: true,
        onToast: (m) => r.toasts.push(m)
      })
    )
  })
  await host.locator('.dispersion-task-list button').filter({ hasText: 'FIX-DISP-A' }).click()
  await host.getByRole('button', { name: '添加', exact: true }).click()
  await host.locator('.dispersion-line-table tbody tr').first().waitFor()
  await host.locator('.dispersion-task-list button').filter({ hasText: 'FIX-DISP-B' }).click()
  await host.locator('.dispersion-task-list button').filter({ hasText: 'FIX-DISP-A' }).click()
  await host.locator('.dispersion-line-table tbody tr').first().waitFor()
  await page.evaluate(() => {
    const r = window.__fix
    r.stopCalls = 0
    r.api.stepDispersionTask = () => new Promise((resolve) => (r.releaseStep = resolve))
    r.api.stopDispersionTask = (...args) => {
      r.stopCalls++
      return r.originals.stopDispersionTask(...args)
    }
  })
  await host.getByRole('button', { name: '开始', exact: true }).click()
  await page.waitForFunction(() => !!window.__fix.releaseStep)
  await host.getByRole('button', { name: '停止', exact: true }).click()
  assert.equal(await page.evaluate(() => window.__fix.stopCalls), 0)
  await page.evaluate(async () => {
    const r = window.__fix
    r.releaseStep(await r.originals.dispersionTask(r.token, r.da.id))
  })
  await page.waitForFunction(() => window.__fix.stopCalls === 1)
  await host.locator('.dispersion-run-panel .state-chip').filter({ hasText: '已停止' }).waitFor()
  checks.push(
    'FIX-04: real dispersion line survives task switch; stop queues behind pending frame and stops automatic progression'
  )

  await page.evaluate(async () => {
    const r = window.__fix
    Object.assign(r.api, r.originals)
    let task = await r.api.createDispersionTask(r.token, {
      name: 'GAP-PLOT',
      frame_count: 1,
      dark_frame_count: 0,
      pre_excitation_seconds: 0
    })
    r.plotLine = await r.api.addDispersionLine(r.token, task.id, { element: 'Fe', wavelength_nm: 260, ccd_index: 0 })
    task = await r.api.startDispersionTask(r.token, task.id)
    for (let index = 0; index < 8 && task.status !== 'completed'; index++)
      task = await r.api.stepDispersionTask(r.token, task.id)
    r.plotTask = task
  })
  await host.getByRole('button', { name: '刷新', exact: true }).click()
  await host.locator('.dispersion-task-list button').filter({ hasText: 'GAP-PLOT' }).click()
  const svg = host.locator('.dispersion-spectrum-view svg')
  await svg.waitFor()
  await host.getByRole('button', { name: '横向放大', exact: true }).click()
  const bounds = await svg.boundingBox()
  await svg.click({ position: { x: bounds.width * 0.75, y: bounds.height * 0.5 } })
  await host.getByLabel('人工定位谱线').selectOption(String(await page.evaluate(() => window.__fix.plotLine.id)))
  const picked = await host.locator('.inspector-readout output').textContent()
  const point = Number(picked.match(/点位 (\d+)/)[1])
  await host.getByRole('button', { name: '横向放大', exact: true }).click()
  await host.getByRole('button', { name: '采用锁定点位', exact: true }).click()
  await page.waitForFunction(async (point) => {
    const r = window.__fix
    const task = await r.originals.dispersionTask(r.token, r.plotTask.id)
    return task.lines[0].located_position === point
  }, point)
  checks.push(
    'GAP-04: actual CCD point selected after zoom, further zoom preserves locked point, saved backend position matches pixel mapping'
  )

  await page.evaluate(async () => {
    const r = window.__fix
    r.root.render(null)
    Object.assign(r.api, r.originals)
    const { SpectralLinesPanel } = await import('/src/pages/methods/SpectralLinesPanel.tsx')
    const method = await r.api.createMethod(r.token, { name: 'FIX-DRAFT' })
    r.api.createLine = async () => {
      throw new Error('FIX-SAVE-FAILED')
    }
    r.root.render(
      r.React.createElement(SpectralLinesPanel, {
        token: r.token,
        methodId: method.id,
        canWrite: true,
        onChanged: async () => {},
        onToast: (m) => r.toasts.push(m)
      })
    )
  })
  await host.locator('.spectral-line-card').first().waitFor()
  await host.getByRole('button', { name: '添加谱线', exact: true }).click()
  await host.getByLabel('理论波长 (nm)', { exact: true }).fill('260.1234')
  await host.getByRole('button', { name: '添加谱线', exact: true }).last().click()
  await host.getByText('FIX-SAVE-FAILED', { exact: true }).waitFor()
  assert.equal(await host.getByRole('heading', { name: '添加谱线', exact: true }).count(), 1)
  assert.equal(await host.getByLabel('理论波长 (nm)', { exact: true }).inputValue(), '260.1234')
  await page.evaluate(() => Object.assign(window.__fix.api, { createLine: window.__fix.originals.createLine }))
  await host.getByRole('button', { name: '添加谱线', exact: true }).last().click()
  await host.locator('.spectral-line-card.active').filter({ hasText: '260.1234' }).waitFor()
  checks.push('FIX-07: 260.1234 nm creation failure retains draft, retry selects newly created line')
  await page.evaluate(async () => {
    const r = window.__fix
    r.root.render(null)
    Object.assign(r.api, r.originals)
    const { SpectrumViewerPage } = await import('/src/pages/spectra/SpectrumViewerPage.tsx')
    let task = await r.api.createAcquisitionTask(r.token, {
      task_kind: 'sample',
      name: 'FIX-SPECTRUM',
      sample_name: 'NEWVIEW',
      burn_frame_count: 1,
      dark_frame_count: 0,
      pre_excitation_seconds: 0,
      countdown_seconds: 0,
      seed: 77,
      storage_mode: 'full_interval'
    })
    task = await r.api.startAcquisitionTask(r.token, task.id)
    for (let index = 0; index < 15 && task.status !== 'completed'; index++)
      task = await r.api.stepAcquisitionTask(r.token, task.id)
    if (task.status !== 'completed') throw new Error('new viewer capture did not finish')
    r.sampleRecord = await r.api.spectrum(r.token, `sample:${task.samples[0].id}`)
    r.root.render(r.React.createElement(SpectrumViewerPage, { token: r.token, onToast: (m) => r.toasts.push(m) }))
  })
  await host.getByLabel('谱图来源').selectOption('sample')
  await host.locator('.spectrum-record-row button').filter({ hasText: 'NEWVIEW' }).click()
  await host.locator('.spectrum-facts').filter({ hasText: 'NEWVIEW' }).waitFor()
  const csvDownload = page.waitForEvent('download')
  await host.getByRole('button', { name: '导出可见范围', exact: true }).click()
  const csv = await readFile(await (await csvDownload).path(), 'utf8')
  const csvRows = csv
    .trim()
    .split(/\r?\n/)
    .map((row) => row.split(','))
  const values = await page.evaluate(() => window.__fix.sampleRecord.ccd.points.map((point) => point.value))
  assert.equal(csvRows.length - 1, values.length)
  assert.equal(Number(csvRows[1][4]), values[0])
  const pdfDownload = page.waitForEvent('download')
  await host.getByRole('button', { name: '打印 PDF', exact: true }).click()
  assert.equal((await readFile(await (await pdfDownload).path())).subarray(0, 5).toString(), '%PDF-')
  if (process.env.API_BROWSER_OUTPUT)
    await host.screenshot({ path: path.join(process.env.API_BROWSER_OUTPUT, 'fixes-spectra.png') })
  checks.push(
    'FIX-06: actual simulated sample is visible in generic spectrum page; CSV point count/value and PDF download verified'
  )
  await page.evaluate(() => {
    const r = window.__fix
    r.root.unmount()
    Object.assign(r.api, r.originals)
    r.host.remove()
    delete window.__fix
  })
}
