import assert from 'node:assert/strict'
import path from 'node:path'
import { call, navigate } from './contract_browser_support.mjs'

export async function checkSerialProfiles(page, result, output) {
  const before = await call(page, '/api/v1/devices/profiles')
  await navigate(page, 'tools', '设备调试', '.device-debug-page')
  await page.getByRole('tab', { name: '设备参数', exact: true }).click()
  const createdResponse = page.waitForResponse(response => response.request().method() === 'POST' && response.url().endsWith('/devices/profiles'))
  await page.getByRole('button', { name: '新建串口档案', exact: true }).click()
  const response = await createdResponse
  assert.equal(response.status(), 201)
  const created = await response.json()
  assert.equal(created.transport, 'serial')
  assert.equal(created.baud_rate, 460800)
  assert.deepEqual((await call(page, '/api/v1/devices/profiles')).slice(0, before.length), before)
  // Intercept before any real check can open a COM port.
  let requested = 0
  const pattern = `**/api/v1/devices/profiles/${created.id}/connection-test**`
  await page.route(pattern, async route => {
    requested++
    await route.fulfill({status:409,contentType:'application/json',body:JSON.stringify({detail:{
      code:'device_connection_test_failed',message:'验收注入：串口可打开但未收到有效CCD响应',details:{connected:false}}})})
  })
  await page.getByRole('button', { name: '连接测试', exact: true }).click()
  await page.getByText('验收注入：串口可打开但未收到有效CCD响应', { exact: true }).first().waitFor()
  assert.equal(requested, 1)
  await page.getByRole('tab', { name: '调试对中', exact: true }).click()
  await page.waitForFunction(()=>document.querySelector('#device-tab-alignment')?.disabled===false)
  assert.equal(await page.getByRole('tab',{name:'设备参数',exact:true}).getAttribute('aria-selected'),'true')
  assert.equal(requested, 2)
  assert.equal((await call(page, '/api/v1/devices/diagnostics')).adapter.connected, false)
  await page.waitForFunction(()=>[...document.querySelectorAll('.alignment-curve')].every(node=>!node.getAttribute('d')))
  result.checks.push('串口可打开但无有效CCD响应时，设备参数测试失败，不能进入真实调试对中，原档案及参数保持')
  await page.unroute(pattern)
  await page.screenshot({ path: path.join(output, 'serial-profile.png') })
  return created
}
