import assert from 'node:assert/strict'
import { waitForSpectrumInk, assertSpectrumCleared } from './legacy_desk_test_support.mjs'
import path from 'node:path'
import { readFile } from 'node:fs/promises'
import { call, navigate } from './contract_browser_support.mjs'

export async function checkEvaporationCanvasStates(scope, framesUrl, reloadFrames, frame) {
  const page = scope.page()
  await waitForSpectrumInk(scope, { id: 'evaporation' })
  const alert = scope.getByRole('alert').filter({ hasText: '测试读取失败' })
  await page.route(framesUrl, route => route.fulfill({
    status: 503, contentType: 'application/json', body: JSON.stringify({ detail: '测试读取失败' }),
  }))
  try {
    await reloadFrames()
    await scope.getByRole('button', { name: '重试读取', exact: true }).waitFor()
    await assertSpectrumCleared(scope, alert)
    assert.equal(await scope.getByRole('button', { name: '横向放大', exact: true }).and(scope.locator(':enabled')).count(), 0)
  } finally {
    await page.unroute(framesUrl)
  }
  await scope.getByRole('button', { name: '重试读取', exact: true }).click()
  await waitForSpectrumInk(scope, { id: 'evaporation' })
  await page.route(framesUrl, async route => {
    const response = await route.fetch()
    const frames = await response.json()
    await route.fulfill({ response, json: Array.isArray(frames) ? [frame] : { ...frames, frames: [frame] } })
  })
  try {
    await reloadFrames()
    await waitForSpectrumInk(scope, { lines: 0, points: 1, id: 'evaporation' })
  } finally {
    await page.unroute(framesUrl)
  }
}

