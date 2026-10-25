import assert from 'node:assert/strict'
import path from 'node:path'
import { readFile } from 'node:fs/promises'
import { call, navigate } from './contract_browser_support.mjs'
import { checkFullSpectroscopy } from './full_spectroscopy_workflow.mjs'
import { leaveLegacyCapture } from './legacy_desk_test_support.mjs'

export async function checkExactExcitation(page, result, output) {
  const seed = (await call(page, '/api/v1/methods')).find(method => method.status === 'active')
  await call(page, '/api/v1/methods/current', { method_id: seed.id })
  const copy = await call(page, '/api/v1/methods', { name: '原图布局对照方法', conditions: { frame_count: 35, exposure_mode: 'line_interval',
    angle_exposures: [{ angle_deg: 0, storage_mode: 'full_interval', start_frame: 1, end_frame: 35 }] } })
  const line = JSON.parse(await readFile(new URL('./fixtures/station17-line.json', import.meta.url), 'utf8'))
  await call(page, `/api/v1/methods/${copy.id}/lines`, { ...line, exposure_start_frame: 1, exposure_end_frame: 35 })
  const saved = await call(page, `/api/v1/methods/${copy.id}/publish`, {})
  const task = await call(page, '/api/v1/acquisitions/tasks', { name: 'AgBSn最大值-35S单线_20261025_1238.cmt',
    task_kind: 'sample', method_id: copy.id, method_version: saved.current_version, sample_name: '',
    burn_frame_count: 35, dark_frame_count: 1, pre_excitation_seconds: 0, repeat_count: 1, storage_mode: 'full_interval' })
  assert.equal(task.storage_mode, 'full_interval')
  await call(page, '/api/v1/methods/current', { method_id: copy.id })
  await page.reload(); await page.getByTestId('workspace').waitFor()
  await navigate(page, 'analysis-tests', '样品摄谱', '[data-testid="sample-acquisition-page"]')
  const host = page.getByTestId('sample-acquisition-page')
  await host.locator(`[data-task-id="${task.id}"]`).getByRole('button').click()
  const desk = host.getByTestId('spectroscopy-console')
  for (const layout of [{ width: 1125, height: 639, name: 'reference' }, { width: 1440, height: 1000, name: 'wide' }, { width: 1060, height: 680, name: 'minimum' }]) {
    if (process.env.QA_CDP) await page.evaluate(value => window.__TAURI__.core.invoke('plugin:window|set_size', { value: { Logical: value } }), { width: layout.width, height: layout.height })
    else await page.setViewportSize({ width: layout.width, height: layout.height })
    await page.waitForTimeout(250)
    const geometry = await desk.evaluate(element => {
      const box = selector => { const r = element.querySelector(selector).getBoundingClientRect(); return { x: r.x, y: r.y, width: r.width, height: r.height, right: r.right, bottom: r.bottom } }
      return { desk: { x: element.getBoundingClientRect().x, y: element.getBoundingClientRect().y, width: element.clientWidth, height: element.clientHeight },
        title: box('.legacy-window-caption'), mainToolbar: box('.legacy-main-toolbar'), left: box('.legacy-record-dock'),
        middle: box('.spectroscopy-view'), right: box('.spectroscopy-operator'), toolbar: box('.inspector-tools'),
        plot: box('.inspector-empty'), banner: box('.legacy-empty-banner'), sample: box('.spectroscopy-sample-input'),
        commands: box('.spectroscopy-command-area'),
        sampleLabels: [...element.querySelectorAll('.spectroscopy-sample-input label > span')].map(label => { const r = label.getBoundingClientRect(); return { x: r.x, y: r.y, height: r.height } }),
        buttons: [...element.querySelectorAll('.spectroscopy-controls button')].map(button => { const r = button.getBoundingClientRect(); return { x: r.x, y: r.y, width: r.width, height: r.height } }),
        emptyColor: getComputedStyle(element.querySelector('.inspector-empty')).backgroundColor,
        bannerColor: getComputedStyle(element.querySelector('.legacy-empty-banner')).backgroundColor,
        controlsStyle: [...element.querySelectorAll('.spectroscopy-line-bar input,.spectroscopy-line-bar select,.spectroscopy-sample-input input,.spectroscopy-sample-input select')].map(control => ({
          name: control.getAttribute('aria-label'), radius: getComputedStyle(control).borderRadius,
          arrow: control.tagName !== 'SELECT' || getComputedStyle(control).backgroundImage !== 'none'
        })),
        pageOverflow: document.documentElement.scrollWidth > innerWidth + 1,
        toolNames: [...element.querySelectorAll('.inspector-tools button')].map(button => button.getAttribute('aria-label')) }
    })
    result.layoutAttempt = { ...layout, geometry }
    assert.equal(geometry.desk.x, 0); assert.equal(geometry.desk.y, 0)
    assert.equal(geometry.desk.width, layout.width); assert.equal(geometry.desk.height, layout.height)
    assert.equal(geometry.title.height, 25); assert.equal(geometry.mainToolbar.y, 25); assert.equal(geometry.mainToolbar.height, 25)
    assert.equal(geometry.left.y, 50); assert.equal(geometry.left.width, 216); assert.equal(geometry.right.width, 217)
    assert.equal(geometry.right.right, layout.width); assert.equal(geometry.plot.y, 89)
    assert.equal(geometry.plot.bottom, layout.height - 12)
    assert.equal(geometry.plot.x - geometry.middle.x, 34)
    assert.equal(geometry.banner.y - geometry.plot.y, 10)
    assert.equal(geometry.emptyColor, 'rgb(166, 202, 240)'); assert.equal(geometry.bannerColor, 'rgb(0, 255, 255)')
    assert.equal(geometry.pageOverflow, false)
    assert.equal(geometry.sampleLabels[0].y, 128); assert.equal(geometry.sampleLabels[0].height, 13)
    assert.equal(geometry.sampleLabels[0].x - geometry.right.x, 15.5)
    assert.equal(geometry.sampleLabels[1].x - geometry.right.x, 119.5)
    assert.ok(geometry.controlsStyle.every(control => control.radius === '0px' && control.arrow))
    const expected = ['上一谱带', '下一谱带', '上一 CCD', '下一 CCD', '十字线', '区域放大', '滚动工具', '适合图像', '一线一点', '一线四点', '十倍 CCD', '横向放大', '横向缩小', '纵向放大', '纵向缩小', '纵向还原', '打印谱图']
    assert.deepEqual(geometry.toolNames, expected)
    const increment = geometry.commands.height / 4
    for (let index = 0; index < 4; index++) {
      const button = geometry.buttons[index]
      assert.ok(Math.abs(button.y - (geometry.commands.y + (increment - button.height) / 2 + index * increment)) < 2)
    }
    assert.equal(await host.getByText('[无谱带可显示]', { exact: true }).isVisible(), true)
    assert.equal(await host.getByRole('textbox', { name: '曝光区间', exact: true }).inputValue(), '1-35')
    assert.equal(await host.getByRole('textbox', { name: '重复摄谱', exact: true }).inputValue(), '1')
    assert.equal(await host.getByRole('button', { name: '停止摄谱', exact: true }).isDisabled(), true)
    assert.equal(await desk.locator('.legacy-empty-record').count(), 1)
    await page.screenshot({ path: path.join(output, `exact-${layout.name}.png`) })
    result.layouts.push({ ...layout, geometry })
  }
  result.checks.push('原图同尺寸：25像素标题／工具栏、固定216/217侧栏、蓝色图框留白、青色提示条、行头与四按钮位置逐项核对')
  let writes = 0
  const count = request => { if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(request.method())) writes++ }
  page.on('request', count)
  await desk.getByRole('button', { name: '隐藏样品面板', exact: true }).click()
  assert.equal(await desk.locator('.legacy-record-dock').isVisible(), false)
  await desk.getByRole('button', { name: '隐藏摄谱窗口', exact: true }).click()
  assert.equal(await desk.locator('.spectroscopy-operator').isVisible(), false)
  await desk.locator('.legacy-window-caption').click({ button: 'right' })
  await page.getByRole('menuitem', { name: '恢复样品表与摄谱窗口' }).click()
  await desk.locator('.legacy-window-caption').click({ button: 'right' })
  await page.getByRole('menuitem', { name: '任务条件与采后命名', exact: true }).click()
  const details = desk.getByRole('dialog', { name: '任务条件与采后命名' })
  await details.waitFor()
  assert.equal(await details.getByTestId('acquisition-measurements').isVisible(), true)
  await details.getByRole('button', { name: '关闭任务详情' }).click()
  page.off('request', count); assert.equal(writes, 0)
  result.checks.push('关闭／恢复停靠面板零写入；条件、测量、消息及采后命名在详情窗口保留')
  const queue = await call(page, '/api/v1/sample-queues', { name: '原图样号表', name_length: 12, items: [{ pre_name: 'EXACT-A', repeats: 2 }] })
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
