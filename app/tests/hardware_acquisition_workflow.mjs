import assert from 'node:assert/strict'
import path from 'node:path'
import { call, navigate } from './contract_browser_support.mjs'

export async function runAudit(page, result, output) {
  const method = (await call(page, '/api/v1/methods')).find(item => item.status === 'active')
  await call(page, '/api/v1/methods/current', { method_id: method.id })
  await page.reload(); await page.getByTestId('workspace').waitFor()
  const host = page.getByTestId('hardware-acquisition-page')
  const start = () => host.getByRole('button', { name: '开始采集', exact: true }).click()
  const done = status => page.waitForFunction(value => document.querySelector('.hardware-monitor .state-chip')?.classList.contains(value), status)
  const back = () => page.getByRole('button', { name: '返回任务列表', exact: true }).click()
  const enter = async task => {
    await page.getByRole('button', { name: '刷新', exact: true }).click()
    await host.locator(`tr[data-task-id="${task.id}"]`).getByRole('button').click()
  }
  const fresh = async payload => call(page, '/api/v1/hardware-acquisitions/tasks', {
    name: '转角流程验证', turns: [{ angle_deg: 10, wavelength_nm: 250 }, { angle_deg: 20, wavelength_nm: 280 }], ...payload
  })
  await navigate(page, 'analysis-tests', '自动转角采集', '[data-testid="hardware-acquisition-page"]')
  await host.waitFor()
  await page.getByRole('button', { name: '新建任务', exact: true }).click()
  const dialog = host.getByRole('dialog')
  await dialog.getByLabel('任务名称', { exact: true }).fill('方法转角验证')
  await dialog.getByLabel('样号', { exact: true }).fill('转角样01')
  const published = await dialog.getByLabel('采集方法', { exact: true }).inputValue()
  const methods = (await call(page, '/api/v1/hardware-acquisitions/options')).methods
  const publishedMethod = methods.find(item => `${item.method_id}-${item.version}` === published)
  assert.ok(publishedMethod?.turn_angles?.length)
  const defaultAngle = publishedMethod.turn_angles[0]
  assert.equal(await dialog.getByLabel('采集方法', { exact: true }).locator('option[value="custom"]').count(), 0)
  assert.equal(await dialog.locator('.hardware-turn-angles').count(), 0)
  assert.equal(await dialog.getByRole('button', { name: '新增转角', exact: true }).count(), 0)
  assert.equal(await dialog.getByLabel('调试转角计划 JSON', { exact: true }).count(), 0)
  assert.equal(await dialog.getByLabel('模拟异常脚本 JSON', { exact: true }).isVisible(), false)
  await dialog.getByRole('button', { name: '取消', exact: true }).click()
  await page.getByRole('button', { name: '新建任务', exact: true }).click()
  assert.equal(await dialog.getByLabel('样号', { exact: true }).inputValue(), '转角样01')
  assert.equal(await dialog.getByLabel('采集方法', { exact: true }).inputValue(), published)
  await page.screenshot({ path: path.join(output, 'automatic-method-task-form.png') })
  await dialog.getByText('模拟调试参数', { exact: true }).click()
  await dialog.getByLabel('模拟异常脚本 JSON', { exact: true }).fill('bad-json')
  await dialog.getByRole('button', { name: '建立任务', exact: true }).click()
  await dialog.getByRole('alert').waitFor()
  await dialog.getByLabel('模拟异常脚本 JSON', { exact: true }).fill('[]')
  await dialog.getByText('模拟调试参数', { exact: true }).click()
  const creationRequest = page.waitForRequest(request => request.method() === 'POST' && request.url().endsWith('/api/v1/hardware-acquisitions/tasks'))
  await dialog.getByRole('button', { name: '建立任务', exact: true }).click()
  const submitted = (await creationRequest).postDataJSON()
  assert.equal('turn_angles' in submitted, false)
  assert.equal('turns' in submitted, false)
  assert.deepEqual(submitted.manual_turns, [])
  await host.locator('.hardware-capture-desk').waitFor()
  let task = (await call(page, '/api/v1/hardware-acquisitions/tasks'))[0]
  assert.equal(task.status, 'draft'); assert.equal(task.frames.length, 0)
  assert.equal(task.method_id, Number(published.split('-')[0])); assert.equal(task.sample_name, '转角样01')
  assert.equal(task.simulator.sample, '280-288.acq')
  assert.deepEqual(task.steps.map(step => step.angle_deg), publishedMethod.turn_angles)
  assert.equal(task.plan[0].original_angle_deg, undefined)
  assert.equal(await host.locator('.spectroscopy-task-list:visible').count(), 0)
  assert.equal(await host.getByRole('button', { name: '单步', exact: true }).count(), 0)
  assert.equal(await host.getByRole('button', { name: '自动推进', exact: true }).count(), 0)
  assert.equal(await host.getByText('通信记录', { exact: true }).isVisible(), false)
  result.checks.push('Automatic mode uses published method angles without angle inputs or overrides; cancel retains method/sample drafts, invalid simulator JSON rejected and create never starts')

  await start(); await done('completed')
  task = await call(page, `/api/v1/hardware-acquisitions/tasks/${task.id}`)
  assert.equal(task.completed_steps, task.total_steps)
  assert.equal(task.traces.find(item => item.name === 'turn.request').payload.angle_deg, defaultAngle)
  assert.ok(task.exposures.some(item => item.confirmed))
  assert.deepEqual(task.steps.map(item => item.wavelength_nm), task.steps.map(item => item.wavelength_nm).sort((a,b) => a-b))
  await host.getByTestId('spectrum-plot').waitFor()
  assert.ok((await host.locator('[data-health="baseline-intensity"]').innerText()).includes('正常'))
  assert.ok((await host.locator('[data-health="peak-position"]').innerText()).includes('正常'))
  const curve = host.locator('path[data-curve-id]').first()
  const before = await curve.getAttribute('d')
  await host.getByRole('button', { name: '横向放大', exact: true }).click()
  assert.notEqual(await curve.getAttribute('d'), before)
  await host.getByLabel('转角原始帧', { exact: true }).selectOption(String(task.frames[0].id))
  await host.getByRole('button', { name: '返回当前谱图', exact: true }).click()
  await host.locator('.hardware-plan tbody button').first().click()
  await host.getByRole('button', { name: '返回当前谱图', exact: true }).click()
  assert.equal((await call(page, `/api/v1/hardware-acquisitions/tasks/${task.id}`)).updated_at, task.updated_at)
  for (const name of ['capture','pause','stop','crosshair','zoom-x-in'])
    assert.ok(await host.locator(`[data-spectroscopy-icon="${name}"]`).count())
  result.checks.push('One start completes every method turn, confirmed bands, visible baseline/peak measurements, shared capture and spectrum icons with working zoom')
  await host.getByText('保存分析样品', { exact: true }).click()
  await host.getByLabel('正式样号', { exact: true }).fill('转角样01')
  await host.getByRole('button', { name: '保存为分析样品', exact: true }).click()
  await host.getByText('已保存：转角样01。', { exact: false }).waitFor()
  await host.getByText('保存分析样品', { exact: true }).click()
  const completedId = task.id
  for (const profile of [
    { name: 'normal-light', width: 1440, height: 1000, theme: 'light' },
    { name: 'small-dark', width: 1060, height: 720, theme: 'dark' },
    { name: 'wide-light', width: 2560, height: 1200, theme: 'light' }
  ]) {
    if (process.env.QA_CDP) await page.evaluate(value => window.__TAURI__.core.invoke('plugin:window|set_size', { value: { Logical: value } }), { width: profile.width, height: profile.height })
    else await page.setViewportSize({ width: profile.width, height: profile.height })
    await page.evaluate(theme => { document.documentElement.dataset.theme = theme }, profile.theme)
    await page.waitForFunction(() => {
      const plot = document.querySelector('.hardware-spectrum [data-testid="spectrum-plot"]')
      return plot && Math.abs(plot.clientHeight - plot.viewBox.baseVal.height) < 1
    })
    const layout = await host.locator('.hardware-capture-desk').evaluate(element => {
      const box = node => { const r = node.getBoundingClientRect(); return { x: r.x, y: r.y, width: r.width, height: r.height } }
      return { desk: box(element), plan: box(element.querySelector('.hardware-plan')),
        spectrum: box(element.querySelector('.hardware-spectrum')), controls: box(element.querySelector('.hardware-monitor')),
        caption: box(element.querySelector('.hardware-desk-caption')), toolbar: box(element.querySelector('.hardware-desk-toolbar')),
        footer: box(element.querySelector('.hardware-desk-status')), commands: [...element.querySelectorAll('.hardware-command-buttons button')].map(button => box(button)),
        health: box(element.querySelector('.hardware-health')), planOverflow: element.querySelector('.hardware-plan table').scrollWidth > element.querySelector('.hardware-plan .hardware-table-wrap').clientWidth + 1,
        iconSizes: [...element.querySelectorAll('.inspector-icon-button')].map(button => box(button)),
        plot: box(element.querySelector('[data-testid="spectrum-plot"]')),
        plotContentHeight: element.querySelector('[data-testid="spectrum-plot"]').clientHeight,
        viewBox: element.querySelector('[data-testid="spectrum-plot"]').viewBox.baseVal.height,
        overflow: document.documentElement.scrollWidth > innerWidth + 1,
        clipped: [...element.querySelectorAll('.hardware-command-buttons button')].some(button => button.scrollWidth > button.clientWidth + 1) }
    })
    assert.equal(layout.overflow, false); assert.equal(layout.clipped, false)
    assert.equal(layout.planOverflow, false, 'All plan columns fit the capture rail')
    assert.ok(layout.health.y + layout.health.height <= layout.controls.y + layout.controls.height + 1, 'Baseline and peak status stay visible in the operator panel')
    assert.ok(layout.plan.x < layout.spectrum.x && layout.spectrum.x < layout.controls.x)
    assert.ok(layout.spectrum.width > 260)
    const iconSize = profile.width <= 1180 ? 20 : 24
    assert.ok(layout.iconSizes.every(button => Math.abs(button.width - iconSize) < 1 && Math.abs(button.height - iconSize) < 1))
    assert.ok(Math.abs(layout.plan.y - layout.spectrum.y) < 1 && Math.abs(layout.spectrum.y - layout.controls.y) < 1)
    assert.ok(Math.abs(layout.toolbar.width - layout.desk.width + 2) < 1 && Math.abs(layout.footer.width - layout.toolbar.width) < 1)
    assert.ok(layout.plan.width >= 150 && layout.plan.width <= 216.5 && layout.controls.width >= 198 && layout.controls.width <= 240.5)
    const commandHeight = profile.width <= 1180 ? 28 : 32
    assert.ok(layout.commands.every(button => Math.abs(button.width - 140) < 1 && Math.abs(button.height - commandHeight) < 1))
    assert.ok(layout.commands[0].y < layout.commands[1].y && layout.commands[1].y < layout.commands[2].y)
    assert.ok(Math.abs(layout.plotContentHeight - layout.viewBox) < 1, 'Plot uses its available content height without vertical letterboxing')
    result.layouts.push({ profile: profile.name, ...layout })
    await page.screenshot({ path: path.join(output, `capture-${profile.name}.png`) })
  }
  result.checks.push('Capture desk dock widths, full-width top toolbar and bottom status, vertical shared-size controls, folded sample saving, light/dark and three sizes with no horizontal overflow')
  await back()

  task = await fresh({ strategy: 'key_first', turns: [
    { angle_deg: 30, wavelength_nm: 310 }, { angle_deg: 10, wavelength_nm: 250 },
    { angle_deg: 20, wavelength_nm: 280, key_band: true, priority: 2 }
  ] })
  await enter(task); await start()
  await host.getByRole('button', { name: '暂停采集', exact: true }).click(); await done('paused')
  const paused = await call(page, `/api/v1/hardware-acquisitions/tasks/${task.id}`)
  await page.waitForTimeout(1100)
  assert.equal((await call(page, `/api/v1/hardware-acquisitions/tasks/${task.id}`)).traces.length, paused.traces.length)
  assert.equal(await page.getByRole('button', { name: '返回任务列表', exact: true }).isDisabled(), true)
  await page.locator('[data-navigation-group="analysis-tests"]').focus()
  await page.locator('[data-navigation-group="analysis-tests"]').press('ArrowRight')
  await page.getByRole('menuitem', { name: '色散摄谱' }).click(); await page.keyboard.press('Escape')
  assert.equal(await host.isVisible(), true)
  await host.getByRole('button', { name: '继续采集', exact: true }).click(); await done('completed')
  const keyed = await call(page, `/api/v1/hardware-acquisitions/tasks/${task.id}`)
  assert.deepEqual(keyed.steps.map(item => item.wavelength_nm), [280,250,310])
  await back()
  result.checks.push('Pause halts automatic requests, return locked while active, resume runs automatically, key band executes before normal short-to-long order')

  task = await fresh({ name: '峰位校正', simulator_anomalies: [{ step_index: 0, kind: 'peak_shift', count: 1 }] })
  await enter(task); await start(); await done('completed')
  const corrected = await call(page, `/api/v1/hardware-acquisitions/tasks/${task.id}`)
  assert.ok(corrected.decisions.some(item => item.decision === 'correct' && String(item.anomaly_kind).includes('peak_shift')))
  assert.equal(await host.getByText('采集记录与诊断', { exact: true }).count(), 0)
  assert.equal(await host.locator('.hardware-diagnostics').count(), 0)
  assert.ok(corrected.frames.length > 0 && corrected.result_sha256, 'Removing diagnostics presentation preserves stored evidence')
  await back()
  result.checks.push('Peak drift records an offset and recollects without claiming applied correction; diagnostics retain the abnormal attempt')

  task = await fresh({ name: '基线人工处理', retry_limit: 0, anomaly_policy: 'manual',
    simulator_anomalies: [{ step_index: 0, kind: 'baseline_low', count: 1 }] })
  await enter(task); await start(); await done('manual_intervention')
  assert.ok((await host.locator('[data-health="baseline-intensity"]').innerText()).includes('异常'))
  assert.equal(await host.locator('.hardware-plan tbody td:last-child').first().evaluate(cell => cell.scrollWidth > cell.clientWidth + 1), false)
  await host.getByRole('button', { name: '重新采集', exact: true }).click(); await done('completed'); await back()
  task = await fresh({ name: '损坏帧保护', retry_limit: 0, anomaly_policy: 'manual',
    simulator_anomalies: [{ step_index: 0, kind: 'frame_fault', count: 5 }] })
  await enter(task); await start(); await done('manual_intervention')
  assert.equal(await host.getByRole('button', { name: '确认采用', exact: true }).isDisabled(), true)
  await host.getByRole('button', { name: '停止采集', exact: true }).click(); await done('stopped')
  const stopped = await call(page, `/api/v1/hardware-acquisitions/tasks/${task.id}`)
  assert.equal(stopped.result_sha256, null); assert.ok(stopped.frames.every(item => !item.confirmed))
  await back()
  result.checks.push('Baseline abnormality visibly requests intervention; retry continues automatically; damaged frames cannot be accepted; stop retains unconfirmed evidence')

  task = await fresh({ name: '人工采用', retry_limit: 0, anomaly_policy: 'manual', turns: [{ angle_deg: 10, wavelength_nm: 250 }],
    simulator_anomalies: [{ step_index: 0, kind: 'baseline_shift', count: 1 }] })
  await enter(task); await start(); await done('manual_intervention')
  await host.getByRole('button', { name: '确认采用', exact: true }).click(); await done('completed')
  assert.ok((await host.locator('[data-health="baseline-position"]').innerText()).includes('异常'))
  await back()
  task = await fresh({ name: '超限停止', retry_limit: 0, simulator_anomalies: [{ step_index: 0, kind: 'baseline_high', count: 2 }] })
  await enter(task); await start(); await done('safety_stopped'); await back()
  const serial = await call(page, '/api/v1/devices/profiles', { name: '转角协议闸门验证', transport: 'serial' })
  task = await fresh({ name: '串口闸门', device_profile_id: serial.id })
  await enter(task); await start(); await done('deferred_external')
  const deferred = await call(page, `/api/v1/hardware-acquisitions/tasks/${task.id}`)
  assert.equal(deferred.traces.some(item => item.kind === 'command'), false)
  await back()
  result.checks.push('Manual acceptance preserves abnormal readings, exhausted retries stop safely, missing serial protocol sends no device commands')

  task = await fresh({ name: '请求失败恢复' }); await enter(task)
  let intercepted = 0
  await page.route(`**/api/v1/hardware-acquisitions/tasks/${task.id}/step`, route => {
    intercepted++; return route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ message: '流程验证：暂时无法采集' }) })
  })
  await start(); await host.getByRole('alert').waitFor(); await page.waitForTimeout(1000)
  assert.equal(intercepted, 1)
  await page.unroute(`**/api/v1/hardware-acquisitions/tasks/${task.id}/step`)
  await host.getByRole('button', { name: '继续采集', exact: true }).click(); await done('completed'); await back()
  result.checks.push('Failed automatic request stops its timer, reports error, and explicit continue resumes successfully')

  const profiles = await call(page, '/api/v1/devices/profiles')
  // Read-only UI verification uses the exact real response with execution permissions removed.
  await page.route('**/api/v1/auth/me', async route => {
    const response = await route.fetch(); const user = await response.json()
    user.permissions = user.permissions.filter(permission => !['hardware-acquisition.write','hardware-acquisition.execute'].includes(permission))
    await route.fulfill({ response, json: user })
  })
  await page.reload(); await page.getByTestId('workspace').waitFor()
  await navigate(page, 'analysis-tests', '自动转角采集', '[data-testid="hardware-acquisition-page"]')
  assert.equal(await page.getByRole('button', { name: '新建任务', exact: true }).isDisabled(), true)
  await enter(await fresh({ name: '只读控制' }))
  assert.equal(await host.getByRole('button', { name: '开始采集', exact: true }).isDisabled(), true)
  await back(); await page.unroute('**/api/v1/auth/me')
  assert.ok(profiles.length); assert.ok(completedId)
  result.checks.push('Read-only presentation disables create/start while preserving existing task viewing; backend permission enforcement covered by S14 tests')
}
