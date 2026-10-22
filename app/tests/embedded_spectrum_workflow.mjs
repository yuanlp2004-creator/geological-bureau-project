import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import path from 'node:path'
import { call, navigate } from './contract_browser_support.mjs'

// 使用真实隔离API与鼠标操作，验证观察不写业务数据及点位坐标没有偏移。
export async function checkEmbeddedSpectra(page, output, checks) {
  const method = await call(page, '/api/v1/methods', { name: '谱图工具检查方法' })
  const line = JSON.parse(await readFile(path.join(process.cwd(), 'tests/fixtures/station17-line.json'), 'utf8'))
  await call(page, `/api/v1/methods/${method.id}/lines`, line)
  await call(page, `/api/v1/methods/${method.id}/publish`, {})
  await call(page, `/api/v1/methods/${method.id}/open`, {})
  let dispersion = await call(page, '/api/v1/dispersion/tasks', {
    name: '谱图检查色散', frame_count: 3, dark_frame_count: 1, pre_excitation_seconds: 0
  })
  const dl = await call(page, `/api/v1/dispersion/tasks/${dispersion.id}/lines`, {
    element: 'Fe', wavelength_nm: 260, ccd_index: 0
  })
  dispersion = await call(page, `/api/v1/dispersion/tasks/${dispersion.id}/start`, {})
  for (let i = 0; i < 12 && dispersion.status !== 'completed'; i++)
    dispersion = await call(page, `/api/v1/dispersion/tasks/${dispersion.id}/step`, {})
  assert.equal(dispersion.status, 'completed')
  const second = await call(page, '/api/v1/dispersion/tasks', { name: '空任务切换检查' })
  let sample = await call(page, '/api/v1/acquisitions/tasks', { name: '谱图检查样品',
    sample_name: 'S001', burn_frame_count: 2, dark_frame_count: 0, pre_excitation_seconds: 0,
    countdown_seconds: 0, method_id: method.id, seed: 123 })
  sample = await call(page, `/api/v1/acquisitions/tasks/${sample.id}/start`, {})
  for (let i = 0; i < 50 && sample.status !== 'completed'; i++)
    sample = await call(page, `/api/v1/acquisitions/tasks/${sample.id}/step`, {})
  assert.equal(sample.status, 'completed')
  const mo = await call(page, '/api/v1/mercury-calibrations/options')
  let mercury = await call(page, '/api/v1/mercury-calibrations/sessions', { name: '谱图检查汞灯',
    line_ids: mo.reference_lines.filter((line) => line.enabled).slice(0, 3).map((line) => line.id) })
  mercury = await call(page, `/api/v1/mercury-calibrations/sessions/${mercury.id}/start`, {})
  for (let i = 0; i < 16 && !['ready', 'safe_off', 'deferred_external'].includes(mercury.status); i++)
    mercury = await call(page, `/api/v1/mercury-calibrations/sessions/${mercury.id}/step`, {})
  assert.equal(mercury.status, 'ready')
  let hardware = await call(page, '/api/v1/hardware-acquisitions/tasks', { name: '谱图检查转角', method_id: method.id })
  hardware = await call(page, `/api/v1/hardware-acquisitions/tasks/${hardware.id}/start`, {})
  for (let i = 0; i < 100 && !['completed', 'failed', 'safety_stopped', 'manual_intervention'].includes(hardware.status); i++)
    hardware = await call(page, `/api/v1/hardware-acquisitions/tasks/${hardware.id}/step`, {})
  assert.equal(hardware.status, 'completed')
  const caps = await call(page, '/api/v1/capabilities')
  const entries = caps.capabilities.flatMap((capability) => capability.navigation_entries ?? [])
  const go = async (name) => {
    const entry = entries.find((entry) => entry.page === name && (name !== 'dispersion' || entry.view === 'curve'))
    await navigate(page, entry.group, entry.label, '.page-content')
  }
  let writes = 0
  const observe = (request) => { if (['POST', 'PATCH', 'DELETE', 'PUT'].includes(request.method())) writes++ }
  page.on('request', observe)
  const readNumber = async (scope) => {
    const text = await scope.getByLabel('谱图点位读数').textContent()
    return Number(text.match(/强度 ([\d,.-]+)/)[1].replaceAll(',', ''))
  }
  const exercise = async (scope, expected, origin) => {
    await scope.locator('svg.spectrum-plot .spectrum-line').waitFor()
    const before = writes
    const input = scope.getByLabel('读取点位', { exact: true })
    await input.fill(String(123 + origin)); await input.blur()
    assert.ok(Math.abs(await readNumber(scope) - expected[123]) < 0.000001)
    await scope.getByRole('button', { name: '横向放大', exact: true }).click()
    await scope.getByRole('button', { name: '纵向放大', exact: true }).click()
    assert.ok(Math.abs(await readNumber(scope) - expected[123]) < 0.000001)
    await scope.getByRole('button', { name: '适合图像', exact: true }).click()
    const svg = scope.locator('svg.spectrum-plot'), box = await svg.boundingBox()
    await scope.getByLabel('谱图工具', { exact: true }).selectOption('box')
    await page.mouse.move(box.x + box.width * 0.3, box.y + box.height * 0.3)
    await page.mouse.down(); await page.mouse.move(box.x + box.width * 0.7, box.y + box.height * 0.7, { steps: 5 }); await page.mouse.up()
    const afterBox = await scope.locator('.inspector-readout small').textContent()
    assert.ok(!afterBox.startsWith(`视野 ${origin}.0–${expected.length - 1 + origin}.0`))
    await scope.getByLabel('谱图工具', { exact: true }).selectOption('pan')
    await page.mouse.move(box.x + box.width * 0.5, box.y + box.height * 0.5)
    await page.mouse.down(); await page.mouse.move(box.x + box.width * 0.6, box.y + box.height * 0.5, { steps: 4 }); await page.mouse.up()
    assert.notEqual(await scope.locator('.inspector-readout small').textContent(), afterBox)
    await scope.getByRole('button', { name: '适合图像', exact: true }).click()
    await scope.getByLabel('谱图工具', { exact: true }).selectOption('crosshair')
    const frame = await svg.locator('.plot-background').boundingBox()
    const x = frame.x + frame.width * 0.25, y = frame.y + frame.height * 0.5
    await page.mouse.move(x, y)
    await page.waitForTimeout(80)
    const expectedIndex = Math.round((expected.length - 1) * 0.25)
    assert.ok(Math.abs(await readNumber(scope) - expected[expectedIndex]) < 0.000001)
    await page.mouse.click(x, y)
    await scope.getByRole('button', { name: '解除锁定', exact: true }).waitFor()
    assert.equal(writes, before, '观察工具应只改变视图')
  }
  try {
    for (const [theme, density, width] of [['light', 'comfortable', 1440], ['dark', 'compact', 1060]]) {
      await page.setViewportSize({ width, height: 1000 })
      await call(page, '/api/v1/settings', { display: { theme, density } }, 'PATCH')
      await page.reload(); await page.locator('.sidebar').waitFor()
      await page.waitForFunction((theme) => document.documentElement.dataset.theme === theme, theme)
      for (const name of ['dispersion', 'sample-acquisition', 'mercury-calibration', 'hardware-acquisition']) {
        await go(name)
        if (name === 'dispersion') await page.locator('.dispersion-task-list button').filter({ hasText: dispersion.name }).click()
        const scope = page.locator('.spectrum-inspector:visible').first()
        await scope.locator('svg.spectrum-plot').waitFor()
        let points, origin = 1
        if (name === 'dispersion') { origin = 0; points = dispersion.last_event.ccds[0].points }
        if (name === 'sample-acquisition') points = (await call(page, `/api/v1/acquisitions/tasks/${sample.id}?include_points=true`)).last_event.ccds[0].points
        if (name === 'mercury-calibration') points = mercury.last_event.ccds[0].points
        if (name === 'hardware-acquisition') points = (await call(page, `/api/v1/hardware-acquisitions/tasks/${hardware.id}/frames?include_points=true`)).at(-1).points
        await exercise(scope, points, origin)
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false, `${name} overflow`)
        await scope.screenshot({ path: path.join(output, `${name}-${theme}-${width}.png`) })
        checks.push(`${name}: ${theme}/${width} 真实点值、十字线、锁定、双轴缩放、框选、平移，观察零写入`)
      }
    }
    await go('dispersion')
    const host = page.locator('.dispersion-page')
    await host.locator('.dispersion-task-list button').filter({ hasText: dispersion.name }).click()
    const scope = host.locator('.spectrum-inspector')
    await scope.getByLabel('读取点位', { exact: true }).fill('123')
    await scope.getByLabel('读取点位', { exact: true }).blur()
    await host.getByLabel('人工定位谱线').selectOption(String(dl.id))
    await scope.getByRole('button', { name: '横向放大', exact: true }).click()
    await Promise.all([
      page.waitForResponse((response) => response.url().includes(`/lines/${dl.id}/position?`) && response.status() === 200),
      host.getByRole('button', { name: '采用锁定点位', exact: true }).click()
    ])
    assert.equal((await call(page, `/api/v1/dispersion/tasks/${dispersion.id}`)).lines[0].located_position, 123)
    checks.push('色散人工定位：缩放后零起点坐标123原样提交，无一位偏移')
    const frames = await call(page, `/api/v1/dispersion/tasks/${dispersion.id}/frames?ccd_index=0`)
    await host.getByLabel('色散谱图数据').selectOption('frame')
    await host.getByLabel('色散历史帧').selectOption(String(frames[0].id))
    await scope.getByLabel('读取点位', { exact: true }).fill('123'); await scope.getByLabel('读取点位', { exact: true }).blur()
    assert.equal(await readNumber(scope), frames[0].points[123])
    const dark = frames.find((frame) => frame.phase === 'dark')
    await host.getByLabel('色散历史帧').selectOption(String(dark.id))
    await scope.getByLabel('读取点位', { exact: true }).fill('123'); await scope.getByLabel('读取点位', { exact: true }).blur()
    assert.equal(await readNumber(scope), dark.points[123])
    await host.getByLabel('色散谱图数据').selectOption('average')
    await scope.getByLabel('读取点位', { exact: true }).fill('123'); await scope.getByLabel('读取点位', { exact: true }).blur()
    const burns = frames.filter((frame) => frame.phase === 'burn')
    assert.ok(Math.abs(await readNumber(scope) - burns.reduce((sum, frame) => sum + frame.points[123], 0) / burns.length) < 0.000001)
    checks.push('色散已保存单帧与燃烧区间观察均值符合原始帧，观察不改拟合输入')
    await host.locator('.dispersion-task-list button').filter({ hasText: second.name }).click()
    await host.getByText('锁定实际点位：未选择', { exact: true }).waitFor()
    assert.equal(await scope.locator('svg').count(), 0)
    assert.equal(await host.getByRole('button', { name: '采用锁定点位', exact: true }).isDisabled(), true)
    checks.push('切换空任务清空锁定与谱图，禁止旧点位提交')
    if (!process.env.QA_CDP) {
      await host.locator('.dispersion-task-list button').filter({ hasText: dispersion.name }).click()
      await page.route(`**/dispersion/tasks/${dispersion.id}/frames*`, (route) => route.fulfill({
        status: 503, contentType: 'application/json', body: JSON.stringify({ message: 'QA历史帧不可用' })
      }))
      await host.getByLabel('色散谱图数据').selectOption('frame')
      await host.getByRole('alert').filter({ hasText: 'QA历史帧不可用' }).waitFor()
      assert.equal(await scope.locator('svg').count(), 0)
      await page.unroute(`**/dispersion/tasks/${dispersion.id}/frames*`)
      await host.getByRole('button', { name: '刷新已保存帧', exact: true }).click()
      await scope.locator('svg').waitFor()
      checks.push('历史帧失败明确提示且不冒充实时帧，刷新可恢复')
    }
    await host.locator('.dispersion-task-list button').filter({ hasText: dispersion.name }).click()
    await scope.locator('svg').waitFor()
    await scope.getByLabel('读取点位', { exact: true }).fill('')
    await scope.getByLabel('读取点位', { exact: true }).blur()
    assert.equal(await host.getByRole('button', { name: '采用锁定点位', exact: true }).isDisabled(), true)
    const captureEntry = entries.find((entry) => entry.page === 'dispersion' && entry.view !== 'curve')
    await navigate(page, captureEntry.group, captureEntry.label, '.dispersion-page[data-view="capture"]')
    const toggle = host.getByRole('button', { name: '新建任务与采集条件', exact: true })
    if (await toggle.getAttribute('aria-expanded') === 'false') await toggle.click()
    const beforeCreate = writes
    await Promise.all([
      page.waitForResponse((response) => response.url().endsWith('/dispersion/tasks') && response.request().method() === 'POST'),
      host.getByRole('button', { name: '新建任务', exact: true }).click()
    ])
    assert.equal(writes, beforeCreate + 1)
    checks.push('观察点位空输入清除定位锁定，不阻断有效采集条件的新建任务')
  } finally { page.off('request', observe) }
}
