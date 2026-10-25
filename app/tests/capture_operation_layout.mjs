import assert from 'node:assert/strict'
import path from 'node:path'
import { readFile } from 'node:fs/promises'
import { call, navigate } from './contract_browser_support.mjs'
import { checkFullSpectroscopy } from './full_spectroscopy_workflow.mjs'
import { leaveLegacyCapture } from './legacy_desk_test_support.mjs'

export async function checkCaptureOperations(page, result, output) {
  const seed = (await call(page, '/api/v1/methods')).find(method => method.status === 'active')
  await call(page, '/api/v1/methods/current', { method_id: seed.id })
  const copy = await call(page, '/api/v1/methods', { name: '操作布局对照方法', conditions: { frame_count: 35, exposure_mode: 'line_interval',
    angle_exposures: [{ angle_deg: 0, storage_mode: 'full_interval', start_frame: 1, end_frame: 35 }] } })
  const line = JSON.parse(await readFile(new URL('./fixtures/station17-line.json', import.meta.url), 'utf8'))
  await call(page, `/api/v1/methods/${copy.id}/lines`, { ...line, exposure_start_frame: 1, exposure_end_frame: 35 })
  const saved = await call(page, `/api/v1/methods/${copy.id}/publish`, {})
  const task = await call(page, '/api/v1/acquisitions/tasks', { name: '操作布局对照样品',
    task_kind: 'sample', method_id: copy.id, method_version: saved.current_version, sample_name: '',
    burn_frame_count: 35, dark_frame_count: 1, pre_excitation_seconds: 0, repeat_count: 1, storage_mode: 'full_interval' })
  assert.equal(task.storage_mode, 'full_interval')
  await call(page, '/api/v1/methods/current', { method_id: copy.id })
  await page.reload(); await page.getByTestId('workspace').waitFor()
  await navigate(page, 'analysis-tests', '样品摄谱', '[data-testid="sample-acquisition-page"]')
  const host = page.getByTestId('sample-acquisition-page')
  await host.locator(`[data-task-id="${task.id}"]`).getByRole('button').click()
  const desk = host.getByTestId('spectroscopy-console')
  for (const layout of [{ width: 1440, height: 1000, theme: 'light', name: 'wide' }, { width: 1060, height: 680, theme: 'dark', name: 'minimum' }, { width: 1125, height: 760, theme: 'light', name: 'medium' }]) {
    const settings = await call(page, '/api/v1/settings')
    await call(page, '/api/v1/settings', { display: { ...settings.display, theme: layout.theme } }, 'PATCH')
    await page.reload(); await page.getByTestId('workspace').waitFor()
    if (process.env.QA_CDP) await page.evaluate(value => window.__TAURI__.core.invoke('plugin:window|set_size', { value: { Logical: value } }), { width: layout.width, height: layout.height })
    else await page.setViewportSize({ width: layout.width, height: layout.height })
    await navigate(page, 'analysis-tests', '样品摄谱', '[data-testid="sample-acquisition-page"]')
    await host.locator(`[data-task-id="${task.id}"]`).getByRole('button').click()
    const geometry = await desk.evaluate(element => {
      const rect = node => { const r = node.getBoundingClientRect(); return { x: r.x, y: r.y, width: r.width, height: r.height, right: r.right, bottom: r.bottom } }
      const box = selector => rect(element.querySelector(selector))
      return { desk: rect(element), sidebar: rect(document.querySelector('.sidebar')), topbar: rect(document.querySelector('.topbar')),
        position: getComputedStyle(element).position, theme: document.querySelector('[data-testid="app-shell"]').dataset.theme,
        themeSurface: getComputedStyle(element).getPropertyValue('--ui-soft').trim(),
        emptyColor: getComputedStyle(element.querySelector('.inspector-empty')).backgroundColor,
        fieldLabelColor: getComputedStyle(element.querySelector('.spectroscopy-sample-input label > span')).backgroundColor,
        left: box('.legacy-record-dock'), middle: box('.spectroscopy-view'), right: box('.spectroscopy-operator'), plot: box('.inspector-empty'),
        buttons: [...element.querySelectorAll('.spectroscopy-controls button')].map(rect),
        icons: [...element.querySelectorAll('.spectroscopy-action-icon')].map(icon => icon.getBoundingClientRect().width),
        pageOverflow: document.documentElement.scrollWidth > innerWidth + 1,
        toolNames: [...element.querySelectorAll('.inspector-tools button')].map(button => button.getAttribute('aria-label')) }
    })
    result.layoutAttempt = { ...layout, geometry }
    assert.equal(await page.locator('.sidebar').isVisible(), true)
    assert.equal(await page.locator('.topbar').isVisible(), true)
    assert.equal(geometry.position, 'relative'); assert.equal(geometry.theme, layout.theme)
    assert.ok(geometry.desk.x >= geometry.sidebar.right && geometry.desk.y >= geometry.topbar.bottom)
    assert.ok(geometry.left.x < geometry.middle.x && geometry.middle.x < geometry.right.x)
    assert.ok(geometry.right.right <= layout.width && geometry.plot.width > 200 && geometry.plot.height > 180)
    assert.equal(geometry.pageOverflow, false)
    assert.equal(geometry.fieldLabelColor, 'rgba(0, 0, 0, 0)')
    const expectedColor = await desk.evaluate(element => {
      const probe = document.createElement('span'); probe.style.backgroundColor = 'var(--ui-soft)'; element.append(probe)
      const value = getComputedStyle(probe).backgroundColor; probe.remove(); return value
    })
    assert.equal(geometry.emptyColor, expectedColor)
    assert.ok(geometry.icons.every(width => width === 16))
    assert.deepEqual(geometry.toolNames, ['上一谱带', '下一谱带', '上一 CCD', '下一 CCD', '十字线', '区域放大', '滚动工具', '适合图像', '一线一点', '一线四点', '十倍 CCD', '横向放大', '横向缩小', '纵向放大', '纵向缩小', '纵向还原', '打印谱图'])
    for (let index = 0; index < 4; index++) {
      const button = geometry.buttons[index]
      assert.ok(button.x >= geometry.right.x && button.right <= geometry.right.right)
      if (index) assert.ok(button.y >= geometry.buttons[index - 1].bottom + 2)
    }
    assert.equal(await host.getByRole('textbox', { name: '曝光区间', exact: true }).inputValue(), '1-35')
    assert.equal(await host.getByRole('textbox', { name: '重复摄谱', exact: true }).inputValue(), '1')
    assert.equal(await host.getByRole('button', { name: '停止摄谱', exact: true }).isDisabled(), true)
    assert.equal(await page.getByRole('button', { name: '返回任务列表', exact: true }).isVisible(), true)
    assert.equal(await desk.getByRole('button', { name: '任务详情', exact: true }).isVisible(), true)
    assert.equal(await desk.getByRole('button', { name: '谱图读数', exact: true }).isVisible(), true)
    await page.screenshot({ path: path.join(output, `operations-${layout.name}.png`) })
    result.layouts.push({ ...layout, geometry })
  }
  result.checks.push('仅操作区沿用旧版三栏和工具顺序；主导航、页头、返回入口及明暗主题保持，三尺寸无横向溢出')
  let writes = 0
  const count = request => { if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(request.method())) writes++ }
  page.on('request', count)
  await desk.getByRole('button', { name: '隐藏样品面板', exact: true }).click()
  assert.equal(await desk.locator('.legacy-record-dock').isVisible(), false)
  await desk.getByRole('button', { name: '隐藏摄谱窗口', exact: true }).click()
  assert.equal(await desk.locator('.spectroscopy-operator').isVisible(), false)
  await desk.getByRole('button', { name: '恢复面板', exact: true }).click()
  await desk.getByRole('button', { name: '任务详情', exact: true }).click()
  const details = desk.getByRole('dialog', { name: '任务条件与采后命名' })
  await details.waitFor()
  assert.equal(await details.getByTestId('acquisition-measurements').isVisible(), true)
  await details.getByRole('button', { name: '关闭任务详情' }).click()
  page.off('request', count); assert.equal(writes, 0)
  result.checks.push('关闭／恢复停靠面板零写入；条件、测量、消息及采后命名在详情窗口保留')
  const queue = await call(page, '/api/v1/sample-queues', { name: '操作布局样号表', name_length: 12, items: [{ pre_name: 'EXACT-A', repeats: 2 }] })
  await desk.getByRole('button', { name: '录入样品编号', exact: true }).click()
  const editor = page.getByRole('dialog', { name: '预录样号', exact: true })
  await editor.getByLabel('选择样品队列').selectOption(String(queue.id))
  if (!process.env.QA_CDP) {
    let release, began
    const hold = new Promise(resolve => { release = resolve }), request = new Promise(resolve => { began = resolve })
    const pattern = '**/api/v1/sample-queues/**'
    await page.route(pattern, async route => {
      if (route.request().method() === 'GET') return route.continue()
      began(); await hold
      await route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'QA样号保存失败' }) })
    })
    await editor.getByLabel('样品名', { exact: true }).fill('EXACT-B')
    await editor.getByRole('button', { name: '插入样品', exact: true }).click()
    await request
    const failed = page.waitForResponse(response => response.status() === 503 && response.url().includes('/sample-queues/'))
    try {
      assert.equal(await editor.getByRole('button', { name: '关闭', exact: true }).isDisabled(), true)
      await page.keyboard.press('Escape'); assert.equal(await editor.isVisible(), true)
    } finally { release() }
    await failed
    await page.unroute(pattern)
    await page.waitForFunction(() => ![...document.querySelectorAll('dialog[open] button')].find(button => button.textContent === '关闭')?.disabled)
    assert.equal(await editor.getByLabel('样品名', { exact: true }).inputValue(), 'EXACT-B')
    result.checks.push('预录窗口保存期间禁止关闭及离开，失败保留输入后恢复操作')
  }
  await editor.getByRole('button', { name: '使用此样号表', exact: true }).click()
  const sample = desk.getByRole('combobox', { name: '样品编号', exact: true })
  assert.equal(await sample.inputValue(), '')
  const created = page.waitForResponse(response => response.url().endsWith('/acquisitions/tasks') && response.request().method() === 'POST')
  await sample.selectOption(`queue:${queue.items[0].id}`)
  const response = await created; assert.equal(response.status(), 201, await response.text())
  const next = await response.json()
  for (const key of ['method_id', 'method_version', 'device_profile_id', 'ccd_layout_id', 'burn_frame_count', 'dark_frame_count', 'sampling_period_seconds']) assert.equal(next[key], task[key], key)
  assert.equal(next.repeat_count, 2); assert.equal(next.status, 'draft'); assert.equal(next.samples.length, 0)
  await desk.getByRole('button', { name: '清除待测样号', exact: true }).click()
  assert.equal(await sample.inputValue(), '')
  assert.equal(await desk.getByRole('button', { name: '试样摄谱', exact: true }).isDisabled(), true)
  await sample.selectOption(`task:${next.id}`)
  assert.equal(await desk.getByRole('textbox', { name: '重复摄谱', exact: true }).inputValue(), '2')
  result.checks.push('预录窗口回传样号表、直接选择建立草稿并带出重复；清除选择不删除数据，不自动激发')
  await leaveLegacyCapture(page)
  await call(page, `/api/v1/methods/${copy.id}/pause`, {})
  await call(page, '/api/v1/methods/current', { method_id: seed.id })
  assert.equal(await page.evaluate(() => !!sessionStorage.getItem('geospectrum.token')), true)
  await page.reload(); await page.getByTestId('workspace').waitFor()
  assert.equal(await page.evaluate(() => !!sessionStorage.getItem('geospectrum.token')), true)
  await checkFullSpectroscopy(page, result, output)
}
