import assert from 'node:assert/strict'
import path from 'node:path'
import { call, navigate } from './contract_browser_support.mjs'
import { openViewerFiles, openViewerPlotAction } from './legacy_desk_test_support.mjs'

// Exercises the actual buttons and populated windows in a synthetic database.
export async function checkDialogLayouts(page, fixture, result, output) {
  const entries = (await call(page, '/api/v1/capabilities')).capabilities.flatMap(item => item.navigation_entries)
  const go = async (name, view, selector) => {
    const entry = entries.find(item => item.page === name && (!view || (view === 'capture' ? item.view !== 'curve' : item.view === view)))
    assert.ok(entry, `${name}/${view}`)
    await navigate(page, entry.group, entry.label, selector)
    return page.locator(selector)
  }
  const button = (scope, name) => scope.getByRole('button', { name, exact: true })
  const resize = async (width, height) => {
    if (process.env.QA_CDP) await page.evaluate(value => window.__TAURI__.core.invoke('plugin:window|set_size', { value: { Logical: value } }), { width, height })
    else await page.setViewportSize({ width, height })
  }
  const audit = async (dialog, name) => {
    await dialog.waitFor()
    for (const [width, height] of [[1440, 1000], [1060, 680], [2560, 1200]]) {
      await resize(width, height)
      for (const theme of ['light', 'dark']) {
        await page.evaluate(theme => { document.documentElement.dataset.theme = theme }, theme)
        const geometry = await dialog.evaluate(node => {
          const r = node.getBoundingClientRect(), box = node.matches('.analysis-preview-modal,.report-preview-modal') ? node.firstElementChild : node
          const visible = el => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0 }
          const controls = [...box.querySelectorAll('button,input,select,textarea')].filter(visible)
          const bad = controls.filter(el => {
            for (let parent = el.parentElement; parent && parent !== box; parent = parent.parentElement) {
              if (parent.scrollWidth > parent.clientWidth + 2 && ['auto', 'scroll'].includes(getComputedStyle(parent).overflowX)) return false
            }
            const b = el.getBoundingClientRect()
            return b.left < r.left - 1 || b.right > r.right + 1
          }).map(el => el.getAttribute('aria-label') || el.textContent.slice(0, 30))
          return { viewport: r.left >= 0 && r.top >= 0 && r.right <= innerWidth + 1 && r.bottom <= innerHeight + 1,
            horizontal: box.scrollWidth <= box.clientWidth + 2, bad, width: r.width, height: r.height }
        })
        assert.ok(geometry.viewport, `${name}: viewport ${JSON.stringify(geometry)}`)
        assert.ok(geometry.horizontal, `${name}: horizontal scroll ${JSON.stringify(geometry)}`)
        assert.deepEqual(geometry.bad, [], `${name}: clipped controls`)
        const lastControl = dialog.locator('button,input,select,textarea').last()
        if (await lastControl.isVisible()) {
          await lastControl.scrollIntoViewIfNeeded()
          const box = await lastControl.boundingBox()
          const viewport = await page.evaluate(() => ({ height: innerHeight, width: innerWidth }))
          assert.ok(box.y >= 0 && box.y + box.height <= viewport.height + 1, `${name}: last control unreachable`)
        }
        await dialog.evaluate(node => { node.scrollTop = 0; for (const child of node.querySelectorAll('.spectroscopy-task-fields')) child.scrollTop = 0 })
        result.layouts.push({ name, width, height, theme })
        if (width === 1060 && theme === 'dark') await page.screenshot({ path: path.join(output, `${name}-small-dark.png`) })
      }
    }
    await resize(1440, 1000)
    await page.evaluate(() => { document.documentElement.dataset.theme = 'light' })
    result.checks.push(name)
    console.log(`PASS dialog: ${name}`)
  }
  const dismiss = async dialog => {
    const close = dialog.locator('button').filter({ hasText: /^(×|取消|关闭|关闭大图)$/ }).first()
    await close.click(); await dialog.waitFor({ state: 'hidden' })
  }
  await call(page, '/api/v1/methods/current', { method_id: fixture.method_id })
  await go('methods', null, '[data-testid="methods-page"]')
  await page.locator('.quick-access-button[aria-label="打开方法"]').click()
  let dialog = page.getByRole('dialog', { name: '打开方法', exact: true })
  await audit(dialog, 'method-open'); await dismiss(dialog)

  // Reproduce the reported task, including a long CCD layout name and cancelled signal.
  let task = await call(page, '/api/v1/dispersion/tasks', { name: '弹窗定位回归', ccd_indices: [0], frame_count: 3, dark_frame_count: 1, pre_excitation_seconds: 0 })
  for (const point of [100, 200, 300, 400]) await call(page, `/api/v1/dispersion/tasks/${task.id}/line-points`, { ccd_index: 0, point_index: point })
  task = await call(page, `/api/v1/dispersion/tasks/${task.id}/start`, {})
  for (let n = 0; n < 20 && task.status !== 'completed'; n++) task = await call(page, `/api/v1/dispersion/tasks/${task.id}/step`, {})
  assert.equal(task.status, 'completed')
  await call(page, `/api/v1/dispersion/tasks/${task.id}/gaps/0?gap_um=9809`, {}, 'PATCH')
  let host = await go('dispersion', 'capture', '[data-testid="dispersion-page"]')
  await button(page, '新建任务').click()
  dialog = page.getByRole('dialog', { name: '建立色散摄谱任务' })
  await audit(dialog, 'dispersion-create'); await dismiss(dialog)
  await host.locator('tr').filter({ hasText: '弹窗定位回归' }).getByRole('button').click()
  await button(host, '任务详情').click()
  dialog = page.getByRole('dialog', { name: '任务条件与采后命名' })
  await audit(dialog, 'dispersion-details')
  assert.equal(await dialog.locator('.task-details-progress dd').allTextContents().then(values => values.join('|')), '100.0%|已完成|3/3 · 1/1')
  await page.screenshot({ path: path.join(output, 'review-details.png') })
  await dismiss(dialog)
  await button(host, '谱图读数').click()
  dialog = page.getByRole('dialog', { name: '谱图点位与视野' })
  await audit(dialog, 'dispersion-readout'); await dismiss(dialog)
  const before = (await call(page, `/api/v1/dispersion/tasks/${task.id}`)).lines
  for (let n = 0; n < 3; n++) {
    const response = page.waitForResponse(r => r.url().includes('/lines/locate-all'))
    await button(host, '校正谱线').click()
    const value = await (await response).json()
    assert.equal(value.located.length, 0); assert.equal(value.errors.length, 4)
    await page.getByText(/4 条失败；失败谱线位置未改变/).first().waitFor()
    assert.deepEqual((await call(page, `/api/v1/dispersion/tasks/${task.id}`)).lines, before)
  }
  result.checks.push('三次批量定位平坦扣暗谱：四条均失败、位置和保存值保持、界面明确报告失败')
  await button(host, '拟合曲线').click()
  dialog = page.getByRole('dialog', { name: '色散曲线', exact: true })
  await audit(dialog, 'capture-curve-fit'); await dismiss(dialog)
  await go('dispersion', 'curve', '[data-testid="dispersion-page"]')
  await button(page, '拟合曲线').click()
  dialog = page.getByRole('dialog', { name: '色散曲线' })
  await audit(dialog, 'dispersion-fit'); await dismiss(dialog)

  for (const [kind, mode] of [['sample', 'sample-acquisition'], ['evaporation', 'evaporation-acquisition']]) {
    let acquisition = await call(page, '/api/v1/acquisitions/tasks', { name: `弹窗-${kind}`, task_kind: kind, method_id: fixture.method_id,
      sample_name: 'QA', burn_frame_count: 3, dark_frame_count: 1, pre_excitation_seconds: 0, countdown_seconds: 0, sampling_period_seconds: .1 })
    acquisition = await call(page, `/api/v1/acquisitions/tasks/${acquisition.id}/start`, {})
    for (let n = 0; n < 60 && acquisition.status !== 'completed'; n++) acquisition = await call(page, `/api/v1/acquisitions/tasks/${acquisition.id}/step`, {})
    assert.equal(acquisition.status, 'completed')
    host = await go(mode, null, `[data-testid="${kind}-acquisition-page"]`)
    await button(page, '新建任务').click()
    dialog = page.locator('dialog.spectroscopy-task-dialog[open]')
    await audit(dialog, `${kind}-create`); await dismiss(dialog)
    await host.locator('tr').filter({ hasText: `弹窗-${kind}` }).getByRole('button').click()
    await button(host, '任务详情').click()
    dialog = page.getByRole('dialog', { name: '任务条件与采后命名' })
    await dialog.locator('summary').first().click()
    await audit(dialog, `${kind}-details`); await dismiss(dialog)
    await button(host, '谱图读数').click()
    dialog = page.getByRole('dialog', { name: '谱图点位与视野' })
    await audit(dialog, `${kind}-readout`); await dismiss(dialog)
    if (kind === 'sample') {
      await button(host, '录入样品编号').click()
      dialog = page.getByRole('dialog', { name: '预录样号' })
      await audit(dialog, 'sample-numbers'); await dismiss(dialog)
    }
  }

  host = await go('spectra', null, '[data-testid="spectrum-viewer-page"]')
  dialog = await openViewerFiles(host)
  await audit(dialog, 'viewer-files'); await dismiss(dialog)
  for (const [name, title] of [['参考校正设置', '参考校正'], ['打印谱图', '显示与打印']]) {
    await button(host, name).click()
    dialog = page.getByRole('dialog', { name: title, exact: true })
    await audit(dialog, `viewer-${title}`); await dismiss(dialog)
  }

  host = await go('evaporation-curves', null, '[data-testid="evaporation-spectrum-page"]')
  await openViewerPlotAction(host, '查看原始帧')
  dialog = page.getByRole('dialog', { name: '原始帧', exact: true })
  await audit(dialog, 'viewer-原始帧'); await dismiss(dialog)
  await openViewerPlotAction(host, '蒸发帧统计')
  dialog = page.getByRole('dialog', { name: '蒸发帧统计', exact: true })
  await audit(dialog, 'evaporation-statistics'); await dismiss(dialog)

  host = await go('analysis', null, '.analysis-page')
  const run = await call(page, `/api/v1/analyses/runs/${fixture.run_id}`)
  await host.locator('.analysis-run-list button').filter({ hasText: run.name }).click()
  for (const label of ['图像预览', '文本预览']) {
    await button(host, label).click()
    dialog = page.locator('.analysis-preview-modal')
    await audit(dialog, `analysis-${label}`); await dismiss(dialog)
  }
  await call(page, `/api/v1/analyses/runs/${fixture.run_id}/results/merge`, { reason: 'dialog QA' })
  await navigate(page, 'data', '打印与导出', '[data-testid="data-processing-page"]')
  const report = page.getByTestId('reports-page')
  await button(report, '预览报告').click()
  dialog = page.locator('.report-preview-modal')
  await dialog.locator('iframe').waitFor()
  await audit(dialog, 'report-preview'); await dismiss(dialog)
  await page.getByRole('tab', { name: '强度数据', exact: true }).click()
  const intensity = page.getByTestId('analysis-intensity-output')
  await intensity.getByLabel('分析批次', { exact: true }).selectOption(String(fixture.run_id))
  await button(intensity, '预览').click()
  dialog = page.locator('.report-preview-modal')
  await dialog.locator('iframe').waitFor()
  await audit(dialog, 'intensity-preview'); await dismiss(dialog)

  await go('help', null, '[data-testid="help-page"]')
  await page.locator('.help-topic-list button').first().waitFor()
  const images = page.getByRole('button', { name: /^放大查看：/ })
  if (!await images.count()) {
    const topics = page.locator('.help-topic-list button')
    for (let i = 0; i < await topics.count() && !await images.count(); i++) await topics.nth(i).click()
  }
  await images.first().click()
  dialog = page.locator('dialog.help-image-dialog')
  await audit(dialog, 'help-image'); await dismiss(dialog)
  result.reviewTaskId = task.id
}
