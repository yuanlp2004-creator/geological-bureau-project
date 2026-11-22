import assert from 'node:assert/strict'
import path from 'node:path'
import { call, navigate } from './contract_browser_support.mjs'

// Run only against an isolated database: current-device writes never touch user data.
export async function checkTurnCurrentDevice(page, result, output) {
  const simulator = await call(page, '/api/v1/devices/profiles', { name: '转角当前模拟设备' })
  const serial = await call(page, '/api/v1/devices/profiles', { name: '转角当前串口', transport: 'serial', port: 256 })
  const select = profile => call(page, '/api/v1/devices/current', { profile_id: profile.id }, 'PUT')
  await select(simulator)
  const options = await call(page, '/api/v1/hardware-acquisitions/options')
  assert.notEqual(options.profiles[0].id, simulator.id)
  const method = options.methods.find(item => item.turns?.length)
  assert.ok(method, 'Seed must provide a published method with turns')
  await navigate(page, 'tools', '设备调试', '[data-testid="device-debug-page"]')
  await page.getByRole('tab', { name: '调试对中', exact: true }).click()
  const debug = page.locator('.device-debug-panel:visible').getByTestId('acquisition-page')
  assert.equal(await debug.getByText('设备档案', { exact: true }).count(), 0)
  await debug.getByRole('button', { name: '连接诊断', exact: true }).click()
  await page.waitForFunction(() => !document.querySelector('.device-debug-panel:not([hidden]) [data-testid="acquisition-page"] button')?.disabled)
  await debug.getByRole('button', { name: '开始', exact: true }).waitFor({ state: 'visible' })
  assert.equal((await call(page, '/api/v1/devices/diagnostics')).adapter.profile_id, simulator.id)
  await debug.getByRole('button', { name: '开始', exact: true }).click()
  await debug.getByRole('button', { name: '停止', exact: true }).waitFor({ state: 'visible' })
  await page.waitForFunction(() => !Array.from(document.querySelectorAll('.device-debug-panel:not([hidden]) button')).find(b => b.textContent.trim() === '停止')?.disabled)
  await debug.getByRole('button', { name: '停止', exact: true }).click()
  await debug.getByRole('button', { name: '断开', exact: true }).click()
  assert.equal((await call(page, '/api/v1/devices/diagnostics')).adapter.connected, false)
  result.checks.push('调试对中取消独立档案，沿用当前模拟设备并完成开始／停止／断开')

  await select(serial)
  const debugAttempts = []
  const debugProbe = '**/api/v1/devices/profiles/*/connection-test?*'
  await page.route(debugProbe, route => {
    debugAttempts.push(route.request().url())
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ passed: false, instrument_responded: false }) })
  })
  await debug.getByRole('button', { name: '连接诊断', exact: true }).click()
  await page.getByText('未收到有效CCD响应，请在设备参数中完成连接测试后再进入摄谱', { exact: true }).waitFor()
  assert.ok(debugAttempts.length === 1 && debugAttempts[0].includes(`/profiles/${serial.id}/connection-test?purpose=devices`))
  assert.equal((await call(page, '/api/v1/devices/diagnostics')).adapter.connected, false)
  await page.unroute(debugProbe)
  await select(simulator)
  result.checks.push('调试对中执行时重读当前串口，检查失败保持断开')
  await navigate(page, 'analysis-tests', '自动转角采集', '[data-testid="hardware-acquisition-page"]')
  const host = page.getByTestId('hardware-acquisition-page'), dialog = host.getByRole('dialog')
  const submit = () => dialog.getByRole('button', { name: '建立任务', exact: true }).click()
  const open = async () => {
    await page.getByRole('button', { name: '新建任务', exact: true }).click()
    await dialog.getByLabel('采集方法', { exact: true }).selectOption(`${method.method_id}-${method.version}`)
    assert.equal(await dialog.getByLabel('设备档案', { exact: true }).count(), 0)
    assert.equal(await dialog.getByText('设备档案', { exact: true }).count(), 0)
  }
  let posts = 0
  const countPosts = request => {
    if (request.method() === 'POST' && request.url().endsWith('/api/v1/hardware-acquisitions/tasks')) posts++
  }
  page.on('request', countPosts)
  await open()
  await dialog.getByLabel('任务名称', { exact: true }).fill('统一设备自动任务')
  await submit(); await host.locator('.hardware-capture-desk').waitFor()
  const automatic = (await call(page, '/api/v1/hardware-acquisitions/tasks'))[0]
  assert.equal(automatic.device_profile_id, simulator.id)
  assert.equal(automatic.transport, 'simulator')
  assert.equal(automatic.execution_mode, 'automatic')
  await host.getByRole('button', { name: '返回任务列表', exact: true }).click()
  result.checks.push('自动任务使用设备参数当前选择，忽略档案首项')

  await open()
  await dialog.getByRole('button', { name: '手动', exact: true }).click()
  assert.equal(await dialog.getByLabel('设备档案', { exact: true }).count(), 0)
  await dialog.getByLabel('任务名称', { exact: true }).fill('统一设备手动任务')
  await dialog.getByLabel('手动角度 1', { exact: true }).selectOption(String(method.turns[0].angle_deg))
  await dialog.getByLabel('采集时长 1', { exact: true }).fill(String(Math.max(10, method.turns[0].end_frame * method.sampling_period_seconds)))
  await submit(); await host.locator('.hardware-capture-desk').waitFor()
  const manual = (await call(page, '/api/v1/hardware-acquisitions/tasks'))[0]
  assert.equal(manual.device_profile_id, simulator.id)
  assert.equal(manual.execution_mode, 'manual')
  await host.getByRole('button', { name: '返回任务列表', exact: true }).click()
  result.checks.push('手动任务共用设备来源，方法转角与时长正常提交')

  await select(serial)
  await open()
  await dialog.getByRole('button', { name: '自动', exact: true }).click()
  await dialog.getByLabel('任务名称', { exact: true }).fill('连接失败保留草稿')
  await dialog.getByRole('status').filter({ hasText: '转角协议尚未接入' }).waitFor()
  assert.equal(await dialog.getByText('模拟调试参数', { exact: true }).count(), 0)
  const attempts = []
  const probePattern = '**/api/v1/devices/profiles/*/connection-test?*'
  await page.route(probePattern, route => {
    attempts.push(route.request().url())
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ passed: false, instrument_responded: false }) })
  })
  const beforeFailure = posts
  for (const mode of ['自动', '手动']) {
    await dialog.getByRole('button', { name: mode, exact: true }).click()
    await submit()
    await dialog.getByRole('alert').filter({ hasText: '未收到有效CCD响应' }).waitFor()
    assert.equal(await dialog.getByLabel('任务名称', { exact: true }).inputValue(), '连接失败保留草稿')
    assert.equal(posts, beforeFailure)
  }
  assert.equal(attempts.length, 2)
  assert.ok(attempts.every(url => url.includes(`/profiles/${serial.id}/connection-test?purpose=hardware-acquisition`)))
  await page.unroute(probePattern)
  result.checks.push('打开表单刷新通讯口，自动和手动均检查当前串口，响应失败零建任务')

  // Controlled CCD success verifies routing only; no physical serial port is opened.
  await page.route(probePattern, route => route.fulfill({ status: 200, contentType: 'application/json',
    body: JSON.stringify({ passed: true, instrument_responded: true }) }))
  await submit(); await host.locator('.hardware-capture-desk').waitFor()
  const serialTask = (await call(page, '/api/v1/hardware-acquisitions/tasks'))[0]
  assert.equal(serialTask.device_profile_id, serial.id)
  assert.equal(serialTask.transport, 'serial')
  await page.unroute(probePattern)
  await host.getByRole('button', { name: '返回任务列表', exact: true }).click()
  await open()
  result.checks.push('受控CCD成功响应后任务绑定当前串口，未打开物理串口')

  const currentPattern = '**/api/v1/devices/current'
  for (const missing of [true, false]) {
    await page.route(currentPattern, route => route.fulfill({ status: missing ? 200 : 503, contentType: 'application/json',
      body: missing ? 'null' : JSON.stringify({ detail: '设备参数暂时读取失败' }) }))
    await submit()
    await dialog.getByRole('alert').filter({ hasText: missing ? '请先在设备参数中选择通讯口' : '设备参数暂时读取失败' }).waitFor()
    assert.equal(posts, beforeFailure + 1)
    assert.equal(await dialog.getByLabel('任务名称', { exact: true }).inputValue(), '连接失败保留草稿')
    await page.unroute(currentPattern)
  }
  result.checks.push('未选设备或读取失败均保留输入，不回退模拟器或旧档案')

  // Switch after the dialog was opened. Submission must read the new current selection.
  await select(simulator)
  await submit(); await host.locator('.hardware-capture-desk').waitFor()
  const retried = (await call(page, '/api/v1/hardware-acquisitions/tasks'))[0]
  assert.equal(retried.device_profile_id, simulator.id)
  assert.equal(retried.execution_mode, 'manual')
  assert.equal((await call(page, `/api/v1/hardware-acquisitions/tasks/${automatic.id}`)).device_profile_id, simulator.id)
  assert.equal((await call(page, `/api/v1/hardware-acquisitions/tasks/${serialTask.id}`)).device_profile_id, serial.id)
  assert.equal(posts, beforeFailure + 2)
  await host.getByRole('button', { name: '返回任务列表', exact: true }).click()
  result.checks.push('提交时重读设备选择，失败重试正常，历史任务原引用保持')

  await open()
  const layouts = []
  for (const width of [1440, 1060]) {
    if (process.env.QA_CDP) await page.evaluate(width => window.__TAURI__.core.invoke('plugin:window|set_size', { value: { Logical: { width, height: width === 1060 ? 680 : 1000 } } }), width)
    else await page.setViewportSize({ width, height: width === 1060 ? 680 : 1000 })
    for (const mode of ['自动', '手动']) {
      await dialog.getByRole('button', { name: mode, exact: true }).click()
      const geometry = await dialog.evaluate(element => ({ width: element.getBoundingClientRect().width, viewport: innerWidth,
        pageOverflow: document.documentElement.scrollWidth > innerWidth,
        contentOverflow: element.scrollWidth > element.clientWidth }))
      assert.equal(geometry.pageOverflow, false)
      assert.equal(geometry.contentOverflow, false)
      assert.ok(geometry.width <= geometry.viewport)
      await page.screenshot({ path: path.join(output, `turn-${width}-${mode}.png`) })
      layouts.push({ width, mode, ...geometry })
    }
  }
  result.layouts = layouts
  result.checks.push('两种窗口大小与自动／手动共四种布局，无档案选择及横向溢出')
  await dialog.getByRole('button', { name: '自动', exact: true }).click()
  page.off('request', countPosts)
}
