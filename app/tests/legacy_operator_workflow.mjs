import assert from 'node:assert/strict'
import path from 'node:path'
import { writeFile } from 'node:fs/promises'
import { call, navigate } from './contract_browser_support.mjs'

export async function checkLegacyOperators(page, fixture, result, output) {
  const check = (id, message) => { result.checks.push({ id, message }); console.log(`PASS ${id}: ${message}`) }
  const entries = (await call(page, '/api/v1/capabilities')).capabilities.flatMap((item) => item.navigation_entries)
  const selectors = { settings: '[data-testid="settings"]', methods: '[data-testid="methods-page"]',
    analysis: '.analysis-page', dispersion: '.dispersion-page',
    'evaporation-acquisition': '[data-testid="evaporation-acquisition-page"]',
    'sample-acquisition': '[data-testid="sample-acquisition-page"]' }
  async function go(name) {
    const entry = entries.find((item) => item.page === name || item.key === name)
    assert.ok(entry, name)
    const selector = selectors[entry.page] ?? (entry.key === 'analysis-tests.spectra' ? '[data-testid="spectrum-viewer-page"]' : '.page-content')
    await navigate(page, entry.group, entry.label, selector)
    if (['dispersion', 'evaporation-acquisition', 'sample-acquisition'].includes(entry.page))
      await page.waitForFunction(() => !document.querySelector('.spectroscopy-lock'))
    return page.locator(selector)
  }
  const openForm = async (host, text) => {
    const button = host.locator('.disclosure-toggle').filter({ hasText: text })
    if (await button.count() && await button.getAttribute('aria-expanded') === 'false') await button.click()
  }
  const fill = async (host, label, value) => { const field = host.getByLabel(label, { exact: true }); await field.fill(String(value)); await field.blur() }
  const mutation = (url, method) => page.waitForResponse((response) => response.url().includes(url)
    && (method ? response.request().method() === method : response.request().method() !== 'GET'))
  const settle = () => page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))))
  // Make the selected published method visible to context-sensitive navigation.
  await call(page, '/api/v1/methods/current', { method_id: fixture.method_id })
  await page.reload()
  await page.getByTestId('workspace').waitFor()
  // Install capture after reload, without reading any existing clipboard contents.
  const capture = async () => page.evaluate(() => {
    window.__operatorClipboard = ''
    window.__operatorExports = []
    if (!window.__operatorObjectURLCapture) {
      window.__operatorObjectURLCapture = true
      const original = URL.createObjectURL
      URL.createObjectURL = function(blob) {
        if (blob instanceof Blob && blob.type === 'application/pdf')
          void blob.arrayBuffer().then(buffer => window.__operatorExports.push(Array.from(new Uint8Array(buffer))))
        return original.call(URL, blob)
      }
    }
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: async text => { window.__operatorClipboard = text } } })
    if (window.__TAURI__?.core && !window.__operatorFileCapture) {
      // Tauri's namespaces are read-only. Its installed SDK sends commands through fetch.
      // Capture only save_export_file's actual payload, then resolve its original callback normally.
      window.__operatorFileCapture = true
      const original = window.fetch
      const replacement = async (input, init) => {
        const url = new URL(typeof input === 'string' ? input : input.url, location.href)
        if (url.hostname === 'ipc.localhost' && url.pathname === '/save_export_file') {
          const args = JSON.parse(init.body)
          window.__operatorExports.push(args.bytes)
          return new Response(JSON.stringify(`QA/${args.fileName}`), { status: 200,
            headers: { 'Content-Type': 'application/json', 'Tauri-Response': 'ok' } })
        }
        return original.call(window, input, init)
      }
      window.fetch = replacement
      if (window.fetch !== replacement) throw new Error('QA native export capture was not installed')
      // The production CSP uses WebView2's postMessage fallback for native IPC.
      const bridge = window.chrome?.webview
      if (typeof bridge?.postMessage !== 'function') throw new Error('QA WebView2 message bridge unavailable')
      const postMessage = bridge.postMessage
      const capturedPostMessage = function(message) {
        const data = typeof message === 'string' ? JSON.parse(message) : message
        if (data.cmd === 'save_export_file') {
          window.__operatorExports.push(data.payload.bytes)
          queueMicrotask(() => window.__TAURI_INTERNALS__.runCallback(data.callback, `QA/${data.payload.fileName}`))
          return
        }
        return postMessage.call(bridge, message)
      }
      bridge.postMessage = capturedPostMessage
      if (bridge.postMessage !== capturedPostMessage) throw new Error('QA WebView2 export capture was not installed')
    }
  })
  await capture()
  const saveCapturedPdf = async (filename, previousCount) => {
    await page.waitForFunction(count => window.__operatorExports.length > count, previousCount)
    const bytes = await page.evaluate(() => window.__operatorExports.at(-1))
    assert.ok(bytes.length > 1000, `empty PDF supplied to saveFile: ${filename}`)
    const data = Buffer.from(bytes)
    assert.equal(data.subarray(0, 4).toString(), '%PDF')
    await writeFile(path.join(output, filename), data)
  }
  let host = await go('settings')
  await fill(host, '空白传输时间（秒）', 9)
  let pending = mutation('/api/v1/settings')
  await host.getByRole('button', { name: '保存设置', exact: true }).click()
  assert.equal((await pending).status(), 200)
  host = await go('methods')
  await host.getByLabel('采样周期 (s)', { exact: true }).waitFor()
  await fill(host, '采样周期 (s)', 2)
  assert.equal(await host.getByLabel('空白次数', { exact: true }).inputValue(), '4')
  pending = mutation(`/api/v1/methods/${fixture.method_id}/save`, 'POST')
  await host.getByRole('button', { name: '保存', exact: true }).click()
  assert.equal((await pending).status(), 200)
  assert.equal((await call(page, `/api/v1/methods/${fixture.method_id}/versions`)).find(v => v.content_sha256 === fixture.method_hash)?.content_sha256, fixture.method_hash)
  check(5, '空白传输时间保存，9/2 按旧版偶数舍入得到4；原发布版本保持')

  host = await go('evaporation-acquisition')
  await openForm(host, '建立蒸发摄谱任务')
  await fill(host, '预激时间（秒）', 4.5)
  await fill(host, '采样周期 (秒)', 1.25)
  await fill(host, '采样次数', 11)
  await fill(host, '空白次数', 7)
  pending = mutation('/api/v1/acquisitions/defaults', 'PUT')
  await host.getByRole('button', { name: '保存激发条件', exact: true }).click()
  const evaporationSaved = await pending
  assert.equal(evaporationSaved.status(), 200)
  assert.equal((await evaporationSaved.json()).frame_count, 11)
  let attempts = 0
  const countDefaultWrites = request => { if (request.url().includes('/acquisitions/defaults') && request.method() === 'PUT') attempts++ }
  page.on('request', countDefaultWrites)
  await fill(host, '采样次数', '')
  await host.getByRole('button', { name: '保存激发条件', exact: true }).click()
  await settle(); assert.equal(attempts, 0)
  page.off('request', countDefaultWrites)
  await fill(host, '采样次数', 11)
  host = await go('dispersion')
  await openForm(host, '采集条件')
  await fill(host, '预激时间（秒）', 6)
  await fill(host, '采样周期（秒）', 1.5)
  await fill(host, '采样次数', 5)
  await fill(host, '空白次数', 3)
  pending = mutation('/api/v1/dispersion/defaults', 'PUT')
  await host.getByRole('button', { name: '保存激发条件', exact: true }).click()
  assert.equal((await pending).status(), 200)
  const evaporationReload = page.waitForResponse(response => response.url().includes('/acquisitions/options') && response.request().method() === 'GET')
  host = await go('evaporation-acquisition')
  await host.getByRole('button', { name: '刷新', exact: true }).click()
  await evaporationReload
  await settle()
  assert.equal((await call(page, '/api/v1/acquisitions/options')).preliminary_defaults.evaporation.frame_count, 11)
  await openForm(host, '建立蒸发摄谱任务')
  await page.waitForFunction(() => [...document.querySelectorAll('[data-testid="evaporation-acquisition-page"] label')]
    .some(label => label.querySelector('span')?.textContent === '采样次数' && label.querySelector('input')?.value === '11'))
  assert.equal(await host.getByLabel('采样次数', { exact: true }).inputValue(), '11')
  assert.equal(await host.getByLabel('空白次数', { exact: true }).inputValue(), '7')
  const defaults = (await call(page, '/api/v1/acquisitions/options')).preliminary_defaults
  assert.equal(defaults.dispersion.pre_excitation_seconds, 6)
  assert.equal(defaults.evaporation.pre_excitation_seconds, 4.5)
  check(6, '色散和蒸发独立保存、重新进入自动载入；非法值零提交')

  host = await go('analysis')
  await host.getByRole('button', { name: '谱图与测量', exact: true }).click()
  const spectrum = host.locator('.analysis-spectrum')
  pending = page.waitForResponse(response => response.url().includes('/spectra/0?line_id='))
  await spectrum.getByRole('button', { name: /^Cu / }).click()
  assert.equal((await pending).status(), 200)
  await spectrum.getByText('观察曝光区间：1–2 帧', { exact: true }).waitFor()
  await fill(spectrum, '读取点位', 903)
  assert.match(await spectrum.getByLabel('任意点强度').textContent(), /490\.000000/)
  check(2, '选谱线同步1–2帧及CCD，原第903点显示490，定量和查看一致')
  await spectrum.getByRole('button', { name: '查看分时明细', exact: true }).click()
  const detail = spectrum.getByRole('region', { name: '原始积分明细' })
  await detail.locator('tbody tr').nth(3).waitFor()
  assert.deepEqual(await detail.locator('tbody tr td:last-child').allTextContents(), ['900', '600', '9000', '20'])
  await detail.getByRole('button', { name: '纵向复制', exact: true }).click()
  await page.waitForFunction(() => window.__operatorClipboard.includes('燃烧\t3\t9000'))
  assert.match(await page.evaluate(() => window.__operatorClipboard), /燃烧\t3\t9000/)
  await detail.getByRole('button', { name: '横向复制', exact: true }).click()
  await page.waitForFunction(() => window.__operatorClipboard.includes('空白1\t20'))
  assert.match(await page.evaluate(() => window.__operatorClipboard), /空白1\t20/)
  pending = mutation('/point-details/print', 'POST')
  await detail.getByRole('button', { name: '打印积分明细 PDF', exact: true }).click()
  const detailPdf = await pending
  assert.equal(detailPdf.status(), 200)
  await saveCapturedPdf('raw-point-details.pdf', 0)
  check(4, '任意点完整燃烧/空白原值、周期信息、横纵复制格式和真实PDF输出')

  await host.getByRole('button', { name: '标准点', exact: true }).click()
  await host.getByRole('columnheader', { name: '相对误差 %', exact: true }).waitFor()
  assert.equal(await host.locator('.analysis-matrix tbody tr').count(), 4)
  assert.ok(!(await host.locator('.analysis-matrix tbody').textContent()).includes('待重新拟合'))
  await host.getByRole('button', { name: '曲线图', exact: true }).click()
  pending = mutation('/preview?mode=text', 'GET')
  await host.getByRole('button', { name: '文本预览', exact: true }).click()
  const html = await pending
  assert.match(await html.text(), /相对误差 %/)
  check(7, '标准点表显示反算含量/相对误差，文本预览带百分误差列')
  // Close the existing preview overlay before manipulating the chart.
  const preview = page.getByRole('dialog')
  await preview.waitFor()
  await preview.getByRole('button', { name: '关闭', exact: true }).click()
  const operator = host.getByLabel('标准点标尺操作', { exact: true })
  await operator.getByLabel('曲线标准点', { exact: true }).selectOption('1')
  await operator.getByLabel('标准点标尺', { exact: true }).selectOption('1')
  await operator.focus()
  pending = mutation('/actions', 'POST')
  await operator.press('Control+ArrowUp')
  const action = await pending
  assert.equal(action.status(), 200)
  const adjusted = await action.json()
  assert.ok(adjusted.curves.lines[0].workspace.points[1].adjusted_intensity > 200)
  await host.getByRole('button', { name: '文本打印 PDF', exact: true }).waitFor({ state: 'visible' })
  assert.equal(await host.getByRole('button', { name: '文本打印 PDF', exact: true }).isDisabled(), true)
  await operator.press('Insert')
  assert.equal(await operator.getByLabel('标准点标尺', { exact: true }).inputValue(), '5')
  await operator.press('Control+ArrowRight')
  assert.equal(await operator.getByLabel('曲线标准点', { exact: true }).inputValue(), '2')
  pending = mutation('/fit', 'POST')
  await host.getByRole('button', { name: '重新拟合', exact: true }).click()
  assert.equal((await pending).status(), 201)
  await host.getByRole('button', { name: '文本打印 PDF', exact: true }).waitFor()
  assert.equal(await host.getByRole('button', { name: '文本打印 PDF', exact: true }).isEnabled(), true)
  for (const index of [0, 1, 2, 3]) {
    await host.getByRole('button', { name: `标准点 S${index + 1}`, exact: true }).click()
    assert.equal(await operator.getByLabel('曲线标准点', { exact: true }).inputValue(), String(index))
  }
  check(10, '图上选点，Ctrl方向键/Insert/1和5标尺微调，修改后禁止旧拟合打印，重新拟合恢复')

  host = await go('analysis-tests.spectra')
  await host.getByLabel('谱图来源', { exact: true }).selectOption('raw')
  await host.locator('.spectrum-record-row').filter({ hasText: 'Raw sample' }).getByRole('button').click()
  await host.locator('.spectrum-record-row').filter({ hasText: 'Raw comparison' }).locator('input[type=checkbox]').check()
  await host.locator('.spectrum-legend button').nth(1).waitFor()
  const locate = host.locator('.spectrum-locate input')
  await locate.fill('2,3')
  await host.getByRole('button', { name: '定位并锁定', exact: true }).click()
  await host.getByRole('heading', { name: '同点强度 · CCD 2 · 点 3', exact: true }).waitFor()
  assert.match(await host.locator('.spectrum-cursor-readout').textContent(), /点 3/)
  const matrix = host.getByRole('region', { name: '多样品同点强度' })
  assert.deepEqual((await matrix.locator('tbody tr td:last-child').allTextContents()).sort(), ['10.000000', '20.000000'])
  check(3, '两份原始谱图叠加，同一CCD/点位并列读取全部样品强度')
  await page.screenshot({ path: path.join(output, 'spectrum-same-point-light.png'), fullPage: true })
  const plot = host.getByTestId('spectrum-plot')
  await plot.focus(); await plot.press('ArrowRight')
  await host.getByRole('heading', { name: '同点强度 · CCD 2 · 点 4', exact: true }).waitFor()
  assert.deepEqual((await matrix.locator('tbody tr td:last-child').allTextContents()).sort(), ['11.000000', '22.000000'])
  const beforeY = await host.locator('.spectrum-pan').textContent()
  await plot.press('ArrowUp')
  assert.notEqual(await host.locator('.spectrum-pan').textContent(), beforeY)
  check(9, 'CCD,点位跨CCD定位、锁定、方向键逐点移动及纵向缩放')
  const settings = host.locator('.spectrum-print-settings')
  await settings.locator('summary').click()
  await settings.getByLabel('灰度谱带', { exact: true }).check()
  await settings.getByLabel('峰形', { exact: true }).uncheck()
  await settings.getByLabel('灰度谱带', { exact: true }).click()
  assert.equal(await settings.getByLabel('灰度谱带', { exact: true }).isChecked(), true)
  await settings.getByLabel('峰形', { exact: true }).check()
  await settings.getByLabel('CCD 打印范围', { exact: true }).selectOption('ccd')
  await settings.getByLabel('CCD 打印比例', { exact: true }).selectOption('fit_short')
  pending = mutation('/print-pdf', 'POST')
  const previousExports = await page.evaluate(() => window.__operatorExports.length)
  await host.getByRole('button', { name: '打印 PDF', exact: true }).click()
  const print = await pending
  assert.equal(print.status(), 200)
  await saveCapturedPdf('ccd-gray-and-curve.pdf', previousExports)
  assert.deepEqual(print.request().postDataJSON().print_layers.sort(), ['curve', 'grayscale'])
  assert.equal(print.request().postDataJSON().print_scope, 'ccd')
  check(8, '当前CCD/当前图像、灰度/峰形至少一层、纸张窄边的真实PDF输出；十倍物理尺寸由黄金测试验证')

  host = await go('sample-acquisition')
  await host.locator('.acquisition-task-rows button').filter({ hasText: 'Queue operator QA' }).click()
  await host.getByRole('button', { name: '试样摄谱', exact: true }).click()
  for (let attempt = 0; attempt < 160; attempt++) {
    const current = (await call(page, '/api/v1/acquisitions/tasks')).find(item => item.queue_id === fixture.queue_id)
    if (current.status === 'completed') break
    if (current.status === 'between_repeats') await host.getByRole('button', { name: '试样摄谱', exact: true }).click()
    await page.waitForTimeout(100)
  }
  await host.getByText('已带出下一样号：QUEUEB，请创建任务后激发。', { exact: true }).waitFor({ timeout: 30000 })
  await openForm(host, '建立样品摄谱任务')
  assert.equal(await host.locator('label').filter({ has: page.getByText('预录样品', { exact: true }) }).locator('select').inputValue(), String(fixture.queue_item_ids[1]))
  const queue = (await call(page, '/api/v1/sample-queues')).find(item => item.id === fixture.queue_id)
  assert.ok(queue.items[0].spectrum_hash)
  assert.equal(queue.items[1].spectrum_hash, null)
  const linked = (await call(page, '/api/v1/acquisitions/tasks')).filter(item => item.queue_id === fixture.queue_id)
  assert.equal(linked.length, 1); assert.equal(linked[0].status, 'completed')
  check(1, '当前项全部重复完成后自动带出下一样号及次数，保留结果哈希，不自动激发下一项')

  for (const [theme, width] of [['light', 1440], ['dark', 1060]]) {
    await call(page, '/api/v1/settings', { display: { theme } }, 'PATCH')
    await page.reload(); await page.getByTestId('workspace').waitFor(); await capture()
    if (process.env.QA_CDP) {
      await page.evaluate(async width => window.__TAURI__.core.invoke('plugin:window|set_size', {
        value: { Logical: { width, height: 1000 } }
      }), width)
    } else await page.setViewportSize({ width, height: 1000 })
    for (const target of ['analysis-tests.spectra', 'analysis', 'sample-acquisition', 'dispersion', 'evaporation-acquisition', 'settings']) {
      const surface = await go(target)
      if (target === 'analysis') await surface.getByRole('button', { name: '曲线图', exact: true }).click()
      const dimensions = await page.evaluate(() => ({ viewport: document.documentElement.clientWidth,
        document: document.documentElement.scrollWidth, body: document.body.scrollWidth }))
      result.layouts.push({ theme, target, ...dimensions })
      assert.ok(dimensions.document <= dimensions.viewport && dimensions.body <= dimensions.viewport, `${theme}/${target} overflow: ${JSON.stringify(dimensions)}`)
      if (['analysis-tests.spectra', 'analysis', 'sample-acquisition'].includes(target))
        await page.screenshot({ path: path.join(output, `${target.replaceAll('.', '-')}-${theme}.png`), fullPage: true })
    }
  }
  assert.equal((await call(page, `/api/v1/methods/${fixture.method_id}/versions`)).find(v => v.content_sha256 === fixture.method_hash)?.content_sha256, fixture.method_hash)
  assert.equal(new Set(result.checks.map(item => item.id)).size, 10)
}
