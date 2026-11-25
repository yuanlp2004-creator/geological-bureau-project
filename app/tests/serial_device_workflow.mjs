import assert from 'node:assert/strict'
import path from 'node:path'
import { call, navigate } from './contract_browser_support.mjs'
import { readAlignmentCanvases } from './alignment_turn_workflow.mjs'

export async function checkSerialProfiles(page, result, output) {
  const before = await call(page, '/api/v1/devices/profiles')
  const created = await call(page, '/api/v1/devices/profiles', { name: '串口对中 QA', transport: 'serial', port: 256 })
  await call(page, '/api/v1/devices/current', { profile_id: created.id }, 'PUT')
  await page.reload()
  await navigate(page, 'tools', '设备调试', '.device-debug-page')
  await page.getByRole('tab', { name: '设备参数', exact: true }).click()
  assert.equal(created.transport, 'serial')
  assert.equal(created.baud_rate, 460800)
  // Intercept before any real check can open a COM port.
  let requested = 0, unexpectedConnects = 0
  const pattern = `**/api/v1/devices/profiles/${created.id}/connection-test**`
  const connectPattern = '**/api/v1/devices/connect'
  await page.route(connectPattern, async route => {
    unexpectedConnects++
    await route.fulfill({ status: 409, json: { detail: 'Unexpected serial connect' } })
  })
  const failure = '验收注入：串口可打开但未收到有效CCD响应'
  await page.route(pattern, async route => {
    requested++
    await route.fulfill({status:409,contentType:'application/json',body:JSON.stringify({detail:{
      code:'device_connection_test_failed',message:failure,details:{connected:false}}})})
  })
  await page.getByRole('button', { name: '连接测试', exact: true }).click()
  await page.getByRole('tabpanel', { name: '设备参数' }).getByText(failure, { exact: true }).waitFor()
  assert.equal(requested, 1)
  await page.getByRole('tab', { name: '调试对中', exact: true }).click()
  const desk = page.getByRole('region', { name: '调试对中工作台' })
  const probe = page.waitForResponse(response => new URL(response.url()).pathname.endsWith(`/profiles/${created.id}/connection-test`))
  await desk.getByRole('button', { name: '连接诊断', exact: true }).click()
  assert.equal((await probe).status(), 409)
  await desk.getByRole('button', { name: '连接诊断', exact: true }).click({ trial: true })
  assert.equal(requested, 2)
  assert.equal(unexpectedConnects, 0)
  assert.equal((await call(page, '/api/v1/devices/diagnostics')).adapter.connected, false)
  assert.equal(await desk.getByRole('button', { name: '开始', exact: true }).isDisabled(), true)
  const plots = await desk.locator('canvas.alignment-canvas-layer').evaluateAll(readAlignmentCanvases)
  assert.equal(plots.length, 3)
  for (const plot of plots) {
    assert.equal(plot.pointCount, '0')
    assert.ok(plot.renderSeq > 0 && plot.backgroundPixels > 0 && plot.gridPixels > 0, JSON.stringify(plot))
    assert.equal(plot.otherPixels, 0, JSON.stringify(plot))
  }
  assert.equal(await desk.locator('svg .alignment-curve').count(), 0)
  assert.deepEqual((await call(page, '/api/v1/devices/profiles')).slice(0, before.length), before)
  result.checks.push('串口无有效 CCD 响应时设备未连接，调试启动保持禁用，三路 Canvas 只显示底色和网格，原档案及参数保持')
  await page.unroute(pattern)
  await page.unroute(connectPattern)
  await page.screenshot({ path: path.join(output, 'serial-profile.png') })
  return created
}
