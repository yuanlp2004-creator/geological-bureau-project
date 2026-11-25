import assert from 'node:assert/strict'
import path from 'node:path'
import { checkAlignmentViews } from './alignment_workflow.mjs'
import { prepareContinuousCaptureMethod } from './continuous_capture_workflow.mjs'
import { call, navigate } from './contract_browser_support.mjs'

const turnPath = '/api/v1/devices/debug/turn'
const stepPath = '/api/v1/devices/debug/step'
const deferred = () => {
  let resolve
  const promise = new Promise(done => { resolve = done })
  return { promise, resolve }
}

export async function checkAlignmentTurns(page, checks, output) {
  if ((await call(page, turnPath)).angles.join(',') !== '4,17') await prepareContinuousCaptureMethod(page)
  const profile = await call(page, '/api/v1/devices/current')
  assert.equal(profile.transport, 'simulator')
  await page.reload()
  await navigate(page, 'tools', '设备调试', '.device-debug-page')
  const tabs = page.getByRole('tablist', { name: '设备调试功能' })
  assert.deepEqual(await tabs.getByRole('tab').allTextContents(), ['软件参数', '设备参数', '设备连接', '调试对中'])
  await tabs.getByRole('tab', { name: '调试对中' }).click()
  const desk = page.getByRole('region', { name: '调试对中工作台' })
  const toolbar = desk.getByRole('toolbar', { name: '调试对中查看工具' })
  const target = toolbar.getByLabel('目标转角')
  const change = toolbar.getByRole('button', { name: '切换转角', exact: true })
  const stop = desk.getByRole('button', { name: '停止', exact: true })
  const disconnect = desk.getByRole('button', { name: '断开', exact: true })
  const connect = desk.getByRole('button', { name: '连接诊断', exact: true })
  const start = desk.getByRole('button', { name: '开始', exact: true })
  const current = text => toolbar.getByText(text, { exact: true }).waitFor()
  const curves = desk.locator('path.alignment-curve[d^="M"]')
  assert.equal(await desk.locator('input[type="file"]').count(), 0)
  assert.equal(await desk.getByText(/汞灯定位|参考 CSV|观测 CSV|确认定位|导出定位/).count(), 0)
  assert.equal(await target.isDisabled(), true)

  const dimensions = []
  for (const viewport of [{ width: 1440, height: 1000 }, { width: 1060, height: 680 }]) {
    await page.setViewportSize(viewport)
    const labels = desk.locator('.alignment-empty')
    await labels.first().waitFor()
    const sizes = await labels.evaluateAll(nodes => nodes.map(label => {
      const chart = label.previousElementSibling.getBoundingClientRect()
      const text = label.getBoundingClientRect()
      return { chartWidth: chart.width, textWidth: text.width, textHeight: text.height,
        fontSize: getComputedStyle(label).fontSize, tag: label.tagName,
        dx: text.x + text.width / 2 - chart.x - chart.width / 2,
        dy: text.y + text.height / 2 - chart.y - chart.height / 2 }
    }))
    assert.equal(sizes.length, 3)
    for (const size of sizes) {
      assert.equal(size.tag, 'SPAN')
      assert.equal(size.fontSize, '12px')
      assert.ok(Math.abs(size.dx) < 1 && Math.abs(size.dy) < 1, JSON.stringify(size))
    }
    dimensions.push(sizes[0])
  }
  assert.notEqual(dimensions[0].chartWidth, dimensions[1].chartWidth)
  assert.equal(dimensions[0].textWidth, dimensions[1].textWidth)
  assert.equal(dimensions[0].textHeight, dimensions[1].textHeight)
  await desk.locator('.alignment-plots').screenshot({ path: path.join(output, 'alignment-empty-three-ccds.png') })
  checks.push('调试对中仍显示三路 CCD，空态文字在两种窗口宽度下保持字号和居中')

  await connect.click()
  await target.selectOption('4')
  assert.deepEqual(await target.locator('option').evaluateAll(options => options.map(option => option.value)), ['', '4', '17'])
  await change.click()
  await current('当前转角 4°')
  await start.click()
  await curves.first().waitFor()

  const oldFrame = deferred(), releaseOld = deferred()
  const move = deferred(), releaseMove = deferred()
  await page.route(`**${stepPath}`, async route => {
    const response = await route.fetch()
    oldFrame.resolve(response)
    await releaseOld.promise
    await route.fulfill({ response })
  }, { times: 1 })
  const holdTurn = async route => {
    if (route.request().method() !== 'POST') return route.continue()
    const response = await route.fetch()
    move.resolve(response)
    await releaseMove.promise
    await route.fulfill({ response })
  }
  await page.route(`**${turnPath}`, holdTurn)
  assert.equal((await (await oldFrame.promise).json()).event.details.angle_deg, 4)
  await target.selectOption('17')
  await change.click()
  await current('正在切换转角')
  assert.equal(await target.isDisabled(), true)
  assert.equal(await stop.isEnabled(), true)
  assert.equal(await disconnect.isEnabled(), true)
  assert.equal(await curves.count(), 0)
  const lateStep = page.waitForResponse(response => new URL(response.url()).pathname === stepPath)
  releaseOld.resolve()
  await lateStep
  assert.equal(await curves.count(), 0)
  const arrival = await move.promise
  assert.equal(arrival.status(), 200, await arrival.text())
  assert.equal((await arrival.json()).current_angle_deg, 17)
  const freshStep = page.waitForResponse(response => new URL(response.url()).pathname === stepPath)
  releaseMove.resolve()
  await current('当前转角 17°')
  assert.equal((await (await freshStep).json()).event.details.angle_deg, 17)
  await curves.first().waitFor()
  await page.unroute(`**${turnPath}`, holdTurn)
  await stop.click()
  await desk.getByText('状态：connected', { exact: true }).waitFor()
  await checkAlignmentViews(page, desk, { checks }, output)
  checks.push('空闲及调试采集均可切角，转动时可停止和断开，迟到的旧角帧不会重画曲线')

  let failures = 0
  const unknownTurn = async route => {
    if (route.request().method() === 'POST') {
      failures++
      return route.fulfill({ status: 409, json: { detail: '切换验证失败' } })
    }
    const response = await route.fetch()
    return route.fulfill({ response, json: { ...await response.json(), current_angle_deg: null } })
  }
  await page.route(`**${turnPath}`, unknownTurn)
  await target.selectOption('4')
  await change.click()
  await current('当前转角 --')
  assert.equal(failures, 1)
  await page.unroute(`**${turnPath}`, unknownTurn)
  await disconnect.click()
  await desk.getByText('状态：idle', { exact: true }).waitFor()
  checks.push('切角失败只发一次请求，刷新后显示未知角并可断开设备')
}
