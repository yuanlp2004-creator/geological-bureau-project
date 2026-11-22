import assert from 'node:assert/strict'
import path from 'node:path'
import { call, navigate } from './contract_browser_support.mjs'

export async function checkLineTurnDetection(page, result, output) {
  const check = message => result.checks.push(message)
  await page.reload()
  await page.locator('[data-navigation-group="methods"]').waitFor()
  const method = await call(page, '/api/v1/methods/1')
  const published = await call(page, '/api/v1/methods/1/lines?version=3')
  const target = published.lines.find(line => line.id === 'AL')
  const alternate = published.lines.find(line => line.id === 'IS')
  assert.ok(target && alternate)
  assert.equal(target.wavelength_nm, 252.737748321013)
  const requests = []
  const record = request => { if (request.method() === 'POST' && /\/methods\/1\/lines\/detect$/.test(request.url())) requests.push(request.postDataJSON()) }
  page.on('request', record)
  await navigate(page, 'methods', '分析谱线', '[data-testid="methods-page"]')
  const host = page.getByTestId('methods-page')
  await host.getByLabel('选择编辑方法', { exact: true }).selectOption('1')
  const list = host.locator('.spectral-list-surface')
  const editor = host.locator('.spectral-editor-surface')
  const input = label => editor.locator('label.field').filter({ has: page.getByText(label, { exact: true }) }).locator('input')
  const card = editor.locator('.detectability-card')
  const choose = async line => {
    await list.locator('.spectral-line-card').filter({ has: page.locator('strong', { hasText: `${line.element} ${line.wavelength_nm.toFixed(4)} nm` }) }).click()
  }
  const expected = async angle => {
    await card.filter({ hasText: `(${angle}°)` }).waitFor()
    await page.waitForFunction(() => document.querySelector('.spectral-editor-surface .detectability-card code')?.textContent === 'detectable')
  }
  await choose(target)
  await expected(17)
  await page.waitForTimeout(500)
  assert.equal(await card.locator('strong').textContent(), '当前条件可检测')
  assert.ok(requests.some(request => request.line_id === 'AL'))
  assert.equal(await editor.getByRole('button', { name: '保存谱线', exact: true }).isEnabled(), true)
  check('截图中的252.7377nm谱线重新检测后仍绑定17°，不再被延迟响应改为误报')

  await choose(alternate)
  await expected(4)
  const wave = input('理论波长 (nm)')
  await wave.fill(String(target.wavelength_nm)); await wave.blur()
  await expected(4)
  const previous = requests.length
  await choose(target)
  await expected(17)
  await page.waitForTimeout(500)
  assert.ok(requests.slice(previous).some(request => request.line_id === 'AL' && request.wavelength_nm === target.wavelength_nm))
  check('不同谱线即使临时输入相同波长，切换后仍重新检测各自绑定')

  const detectPattern = /\/methods\/1\/lines\/detect$/
  let pending
  await page.route(detectPattern, async route => {
    if (route.request().postDataJSON().line_id === 'AL') { pending = route.request(); await new Promise(resolve => setTimeout(resolve, 800)) }
    await route.continue()
  })
  await choose(alternate); await expected(4)
  const delayedRequest = page.waitForRequest(request => request.method() === 'POST' && detectPattern.test(request.url()) && request.postDataJSON().line_id === 'AL')
  await choose(target); await delayedRequest
  await choose(alternate); await expected(4)
  await page.waitForTimeout(1100)
  assert.ok(pending)
  assert.ok((await card.textContent()).includes('(4°)'))
  await page.unroute(detectPattern)
  check('上一谱线的慢响应不覆盖当前谱线检测结果')

  await choose(target); await expected(17)
  for (const label of ['理论波长 (nm)', '实际波长 (nm)']) {
    assert.equal(await input(label).evaluate(input => input.checkValidity()), true)
  }
  await input('理论波长 (nm)').fill('159')
  await input('理论波长 (nm)').blur()
  assert.equal(await input('理论波长 (nm)').evaluate(input => input.checkValidity()), false)
  await input('理论波长 (nm)').fill(String(target.wavelength_nm)); await input('理论波长 (nm)').blur()
  await expected(17)
  await input('实际波长 (nm)').fill(String(target.wavelength_nm + .31))
  await input('实际波长 (nm)').blur()
  await page.waitForFunction(() => document.querySelector('.spectral-editor-surface .detectability-card code')?.textContent === 'sample_line_turn_missing')
  assert.equal(await editor.getByRole('button', { name: '保存谱线', exact: true }).isDisabled(), true)
  await input('实际波长 (nm)').fill(String(target.actual_wavelength_nm)); await input('实际波长 (nm)').blur(); await expected(17)
  check('完整精度波长可原样保存，范围与偏差非法输入仍被拦截')
  const saved = page.waitForResponse(response => response.request().method() === 'PATCH' && /\/methods\/1\/lines\/AL$/.test(response.url()))
  await editor.getByRole('button', { name: '保存谱线', exact: true }).click()
  const response = await saved
  assert.equal(response.status(), 200)
  await expected(17)
  const after = await call(page, '/api/v1/methods/1')
  assert.deepEqual(after.version.conditions.angle_exposures, method.version.conditions.angle_exposures)
  assert.deepEqual(await call(page, '/api/v1/methods/1/lines?version=3'), published)
  check('已有谱线可保存为新版本，原发布版本及转角关联保持')

  await list.getByRole('button', { name: '添加谱线', exact: true }).click()
  await input('理论波长 (nm)').fill(String(target.wavelength_nm))
  await input('理论波长 (nm)').blur()
  await page.waitForFunction(() => document.querySelector('.spectral-editor-surface .detectability-card code')?.textContent === 'sample_line_turn_ambiguous')
  assert.equal(await editor.getByRole('button', { name: '添加谱线', exact: true }).isDisabled(), true)
  assert.ok(requests.slice(-1).every(request => !request.line_id))
  check('新增谱线不借用已有标识，确有多转角歧义时继续禁止保存')
  await choose(target); await expected(17); await page.waitForTimeout(400)
  await card.scrollIntoViewIfNeeded()
  await page.screenshot({ path: path.join(output, 'line-turn-detection.png') })
  assert.equal(await input('理论波长 (nm)').inputValue(), String(target.wavelength_nm))
  assert.equal(await input('实际波长 (nm)').inputValue(), String(target.actual_wavelength_nm))
  page.off('request', record)
  result.methodId = 1
  result.boundAngle = 17
  result.requestIdentities = requests.map(request => request.line_id ?? null)
}
