import assert from 'node:assert/strict'
import path from 'node:path'
import { call, navigate } from './contract_browser_support.mjs'

// 同一真实 API/UI 流程可在隔离浏览器和冻结 QA EXE 中执行。
export async function checkMethodCcd(page, fixture, result, output) {
  const options = await call(page, '/api/v1/methods/options')
  const defaultCurve = options.dispersion_calibrations.find(item => item.name === 'default')
  const alternate = options.dispersion_calibrations.find(item => item.name === 'CCD自动测试曲线')
  const alternateLayout = options.ccd_layouts.find(item => item.id === alternate.ccd_layout_id)
  const existing = await call(page, '/api/v1/methods', { name: '已有CCD方法', conditions: { selected_ccds: [0] } })
  const published = await call(page, `/api/v1/methods/${existing.id}/publish`, {})
  const publishedSnapshot = published.published_version
  const versions = await call(page, `/api/v1/methods/${existing.id}/versions`)
  const manifest = await call(page, '/api/v1/capabilities')
  const entry = manifest.capabilities.flatMap(item => item.navigation_entries || [])
    .find(item => item.page === 'methods' && item.view === 'lifecycle')
    ?? manifest.capabilities.flatMap(item => item.navigation_entries || []).find(item => item.page === 'methods')
  await navigate(page, entry.group, entry.label, '.methods-page')
  await page.getByLabel('选择编辑方法').selectOption(String(existing.id))
  await page.getByLabel('色散曲线', { exact: true }).waitFor()
  assert.equal(await page.locator('.method-ccd-selection, .method-ccd-details, .ccd-ranges').count(), 0)
  assert.equal(await page.getByText('启用 CCD', { exact: true }).count(), 0)
  assert.equal(await page.getByText(/1000 ug\/g = 1 mg\/g/).count(), 0)
  assert.equal(await page.getByText('CCD 布局', { exact: true }).count(), 0)
  assert.deepEqual(await call(page, `/api/v1/methods/${existing.id}/versions`), versions)
  result.checks.push('CCD controls, layout display and unit hint removed; opening causes zero version writes')

  const save = async () => {
    const response = page.waitForResponse(response => response.url().endsWith(`/api/v1/methods/${existing.id}/save`)
      && response.request().method() === 'POST')
    await page.getByRole('button', { name: '保存', exact: true }).first().click()
    const saved = await response
    assert.equal(saved.status(), 200, await saved.text())
    await page.getByRole('button', { name: '保存', exact: true }).first().waitFor({ state: 'visible' })
    await page.waitForFunction(() => ![...document.querySelectorAll('button')].find(b => b.textContent.trim() === '保存')?.disabled)
    return call(page, `/api/v1/methods/${existing.id}`)
  }
  await page.getByLabel('方法名称').fill('原CCD数据保留')
  let saved = await save()
  assert.deepEqual(saved.version.conditions.selected_ccds, [0])
  assert.equal(saved.version.conditions.ccd_layout_id, publishedSnapshot.conditions.ccd_layout_id)
  assert.equal(saved.version.conditions.dispersion_calibration_id, publishedSnapshot.conditions.dispersion_calibration_id)
  assert.deepEqual((await call(page, `/api/v1/methods/${existing.id}/versions`)).find(v => v.id === publishedSnapshot.id), publishedSnapshot)
  assert.deepEqual(saved.published_version, saved.version)
  assert.deepEqual(saved.version.lines, publishedSnapshot.lines)
  result.checks.push('Unrelated save preserves existing subset, curve, layout, lines and immutable published snapshot')

  await page.getByLabel('色散曲线', { exact: true }).selectOption(String(alternate.id))
  saved = await save()
  assert.equal(saved.version.conditions.ccd_layout_id, alternateLayout.id)
  assert.equal(saved.version.conditions.dispersion_calibration_id, alternate.id)
  assert.deepEqual(saved.version.conditions.selected_ccds, [0, 2])
  assert.deepEqual(saved.version.validation_errors, [])
  assert.deepEqual((await call(page, `/api/v1/methods/${existing.id}/versions`)).find(v => v.id === publishedSnapshot.id), publishedSnapshot)
  assert.deepEqual(saved.published_version, saved.version)
  await page.reload()
  await page.getByTestId('workspace').waitFor()
  await navigate(page, entry.group, entry.label, '.methods-page')
  await page.getByLabel('选择编辑方法').waitFor()
  await page.getByLabel('选择编辑方法').selectOption(String(existing.id))
  assert.equal(await page.getByLabel('色散曲线', { exact: true }).inputValue(), String(alternate.id))
  result.checks.push('Cross-layout curve selection derives and persists exact installed CCDs and layout across reload')

  const detect = wavelength_nm => call(page, `/api/v1/methods/${existing.id}/lines/detect`, { wavelength_nm })
  assert.equal((await detect(254)).detectable, true)
  assert.equal((await detect(500)).reason_code, 'wavelength_not_on_ccd')
  const range = alternate.ccd_ranges.find(item => item.ccd_index === 0)
  const unsafe = (range.wavelength_start_nm + range.safe_start_nm) / 2
  assert.equal((await detect(unsafe)).reason_code, 'wavelength_outside_safe_boundary')
  await page.locator('.method-editor-tabs button').filter({ hasText: '分析谱线' }).click()
  await page.getByRole('button', { name: '添加谱线', exact: true }).click()
  const wavelength = page.getByLabel('理论波长 (nm)', { exact: true })
  await wavelength.fill('254')
  await page.locator('.detectability-card').getByText('当前条件可检测', { exact: true }).waitFor()
  await wavelength.fill('500')
  await page.locator('.detectability-card').getByText('当前条件不可检测', { exact: true }).waitFor()
  const unchangedVersion = saved.version.content_sha256
  assert.equal((await call(page, `/api/v1/methods/${existing.id}`)).version.content_sha256, unchangedVersion)
  result.checks.push('Automatic added-line feedback and API coverage/safety rejection remain active without writing invalid drafts')
  await page.locator('.method-editor-tabs button').filter({ hasText: '方法管理与参数' }).click()

  const quality = page.locator('.method-error-settings')
  assert.equal(await page.locator('details.method-error-settings').count(), 0)
  const threshold = quality.getByLabel('重复摄谱最大允许误差[^P]', { exact: true })
  await threshold.waitFor({ state: 'visible' })
  await threshold.fill('')
  const invalidVersion = saved.version.content_sha256
  let invalidWrites = 0
  const trackWrite = request => { if (request.method() === 'POST' && request.url().endsWith(`/api/v1/methods/${existing.id}/save`)) invalidWrites++ }
  page.on('request', trackWrite)
  await page.getByRole('button', { name: '保存', exact: true }).first().click()
  assert.equal(await threshold.evaluate(node => document.activeElement === node), true)
  assert.equal(invalidWrites, 0)
  assert.equal((await call(page, `/api/v1/methods/${existing.id}`)).version.content_sha256, invalidVersion)
  page.off('request', trackWrite)
  await threshold.fill('6.5')
  await quality.getByLabel('相对偏差校验', { exact: true }).check()
  await quality.getByLabel('最大允许Rsd[%]', { exact: true }).fill('7.5')
  await page.getByRole('button', { name: '添加角度', exact: true }).click()
  await page.getByRole('button', { name: '添加角度', exact: true }).click()
  await page.getByLabel('第2项转角', { exact: true }).fill('10')
  await page.getByLabel('第3项转角', { exact: true }).fill('20')
  await page.getByLabel('第2项存储方式', { exact: true }).selectOption('full_interval')
  saved = await save()
  assert.equal(saved.version.conditions.maximum_id_deviation, 6.5)
  assert.equal(saved.version.conditions.rsd_threshold, 7.5)
  assert.deepEqual(saved.version.conditions.angle_exposures.map(item => [item.angle_deg, item.storage_mode]),
    [[0, 'averaged'], [10, 'full_interval'], [20, 'averaged']])
  assert.deepEqual((await call(page, `/api/v1/methods/${existing.id}/versions`)).find(v => v.id === publishedSnapshot.id), publishedSnapshot)
  assert.deepEqual(saved.published_version, saved.version)
  result.checks.push('Always visible error controls validate empty input with zero writes; error values and three angles save without changing published data')

  for (const [theme, density, width] of [['light', 'comfortable', 1440], ['dark', 'compact', 1060], ['light', 'compact', 1060], ['dark', 'comfortable', 1440]]) {
    if (process.env.QA_CDP) {
      await page.evaluate(width => window.__TAURI__.core.invoke('plugin:window|set_size', { value: { Logical: { width, height: 1000 } } }), width)
      await page.waitForFunction(width => Math.abs(innerWidth - width) < 2, width)
    } else await page.setViewportSize({ width, height: 1000 })
    await call(page, '/api/v1/settings', { display: { theme, density } }, 'PATCH')
    await page.getByRole('button', { name: '刷新服务状态', exact: true }).click()
    await page.waitForFunction(({ theme, density }) => document.querySelector('.app-shell')?.dataset.theme === theme
      && document.querySelector('.app-shell')?.dataset.density === density, { theme, density })
    const layout = await page.evaluate(() => ({ width: innerWidth, devicePixelRatio,
      overflow: document.documentElement.scrollWidth > innerWidth + 1,
      fields: [...document.querySelectorAll('.method-geometry .field')].map(node => {
        const rect = node.getBoundingClientRect(); return { label: node.textContent, x: rect.x, right: rect.right }
      }) }))
    assert.equal(layout.overflow, false)
    assert.ok(layout.fields.every(field => field.x >= 0 && field.right <= width + 1))
    const geometry = await page.locator('.method-geometry').boundingBox()
    const excitation = await page.locator('.method-excitation').boundingBox()
    const angles = await page.locator('.method-angle-selection').boundingBox()
    const entries = await page.locator('.method-angle-entry').evaluateAll(nodes => nodes.map(node => {
      const { x, y, width, height } = node.getBoundingClientRect(); return { x, y, width, height }
    }))
    assert.ok(Math.abs(geometry.y - excitation.y) < 2 && Math.abs(geometry.height - excitation.height) < 2,
      'Spectrum and excitation panels align at both top and bottom')
    assert.ok(excitation.x > geometry.x + geometry.width)
    assert.ok(angles.y >= geometry.y + geometry.height && Math.abs(angles.x - geometry.x) < 2
      && Math.abs(angles.width - (excitation.x + excitation.width - geometry.x)) < 2, 'Angles occupy their own full-width row below both panels')
    assert.equal(entries.length, 3)
    assert.ok(Math.abs(entries[0].y - entries[1].y) < 2 && entries[1].x > entries[0].x)
    assert.ok(entries[2].y > entries[0].y && Math.abs(entries[2].x - entries[0].x) < 2, 'Third angle wraps after exactly two entries')
    assert.equal(await threshold.isVisible(), true)
    result.layouts.push({ theme, density, ...layout, geometry, excitation, angles, entries })
    await page.locator('.method-parameters-grid').evaluate(node => node.scrollIntoView({ block: 'start' }))
    await page.screenshot({ path: path.join(output, `methods-${width}-${theme}.png`) })
    if (theme === 'light' && width === 1440 || theme === 'dark' && width === 1060) {
      await page.locator('.method-quality').evaluate(node => node.scrollIntoView({ block: 'center' }))
      await page.locator('.method-quality').screenshot({ path: path.join(output, `quality-${width}-${theme}.png`) })
    }
  }

  await page.getByLabel('色散曲线', { exact: true }).selectOption(String(defaultCurve.id))
  saved = await save()
  assert.deepEqual(saved.version.conditions.selected_ccds, options.ccd_layouts.find(item => item.id === defaultCurve.ccd_layout_id).ccd_indices)
  assert.equal(saved.version.conditions.dispersion_calibration_id, defaultCurve.id)
  assert.deepEqual((await call(page, `/api/v1/methods/${existing.id}/versions`)).find(v => v.id === publishedSnapshot.id), publishedSnapshot)
  assert.deepEqual(saved.published_version, saved.version)
  result.checks.push('Switching back restores CCD set; four layouts keep equal panels, full-width two-column angles, and expanded error fields without overflow')
}
