import assert from 'node:assert/strict'
import path from 'node:path'
import { call, navigate } from './contract_browser_support.mjs'

export async function checkAnalysisWorkspace(page, fixture, result, output) {
  const check = (message) => { result.checks.push(message); console.log(`PASS: ${message}`) }
  const entries = (await call(page, '/api/v1/capabilities')).capabilities.flatMap(item => item.navigation_entries)
  assert.deepEqual(entries.filter(entry => entry.page === 'analysis').map(entry => entry.label), ['样品分析'])
  await call(page, '/api/v1/methods/current', { method_id: fixture.method_id })
  await page.reload(); await page.getByTestId('workspace').waitFor()
  const emptyRuns = /\/api\/v1\/analyses\/runs$/
  const emptyList = route => route.request().method() === 'GET'
    ? route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }) : route.continue()
  await page.route(emptyRuns, emptyList)
  await navigate(page, 'analysis-tests', '样品分析', '.analysis-page')
  const preparation = page.locator('.analysis-preparing')
  await preparation.getByRole('heading', { name: '准备分析', exact: true }).waitFor()
  await preparation.locator('.analysis-sample-groups input').first().waitFor()
  assert.equal(await preparation.locator('.analysis-sidebar').isVisible(), false)
  result.preparationLayouts = []
  for (const [width, height, theme] of [[1440, 1000, 'light'], [1060, 1000, 'dark'], [1060, 680, 'light']]) {
    await call(page, '/api/v1/settings', { display: { theme, density: 'comfortable' } }, 'PATCH')
    await page.getByRole('button', { name: '刷新服务状态', exact: true }).click()
    if (process.env.QA_CDP) await page.evaluate(({ width, height }) => window.__TAURI__.core.invoke('plugin:window|set_size', { value: { Logical: { width, height } } }), { width, height })
    else await page.setViewportSize({ width, height })
    await preparation.locator('.analysis-create-footer button').scrollIntoViewIfNeeded()
    const layout = await preparation.evaluate(element => {
      const form = element.querySelector('.analysis-create'), body = form.closest('.disclosure-body'), button = form.querySelector('button[type="submit"]').getBoundingClientRect()
      return { width: innerWidth, height: innerHeight, documentWidth: document.documentElement.scrollWidth, formWidth: form.getBoundingClientRect().width,
        position: getComputedStyle(body).position, buttonTop: button.top, buttonBottom: button.bottom }
    })
    assert.equal(layout.position, 'static')
    assert.ok(layout.documentWidth <= layout.width + 1 && layout.formWidth > 500, JSON.stringify(layout))
    assert.ok(layout.buttonTop >= 0 && layout.buttonBottom <= layout.height + 1, JSON.stringify(layout))
    await preparation.scrollIntoViewIfNeeded()
    const file = `analysis-preparation-${width}-${height}-${theme}.png`
    await preparation.screenshot({ path: path.join(output, file) })
    result.preparationLayouts.push({ file, ...layout })
  }
  const sourceOptions = await call(page, '/api/v1/analyses/options')
  const storedSource = sourceOptions.samples.find(item => item.id === fixture.sample_id)
  const optionsUrl = /\/api\/v1\/analyses\/options$/
  let visibleSources = [{ ...storedSource, sample_name: '' }]
  const showOptions = route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ...sourceOptions, samples: visibleSources }) })
  await page.route(optionsUrl, showOptions)
  const reloadPreparation = async () => {
    await page.reload(); await page.getByTestId('workspace').waitFor()
    await navigate(page, 'analysis-tests', '样品分析', '.analysis-page')
    await preparation.getByRole('heading', { name: '准备分析', exact: true }).waitFor()
  }
  await reloadPreparation()
  await preparation.getByText(`未命名样品 #${storedSource.id}`, { exact: true }).waitFor()
  await preparation.screenshot({ path: path.join(output, 'analysis-preparation-single.png') })
  visibleSources = []
  await reloadPreparation()
  await preparation.getByText('暂无已完成采集的样品，请先完成样品摄谱。', { exact: true }).waitFor()
  await preparation.getByRole('button', { name: '建立并锁定输入', exact: true }).click()
  await preparation.getByRole('alert').filter({ hasText: '请至少选择一个已完成采集样品' }).waitFor()
  await preparation.screenshot({ path: path.join(output, 'analysis-preparation-empty.png') })
  await page.unroute(optionsUrl, showOptions)
  await reloadPreparation()
  await preparation.locator('.analysis-sample-groups > div').filter({ has: page.getByText(storedSource.acquisition_task_name, { exact: true }) }).locator('label')
    .filter({ has: page.getByText(storedSource.sample_name, { exact: true }) })
    .filter({ hasText: `重复 ${storedSource.repeat_index + 1}` }).locator('input').check()
  await preparation.locator('.analysis-form-grid select').selectOption('legacy_2_0_2')
  assert.match(await preparation.locator('.analysis-create-footer').innerText(), /已选择 1 条采集记录/)
  await preparation.getByLabel('批次名称', { exact: true }).fill('准备页建立验证')
  const createdResponse = page.waitForResponse(item => /\/api\/v1\/analyses\/runs$/.test(item.url()) && item.request().method() === 'POST')
  await preparation.getByRole('button', { name: '建立并锁定输入', exact: true }).click()
  const created = await createdResponse
  assert.equal(created.status(), 201, await created.text())
  await page.locator('.analysis-detail').waitFor()
  await page.unroute(emptyRuns, emptyList)
  await page.reload(); await page.getByTestId('workspace').waitFor()
  await navigate(page, 'analysis-tests', '样品分析', '.analysis-page')
  await page.locator('.analysis-run-list button').first().waitFor()
  check('准备页无空白批次栏，三种窗口明暗布局正常、建立按钮可达，所选记录通过真实API建立分析')
  const host = page.locator('.analysis-page'), curve = host.locator('.analysis-review-content'), qc = host.locator('.analysis-review-qc')
  const endpoint = `/api/v1/analyses/runs/${fixture.review_run_id}`
  const response = (suffix) => page.waitForResponse(item => item.url().includes(suffix) && item.request().method() === 'POST')
  async function clickSave(button, suffix) {
    const pending = response(suffix); await button.click(); const saved = await pending
    assert.ok(saved.status() >= 200 && saved.status() < 300, `HTTP ${saved.status()}: ${(await saved.text()).slice(0, 500)}`)
    await host.locator('.analysis-run-list button:disabled').first().waitFor({ state: 'hidden' })
    return saved.json()
  }
  await host.locator('.analysis-run-list button').filter({ hasText: 'S17 完成批次' }).click()
  await host.getByLabel('重复性检查样品').waitFor()
  assert.equal(await host.getByRole('button', { name: '重复质控', exact: true }).count(), 0)
  assert.equal(await host.locator('.analysis-line-nav button').count(), 2)
  check('单一菜单入口，共用批次及两条谱线；曲线与重复性检查同时可用')
  const setup = host.locator('.analysis-setup')
  const createToggle = setup.getByRole('button', { name: '建立分析运行', exact: true })
  await createToggle.click()
  await host.locator('.analysis-create').getByLabel('批次名称', { exact: true }).fill('布局检查草稿')
  await host.screenshot({ path: path.join(output, 'analysis-create.png') })
  await setup.getByRole('button', { name: '旧 CDT/CMT 再分析', exact: true }).click()
  assert.equal(await createToggle.getAttribute('aria-expanded'), 'false')
  await createToggle.click()
  assert.equal(await host.locator('.analysis-create').getByLabel('批次名称', { exact: true }).inputValue(), '布局检查草稿')
  await createToggle.click()
  check('建立分析与旧数据面板互斥展开，折叠和切换保留表单草稿')

  const original = await call(page, endpoint)
  const originalHash = original.result_sha256
  await qc.locator('.qc-members tbody tr').nth(2).waitFor()
  const excluded = await clickSave(qc.getByRole('button', { name: '剔除', exact: true }).first(), '/quality/decisions')
  let group = excluded.quality.latest_snapshot.groups.find(item => item.line_id === 'L1' && item.sample_name === 'S1')
  assert.equal(group.statistics.effective_count, 2)
  const restored = await clickSave(qc.getByRole('button', { name: '恢复', exact: true }), '/quality/decisions')
  group = restored.quality.latest_snapshot.groups.find(item => item.line_id === 'L1' && item.sample_name === 'S1')
  assert.equal(group.statistics.effective_count, 3)
  await clickSave(qc.getByRole('button', { name: '接受提示', exact: true }), '/quality/decisions')
  check('当前样品重复值剔除、恢复、接受预警走真实API，统计重新计算')

  await host.getByRole('button', { name: '标准点', exact: true }).click()
  const input = curve.locator('tbody tr').first().locator('input[type="text"]')
  await input.fill('1.125'); await input.blur()
  let attempts = 0
  const actions = `**${endpoint}/curves/L1/actions`
  const fail = async route => {
    attempts++
    await route.fulfill({ status: 409, contentType: 'application/json', body: JSON.stringify({ detail: { code: 'qa_save_conflict', message: '模拟保存冲突，请重试' } }) })
  }
  await page.route(actions, fail)
  const failed = response('/curves/L1/actions')
  await curve.getByRole('button', { name: '保存修正', exact: true }).first().click()
  assert.equal((await failed).status(), 409)
  await host.locator('.analysis-run-list button:disabled').first().waitFor({ state: 'hidden' })
  assert.equal(await input.inputValue(), '1.125')
  await page.unroute(actions, fail)
  assert.equal(attempts, 1)
  const changed = await clickSave(curve.getByRole('button', { name: '保存修正', exact: true }).first(), '/curves/L1/actions')
  assert.equal(changed.curves.lines[0].workspace.points[0].adjusted_intensity, 1.125)
  assert.equal(changed.curves.lines[0].workspace.points[0].original_intensity, 1)
  await clickSave(curve.getByRole('button', { name: '恢复原始', exact: true }).first(), '/curves/L1/actions')
  check('标准点保存失败保留输入，重试可保存，原始强度保持且可恢复')

  await host.getByRole('button', { name: '曲线图', exact: true }).click()
  const modes = await curve.getByLabel('拟合方式').locator('option').evaluateAll(items => items.map(item => item.value))
  assert.deepEqual(modes, ['linear', 'quadratic', 'cubic', 'spline'])
  await clickSave(curve.getByRole('button', { name: '重新拟合', exact: true }), '/curves/L1/fit')
  await clickSave(curve.getByRole('button', { name: '保存曲线', exact: true }), '/curves/L1/publish')
  await host.getByRole('button', { name: '下一条谱线', exact: true }).click()
  assert.match(await host.locator('.analysis-line-nav button.active').innerText(), /Zn/)
  await clickSave(curve.getByRole('button', { name: '重新拟合', exact: true }), '/curves/L2/fit')
  await clickSave(curve.getByRole('button', { name: '保存曲线', exact: true }), '/curves/L2/publish')
  const saved = await clickSave(host.getByRole('button', { name: '完成并保存结果', exact: true }), '/merge')
  assert.equal(saved.result_sha256, originalHash)
  assert.equal(saved.curves.merges.length, 1)
  assert.equal(saved.curves.merges[0].curve_snapshot_ids.length, 2)
  assert.equal(await host.getAttribute('data-navigation-view'), 'samples')
  assert.equal(await qc.getByLabel('重复性检查样品').count(), 1)
  check('逐线拟合、保存、下一条及最后合并串联完成，原分析结果哈希保持')

  await host.getByRole('button', { name: '曲线图', exact: true }).click()
  for (const [width, height, theme, density] of [[1440, 1000, 'light', 'comfortable'], [1060, 1000, 'dark', 'compact'], [1060, 680, 'light', 'compact']]) {
    await call(page, '/api/v1/settings', { display: { theme, density } }, 'PATCH')
    await page.getByRole('button', { name: '刷新服务状态', exact: true }).click()
    if (process.env.QA_CDP) await page.evaluate(({ width, height }) => window.__TAURI__.core.invoke('plugin:window|set_size', { value: { Logical: { width, height } } }), { width, height })
    else await page.setViewportSize({ width, height })
    await page.waitForFunction(theme => document.documentElement.dataset.theme === theme, theme)
    await host.getByRole('button', { name: '曲线图', exact: true }).click()
    await page.evaluate(() => window.scrollTo(0, 0))
    const layout = await page.evaluate(() => {
      const page = document.querySelector('.analysis-workbench'), qc = page.querySelector('.analysis-review-qc'), content = page.querySelector('.analysis-review-content')
      return { width: innerWidth, height: innerHeight, document: document.documentElement.scrollWidth, documentHeight: document.documentElement.scrollHeight, pageWidth: page.clientWidth, pageScroll: page.scrollWidth,
        qcWidth: qc.getBoundingClientRect().width, chartWidth: content.getBoundingClientRect().width,
        footerBottom: page.querySelector('.analysis-progress-actions').getBoundingClientRect().bottom,
        reviewColumns: getComputedStyle(page.querySelector('.analysis-review-layout')).gridTemplateColumns }
    })
    assert.ok(layout.document <= layout.width + 1, JSON.stringify(layout))
    assert.ok(layout.pageScroll <= layout.pageWidth + 1, JSON.stringify(layout))
    assert.ok(layout.qcWidth > 200 && layout.chartWidth > 300, JSON.stringify(layout))
    assert.ok(layout.footerBottom <= layout.height + 1, JSON.stringify(layout))
    assert.ok(layout.documentHeight <= layout.height + 1, JSON.stringify(layout))
    const name = `analysis-${width}-${height}-${theme}.png`
    await page.locator('.toast').waitFor({ state: 'hidden' })
    await host.screenshot({ path: path.join(output, name) })
    if (width === 1440) {
      for (const [label, file] of [['标准点', 'analysis-standards.png'], ['样品结果', 'analysis-results.png']]) {
        await host.getByRole('button', { name: label, exact: true }).click()
        await host.screenshot({ path: path.join(output, file) })
      }
      await host.getByRole('button', { name: '曲线图', exact: true }).click()
    }
    result.layouts.push({ name, ...layout })
  }
  check('1440/1060及680高窗口、明暗主题紧凑布局无页面横向溢出')
  const beforeQc = await call(page, endpoint)
  const lastLine = beforeQc.curves.lines.find(item => item.line_id === 'L2')
  await clickSave(qc.getByRole('button', { name: '剔除', exact: true }).first(), '/quality/decisions')
  assert.equal(await host.getByRole('button', { name: '完成并保存结果', exact: true }).isDisabled(), true)
  await clickSave(qc.getByRole('button', { name: '恢复', exact: true }), '/quality/decisions')
  const afterQc = await call(page, endpoint)
  assert.equal(afterQc.curves.merges.length, 1)
  assert.ok(afterQc.curves.lines.find(item => item.line_id === 'L2').snapshots.some(item => item.id === lastLine.active_curve_snapshot_id))
  check('质控变化后旧曲线不能继续完成流程；历史曲线和已保存合并结果保留')


  // A real stored sample exercises the preserved start -> slow intervention -> review transition.
  const options = await call(page, '/api/v1/analyses/options')
  const source = options.samples.find(item => item.id === fixture.sample_id)
  const slow = await call(page, '/api/v1/analyses/runs', { name: '慢进整合流程', acquisition_sample_ids: [fixture.sample_id],
    method_version_id: source.method_version_id, calculation_profile: 'legacy_2_0_2', slow_mode: true, intervention_timeout_seconds: 300 })
  await host.getByRole('button', { name: '刷新', exact: true }).click()
  await host.locator('.analysis-run-list button').filter({ hasText: '慢进整合流程' }).click()
  await clickSave(host.getByRole('button', { name: '开始', exact: true }), `/runs/${slow.id}/start`)
  for (let count = 0; count < 12; count++) {
    const run = await call(page, `/api/v1/analyses/runs/${slow.id}`)
    if (run.status === 'completed') break
    if (run.status === 'paused') await clickSave(host.getByRole('button', { name: '接受调整', exact: true }), '/intervene')
    else await clickSave(host.getByRole('button', { name: '推进一条谱线', exact: true }), `/runs/${slow.id}/step`)
  }
  assert.equal((await call(page, `/api/v1/analyses/runs/${slow.id}`)).status, 'completed')
  await page.waitForFunction(() => document.querySelector('.analysis-page')?.dataset.navigationView === 'curve')
  await qc.getByLabel('重复性检查样品').waitFor()
  check('真实存储谱图的慢进启动、峰位接受及完成后自动进入同一工作区复核')
  await host.getByRole('button', { name: '谱图与测量', exact: true }).click()
  const spectrum = host.locator('.analysis-spectrum')
  await spectrum.locator('[data-testid="spectrum-plot"] .spectrum-line').first().waitFor()
  await spectrum.getByText('校线', { exact: true }).click()
  const calibration = page.waitForResponse(item => item.url().endsWith('/calibration') && item.request().method() === 'GET')
  await spectrum.getByRole('button', { name: '日常校线预览', exact: true }).click()
  assert.equal((await calibration).status(), 200)
  await spectrum.getByText('校线', { exact: true }).click()
  await host.locator('.analysis-measurement-content').evaluate(element => { element.scrollTop = 0 })
  await page.locator('.toast').waitFor({ state: 'hidden' })
  await host.screenshot({ path: path.join(output, 'analysis-measurement.png') })
}
