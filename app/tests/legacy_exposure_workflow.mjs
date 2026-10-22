import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import path from 'node:path'
import { call, navigate } from './contract_browser_support.mjs'

export async function checkLegacyExposure(page, checks, output) {
  let method = await call(page, '/api/v1/methods', { name: '曝光逻辑检查', conditions: {
    frame_count: 4, dark_frame_count: 0, pre_excitation_seconds: 1, selected_ccds: [0],
    angle_exposures: [{ angle_deg: 0, storage_mode: 'averaged', start_frame: 2, end_frame: 3 }]
  } })
  const line = JSON.parse(await readFile(path.join(process.cwd(), 'tests/fixtures/station17-line.json'), 'utf8'))
  line.wavelength_nm = Number(line.wavelength_nm.toFixed(4))
  line.actual_wavelength_nm = Number(line.actual_wavelength_nm.toFixed(4))
  method = await call(page, `/api/v1/methods/${method.id}/lines`, line)
  const lineId = method.changed_line_id
  method = await call(page, `/api/v1/methods/${method.id}/publish`, {})
  const legacyPublished = method.published_version
  assert.equal(method.version.conditions.exposure_mode, 'simple_mean')
  const go = async (label) => {
    await navigate(page, 'methods', label, '.methods-page')
    const picker = page.getByLabel('选择编辑方法')
    await picker.locator(`option[value="${method.id}"]`).waitFor({ state: 'attached' })
    if (await picker.inputValue() !== String(method.id)) await picker.selectOption(String(method.id))
    return page.getByTestId('methods-page')
  }
  const selectLine = async () => {
    const host = await go('分析谱线')
    await host.locator('.spectral-line-card').filter({ has: page.locator(`strong[title="${line.element} ${line.wavelength_nm.toFixed(4)} nm"]`) }).click()
    await host.locator('.spectral-editor-surface').getByText('曝光起始帧', { exact: true }).waitFor()
    return host
  }
  const saveMethod = async () => {
    const pending = page.waitForResponse((r) => r.url().endsWith(`/api/v1/methods/${method.id}`) && r.request().method() === 'PATCH')
    await page.getByRole('button', { name: '保存方法草稿', exact: true }).click()
    const response = await pending
    assert.equal(response.status(), 200)
    method = await response.json()
    await page.locator('.method-save-footer button.primary-button:enabled').waitFor()
  }
  const fill = async (label, value) => {
    const input = page.locator('.spectral-editor-surface label.field').filter({ has: page.getByText(label, { exact: true }) }).locator('input')
    await input.fill(String(value)); await input.blur()
  }
  let host = await go('方法管理与参数')
  assert.equal(await host.getByRole('checkbox', { name: '区间曝光', exact: true }).isChecked(), false)
  assert.equal(await host.getByText('曝光起始帧', { exact: true }).count(), 0)
  assert.equal(await host.locator('.method-advanced-exposure').count(), 0)
  assert.equal(await host.locator('.angle-storage-table').count(), 0)
  assert.equal(await host.getByText('高级采集存储范围', { exact: true }).count(), 0)
  assert.equal(await host.getByRole('columnheader', { name: /起始帧|结束帧/, includeHidden: true }).count(), 0)
  const angleSelection = host.locator('.method-angle-selection')
  const firstAngle = angleSelection.getByLabel('第1项转角', { exact: true })
  assert.equal(await firstAngle.inputValue(), '0')
  let methodWrites = 0
  const methodListener = (request) => { if (request.url().endsWith(`/api/v1/methods/${method.id}`) && request.method() === 'PATCH') methodWrites++ }
  page.on('request', methodListener)
  await firstAngle.fill('361'); await firstAngle.blur()
  await host.getByRole('button', { name: '保存方法草稿', exact: true }).click()
  assert.equal(methodWrites, 0)
  await firstAngle.fill('12.5'); await firstAngle.blur()
  await angleSelection.getByRole('button', { name: '添加角度', exact: true }).click()
  await angleSelection.getByRole('button', { name: '添加角度', exact: true }).click()
  assert.equal(await angleSelection.getByLabel('第3项转角', { exact: true }).inputValue(), '32.5')
  await angleSelection.getByTitle('移除此角度', { exact: true }).nth(2).click()
  checks.push('方法页移除整个高级存储块及全部起止帧输入；转角增改删保留，361度越界零提交')

  await angleSelection.getByLabel('第1项存储方式', { exact: true }).selectOption('full_interval')
  assert.equal(await angleSelection.getByRole('group', { name: '第1项转角配置', exact: true }).getByLabel('第1项存储方式', { exact: true }).inputValue(), 'full_interval')
  assert.equal(await angleSelection.getByLabel('第2项存储方式', { exact: true }).inputValue(), 'averaged')
  assert.equal(methodWrites, 0)
  await saveMethod()
  assert.equal(methodWrites, 1)
  page.off('request', methodListener)
  assert.equal(method.version.conditions.exposure_mode, 'simple_mean')
  assert.deepEqual(method.version.conditions.angle_exposures, [
    { angle_deg: 12.5, storage_mode: 'full_interval', start_frame: 1, end_frame: 4 },
    { angle_deg: 22.5, storage_mode: 'averaged', start_frame: 1, end_frame: 4 }
  ])
  assert.equal(method.published_version.content_sha256, legacyPublished.content_sha256)
  assert.equal(method.published_version.conditions.angle_exposures[0].start_frame, 2)
  assert.equal(method.published_version.conditions.angle_exposures[0].end_frame, 3)
  checks.push('存储方式与转角同行并一次保存；旧2–3帧范围在新草稿改为完整1–4帧，原发布快照保持')

  host = await selectLine()
  assert.equal(await host.getByLabel('曝光起始帧').isDisabled(), true)
  assert.equal(await host.getByLabel('曝光结束帧').inputValue(), '4')
  assert.equal(await host.locator('.method-advanced-exposure').count(), 0)
  assert.equal(await host.locator('.method-angle-selection').count(), 0)
  const exposure = host.getByRole('region', { name: '谱线曝光区间', exact: true })
  await exposure.getByRole('heading', { name: '谱线曝光区间', exact: true }).waitFor()
  const exposureBox = await exposure.boundingBox()
  const typeBox = await host.locator('.spectral-form-grid > label.field').filter({ has: page.getByText('谱线类型', { exact: true }) }).boundingBox()
  assert.ok(exposureBox && typeBox && exposureBox.y + exposureBox.height <= typeBox.y)
  checks.push('分析谱线顶部保留唯一逐线曝光区间，位于其他谱线参数之前')

  host = await go('方法管理与参数')
  await host.getByRole('checkbox', { name: '区间曝光', exact: true }).check()
  await saveMethod()
  assert.equal(method.version.conditions.exposure_mode, 'line_interval')
  host = await selectLine()
  assert.equal(await host.getByLabel('曝光起始帧').isEnabled(), true)
  await fill('曝光起始帧', 2); await fill('曝光结束帧', 3)
  const saved = page.waitForResponse((r) => r.url().endsWith(`/api/v1/methods/${method.id}/lines/${lineId}`) && r.request().method() === 'PATCH')
  await host.getByRole('button', { name: '保存谱线', exact: true }).click()
  const response = await saved
  assert.equal(response.status(), 200)
  method = await response.json()
  const stored = method.version.lines.find((item) => item.id === lineId)
  assert.equal(stored.exposure_start_frame, 2); assert.equal(stored.exposure_end_frame, 3)
  const version = method.version.version
  let writes = 0
  const listener = (r) => { if (r.url().endsWith(`/lines/${lineId}`) && r.method() === 'PATCH') writes++ }
  page.on('request', listener)
  await fill('曝光结束帧', 5)
  await host.getByRole('button', { name: '保存谱线', exact: true }).click()
  assert.equal(writes, 0)
  page.off('request', listener)
  const unchanged = await call(page, `/api/v1/methods/${method.id}/lines`)
  assert.equal(unchanged.version, version)
  assert.equal(unchanged.lines.find((item) => item.id === lineId).exposure_end_frame, 3)
  await fill('曝光结束帧', 3)
  checks.push('顶部曝光保存逐线2–3帧，越界5帧零提交且不新增版本')

  host = await go('方法管理与参数')
  const frameCount = host.getByLabel('采样次数', { exact: true })
  methodWrites = 0
  page.on('request', methodListener)
  await frameCount.fill('256'); await frameCount.blur()
  await host.getByRole('button', { name: '保存方法草稿', exact: true }).click()
  assert.equal(methodWrites, 0)
  await frameCount.fill('6'); await frameCount.blur()
  await host.getByLabel('第1项存储方式', { exact: true }).selectOption('averaged')
  const changedAngle = host.getByLabel('第1项转角', { exact: true })
  await changedAngle.fill('15.5'); await changedAngle.blur()
  await saveMethod()
  assert.equal(methodWrites, 1)
  page.off('request', methodListener)
  assert.deepEqual(method.version.conditions.angle_exposures, [
    { angle_deg: 15.5, storage_mode: 'averaged', start_frame: 1, end_frame: 6 },
    { angle_deg: 22.5, storage_mode: 'averaged', start_frame: 1, end_frame: 6 }
  ])
  assert.equal(method.published_version.content_sha256, legacyPublished.content_sha256)
  assert.equal(method.version.lines.find((item) => item.id === lineId).exposure_start_frame, 2)
  assert.equal(method.version.lines.find((item) => item.id === lineId).exposure_end_frame, 3)
  host = await selectLine()
  assert.equal(await host.getByLabel('曝光起始帧').inputValue(), '2')
  assert.equal(await host.getByLabel('曝光结束帧').inputValue(), '3')
  checks.push('总帧数越界零提交；改为6帧后各转角自动1–6，保存方式和角度更改保留逐线曝光及原发布哈希')

  for (const [theme, density, width] of [['light', 'comfortable', 1440], ['dark', 'compact', 1060]]) {
    await call(page, '/api/v1/settings', { display: { theme, density } }, 'PATCH')
    await page.setViewportSize({ width, height: 1000 })
    await page.getByRole('button', { name: '刷新服务状态', exact: true }).click()
    await page.waitForFunction((theme) => document.documentElement.dataset.theme === theme, theme)
    host = await go('方法管理与参数')
    assert.equal(await host.getByLabel('第1项转角', { exact: true }).inputValue(), '15.5')
    assert.equal(await host.getByLabel('第1项存储方式', { exact: true }).inputValue(), 'averaged')
    assert.equal(await host.getByRole('columnheader', { name: /起始帧|结束帧/, includeHidden: true }).count(), 0)
    await host.locator('.method-angle-selection').scrollIntoViewIfNeeded()
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true)
    if (output) await page.screenshot({ path: path.join(output, `angle-storage-${theme}.png`) })
    host = await selectLine()
    await host.getByRole('region', { name: '谱线曝光区间', exact: true }).scrollIntoViewIfNeeded()
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true)
    if (output) await page.screenshot({ path: path.join(output, `exposure-lines-${theme}.png`) })
  }
  checks.push('明暗1440/1060窗口下存储方式与转角同行，曝光保持在谱线顶部且方法页无隐藏区间编辑器')
  method = await call(page, `/api/v1/methods/${method.id}/publish`, {})
  const published = method.published_version
  await call(page, `/api/v1/methods/${method.id}/open`, {})
  let task = await call(page, '/api/v1/acquisitions/tasks', {
    method_id: method.id, sample_name: 'U001', repeat_count: 1, use_method_conditions: true, use_method_intervals: true,
  })
  assert.equal(task.storage_mode, 'full_interval')
  task = await call(page, `/api/v1/acquisitions/tasks/${task.id}/start`, {})
  for (let i = 0; i < 24 && task.status !== 'completed'; i++)
    task = await call(page, `/api/v1/acquisitions/tasks/${task.id}/step`, {})
  assert.equal(task.status, 'completed')
  assert.equal(task.samples[0].bands[0].storage_mode, 'full_interval')
  assert.ok(task.samples[0].bands[0].burn_sha256)
  assert.equal(task.samples[0].bands[0].burn_frame_count, 6)
  const measurements = await call(page, `/api/v1/acquisitions/tasks/${task.id}/measurements`)
  assert.ok(measurements.rows.some((row) => row.line_id === lineId && row.quantitative_signal != null))
  checks.push('区间曝光发布后自动全时保存完整帧，逐线区间用于即时测量')

  host = await go('方法管理与参数')
  await host.getByRole('checkbox', { name: '区间曝光', exact: true }).uncheck()
  await saveMethod()
  assert.equal(method.published_version.content_sha256, published.content_sha256)
  host = await selectLine()
  assert.equal(await host.getByLabel('曝光起始帧').isDisabled(), true)
  assert.equal(await host.getByLabel('曝光起始帧').inputValue(), '2')
  assert.equal(await host.getByLabel('曝光结束帧').inputValue(), '3')
  method = await call(page, `/api/v1/methods/${method.id}/publish`, {})
  const mean = await call(page, '/api/v1/acquisitions/tasks', {
    method_id: method.id, sample_name: 'U002', use_method_conditions: true, repeat_count: 1, storage_mode: 'full_interval',
  })
  assert.equal(mean.storage_mode, 'averaged')
  checks.push('关闭后保留逐线配置但禁用并按简单均值保存；原已发布版本哈希保持')

  host = await go('方法管理与参数')
  await host.getByLabel('第1项存储方式', { exact: true }).selectOption('full_interval')
  await saveMethod()
  assert.equal(method.version.conditions.angle_exposures[0].start_frame, 1)
  assert.equal(method.version.conditions.angle_exposures[0].end_frame, 6)
  method = await call(page, `/api/v1/methods/${method.id}/publish`, {})
  await call(page, `/api/v1/methods/${method.id}/open`, {})
  await page.reload(); await page.locator('[data-navigation-group="analysis-tests"]').waitFor()
  await navigate(page, 'analysis-tests', '样品摄谱', '[data-testid="sample-acquisition-page"]')
  const sampleHost = page.getByTestId('sample-acquisition-page')
  await sampleHost.locator('.acquisition-task-list button').first().waitFor()
  const toggle = sampleHost.locator('.disclosure-toggle')
  if (await toggle.getAttribute('aria-expanded') === 'false') await toggle.click()
  const sampleForm = sampleHost.locator('.acquisition-form')
  await sampleForm.getByLabel('存储设置来源').selectOption('method')
  assert.equal(await sampleForm.getByLabel('保存模式').inputValue(), 'full_interval')
  assert.equal(await sampleForm.getByLabel('保存模式').isDisabled(), true)
  const created = page.waitForResponse((r) => r.url().endsWith('/api/v1/acquisitions/tasks') && r.request().method() === 'POST')
  await sampleForm.getByRole('button', { name: '创建任务', exact: true }).click()
  const createdResponse = await created
  assert.equal(createdResponse.status(), 201)
  let fullTask = await createdResponse.json()
  assert.equal(fullTask.storage_mode, 'full_interval')
  fullTask = await call(page, `/api/v1/acquisitions/tasks/${fullTask.id}/start`, {})
  for (let i = 0; i < 24 && fullTask.status !== 'completed'; i++)
    fullTask = await call(page, `/api/v1/acquisitions/tasks/${fullTask.id}/step`, {})
  assert.equal(fullTask.status, 'completed')
  assert.equal(fullTask.samples[0].bands[0].burn_frame_count, 6)
  assert.ok(fullTask.samples[0].bands[0].burn_sha256)
  checks.push('方法表选择全时保存并发布后，样品按方法存储实际保留完整6帧，未沿用旧2–3帧裁剪')
}
