import assert from 'node:assert/strict'
import path from 'node:path'
import { readFile } from 'node:fs/promises'
import { call, navigate } from './contract_browser_support.mjs'
import { leaveLegacyCapture, openSpectrumReadout, closeSpectrumReadout } from './legacy_desk_test_support.mjs'

// One isolated workflow covers the legacy operating surface, read-only browsing and mode boundaries.
export async function checkFullSpectroscopy(page, result, output) {
  const check = text => result.checks.push(text)
  const method = (await call(page, '/api/v1/methods')).find(item => item.status === 'active')
  assert.ok(method)
  await call(page, '/api/v1/methods/current', { method_id: method.id })
  const entries = (await call(page, '/api/v1/capabilities')).capabilities.flatMap(item => item.navigation_entries)
  const tasks = []
  for (const mode of ['sample-acquisition', 'evaporation-acquisition', 'dispersion']) {
    const dispersion = mode === 'dispersion', domain = dispersion ? 'dispersion' : 'acquisitions'
    let task = await call(page, `/api/v1/${domain}/tasks`, dispersion
      ? { name: '完整工作台色散', frame_count: 2, dark_frame_count: 1, pre_excitation_seconds: 0 }
      : { name: `完整工作台-${mode}`, task_kind: mode === 'sample-acquisition' ? 'sample' : 'evaporation',
        method_id: method.id, sample_name: 'FULL01', burn_frame_count: 2, dark_frame_count: 1,
        repeat_count: mode === 'sample-acquisition' ? 2 : 1, countdown_seconds: 0, pre_excitation_seconds: 0 })
    task = await call(page, `/api/v1/${domain}/tasks/${task.id}/start`, {})
    for (let i = 0; i < 100 && task.status !== 'completed'; i++)
      task = await call(page, `/api/v1/${domain}/tasks/${task.id}/${task.status === 'between_repeats' ? 'start' : 'step'}`, {})
    assert.equal(task.status, 'completed')
    assert.ok(task.profile.screen_width_mm > 0 && task.profile.screen_resolution_px > 0 && task.layout.point_width_um > 0)
    tasks.push({ mode, domain, task, origin: dispersion ? 0 : 1 })
  }
  const go = async item => {
    await leaveLegacyCapture(page)
    const entry = entries.find(entry => entry.page === item.mode && (!entry.view || entry.view === 'capture'))
    await navigate(page, entry.group, entry.label, `[data-testid="${item.mode}-page"]`)
    const back = page.getByRole('button', { name: '返回任务列表', exact: true })
    if (await back.isVisible()) await back.click()
    const host = page.getByTestId(`${item.mode}-page`)
    await host.locator(`[data-task-id="${item.task.id}"]`).getByRole('button').click()
    await host.locator('svg.spectrum-plot .spectrum-line').waitFor()
    return host
  }
  const readRange = async scope => {
    await openSpectrumReadout(scope)
    const text = await scope.locator('.inspector-readout > small').textContent()
    const [, x1, x2, y1, y2] = text.match(/视野 ([\d.-]+)–([\d.-]+) · 强度 ([\d.-]+)–([\d.-]+)/)
    await closeSpectrumReadout(scope)
    return [Number(x1), Number(x2), Number(y1), Number(y2)]
  }
  const pointValue = async (scope, point) => {
    await openSpectrumReadout(scope)
    const input = scope.getByLabel('读取点位', { exact: true })
    await input.fill(String(point)); await input.blur()
    const value = Number((await scope.getByLabel('谱图点位读数').textContent()).match(/强度 ([\d,.-]+)/)[1].replaceAll(',', ''))
    await closeSpectrumReadout(scope)
    return value
  }
  for (const layout of [{ width: 1440, height: 1000, theme: 'light', density: 'comfortable' },
    { width: 1060, height: 680, theme: 'dark', density: 'compact' }]) {
    const settings = await call(page, '/api/v1/settings')
    await call(page, '/api/v1/settings', { display: { ...settings.display, theme: layout.theme, density: layout.density } }, 'PATCH')
    await page.reload(); await page.getByTestId('workspace').waitFor()
    if (process.env.QA_CDP) await page.evaluate(value => window.__TAURI__.core.invoke('plugin:window|set_size', { value: { Logical: value } }), { width: layout.width, height: layout.height })
    else await page.setViewportSize({ width: layout.width, height: layout.height })
    for (const item of tasks) {
      const host = await go(item), scope = host.locator('.spectrum-inspector'), svg = scope.locator('svg.spectrum-plot')
      const buttons = await scope.locator('.inspector-tools button').evaluateAll(elements => elements.map(element => ({
        image: element.querySelector('img')?.naturalWidth, title: element.title, label: element.getAttribute('aria-label')
      })))
      assert.ok(buttons.length >= 15 && buttons.every(button => button.image === 256 && button.title && button.label))
      const columns = await host.locator('.spectroscopy-console').evaluate(element => {
        const left = element.querySelector('.spectroscopy-records').getBoundingClientRect()
        const middle = element.querySelector('.spectroscopy-view').getBoundingClientRect()
        const right = element.querySelector('.spectroscopy-operator').getBoundingClientRect()
        return { left: left.x, middle: middle.x, right: right.x, width: innerWidth, rightEdge: right.right }
      })
      assert.ok(columns.left < columns.middle && columns.middle < columns.right && columns.rightEdge <= columns.width + 1)
      let writes = 0
      const count = request => { if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(request.method())) writes++ }
      page.on('request', count)
      const reset = scope.getByRole('button', { name: '适合图像', exact: true })
      await reset.click()
      const original = await readRange(scope), box = await svg.boundingBox(), originalPath = await svg.locator('.spectrum-line').getAttribute('d')
      for (const fraction of [.15, .7]) {
        await page.mouse.move(box.x + box.width * fraction, box.y + box.height * .45); await page.waitForTimeout(80)
        assert.deepEqual(await readRange(scope), original)
        assert.equal(await svg.locator('.spectrum-line').getAttribute('d'), originalPath)
        assert.deepEqual(await svg.boundingBox(), box)
      }
      await scope.getByRole('button', { name: '一线一点', exact: true }).click()
      const one = await readRange(scope)
      await scope.getByRole('button', { name: '一线四点', exact: true }).click()
      const four = await readRange(scope)
      assert.ok(Math.abs((one[1] - one[0]) / (four[1] - four[0]) - 4) < .025)
      await scope.getByRole('button', { name: '十倍 CCD', exact: true }).click()
      const physical = await readRange(scope)
      const pixels = await svg.evaluate(element => ({ width: element.clientWidth - 88, dpr: devicePixelRatio }))
      const spacing = item.task.layout.point_width_um / 1000 * 10 * item.task.profile.screen_resolution_px / item.task.profile.screen_width_mm / pixels.dpr
      assert.ok(Math.abs((physical[1] - physical[0]) - pixels.width / spacing) < .2)
      await reset.click()
      await scope.getByRole('button', { name: '横向放大', exact: true }).click()
      const zoomed = await readRange(scope)
      await scope.getByRole('button', { name: '纵向放大', exact: true }).click()
      await scope.getByRole('button', { name: '纵向还原', exact: true }).click()
      assert.deepEqual(await readRange(scope), [zoomed[0], zoomed[1], original[2], original[3]])
      await reset.click()
      await scope.getByRole('button', { name: '区域放大', exact: true }).click()
      const plot = await svg.locator('.plot-background').boundingBox()
      await page.mouse.move(plot.x + plot.width * .2, plot.y + plot.height * .2); await page.mouse.down()
      await page.mouse.move(plot.x + plot.width * .7, plot.y + plot.height * .7, { steps: 4 }); await page.mouse.up()
      assert.notDeepEqual(await readRange(scope), original)
      await reset.click(); await scope.getByRole('button', { name: '十字线', exact: true }).click()
      const ccd = host.getByRole('combobox', { name: '选择CCD', exact: true })
      if (item.task.ccd_indices.length > 1) {
        await host.getByRole('button', { name: '下一 CCD', exact: true }).click()
        assert.equal(await ccd.inputValue(), String(item.task.ccd_indices[1]))
        await host.getByRole('button', { name: '上一 CCD', exact: true }).click()
        assert.equal(await ccd.inputValue(), String(item.task.ccd_indices[0]))
      }
      page.off('request', count); assert.equal(writes, 0)
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false)
      result.layouts.push({ ...layout, mode: item.mode, columns, iconButtons: buttons.length, observationWrites: writes })
      check(`${item.mode}/${layout.theme}: 三分区、完整工具、真实比例、纵向还原、CCD切换及悬停稳定`)
      if (item.mode === 'sample-acquisition') await host.locator('.spectroscopy-console').screenshot({ path: path.join(output, `workbench-${layout.theme}.png`) })
    }
  }
  const item = tasks[0], host = await go(item), scope = host.locator('.spectrum-inspector')
  const rows = host.locator('.capture-record-table tbody tr')
  assert.equal(await rows.count(), 2)
  await rows.first().getByRole('button').click(); await scope.locator('svg .spectrum-line').waitFor()
  const saved = await call(page, `/api/v1/acquisitions/samples/${item.task.samples[0].id}/bands?include_points=true`)
  assert.ok(Math.abs(await pointValue(scope, 124) - saved[0].mean_points[123]) < .000001)
  const printResponse = page.waitForResponse(response => response.url().includes('/print-pdf') && response.request().method() === 'POST')
  if (process.env.QA_CDP) {
    await page.evaluate(() => {
      const bridge = window.chrome.webview, original = bridge.postMessage
      window.__spectroscopySaveOriginal = original
      const capture = function(message) {
        const command = typeof message === 'string' ? JSON.parse(message) : message
        if (command.cmd === 'save_export_file') {
          window.__spectroscopyPdf = command.payload
          queueMicrotask(() => window.__TAURI_INTERNALS__.runCallback(command.callback, null))
          return
        }
        return original.call(bridge, message)
      }
      bridge.postMessage = capture
      if (bridge.postMessage !== capture) throw new Error('QA PDF interception unavailable')
    })
    try {
      await scope.getByRole('button', { name: '打印谱图', exact: true }).click()
      const response = await printResponse; assert.equal(response.status(), 200, await response.text())
      await page.waitForFunction(() => !!window.__spectroscopyPdf)
      const pdf = await page.evaluate(() => ({ type: window.__spectroscopyPdf.contentType,
        signature: String.fromCharCode(...window.__spectroscopyPdf.bytes.slice(0, 4)), size: window.__spectroscopyPdf.bytes.length }))
      assert.equal(pdf.type, 'application/pdf'); assert.equal(pdf.signature, '%PDF'); assert.ok(pdf.size > 1000)
    } finally {
      await page.evaluate(() => { window.chrome.webview.postMessage = window.__spectroscopySaveOriginal; delete window.__spectroscopyPdf; delete window.__spectroscopySaveOriginal })
    }
  } else {
    const downloaded = page.waitForEvent('download')
    await scope.getByRole('button', { name: '打印谱图', exact: true }).click()
    const response = await printResponse; assert.equal(response.status(), 200, await response.text())
    const download = await downloaded, destination = path.join(output, 'saved-spectrum.pdf')
    await download.saveAs(destination)
    const pdf = await readFile(destination); assert.equal(pdf.subarray(0, 4).toString(), '%PDF'); assert.ok(pdf.length > 1000)
  }
  check('工作台已保存谱带按当前可见范围生成真实PDF，桌面取消保存不改变谱带')
  await host.getByRole('button', { name: '锁定谱带记录', exact: true }).click()
  assert.equal(await rows.last().getByRole('button').isDisabled(), true)
  await host.getByRole('button', { name: '解锁谱带记录', exact: true }).click()
  await scope.getByRole('button', { name: '下一谱带', exact: true }).click()
  assert.equal(await rows.last().getAttribute('aria-selected'), 'true')
  check('已保存均值谱带点值与后端原值一致，谱带前后切换及记录锁定正常')
  if (!process.env.QA_CDP) {
    await host.getByRole('button', { name: '返回实时谱图', exact: true }).click()
    const route = `**/acquisitions/samples/${item.task.samples[0].id}/bands*`
    await page.route(route, route => route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ message: 'QA已保存谱带读取失败' }) }))
    await rows.first().getByRole('button').click()
    await host.getByRole('alert').filter({ hasText: 'QA已保存谱带读取失败' }).waitFor()
    assert.equal(await scope.locator('svg').count(), 0)
    await page.unroute(route)
    await host.getByRole('button', { name: '返回实时谱图', exact: true }).click()
    await rows.first().getByRole('button').click(); await scope.locator('svg .spectrum-line').waitFor()
    check('读取已保存谱带失败时明确提示并清空曲线，切回后可重试，无实时数据冒充')
  }
  const dispersion = tasks[2], dh = await go(dispersion), ds = dh.locator('.spectrum-inspector')
  await dh.locator('.capture-record-table tbody tr').first().getByRole('button').click()
  const frames = await call(page, `/api/v1/dispersion/tasks/${dispersion.task.id}/frames?ccd_index=0`)
  assert.equal(await pointValue(ds, 123), frames[0].points[123])
  await dh.getByRole('button', { name: '返回实时谱图', exact: true }).click()
  await dh.getByRole('button', { name: '拟合曲线', exact: true }).click()
  const processing = dh.getByRole('region', { name: '当前色散任务处理' })
  await processing.waitFor()
  assert.equal(await processing.getByRole('heading', { name: '谱线定位与位置' }).isVisible(), true)
  const definitions = [['Fe', 250, 100], ['Mg', 260, 200], ['Ca', 270, 300]]
  for (const [element, wavelength, position] of definitions) {
    await processing.getByLabel('元素', { exact: true }).fill(element)
    const input = processing.getByLabel('波长 (nm)', { exact: true })
    await input.fill(String(wavelength)); await input.blur()
    const created = page.waitForResponse(response => response.url().endsWith(`/dispersion/tasks/${dispersion.task.id}/lines`) && response.request().method() === 'POST')
    await processing.getByRole('button', { name: '添加', exact: true }).click()
    const response = await created; assert.equal(response.status(), 201, await response.text())
    const line = await response.json()
    await openSpectrumReadout(ds)
    await ds.getByLabel('读取点位', { exact: true }).fill(String(position)); await ds.getByLabel('读取点位', { exact: true }).blur()
    await closeSpectrumReadout(ds)
    await processing.getByLabel('人工定位谱线').selectOption(String(line.id))
    const positioned = page.waitForResponse(response => response.url().includes(`/lines/${line.id}/position?`) && response.request().method() === 'POST')
    await processing.getByRole('button', { name: '采用锁定点位', exact: true }).click()
    assert.equal((await positioned).status(), 200)
  }
  const fitted = page.waitForResponse(response => response.url().endsWith(`/dispersion/tasks/${dispersion.task.id}/calibrations/fit`) && response.request().method() === 'POST')
  await processing.getByRole('button', { name: '二次拟合', exact: true }).click()
  const fitResponse = await fitted; assert.equal(fitResponse.status(), 201, await fitResponse.text())
  const calibration = await fitResponse.json(); assert.equal(calibration.point_count, 3)
  check('当前工作台完成三条谱线录入、零起点实际点位采用和真实二次拟合，发布门禁保留')
  check('色散已保存燃烧/暗帧可在当前任务观察，定位、拟合和保存面板在当前工作台展开')
  await dh.getByRole('button', { name: '关闭色散处理窗口', exact: true }).click()
  await dh.getByRole('button', { name: '结束', exact: true }).click()
  assert.equal(await dh.getByTestId('spectroscopy-console').isVisible(), false)
  assert.equal(await dh.getByRole('heading', { name: '色散摄谱任务' }).isVisible(), true)
  check('结束返回任务列表，采集记录保留，准备页和当前采集继续分开')
  const roles = await call(page, '/api/v1/roles')
  await call(page, '/api/v1/users', { username: 'full-workbench-viewer', password: 'viewer-correct-horse',
    role_ids: [roles.find(role => role.name === 'read_only_auditor').id] })
  const login = await call(page, '/api/v1/auth/login', { username: 'full-workbench-viewer', password: 'viewer-correct-horse' })
  await page.evaluate(token => sessionStorage.setItem('geospectrum.token', token), login.access_token)
  await page.reload(); await page.getByTestId('workspace').waitFor()
  const readOnly = await go(dispersion)
  for (const name of ['试样摄谱', '预热摄谱', '暂停', '停止摄谱', '增加谱线', '校正谱线'])
    assert.equal(await readOnly.getByRole('button', { name, exact: true }).isDisabled(), true)
  await readOnly.getByRole('button', { name: '拟合曲线', exact: true }).click()
  assert.equal(await readOnly.getByRole('button', { name: '二次拟合', exact: true }).isDisabled(), true)
  check('只读账户可浏览完成谱图与曲线，激发、谱线写入和拟合均按原权限禁用')
}