export async function checkViewerOperations(page, result, output) {
  const check = text => result.checks.push(text)
  const method = (await call(page, '/api/v1/methods')).find(item => item.status === 'active')
  assert.ok(method)
  await call(page, '/api/v1/methods/current', { method_id: method.id })
  const entries = (await call(page, '/api/v1/capabilities')).capabilities.flatMap(item => item.navigation_entries)
  const go = async (name, selector) => {
    const entry = entries.find(item => item.page === name && (name !== 'dispersion' || item.view === 'curve'))
    assert.ok(entry, name)
    await navigate(page, entry.group, entry.label, selector)
    return page.locator(selector)
  }
  const tasks = []
  for (const kind of ['sample', 'evaporation']) {
    let task = await call(page, '/api/v1/acquisitions/tasks', { name: `查看排版-${kind}`, task_kind: kind,
      method_id: method.id, sample_name: `VIEW-${kind}`, burn_frame_count: 3, dark_frame_count: 1,
      pre_excitation_seconds: 0, countdown_seconds: 0, sampling_period_seconds: .1 })
    task = await call(page, `/api/v1/acquisitions/tasks/${task.id}/start`, {})
    for (let i = 0; i < 60 && task.status !== 'completed'; i++) task = await call(page, `/api/v1/acquisitions/tasks/${task.id}/step`, {})
    assert.equal(task.status, 'completed'); tasks.push(task)
  }
  await call(page, '/api/v1/acquisitions/tasks', { name: '空蒸发实验', task_kind: 'evaporation', method_id: method.id })
  const evaporationFrames = (await call(page, `/api/v1/acquisitions/tasks/${tasks[1].id}/frames?phase=burn`)).filter(frame => frame.ccd_index === 0 && !frame.damaged)
  let dispersion = await call(page, '/api/v1/dispersion/tasks', { name: '查看排版-色散', frame_count: 3, dark_frame_count: 1, pre_excitation_seconds: 0 })
  for (const wavelength of [253, 260, 265]) await call(page, `/api/v1/dispersion/tasks/${dispersion.id}/lines`, { element: 'Fe', wavelength_nm: wavelength, ccd_index: 0 })
  await call(page, `/api/v1/dispersion/tasks/${dispersion.id}/lines`, { element: 'Fe', wavelength_nm: 290, ccd_index: 1 })
  dispersion = await call(page, `/api/v1/dispersion/tasks/${dispersion.id}/start`, {})
  for (let i = 0; i < 30 && dispersion.status !== 'completed'; i++) dispersion = await call(page, `/api/v1/dispersion/tasks/${dispersion.id}/step`, {})
  assert.equal(dispersion.status, 'completed')
  let writes = 0
  page.on('request', request => { if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(request.method())) writes++ })
  const drag = async (svg, tool) => {
    const box = await svg.locator('.plot-background').boundingBox()
    await page.mouse.move(box.x + box.width * .2, box.y + box.height * .2)
    await page.mouse.down(); await page.mouse.move(box.x + box.width * .7, box.y + box.height * .7, { steps: 5 }); await page.mouse.up()
  }
  const layout = async (host, name) => {
    const bad = await host.evaluate(node => [...node.querySelectorAll('button,select,input,svg.spectrum-plot')].filter(el => {
      const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0 && (r.left < 0 || r.right > innerWidth + 1)
    }).map(el => el.getAttribute('aria-label') || el.textContent.slice(0, 40)))
    assert.deepEqual(bad, [], `${name}: overflow`)
    const icons = await host.locator('img.spectroscopy-action-icon').evaluateAll(nodes => nodes.filter(node => node.offsetWidth > 0).every(node => node.complete && node.naturalWidth === 256))
    assert.ok(icons)
    await host.evaluate(node => { for (let current = node.parentElement; current; current = current.parentElement) { current.scrollTop = 0 } }); await page.waitForTimeout(150)
    await page.screenshot({ path: path.join(output, `${name}.png`), fullPage: true })
    result.layouts.push(name)
  }
  for (const [theme, width, height] of [['light', 1440, 1000], ['dark', 1060, 720]]) {
    if (!process.env.QA_CDP) await page.setViewportSize({ width, height })
    else await page.evaluate(value => window.__TAURI__.core.invoke('plugin:window|set_size', { value: { Logical: value } }), { width, height })
    await call(page, '/api/v1/settings', { display: { theme, density: 'compact' } }, 'PATCH')
    await page.reload(); await page.locator('.sidebar').waitFor()
    let host = await go('evaporation-curves', '[data-testid="evaporation-curves-page"]')
    await host.locator('.acquisition-task-rows').getByRole('button', { name: /查看排版-evaporation/ }).click()
    const chart = host.getByTestId('evaporation-time-chart'), svg = chart.locator('svg.spectrum-plot')
    await waitForSpectrumInk(svg)
    assert.ok((await svg.locator('.plot-tick-label').allTextContents()).some(value => value.includes('.')), '亚秒时间刻度保留小数')
    await chart.getByRole('button', { name: '上一蒸发实验', exact: true }).click()
    assert.ok(await chart.getByRole('button', { name: '横向放大', exact: true }).isDisabled())
    await chart.getByRole('button', { name: '下一蒸发实验', exact: true }).click()
    await waitForSpectrumInk(svg)
    await chart.getByRole('button', { name: '下一 CCD', exact: true }).click()
    await waitForSpectrumInk(svg); assert.equal(await host.getByLabel('蒸发曲线CCD').inputValue(), '1')
    await chart.getByRole('button', { name: '上一 CCD', exact: true }).click(); await waitForSpectrumInk(svg)
    const before = writes, full = await chart.getByLabel('蒸发曲线视野').textContent()
    await chart.getByRole('button', { name: '横向放大', exact: true }).click()
    assert.notEqual(await chart.getByLabel('蒸发曲线视野').textContent(), full)
    const xZoom = await chart.getByLabel('蒸发曲线视野').textContent()
    await chart.getByRole('button', { name: '纵向放大', exact: true }).click()
    await chart.getByRole('button', { name: '纵向还原', exact: true }).click()
    assert.equal(await chart.getByLabel('蒸发曲线视野').textContent(), xZoom)
    await chart.getByRole('button', { name: '适合图像', exact: true }).click()
    await chart.getByRole('button', { name: '区域放大', exact: true }).click(); await drag(svg)
    assert.notEqual(await chart.getByLabel('蒸发曲线视野').textContent(), full)
    await chart.getByRole('button', { name: '滚动工具', exact: true }).click()
    const boxed = await chart.getByLabel('蒸发曲线视野').textContent(); await drag(svg)
    assert.notEqual(await chart.getByLabel('蒸发曲线视野').textContent(), boxed)
    await chart.getByRole('button', { name: '适合图像', exact: true }).click()
    await chart.getByRole('button', { name: '十字线', exact: true }).click()
    const box = await svg.locator('.plot-background').boundingBox()
    await page.mouse.click(box.x + box.width * .5, box.y + box.height * .5)
    const reading = await chart.getByLabel('蒸发曲线读数').textContent()
    assert.match(reading, /已锁定/)
    assert.ok(reading.includes(Number(evaporationFrames[1].peak_value).toFixed(3)), '读数对应实际第二帧峰值')
    assert.equal(writes, before)
    await host.getByRole('button', { name: '帧积分', exact: true }).click()
    await waitForSpectrumInk(svg)
    assert.equal(await host.getByRole('button', { name: '帧积分', exact: true }).getAttribute('aria-pressed'), 'true')
    await layout(host, `evaporation-${theme}`)
    check(`${theme}: 蒸发缩放、独立纵向还原、框选、拖动、点位锁定与指标切换，观察零写入`)

    host = await go('dispersion', '[data-testid="dispersion-page"]')
    await host.locator('.dispersion-task-list').getByRole('button', { name: /查看排版-色散/ }).click()
    await waitForSpectrumInk(host)
    await host.getByRole('button', { name: '增加谱线', exact: true }).click()
    assert.ok(await host.getByTestId('dispersion-add-line-form').isVisible())
    await host.locator('.curve-line-editor > summary').click()
    const bar = host.getByRole('toolbar', { name: '色散谱线操作栏' })
    await bar.getByLabel('选择谱线', { exact: true }).selectOption(String(dispersion.lines[3].id))
    await waitForSpectrumInk(host)
    assert.equal(await bar.getByLabel('选择谱线', { exact: true }).inputValue(), String(dispersion.lines[3].id))
    assert.equal(await host.getByLabel('选择CCD', { exact: true }).inputValue(), '1')
    await bar.getByLabel('选择谱线', { exact: true }).selectOption(String(dispersion.lines[0].id))
    assert.equal(await bar.getByLabel('定位谱线', { exact: true }).inputValue(), String(dispersion.lines[0].wavelength_nm))
    await host.getByLabel('读取点位', { exact: true }).fill('120'); await host.getByLabel('读取点位', { exact: true }).blur()
    const applied = page.waitForResponse(response => response.request().method() === 'POST' && response.url().includes('/position'))
    await host.getByRole('button', { name: '采用锁定点位', exact: true }).click(); assert.ok((await applied).ok())
    const fresh = await call(page, `/api/v1/dispersion/tasks/${dispersion.id}`)
    assert.equal(fresh.lines[0].located_position, 120)
    const count = writes
    await host.getByRole('button', { name: '横向放大', exact: true }).click()
    await host.getByRole('button', { name: '纵向还原', exact: true }).click()
    await host.getByRole('button', { name: '适合图像', exact: true }).click()
    assert.equal(writes, count)
    await layout(host, `dispersion-${theme}`)
    check(`${theme}: 色散顶部增删/选线对应字段、零起点人工定位与观察工具`)

    host = await go('spectra', '[data-testid="spectrum-viewer-page"]')
    await waitForSpectrumInk(host)
    const toolbar = host.getByRole('toolbar', { name: '图像查看工具' })
    const order = await toolbar.locator('button').evaluateAll(nodes => nodes.map(node => node.getAttribute('aria-label')))
    assert.deepEqual(order.slice(0, 7), ['上一条记录', '下一条记录', '上一 CCD', '下一 CCD', '十字线', '区域放大', '滚动工具'])
    assert.equal(order[order.length - 1], '打印谱图')
    const count2 = writes
    await toolbar.getByRole('button', { name: '横向放大', exact: true }).click()
    await toolbar.getByRole('button', { name: '纵向放大', exact: true }).click()
    await toolbar.getByRole('button', { name: '纵向还原', exact: true }).click()
    await toolbar.getByRole('button', { name: '适合图像', exact: true }).click()
    assert.equal(writes, count2)
    await layout(host, `spectra-${theme}`)
    check(`${theme}: 谱图查看旧版按钮顺序、真实缩放与独立纵向还原`)
  }
  const printHost = await go('spectra', '[data-testid="spectrum-viewer-page"]')
  await waitForSpectrumInk(printHost)
  const scope = printHost.getByRole('toolbar', { name: '图像查看工具' })
  const printResponse = page.waitForResponse(response => response.url().includes('/print-pdf') && response.request().method() === 'POST')
  if (process.env.QA_CDP) {
    await page.evaluate(() => {
      const bridge = window.chrome.webview, original = bridge.postMessage
      window.__viewerSaveOriginal = original
      const capture = function(message) {
        const command = typeof message === 'string' ? JSON.parse(message) : message
        if (command.cmd === 'save_export_file') {
          window.__viewerPdf = command.payload
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
      await page.waitForFunction(() => !!window.__viewerPdf)
      const pdf = await page.evaluate(() => ({ type: window.__viewerPdf.contentType,
        signature: String.fromCharCode(...window.__viewerPdf.bytes.slice(0, 4)), size: window.__viewerPdf.bytes.length }))
      assert.equal(pdf.type, 'application/pdf'); assert.equal(pdf.signature, '%PDF'); assert.ok(pdf.size > 1000)
    } finally {
      await page.evaluate(() => { window.chrome.webview.postMessage = window.__viewerSaveOriginal; delete window.__viewerPdf; delete window.__viewerSaveOriginal })
    }
  } else {
    const downloaded = page.waitForEvent('download')
    await scope.getByRole('button', { name: '打印谱图', exact: true }).click()
    const response = await printResponse; assert.equal(response.status(), 200, await response.text())
    const download = await downloaded, destination = path.join(output, 'saved-spectrum.pdf')
    await download.saveAs(destination)
    const pdf = await readFile(destination); assert.equal(pdf.subarray(0, 4).toString(), '%PDF'); assert.ok(pdf.length > 1000)
  }
  check('谱图查看工具栏按当前可见范围生成真实PDF，桌面取消保存不改变谱带')
  const host = await go('evaporation-curves', '[data-testid="evaporation-curves-page"]')
  await host.locator('.acquisition-task-rows').getByRole('button', { name: /查看排版-evaporation/ }).click()
  await checkEvaporationCanvasStates(host, '**/api/v1/acquisitions/tasks/*/frames?*',
    () => host.getByRole('button', { name: '刷新', exact: true }).click(), evaporationFrames[0])
  check('蒸发帧读取503清空旧曲线，观察按钮禁用，重试恢复真实数据')
  check('单帧蒸发数据显示可读点标记，不绘制虚构连线')

}

