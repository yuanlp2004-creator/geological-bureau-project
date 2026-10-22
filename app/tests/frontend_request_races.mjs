import assert from 'node:assert/strict'

export async function checkRequestRaces(page, checks) {
  await page.evaluate(async () => {
    const reactModule = await import('/node_modules/.vite/deps/react.js')
    const React = reactModule.default ?? reactModule
    const clientModule = await import('/node_modules/.vite/deps/react-dom_client.js')
    const { createRoot } = clientModule.default ?? clientModule
    const { api } = await import('/src/api/index.ts')
    const { ReportsPage } = await import('/src/pages/reports/ReportsPage.tsx')
    const host = document.createElement('div')
    host.id = 'reliability-test'
    host.style.cssText = 'position:fixed;inset:0;z-index:99999;overflow:auto;background:white'
    document.body.append(host)
    const root = createRoot(host),
      originals = { ...api },
      pending = {}
    const defer = (key) =>
      new Promise((resolve) => {
        pending[key] = resolve
      })
    const reports = [1, 2].map((id) => ({
      id,
      report_number: `RACE-${id}`,
      version: 1,
      status: 'confirmed',
      source_run_ids: [],
      model: { rows: [] },
      model_sha256: 'test-hash'
    }))
    Object.assign(api, {
      analysisRuns: async () => [],
      reports: async () => reports,
      reportTemplates: async () => [],
      reportPrinters: async () => ({ printers: [] }),
      report: (_token, id) => defer(`report-${id}`),
      reportPreview: (_token, id) => defer(`preview-${id}`)
    })
    const token = sessionStorage.getItem('geospectrum.token')
    const props = { token, canWrite: true, canExecute: true, canExport: true, onToast: () => {} }
    window.__race = { api, originals, pending, defer, reports, root, host, React, props }
    root.render(React.createElement(ReportsPage, props))
  })
  const host = page.locator('#reliability-test')
  const selector = host.locator('.report-version-selector select')
  await selector.selectOption('1')
  await page.waitForFunction(() => !!window.__race.pending['report-1'])
  await selector.selectOption('2')
  await page.waitForFunction(() => !!window.__race.pending['report-2'])
  await page.evaluate(() => {
    const r = window.__race
    r.pending['report-2'](r.reports[1])
  })
  await page.evaluate(() => {
    const r = window.__race
    r.pending['report-1'](r.reports[0])
  })
  await page.waitForTimeout(50)
  assert.equal(await selector.inputValue(), '2')
  await host.getByRole('button', { name: '预览', exact: true }).click()
  await page.waitForFunction(() => !!window.__race.pending['preview-2'])
  await selector.selectOption('1')
  await page.evaluate(() => window.__race.pending['preview-2']('<p>obsolete preview</p>'))
  await page.waitForTimeout(50)
  assert.equal(await host.getByRole('dialog').count(), 0)
  assert.equal(await selector.inputValue(), '1')
  checks.push('report detail and preview ignore responses from an earlier selection')

  // 拆分报告区域后，继续从真实控件核对建立、确认、导出与打印的请求契约。
  await page.evaluate(() => {
    const r = window.__race
    r.reportCalls = []
    Object.assign(r.api, {
      analysisRuns: async () => [{ id: 11, status: 'completed', name: 'REPORT-RUN', samples: [] }],
      reportTemplates: async () => [{ id: 1, key: 'test-template', name: '测试模板', version: 1 }],
      reportPrinters: async () => ({ printers: [{ name: 'printer-test', display_name: '测试打印机', virtual: true }] }),
      createReport: async (_token, payload) => {
        r.reportCalls.push({ action: 'create', payload })
        return { ...r.reports[0], id: 3, report_number: 'CREATED', status: 'draft' }
      },
      confirmReport: async (_token, id) => {
        r.reportCalls.push({ action: 'confirm', id })
        return { ...r.reports[0], id: 3, report_number: 'CREATED', status: 'confirmed' }
      },
      exportReport: async (_token, id, payload) => {
        r.reportCalls.push({ action: 'export', id, payload })
        return { path: 'test-output' }
      }
    })
  })
  await host.getByRole('button', { name: '刷新', exact: true }).click()
  await host.getByRole('button', { name: '选择来源并建立报告', exact: true }).click()
  await host.getByRole('checkbox', { name: /REPORT-RUN/ }).check()
  await host.getByLabel('报告编号（可选）', { exact: true }).fill('ORDER-9')
  await host.getByRole('button', { name: '交换排列', exact: true }).click()
  await host.getByLabel('样品筛选', { exact: true }).fill('S1')
  await host.getByLabel('元素筛选', { exact: true }).fill('Cu')
  await host.getByRole('button', { name: '建立报告版本', exact: true }).click()
  await host.getByRole('button', { name: '确认报告', exact: true }).click()
  await page.waitForFunction(() => window.__race.reportCalls.some((call) => call.action === 'confirm'))
  await host.getByRole('button', { name: 'CSV', exact: true }).click()
  assert.equal(
    await page.evaluate(() => window.__race.reportCalls.filter((call) => call.action === 'export').length),
    0
  )
  await host.getByLabel('输出目录', { exact: true }).fill('C:\\Exports')
  await host.getByLabel('文件名', { exact: true }).fill('result')
  await host.getByRole('button', { name: 'CSV', exact: true }).click()
  await page.waitForFunction(() => window.__race.reportCalls.some((call) => call.action === 'export'))
  await host.getByLabel('输出目录', { exact: true }).fill('')
  await host.getByRole('button', { name: '打印', exact: true }).click()
  await page.waitForFunction(() => window.__race.reportCalls.filter((call) => call.action === 'export').length === 2)
  const reportCalls = await page.evaluate(() => window.__race.reportCalls)
  assert.deepEqual(reportCalls[0].payload, {
    analysis_run_ids: [11],
    template_key: 'test-template',
    report_number: 'ORDER-9',
    arrangement: 'exchange',
    table_layout: 'legacy_matrix',
    filters: { sample_name: 'S1', element: 'Cu' }
  })
  assert.equal(reportCalls[2].id, 3)
  assert.deepEqual(reportCalls[2].payload, {
    format: 'csv',
    output_directory: 'C:\\Exports',
    filename: 'result',
    printer_name: undefined,
    same_name_strategy: 'suffix'
  })
  assert.equal(reportCalls[3].payload.printer_name, 'printer-test')
  assert.equal(reportCalls[3].payload.format, 'print')
  checks.push('report panels preserve create/confirm/export payloads, missing-directory guard and printer selection')

  await page.evaluate(async () => {
    const r = window.__race
    Object.assign(r.api, r.originals)
    const { SpectralLinesPanel } = await import('/src/pages/methods/SpectralLinesPanel.tsx')
    const a = await r.api.createMethod(r.props.token, { name: 'race-method-A' })
    const b = await r.api.createMethod(r.props.token, { name: 'race-method-B' })
    r.linesA = await r.api.methodLines(r.props.token, a.id)
    r.linesB = await r.api.methodLines(r.props.token, b.id)
    r.linesA.lines[0].element = 'OLD_RESPONSE'
    r.linesB.lines[0].element = 'NEW_RESPONSE'
    r.api.methodLines = (_token, id) => r.defer(`lines-${id}`)
    r.methodA = a.id
    r.methodB = b.id
    r.mountMethod = (id) =>
      r.root.render(r.React.createElement(SpectralLinesPanel, { ...r.props, methodId: id, onChanged: async () => {} }))
    r.mountMethod(a.id)
  })
  await page.waitForFunction(() => !!window.__race.pending[`lines-${window.__race.methodA}`])
  await page.evaluate(() => window.__race.mountMethod(window.__race.methodB))
  await page.waitForFunction(() => !!window.__race.pending[`lines-${window.__race.methodB}`])
  await page.evaluate(() => {
    const r = window.__race
    r.pending[`lines-${r.methodB}`](r.linesB)
  })
  await host.locator('strong[title^="NEW_RESPONSE"]').waitFor()
  await page.evaluate(() => {
    const r = window.__race
    r.pending[`lines-${r.methodA}`](r.linesA)
  })
  await page.waitForTimeout(50)
  assert.equal(await host.locator('strong[title^="OLD_RESPONSE"]').count(), 0)
  checks.push('method switch ignores the previous method line response')

  await page.evaluate(async () => {
    const r = window.__race
    Object.assign(r.api, r.originals)
    const { EvaporationAcquisitionPage } = await import('/src/pages/acquisition/EvaporationAcquisitionPage.tsx')
    const a = await r.api.createAcquisitionTask(r.props.token, {
      task_kind: 'evaporation',
      name: 'RACE-TASK-A',
      burn_frame_count: 3,
      pre_excitation_seconds: 0
    })
    const b = await r.api.createAcquisitionTask(r.props.token, {
      task_kind: 'evaporation',
      name: 'RACE-TASK-B',
      burn_frame_count: 3,
      pre_excitation_seconds: 0
    })
    r.taskA = await r.api.startAcquisitionTask(r.props.token, a.id)
    r.taskB = b
    r.api.acquisitionTasks = async () => [r.taskA, r.taskB]
    r.api.acquisitionTask = async (_token, id) => id === r.taskA.id ? r.taskA : r.taskB
    r.api.stepAcquisitionTask = (_token, id) => r.defer(`step-${id}`)
    r.root.render(r.React.createElement(EvaporationAcquisitionPage, r.props))
  })
  await host.getByRole('button', { name: /RACE-TASK-B/ }).waitFor()
  // The current workbench keeps the running task selected until its command settles.
  await host.getByRole('button', { name: /单步/ }).click()
  await page.waitForFunction(() => !!window.__race.pending[`step-${window.__race.taskA.id}`])
  assert.equal(await host.getByRole('button', { name: /RACE-TASK-B/ }).isDisabled(), true)
  await page.evaluate(() => {
    const r = window.__race
    r.taskA = { ...r.taskA, status: 'completed', completed_repeats: 1 }
    r.pending[`step-${r.taskA.id}`](r.taskA)
  })
  await host.getByRole('button', { name: /RACE-TASK-B/ }).click()
  assert.match(await host.locator('button.active').filter({ hasText: 'RACE-TASK-B' }).innerText(), /RACE-TASK-B/)
  checks.push('manual acquisition locks task selection in flight and unlocks after completion')
  await page.evaluate(async () => {
    const r = window.__race
    delete r.pending[`step-${r.taskA.id}`]
    r.taskA = await r.originals.acquisitionTask(r.props.token, r.taskA.id)
    const { EvaporationAcquisitionPage } = await import('/src/pages/acquisition/EvaporationAcquisitionPage.tsx')
    r.root.render(r.React.createElement(EvaporationAcquisitionPage, { ...r.props, key: 'automatic-race' }))
  })
  await host.getByRole('button', { name: /RACE-TASK-A/ }).click()
  await host.getByRole('button', { name: '连续采集', exact: true }).click()
  await page.waitForFunction(() => !!window.__race.pending[`step-${window.__race.taskA.id}`])
  assert.equal(await host.getByRole('button', { name: /RACE-TASK-B/ }).isDisabled(), true)
  await page.evaluate(() => {
    const r = window.__race
    r.taskA = { ...r.taskA, status: 'completed', completed_repeats: 1 }
    r.pending[`step-${r.taskA.id}`](r.taskA)
  })
  await host.getByRole('button', { name: /RACE-TASK-B/ }).click()
  assert.equal(await host.locator('button.active').filter({ hasText: 'RACE-TASK-B' }).count(), 1)
  assert.equal(await host.getByRole('button', { name: '停止连续', exact: true }).count(), 0)
  checks.push('automatic acquisition locks selection until completion, stops its timer and allows the next task')
  await page.evaluate(() => {
    const r = window.__race
    r.root.unmount()
    Object.assign(r.api, r.originals)
    r.host.remove()
    delete window.__race
  })
}
