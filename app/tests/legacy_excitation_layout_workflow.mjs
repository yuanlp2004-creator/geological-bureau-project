import assert from 'node:assert/strict'
import path from 'node:path'
import { checkFullSpectroscopy } from './full_spectroscopy_workflow.mjs'
import { call, navigate } from './contract_browser_support.mjs'

export async function checkExcitationControls(desk, commands) {
  const geometry = await desk.evaluate(element => {
    const rectFor = node => { const r = node.getBoundingClientRect(); return { x: r.x, y: r.y, width: r.width, height: r.height, right: r.right, bottom: r.bottom } }
    const rect = selector => rectFor(element.querySelector(selector))
    const select = element.querySelector('select[aria-label="选择CCD"]')
    const picker = select.closest('.classic-ccd-picker')
    const hit = select.getBoundingClientRect()
    const icon = picker.querySelector('img')?.getBoundingClientRect()
    const controlArea = element.querySelector('.spectroscopy-command-area')
    return { left: rect('.legacy-record-dock'), middle: rect('.spectroscopy-view'), right: rect('.spectroscopy-operator'),
      sample: rect('.spectroscopy-sample-input'), commands: rect('.spectroscopy-command-area'), lineBar: rect('.spectroscopy-line-bar'),
      compact: matchMedia('(max-height: 760px)').matches,
      messageTop: document.querySelector('.runtime-message-panel')?.getBoundingClientRect().top ?? innerHeight,
      buttons: [...element.querySelectorAll('.spectroscopy-controls button')].map(button => ({
        ...rectFor(button), command: button.dataset.command,
        icon: button.querySelector('svg.capture-command-icon')?.getBoundingClientRect().width
      })),
      icons: [...element.querySelectorAll('.spectroscopy-action-icon')].map(image => ({ width: image.getBoundingClientRect().width, height: image.getBoundingClientRect().height })),
      tool: rect('.inspector-icon-button'), spectrumTool: rect('.inspector-tools .inspector-icon-button'),
      commandsOverflow: controlArea.scrollHeight > controlArea.clientHeight + 1,
      toolsOverflow: element.querySelector('.inspector-tools').scrollWidth > element.querySelector('.inspector-tools').clientWidth + 1,
      ccd: { name: select.getAttribute('aria-label'), option: select.selectedOptions[0]?.textContent,
        hitWidth: hit.width, hitHeight: hit.height, iconWidth: icon?.width }, viewport: innerWidth, overflow: document.documentElement.scrollWidth > innerWidth + 1 }
  })
  assert.ok(geometry.left.x < geometry.middle.x && geometry.middle.x < geometry.right.x)
  assert.ok(geometry.lineBar.bottom <= geometry.left.y + 1)
  assert.ok(geometry.sample.bottom < geometry.commands.y + 1)
  assert.deepEqual(geometry.buttons.map(button => button.command), commands)
  if (!geometry.compact) {
    for (const column of [geometry.left, geometry.middle, geometry.right]) {
      assert.ok(Math.abs(column.bottom - geometry.commands.bottom) <= 1)
    }
    const steps = geometry.buttons.slice(1).map((button, index) => button.y - geometry.buttons[index].y)
    assert.ok(Math.max(...steps) - Math.min(...steps) <= 1, 'Excitation commands should be evenly spaced')
  }
  assert.ok(geometry.buttons.every((button, i, all) =>
    Math.abs(button.width - all[0].width) < 1 && Math.abs(button.x - all[0].x) < 1
    && button.y >= geometry.commands.y && button.bottom <= Math.min(geometry.commands.bottom, geometry.messageTop) + 1 && button.icon === 16
    && (!i || button.y >= all[i - 1].bottom + 2)))
  assert.ok(geometry.icons.every(icon => icon.width === 16 && icon.height === 16))
  assert.equal(geometry.tool.width, 24); assert.equal(geometry.tool.height, 24)
  assert.equal(geometry.spectrumTool.width, geometry.middle.width <= 420 ? 20 : 24)
  assert.equal(geometry.commandsOverflow, false); assert.equal(geometry.toolsOverflow, false)
  assert.equal(geometry.ccd.name, '选择CCD')
  assert.ok(geometry.ccd.option && geometry.ccd.hitWidth >= 36 && geometry.ccd.hitHeight >= 24 && geometry.ccd.iconWidth === 16)
  assert.equal(geometry.overflow, false)
  assert.deepEqual(await desk.locator('.capture-record-table th').allTextContents(), ['', '记录号', '样品编号', '样品序号'])
  return geometry
}

