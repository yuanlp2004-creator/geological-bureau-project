import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import path from 'node:path'
import { call, navigate } from './contract_browser_support.mjs'
import { leaveLegacyCapture } from './legacy_desk_test_support.mjs'

export async function checkCaptureLines(page, result, output) {
  const check = text => result.checks.push(text)
  const options = await call(page, '/api/v1/methods/options')
  const calibration = options.dispersion_calibrations.find(item => item.name === 'default')
  assert.ok(calibration)
  const method = await call(page, '/api/v1/methods', { name: `谱线布局${Date.now().toString(36)}`, conditions: {
    exposure_mode: 'simple_mean', selected_ccds: [0, 1], frame_count: 2, dark_frame_count: 1,
    pre_excitation_seconds: 1, sampling_period_seconds: 1,
    angle_exposures: [{ angle_deg: 0, storage_mode: 'averaged', start_frame: 1, end_frame: 2 }]
  } })
  const template = JSON.parse(await readFile(new URL('./fixtures/station17-line.json', import.meta.url), 'utf8'))
  for (const ccd of [0, 1]) {
    const range = calibration.ccd_ranges.find(item => item.ccd_index === ccd)
    const wave = (range.safe_start_nm + range.safe_end_nm) / 2
    await call(page, `/api/v1/methods/${method.id}/lines`, {
      ...template, element: ccd ? 'Fe' : 'Cu', wavelength_nm: wave, actual_wavelength_nm: wave
    })
  }
  const published = await call(page, `/api/v1/methods/${method.id}/publish`, {})
  await call(page, '/api/v1/methods/current', { method_id: method.id })
  const linesUrl = `/api/v1/methods/${method.id}/lines?version=${published.current_version}`
  const snapshot = await call(page, linesUrl)
  const tasks = []
  const complete = async (base, task) => {
    await call(page, `${base}/${task.id}/start`, {})
    for (let i = 0; i < 60; i++) {
      const current = await call(page, `${base}/${task.id}/step`, {})
      if (current.status === 'completed') return current
      assert.ok(!['failed', 'stopped'].includes(current.status), current.failure_message)
    }
    assert.fail('模拟摄谱未完成')
  }
  for (const kind of ['sample', 'evaporation']) {
    const task = await call(page, '/api/v1/acquisitions/tasks', {
      name: `谱线布局-${kind}`, task_kind: kind, method_id: method.id, method_version: published.current_version,
      ccd_indices: [0, 1], burn_frame_count: 2, dark_frame_count: 1,
      pre_excitation_seconds: 1, sampling_period_seconds: 1, repeat_count: 1, countdown_seconds: 0,
      sample_name: 'LINE01'
    })
    tasks.push(await complete('/api/v1/acquisitions/tasks', task))
  }
  let dispersion = await call(page, '/api/v1/dispersion/tasks', {
    name: '谱线布局-dispersion', frame_count: 2, dark_frame_count: 1, pre_excitation_seconds: 1, ccd_indices: [0, 1]
  })
  dispersion = await complete('/api/v1/dispersion/tasks', dispersion)
  for (const [ccd, position] of [[0, 0], [0, 500], [1, 800]])
    await call(page, `/api/v1/dispersion/tasks/${dispersion.id}/line-points`, { ccd_index: ccd, point_index: position })
  dispersion = await call(page, `/api/v1/dispersion/tasks/${dispersion.id}`)
  // A newer draft must never replace the lines bound to the existing capture tasks.
  const draftWave = snapshot.lines.find(line => line.element === 'Fe').wavelength_nm + 0.1
  await call(page, `/api/v1/methods/${method.id}/lines`, { ...template, element: 'Zn', wavelength_nm: draftWave, actual_wavelength_nm: draftWave })
  await page.reload(); await page.getByTestId('workspace').waitFor()
  const go = async (kind, id) => {
    await leaveLegacyCapture(page)
    const label = { sample: '样品摄谱', evaporation: '蒸发摄谱', dispersion: '色散摄谱' }[kind]
    const host = page.getByTestId(kind === 'dispersion' ? 'dispersion-page' : `${kind}-acquisition-page`)
    await navigate(page, 'analysis-tests', label, `[data-testid="${kind === 'dispersion' ? 'dispersion' : `${kind}-acquisition`}-page"]`)
    await host.locator(`tr[data-task-id="${id}"]`).getByRole('button').click()
    await host.locator('path.spectrum-line[d]').waitFor()
    return host
  }
  const selected = async (host, id, ccd, point, origin) => {
    await page.waitForFunction(({ id, ccd }) => {
      const host = document.querySelector('.legacy-capture-desk')
      return host?.querySelector('select[aria-label="选择谱线"]')?.value === String(id)
        && host.querySelector('.spectrum-inspector')?.getAttribute('aria-label').startsWith(`CCD ${ccd + 1} `)
        && Boolean(host.querySelector('.plot-position-marker[aria-pressed="true"]'))
    }, { id, ccd })
    const coordinate = new RegExp(`坐标：${Math.round(point) + origin}(?: ·|$)`)
    await host.getByLabel('谱图同步读数', { exact: true }).filter({ hasText: coordinate }).waitFor()
    assert.match(await host.getByLabel('谱图同步读数', { exact: true }).textContent(), coordinate)
  }
  const layouts = [{ width: 1440, height: 1000, theme: 'light' }, { width: 1060, height: 680, theme: 'dark' }]
  for (const kind of ['sample', 'evaporation', 'dispersion']) {
    const task = kind === 'dispersion' ? dispersion : tasks.find(task => task.task_kind === kind)
    const host = await go(kind, task.id)
    const lines = kind === 'dispersion' ? dispersion.lines : snapshot.lines
    const dropdown = host.getByLabel('选择谱线', { exact: true })
    await page.waitForFunction(count => document.querySelector('select[aria-label="选择谱线"]').options.length === count, lines.length + 1)
    assert.equal(await host.locator('.inspector-markers').count(), 0)
    for (const name of ['任务详情', '谱图读数', '采后样号与任务详情'])
      assert.equal(await host.getByRole('button', { name, exact: true }).count(), 0)
    assert.equal(await host.locator('.legacy-task-details, .spectrum-observer-dialog, .acquisition-facts').count(), 0)
    assert.equal(await host.locator('.legacy-window-caption + .capture-context').count(), 0)
    const sampleInput = host.getByRole('group', { name: '样号输入', exact: true })
    if (kind === 'sample') {
      assert.equal(await sampleInput.getByRole('combobox', { name: '样品编号', exact: true }).count(), 1)
      assert.equal(await sampleInput.getByRole('textbox', { name: '重复摄谱', exact: true }).count(), 1)
    } else {
      assert.equal(await sampleInput.getByRole('textbox', { name: kind === 'dispersion' ? '色散谱带名' : '蒸发谱带名', exact: true }).count(), 1)
      assert.equal(await sampleInput.getByRole('combobox').count(), 0)
      assert.equal(await sampleInput.getByRole('textbox', { name: '重复摄谱', exact: true }).count(), 0)
      const inputBox = await sampleInput.getByRole('textbox').boundingBox()
      const groupBox = await sampleInput.boundingBox()
      assert.ok(inputBox.width >= groupBox.width * 0.8, '色散／蒸发谱带名称应占满单列')
    }
    await host.locator('.legacy-plot-frame').dblclick({ position: { x: 15, y: 15 } })
    assert.equal(await host.locator('dialog[open]').count(), 0)
    const otherCcd = lines.find(line => (line.ccd_index ?? line.detectability?.ccd_index) === 1)
    const point = otherCcd.located_position ?? otherCcd.detectability?.point_index
    await dropdown.selectOption(String(otherCcd.id))
    await selected(host, otherCcd.id, 1, point, kind === 'dispersion' ? 0 : 1)
    await dropdown.selectOption('')
    const marker = host.locator('.plot-position-marker[role="button"]').first()
    await marker.locator('circle').click()
    assert.equal(await dropdown.inputValue(), String(otherCcd.id))
    await dropdown.selectOption(''); await marker.focus(); await marker.press('Enter')
    assert.equal(await dropdown.inputValue(), String(otherCcd.id))
    await dropdown.selectOption(''); await marker.focus(); await marker.press('Space')
    assert.equal(await dropdown.inputValue(), String(otherCcd.id))
    assert.equal(await marker.evaluate(element => getComputedStyle(element).outlineStyle), 'none', '键盘焦点应标识圆点，不能围住整条竖线')
    check(`${kind}：无任务详情／读数按钮、弹窗及底栏；图内读数，顶部与标记跨CCD联动；样号输入符合旧版分类`)
    if (kind === 'dispersion') {
      const zero = lines.find(line => line.located_position === 0)
      await dropdown.selectOption(String(zero.id)); await selected(host, zero.id, 0, 0, 0)
      check('色散第0点可选择并定位，无起点偏移')
    }
    for (const layout of layouts) {
      if (process.env.QA_CDP) await page.evaluate(size => window.__TAURI__.core.invoke('plugin:window|set_size', { value: { Logical: size } }), { width: layout.width, height: layout.height })
      else await page.setViewportSize({ width: layout.width, height: layout.height })
      await page.evaluate(theme => { document.documentElement.dataset.theme = theme }, layout.theme)
      const box = await host.locator('.spectrum-inspector').boundingBox()
      assert.ok(box.height > 150 && box.width > 200, JSON.stringify(box))
      assert.equal(await host.locator('.inspector-markers').count(), 0)
      await page.screenshot({ path: path.join(output, `${kind}-${layout.width}-${layout.theme}.png`) })
      result.layouts.push({ kind, ...layout, plot: box })
    }
  }
  assert.deepEqual(await call(page, linesUrl), snapshot)
  for (const task of tasks) {
    const current = await call(page, `/api/v1/acquisitions/tasks/${task.id}`)
    assert.equal(current.result_sha256, task.result_sha256)
  }
  check('历史任务使用确切已发布谱线，观察操作保持正式谱带哈希')
  // Failed reads must leave the top selector empty and never show lines from the previous task.
  await leaveLegacyCapture(page)
  await page.route(`**${linesUrl}`, route => route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: { code: 'QA_LINES_UNAVAILABLE', message: '模拟谱线读取失败' } }) }))
  await page.reload(); await page.getByTestId('workspace').waitFor()
  const failed = await go('sample', tasks[0].id)
  const empty = failed.getByLabel('选择谱线', { exact: true })
  await page.waitForFunction(() => document.querySelector('select[aria-label="选择谱线"]')?.title.includes('模拟谱线读取失败'))
  assert.equal(await empty.isDisabled(), true)
  assert.equal(await failed.locator('.plot-position-marker, .inspector-markers').count(), 0)
  assert.ok(await failed.locator('path.spectrum-line[d]').count())
  await page.unroute(`**${linesUrl}`)
  check('谱线读取失败时清空并禁用选择，已保存谱图仍可观察')
  await leaveLegacyCapture(page)
  assert.equal(await failed.locator('.acquisition-record-review, .acquisition-rename, .acquisition-measurements, .acquisition-messages').count(), 0)
  assert.equal((await call(page, `/api/v1/acquisitions/tasks/${tasks[0].id}`)).result_sha256, tasks[0].result_sha256)
  check('返回任务列表后不再显示额外记录详情，历史任务与原始结果哈希保持')
}
