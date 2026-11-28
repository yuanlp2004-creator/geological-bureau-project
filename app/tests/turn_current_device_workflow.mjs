import assert from 'node:assert/strict'
import { call, navigate } from './contract_browser_support.mjs'

// Run only against an isolated database: current-device writes never touch user data.
export async function checkTurnCurrentDevice(page, result) {
  const simulator = await call(page, '/api/v1/devices/profiles', { name: '转角当前模拟设备' })
  const serial = await call(page, '/api/v1/devices/profiles', { name: '转角当前串口', transport: 'serial', port: 256 })
  const select = profile => call(page, '/api/v1/devices/current', { profile_id: profile.id }, 'PUT')
  await select(simulator)
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
}