// Reuse spectrum/permissions/printing coverage, then exercise the permanent sample selector.
export async function checkLegacyExcitationLayout(page, result, output) {
  const adminToken = await page.evaluate(() => sessionStorage.getItem('geospectrum.token'))
  await checkFullSpectroscopy(page, result, output)
  await page.evaluate(token => sessionStorage.setItem('geospectrum.token', token), adminToken)
  await page.reload(); await page.getByTestId('workspace').waitFor()
  const method = (await call(page, '/api/v1/methods')).find(item => item.status === 'active')
  const queue = await call(page, '/api/v1/sample-queues', { name: '旧版布局样号表', name_length: 12,
    items: [{ pre_name: 'LEGACY-A', repeats: 1 }, { pre_name: 'LEGACY-B', repeats: 3 }] })
  const first = await call(page, '/api/v1/acquisitions/tasks', { name: '旧版布局样号切换', task_kind: 'sample',
    method_id: method.id, queue_id: queue.id, queue_item_id: queue.items[0].id,
    burn_frame_count: 2, dark_frame_count: 1, countdown_seconds: 0, pre_excitation_seconds: 0,
    sampling_period_seconds: .25, burn_cycle_seconds: .25, dark_cycle_seconds: .25 })
  await navigate(page, 'analysis-tests', '样品摄谱', '[data-testid="sample-acquisition-page"]')
  const host = page.getByTestId('sample-acquisition-page')
  await host.locator(`[data-task-id="${first.id}"]`).getByRole('button', { name: '进入摄谱', exact: true }).click()
  const sample = host.getByRole('combobox', { name: '样品编号', exact: true })
  const repeats = host.getByRole('textbox', { name: '重复摄谱', exact: true })
  assert.equal(await sample.inputValue(), `task:${first.id}`)
  assert.equal(await repeats.inputValue(), '1')
  assert.equal(await repeats.getAttribute('readonly'), '')
  const versions = await call(page, `/api/v1/methods/${method.id}/versions`)
  const snapshot = versions.find(version => version.version === first.method_version)
  assert.ok(snapshot?.lines.length)
  const lineSelect = host.getByRole('combobox', { name: '选择谱线', exact: true })
  await page.waitForFunction(count => document.querySelector('select[aria-label="选择谱线"]')?.options.length === count, snapshot.lines.length + 1)
  const line = snapshot.lines[0]
  await lineSelect.selectOption(line.id)
  assert.equal(await host.getByRole('textbox', { name: '定位谱线', exact: true }).inputValue(), String(line.actual_wavelength_nm ?? line.wavelength_nm))
  assert.equal(await host.getByRole('textbox', { name: '曝光区间', exact: true }).inputValue(), `${line.exposure_start_frame ?? 1}-${line.exposure_end_frame ?? first.burn_frame_count}`)
  result.checks.push('顶部谱线栏读取任务绑定的确切已发布版本，波长及曝光区间只读展示')
  if (!process.env.QA_CDP) {
    const failed = '**/api/v1/acquisitions/tasks'
    await page.route(failed, route => route.request().method() === 'POST'
      ? route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'QA切换失败' }) })
      : route.continue())
    const failure = page.waitForResponse(response => response.url().endsWith('/acquisitions/tasks') && response.status() === 503)
    await sample.selectOption(`queue:${queue.items[1].id}`)
    await failure
    await page.waitForTimeout(150)
    assert.equal(await sample.inputValue(), `task:${first.id}`)
    assert.equal(await repeats.inputValue(), '1')
    await page.unroute(failed)
    result.checks.push('样号切换失败保留原任务和重复次数，可重试')
  }
  const creation = page.waitForResponse(response => response.url().endsWith('/acquisitions/tasks') && response.request().method() === 'POST')
  await sample.selectOption(`queue:${queue.items[1].id}`)
  const response = await creation; assert.equal(response.status(), 201, await response.text())
  const next = await response.json()
  await page.waitForFunction(id => document.querySelector('select[aria-label="样品编号"]')?.value === `task:${id}`, next.id)
  assert.equal(await repeats.inputValue(), '3')
  for (const key of ['method_id', 'method_version', 'device_profile_id', 'ccd_layout_id', 'burn_frame_count', 'dark_frame_count',
    'countdown_seconds', 'pre_excitation_seconds', 'sampling_period_seconds', 'burn_cycle_seconds', 'dark_cycle_seconds'])
    assert.equal(next[key], first[key], key)
  assert.deepEqual(next.ccd_indices, first.ccd_indices)
  assert.equal(next.status, 'draft'); assert.equal(next.samples.length, 0)
  assert.equal(await host.getByRole('dialog').isVisible(), false)
  await sample.selectOption(`task:${first.id}`); assert.equal(await repeats.inputValue(), '1')
  await sample.selectOption(`task:${next.id}`); assert.equal(await repeats.inputValue(), '3')
  assert.equal((await call(page, '/api/v1/acquisitions/tasks')).filter(task => task.queue_item_id === next.queue_item_id && task.sample_kind !== 'preheat').length, 1)
  result.checks.push('常驻样号下拉直接切换预录样品、自动带出次数、继承当前条件、不重复建任务、不自动激发')
  for (const layout of [{ width: 1440, height: 1000, theme: 'light' }, { width: 1060, height: 680, theme: 'dark' }]) {
    await page.evaluate(theme => { document.documentElement.dataset.theme = theme }, layout.theme)
    if (process.env.QA_CDP) await page.evaluate(value => window.__TAURI__.core.invoke('plugin:window|set_size', { value: { Logical: value } }), { width: layout.width, height: layout.height })
    else await page.setViewportSize({ width: layout.width, height: layout.height })
    const geometry = await checkExcitationControls(host.getByTestId('spectroscopy-console'), ['start', 'preheat', 'stop', 'finish'])
    await page.waitForTimeout(3200)
    await host.getByTestId('spectroscopy-console').screenshot({ path: path.join(output, `legacy-input-${layout.theme}.png`) })
    await page.screenshot({ path: path.join(output, `workspace-${layout.theme}.png`) })
    result.layouts.push({ ...layout, mode: 'sample-input', geometry })
  }
  const start = page.waitForResponse(response => response.url().endsWith(`/acquisitions/tasks/${next.id}/start`))
  await host.getByRole('button', { name: '试样摄谱', exact: true }).click(); assert.equal((await start).status(), 200)
  assert.equal(await sample.isDisabled(), true)
  let captured
  for (let i = 0; i < 100; i++) {
    captured = await call(page, `/api/v1/acquisitions/tasks/${next.id}`)
    if (captured.status === 'between_repeats') break
    await page.waitForTimeout(100)
  }
  assert.equal(captured.status, 'between_repeats'); assert.equal(captured.completed_repeats, 1)
  assert.equal(await repeats.inputValue(), '3')
  await page.waitForTimeout(600)
  assert.equal((await call(page, `/api/v1/acquisitions/tasks/${next.id}`)).completed_repeats, 1)
  result.checks.push('激发中禁止切换样号；一次点击只完成一次重复，剩余重复等待人工点击')
}
