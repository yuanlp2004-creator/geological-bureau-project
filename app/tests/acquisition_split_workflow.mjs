import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import path from 'node:path'
import { call, navigate } from './contract_browser_support.mjs'

// 同一隔离库中验证两个入口、历史记录、任务控制与延迟响应归属。
export async function checkAcquisitionSplit(page, checks, output) {
  const adminToken = await page.evaluate(() => sessionStorage.getItem('geospectrum.token'))
  const method = await call(page, '/api/v1/methods', { name: '摄谱拆分检查方法', conditions: {
    exposure_mode: 'line_interval', frame_count: 2,
    angle_exposures: [{ angle_deg: 0, storage_mode: 'averaged', start_frame: 1, end_frame: 2 }]
  } })
  const line = JSON.parse(await readFile(path.join(process.cwd(), 'tests/fixtures/station17-line.json'), 'utf8'))
  await call(page, `/api/v1/methods/${method.id}/lines`, line)
  const published = await call(page, `/api/v1/methods/${method.id}/publish`, {})
  await call(page, `/api/v1/methods/${method.id}/open`, {})
  const oldSample = await call(page, '/api/v1/acquisitions/tasks', {
    name: '拆分前样品记录', method_id: method.id, sample_name: 'U001', task_kind: 'sample',
  })
  const oldEvaporation = await call(page, '/api/v1/acquisitions/tasks', {
    name: '拆分前蒸发记录', task_kind: 'evaporation',
  })
  await page.reload()
  await page.locator('[data-navigation-group="analysis-tests"]').waitFor()
  const go = async (kind) => {
    await navigate(page, 'analysis-tests', kind === 'sample' ? '样品摄谱' : '蒸发摄谱',
      `[data-testid="${kind}-acquisition-page"]`)
    const host = page.getByTestId(`${kind}-acquisition-page`)
    await host.locator('.acquisition-task-list button').first().waitFor()
    const disclosure = host.locator('.disclosure-toggle')
    if (await disclosure.getAttribute('aria-expanded') === 'false') await disclosure.click()
    await host.locator('.acquisition-form').waitFor()
    await page.waitForFunction((kind) => !document.querySelector(`[data-testid="${kind}-acquisition-page"] .acquisition-form button[type="submit"]`)?.disabled, kind)
    assert.equal(await host.getByLabel('任务类型').count(), 0)
    return host
  }
  const fill = async (form, label, value) => {
    const input = form.locator('label.field').filter({ has: page.getByText(label, { exact: true }) }).locator('input')
    await input.fill(String(value)); await input.blur()
  }
  const create = async (host, name) => {
    const form = host.locator('.acquisition-form')
    await fill(form, '任务名称', name)
    await fill(form, '采样次数', 2); await fill(form, '空白次数', 0)
    await fill(form, '采样周期 (秒)', 0.01)
    await fill(form, '预激时间（秒）', 0)
    const advanced = form.locator('details').filter({ has: page.getByText('高级采集设置', { exact: true }) })
    if (await advanced.getAttribute('open') === null) await advanced.locator('summary').click()
    await fill(form, '倒计时（秒）', 0)
    const pending = page.waitForResponse((r) => r.url().endsWith('/api/v1/acquisitions/tasks') && r.request().method() === 'POST')
    await form.getByRole('button', { name: '创建任务', exact: true }).click()
    const response = await pending
    assert.equal(response.status(), 201)
    return response.json()
  }
  const complete = async (host, task) => {
    let current = task
    const control = async (label, action) => {
      const pending = page.waitForResponse((r) => r.url().endsWith(`/acquisitions/tasks/${task.id}/${action}`) && r.request().method() === 'POST')
      await host.getByRole('button', { name: label, exact: true }).click()
      const response = await pending
      assert.equal(response.status(), 200)
      current = await response.json()
    }
    await control('试样摄谱', 'start'); await control('暂停', 'pause'); await control('继续', 'resume')
    for (let i = 0; i < 160 && current.status !== 'completed'; i++) {
      current = await call(page, `/api/v1/acquisitions/tasks/${task.id}`)
      if (current.status === 'between_repeats') await control('试样摄谱', 'start')
      await page.waitForTimeout(100)
    }
    assert.equal(current.status, 'completed'); assert.ok(current.result_sha256)
    await host.locator('svg.spectrum-plot .spectrum-line').first().waitFor()
    return current
  }

  let host = await go('sample')
  await host.locator('.acquisition-task-list button').filter({ hasText: oldSample.name }).waitFor()
  assert.equal(await host.locator('.acquisition-task-list').getByText(oldEvaporation.name, { exact: true }).count(), 0)
  const form = host.locator('.acquisition-form')
  await form.getByLabel(/^已发布方法版本/).selectOption(`${method.id}:${published.current_version}`)
  await form.getByText('高级采集设置', { exact: true }).click()
  await form.getByLabel('激发参数与默认次数').selectOption('custom')
  assert.equal(await form.getByLabel('保存模式').isDisabled(), true)
  assert.equal(await form.getByLabel('保存模式').inputValue(), 'full_interval')
  await fill(form, '临时样号', 'U002'); await fill(form, '采样次数', '')
  let writes = 0
  const record = (r) => { if (r.url().endsWith('/api/v1/acquisitions/tasks') && r.method() === 'POST') writes++ }
  page.on('request', record)
  await form.getByRole('button', { name: '创建任务', exact: true }).click()
  assert.equal(writes, 0, '非法数值不得提交任务'); page.off('request', record)
  const sample = await create(host, '独立样品摄谱')
  assert.equal(sample.task_kind, 'sample'); assert.equal(sample.storage_mode, 'full_interval')
  assert.equal(sample.method_id, method.id)
  await complete(host, sample)
  await host.getByRole('heading', { name: '即时测量结果', exact: true }).waitFor()
  assert.equal(await host.getByRole('heading', { name: '全时采集区间', exact: true }).count(), 0)
  checks.push('样品入口：历史记录、方法与全时保存、非法输入零写入、暂停恢复及模拟完成')
  if (output) await page.screenshot({ path: path.join(output, 'sample-light.png') })

  host = await go('evaporation')
  await host.locator('.acquisition-task-list button').filter({ hasText: oldEvaporation.name }).waitFor()
  assert.equal(await host.locator('.acquisition-task-list').getByText(sample.name, { exact: true }).count(), 0)
  for (const label of ['已发布方法版本', '样品队列', '样品类型', '保存模式', '重复次数'])
    assert.equal(await host.locator('.acquisition-form').getByText(label, { exact: true }).count(), 0)
  assert.equal(await host.getByRole('heading', { name: '即时测量结果', exact: true }).count(), 0)
  const evaporation = await create(host, '独立蒸发实验')
  assert.equal(evaporation.task_kind, 'evaporation'); assert.equal(evaporation.storage_mode, 'full_interval')
  assert.equal(evaporation.repeat_count, 1); assert.equal(evaporation.method_id, null)
  const finished = await complete(host, evaporation)
  assert.equal(await host.getByRole('button', { name: '标记区间', exact: true }).count(), 0)
  const frames = await call(page, `/api/v1/acquisitions/tasks/${evaporation.id}/frames`)
  assert.equal(frames.length, finished.layout.ccd_indices.length * 2)
  checks.push('蒸发入口：独立条件、单次完整全时帧和暂停恢复，无手工区间标记、样品配置或定量面板')
  if (output) await page.screenshot({ path: path.join(output, 'evaporation-light.png') })

  host = await go('sample')
  await page.evaluate(() => { window.__splitSampleRoot = document.querySelector('[data-testid="sample-acquisition-page"]') })
  host = await go('evaporation')
  await host.locator('.acquisition-task-list button').filter({ hasText: evaporation.name }).waitFor()
  assert.equal(await host.locator('.acquisition-task-list').getByText(sample.name, { exact: true }).count(), 0)
  host = await go('sample')
  assert.equal(await page.evaluate(() => window.__splitSampleRoot === document.querySelector('[data-testid="sample-acquisition-page"]')), true)
  await host.locator('.acquisition-task-list button').filter({ hasText: sample.name }).waitFor()
  assert.equal(await host.locator('.acquisition-task-list').getByText(evaporation.name, { exact: true }).count(), 0)
  checks.push('两个任务列表独立，共用工作台切换保留各自实例，不污染另一业务模式')

  await call(page, '/api/v1/settings', { display: { theme: 'dark', density: 'compact' } }, 'PATCH')
  await page.setViewportSize({ width: 1060, height: 800 })
  await page.reload(); await page.locator('[data-navigation-group="analysis-tests"]').waitFor()
  for (const kind of ['sample', 'evaporation']) {
    host = await go(kind)
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth && document.body.scrollWidth <= document.documentElement.clientWidth), true)
    if (output) await page.screenshot({ path: path.join(output, `${kind}-dark.png`) })
  }
  checks.push('两个页面在暗色紧凑1060宽窗口无横向溢出')

  const roles = await call(page, '/api/v1/roles')
  const role = roles.find((role) => role.name === 'read_only_auditor')
  await call(page, '/api/v1/users', { username: 'split-viewer', password: 'split-viewer-password', role_ids: [role.id] })
  const login = await call(page, '/api/v1/auth/login', { username: 'split-viewer', password: 'split-viewer-password' })
  await page.evaluate((token) => sessionStorage.setItem('geospectrum.token', token), login.access_token)
  await page.reload(); await page.locator('[data-navigation-group="analysis-tests"]').waitFor()
  const trigger = page.locator('[data-navigation-group="analysis-tests"]')
  await trigger.focus(); await trigger.press('ArrowRight')
  for (const label of ['样品摄谱', '蒸发摄谱']) {
    const entry = page.getByRole('menuitem', { name: label })
    assert.equal(await entry.getAttribute('aria-disabled'), 'true')
    assert.equal(await entry.getAttribute('title'), '请先选择已发布的当前方法')
  }
  const identity = await call(page, '/api/v1/auth/me')
  assert.ok(identity.permissions.includes('acquisition.read'))
  assert.ok(!identity.permissions.includes('acquisition.write') && !identity.permissions.includes('acquisition.execute'))
  checks.push('只读角色可见两个入口；无当前方法时禁用，既有采集读写权限边界保持')
  await page.evaluate((token) => sessionStorage.setItem('geospectrum.token', token), adminToken)
  await page.reload()
}
