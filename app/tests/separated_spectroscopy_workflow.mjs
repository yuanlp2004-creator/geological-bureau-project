import assert from 'node:assert/strict'
import path from 'node:path'
import { call, navigate } from './contract_browser_support.mjs'

export async function checkSeparatedSpectroscopy(page, fixture, result, output) {
  const check = (message) => { result.checks.push(message); console.log(`PASS: ${message}`) }
  const resize = async (width, height = 1000) => {
    if (process.env.QA_CDP) await page.evaluate(({ width, height }) => window.__TAURI__.core.invoke('plugin:window|set_size', { value: { Logical: { width, height } } }), { width, height })
    else await page.setViewportSize({ width, height })
  }
  await resize(1440)
  const caps = (await call(page, '/api/v1/capabilities')).capabilities
  const entries = caps.flatMap((capability) => capability.navigation_entries)
  assert.equal(entries.length, 29)
  const go = async (key) => {
    const entry = entries.find((item) => item.key === key)
    assert.ok(entry, key)
    await navigate(page, entry.group, entry.label, '.page-content')
    if (entry.page !== 'evaporation-curves') await page.waitForFunction(() => !document.querySelector('.spectroscopy-lock'))
  }
  const captureChecks = async (scope) => {
    for (const heading of ['全时采集区间', '蒸发区间', '谱线定位与位置', '拟合、发布与方法绑定', '色散曲线版本管理'])
      assert.equal(await scope.getByRole('heading', { name: heading, exact: true }).count(), 0)
    assert.equal(await scope.getByRole('button', { name: '标记区间', exact: true }).count(), 0)
    assert.equal(await scope.locator('.interval-form').count(), 0)
    assert.equal(await scope.getByTestId('spectroscopy-console').count(), 1)
  }
  for (const [key, id] of [['analysis-tests.acquisition', 'sample-acquisition-page'], ['analysis-tests.evaporation', 'evaporation-acquisition-page'], ['analysis-tests.dispersion', 'dispersion-page']]) {
    await go(key)
    await captureChecks(page.getByTestId(id))
  }
  check('三个摄谱页只有采集与观察，均无手工区间卡片或色散曲线编辑区')

  const sample = (await call(page, '/api/v1/acquisitions/tasks?task_kind=sample')).find((task) => task.status === 'completed' && task.samples.some((item) => !item.discarded))
  assert.ok(sample)
  await go('analysis-tests.acquisition')
  const host = page.getByTestId('sample-acquisition-page')
  await host.locator('.acquisition-task-list button').filter({ hasText: sample.name }).click()
  const rename = host.getByTestId('acquisition-rename')
  assert.equal(await rename.evaluate((node) => !!node.closest('.spectroscopy-setup')), true)
  await rename.locator('summary').click()
  await rename.getByLabel('采集后样号长度').selectOption('20')
  const input = rename.getByPlaceholder('完整采集后输入正式样号')
  await input.fill('SPLIT-RENAME-20')
  const url = `/api/v1/acquisitions/tasks/${sample.id}/samples/${sample.samples.find((item) => !item.discarded).id}/rename`
  const failureRoute = async (route) => route.fulfill({ status: 409, contentType: 'application/json', body: JSON.stringify({ detail: { message: 'QA重命名失败保留输入' } }) })
  await page.route(`**${url}`, failureRoute)
  await rename.getByRole('button', { name: '保存名称', exact: true }).click()
  await page.getByText('QA重命名失败保留输入', { exact: true }).waitFor()
  assert.equal(await input.inputValue(), 'SPLIT-RENAME-20')
  await page.unroute(`**${url}`, failureRoute)
  let release, arrived
  const arrival = new Promise((resolve) => { arrived = resolve })
  const gate = new Promise((resolve) => { release = resolve })
  const delayed = async (route) => { arrived(); await gate; await route.continue() }
  await page.route(`**${url}`, delayed)
  const response = page.waitForResponse((item) => item.url().endsWith(url) && item.request().method() === 'POST')
  await rename.getByRole('button', { name: '保存名称', exact: true }).click()
  await arrival
  assert.equal(await rename.getByRole('button', { name: '保存名称', exact: true }).isDisabled(), true)
  assert.equal(await host.locator('.acquisition-task-list button').first().isDisabled(), true)
  release()
  assert.equal((await response).status(), 200)
  await page.unroute(`**${url}`, delayed)
  await page.waitForFunction(() => !document.querySelector('.spectroscopy-lock'))
  const renamed = await call(page, `/api/v1/acquisitions/tasks/${sample.id}`)
  assert.equal(renamed.sample_name, 'SPLIT-RENAME-20')
  assert.equal(renamed.result_sha256, sample.result_sha256)
  assert.equal(renamed.samples[0].result_sha256, sample.samples[0].result_sha256)
  const renameOverflow = await rename.evaluate((node) => Math.max(...[node, ...node.querySelectorAll('.sample-result-list')].map((item) => item.scrollWidth - item.clientWidth)))
  assert.ok(renameOverflow <= 1, `sidebar rename must wrap without horizontal scrolling: ${renameOverflow}`)
  assert.ok(await host.getByRole('heading', { name: '即时测量结果', exact: true }).isVisible())
  assert.ok(await host.getByRole('button', { name: '删除异常样品（能量不足）', exact: true }).isVisible())
  await page.screenshot({ path: path.join(output, 'rename-sidebar.png') })
  check('采后重命名位于右侧，20位名称保存且哈希保持；失败留稿、请求期间禁止重复和换任务，即时结果与异常删除保留')

  const curveTask = await call(page, '/api/v1/dispersion/tasks', { name: '独立色散曲线测试', frame_count: 1, dark_frame_count: 0, pre_excitation_seconds: 0,
    lines: [{ element: 'A', wavelength_nm: 250, ccd_index: 0, actual_position: 100 }, { element: 'B', wavelength_nm: 260, ccd_index: 0, actual_position: 200 }, { element: 'C', wavelength_nm: 270, ccd_index: 0, actual_position: 300 }] })
  // Refresh once in capture; the same mounted state is retained by the curve entry.
  await go('analysis-tests.dispersion')
  let dispersion = page.getByTestId('dispersion-page')
  await dispersion.getByRole('button', { name: '刷新', exact: true }).click()
  await dispersion.locator('.dispersion-task-list button').filter({ hasText: curveTask.name }).click()
  await page.waitForFunction(() => !document.querySelector('.spectroscopy-lock'))
  await go('analysis-tests.dispersion-curves')
  assert.equal(await dispersion.getAttribute('data-view'), 'curve')
  assert.equal(await dispersion.getByTestId('spectroscopy-console').count(), 0)
  assert.equal(await dispersion.getByRole('button', { name: '新建任务', exact: true }).count(), 0)
  await dispersion.getByLabel('元素', { exact: true }).fill('KEEP-DRAFT')
  await page.getByRole('button', { name: '返回色散摄谱', exact: true }).click()
  await captureChecks(dispersion)
  await go('analysis-tests.dispersion-curves')
  assert.equal(await dispersion.getByLabel('元素', { exact: true }).inputValue(), 'KEEP-DRAFT')
  const fitResponse = page.waitForResponse((item) => item.url().endsWith(`/dispersion/tasks/${curveTask.id}/calibrations/fit`) && item.request().method() === 'POST')
  await dispersion.getByRole('button', { name: '二次拟合', exact: true }).click()
  assert.equal((await fitResponse).status(), 201)
  const publish = dispersion.getByRole('button', { name: '发布版本', exact: true })
  assert.equal(await publish.isEnabled(), true)
  const publishing = page.waitForResponse((item) => item.url().endsWith('/publish') && item.request().method() === 'POST')
  await publish.click(); assert.equal((await publishing).status(), 200)
  await dispersion.locator('.dispersion-bind select').selectOption(String(fixture.method_id))
  const binding = page.waitForResponse((item) => item.url().endsWith('/bind') && item.request().method() === 'POST')
  await dispersion.getByRole('button', { name: '绑定修订', exact: true }).click(); assert.equal((await binding).status(), 200)
  await page.waitForFunction(() => !document.querySelector('.spectroscopy-lock'))
  await page.screenshot({ path: path.join(output, 'dispersion-curves.png') })
  check('独立色散曲线可定位编辑、拟合、发布并绑定；摄谱与曲线切换保留同一任务及草稿，曲线页没有采集按钮')

  const evaporation = (await call(page, '/api/v1/acquisitions/tasks?task_kind=evaporation')).find((task) => task.status === 'completed')
  const frames = await call(page, `/api/v1/acquisitions/tasks/${evaporation.id}/frames?phase=burn`)
  let writes = 0
  const observe = (request) => { if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(request.method())) writes++ }
  page.on('request', observe)
  await go('analysis-tests.evaporation-curves')
  const curves = page.getByTestId('evaporation-curves-page')
  await curves.locator('.acquisition-task-list button').filter({ hasText: evaporation.name }).click()
  await curves.getByTestId('evaporation-time-chart').waitFor()
  const expected = frames.filter((frame) => frame.ccd_index === 0 && !frame.damaged).sort((a, b) => a.virtual_time_ms - b.virtual_time_ms || a.frame_index - b.frame_index)
  assert.equal(await curves.locator('tbody tr').count(), expected.length)
  assert.equal(await curves.locator('tbody tr').first().locator('td').last().innerText(), String(expected[0].peak_value))
  await curves.getByLabel('蒸发曲线数据').selectOption('integral_value')
  assert.equal(await curves.locator('tbody tr').first().locator('td').last().innerText(), String(expected[0].integral_value))
  const plotted = await curves.locator('polyline').getAttribute('points')
  assert.equal(plotted.trim().split(/\s+/).length, expected.length)
  assert.ok(plotted.trim().split(/\s+/).every((pair) => { const y = Number(pair.split(',')[1]); return y > 0 && y < 300 }), 'curve stays inside the plot area')
  assert.equal(writes, 0)
  page.off('request', observe)
  await page.screenshot({ path: path.join(output, 'evaporation-curves.png') })
  check('独立蒸发曲线读取实际保存的燃烧帧，峰值/积分及时间与API一致，查看和切换零业务写入')

  const failing = async (route) => route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: { message: 'QA蒸发帧读取失败' } }) })
  await page.route(`**/acquisitions/tasks/${evaporation.id}/frames*`, failing)
  await curves.getByRole('button', { name: '刷新', exact: true }).click()
  await curves.getByRole('alert').waitFor()
  assert.equal(await curves.getByTestId('evaporation-time-chart').count(), 0)
  await page.unroute(`**/acquisitions/tasks/${evaporation.id}/frames*`, failing)
  await curves.getByRole('button', { name: '刷新', exact: true }).click()
  await curves.getByTestId('evaporation-time-chart').waitFor()
  check('蒸发帧读取失败清空旧曲线，刷新恢复，不将旧任务数据冒充新结果')

  for (const [width, theme] of [[1440, 'light'], [1060, 'dark']]) {
    await resize(width)
    await page.evaluate((theme) => { document.documentElement.dataset.theme = theme; document.querySelector('.app-shell').dataset.theme = theme }, theme)
    for (const key of ['analysis-tests.dispersion-curves', 'analysis-tests.evaporation-curves']) {
      await go(key)
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)
      assert.ok(overflow <= 1)
      result.layouts.push({ key, width, theme, overflow })
      await page.screenshot({ path: path.join(output, `${key}-${width}-${theme}.png`) })
    }
  }
  check('两个独立曲线入口在1440明色/1060暗色下可用且无整页横向溢出')
}
