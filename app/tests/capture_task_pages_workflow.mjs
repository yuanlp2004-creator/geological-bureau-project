import assert from 'node:assert/strict'
import path from 'node:path'
import { call, navigate } from './contract_browser_support.mjs'

export async function checkCaptureTaskPages(page, result, output) {
  const bench = page.getByTestId('spectroscopy-workbench')
  const tabs = bench.getByRole('navigation', { name: '摄谱方式' })
  const modes = [['sample-acquisition', '样品摄谱'], ['evaporation-acquisition', '蒸发摄谱'], ['dispersion', '色散摄谱']]
  const methods = await call(page, '/api/v1/methods')
  await call(page, '/api/v1/methods/current', { method_id: methods.find(item => item.status === 'active').id })
  await page.reload(); await page.getByTestId('workspace').waitFor()
  const hostFor = mode => page.getByTestId(`${mode}-page`)
  const dialogFor = host => host.getByRole('dialog')
  const input = (scope, label) => scope.locator('label.field').filter({ has: page.getByText(label, { exact: true }).and(page.locator('span')) }).locator('input,select').first()
  const fill = async (scope, label, value) => { await input(scope, label).fill(String(value)); await input(scope, label).blur() }
  const back = async () => {
    const button = bench.getByRole('button', { name: '返回任务列表', exact: true })
    if (await button.isVisible()) { await button.click(); await tabs.waitFor() }
  }
  const go = async mode => {
    await navigate(page, 'analysis-tests', modes.find(item => item[0] === mode)[1], `[data-testid="${mode}-page"]`)
    await back()
    assert.equal(await tabs.getByRole('button').count(), 3)
    assert.equal(await bench.getByRole('button', { name: '新建任务', exact: true }).count(), 1)
    return hostFor(mode)
  }
  const open = async host => {
    await bench.getByRole('button', { name: '新建任务', exact: true }).click()
    const dialog = dialogFor(host); await dialog.waitFor(); return dialog
  }
  const assertCapture = async host => {
    await page.waitForFunction(() => document.querySelector('[data-testid="spectroscopy-workbench"]')?.dataset.stage === 'capture')
    assert.equal(await tabs.isVisible(), false)
    assert.equal(await host.locator('.spectroscopy-task-list').isVisible(), false)
    assert.equal(await host.locator('.spectroscopy-task-dialog').isVisible(), false)
    assert.equal(await host.locator('.spectroscopy-setup .acquisition-form, .spectroscopy-setup .dispersion-setup').count(), 0)
    assert.equal(await host.getByLabel('当前任务条件', { exact: true }).isVisible(), true)
    assert.equal(await host.getByRole('button', { name: '试样摄谱', exact: true }).isVisible(), true)
  }
  const create = async (dialog, domain) => {
    const response = page.waitForResponse(r => new URL(r.url()).pathname === `/api/v1/${domain}/tasks` && r.request().method() === 'POST')
    await dialog.getByRole('button', { name: domain === 'dispersion' ? '新建任务' : '创建任务', exact: true }).click()
    const received = await response; assert.equal(received.status(), 201, await received.text()); return received.json()
  }
  const finish = async (host, task, domain) => {
    const response = page.waitForResponse(r => new URL(r.url()).pathname === `/api/v1/${domain}/tasks/${task.id}/start` && r.request().method() === 'POST')
    await host.getByRole('button', { name: '试样摄谱', exact: true }).click()
    assert.equal((await response).status(), 200)
    assert.equal(await bench.getByRole('button', { name: '返回任务列表', exact: true }).isDisabled(), true)
    let current
    for (let i = 0; i < 100; i++) {
      current = await call(page, `/api/v1/${domain}/tasks/${task.id}`)
      if (current.status === 'completed') break
      assert.ok(!['failed', 'stopped'].includes(current.status), current.failure_message)
      await page.waitForTimeout(100)
    }
    assert.equal(current.status, 'completed')
    await host.locator('.state-chip.completed').waitFor()
  }

  let host = await go('sample-acquisition')
  let dialog = await open(host)
  await fill(dialog, '任务名称', '任务页样品验证')
  await fill(dialog, '临时样号', 'TASK01')
  await dialog.locator('details.advanced-settings').evaluateAll(nodes => nodes.forEach(node => { node.open = true }))
  await input(dialog, '激发参数与默认次数').selectOption('custom')
  await fill(dialog, '采样次数', 0)
  let creations = 0
  const count = request => { if (request.method() === 'POST' && new URL(request.url()).pathname === '/api/v1/acquisitions/tasks') creations++ }
  page.on('request', count)
  await dialog.getByRole('button', { name: '创建任务', exact: true }).click()
  await page.waitForTimeout(100); assert.equal(creations, 0)
  await dialog.getByRole('button', { name: '取消', exact: true }).click()
  dialog = await open(host)
  assert.equal(await input(dialog, '任务名称').inputValue(), '任务页样品验证')
  assert.equal(await input(dialog, '采样次数').inputValue(), '0')
  await fill(dialog, '采样次数', 2); await fill(dialog, '空白次数', 0)
  await fill(dialog, '预激时间（秒）', 0); await fill(dialog, '采样周期 (秒)', .01)
  await fill(dialog, '重复次数', 1); await fill(dialog, '倒计时（秒）', 0)
  await page.route('**/api/v1/acquisitions/tasks', route => route.request().method() === 'POST'
    ? route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: { code: 'QA_RETRY', message: '模拟新建失败' } }) }) : route.continue())
  await dialog.getByRole('button', { name: '创建任务', exact: true }).click()
  await dialog.getByRole('alert').waitFor()
  assert.equal(await input(dialog, '任务名称').inputValue(), '任务页样品验证')
  await page.unroute('**/api/v1/acquisitions/tasks')
  const sample = await create(dialog, 'acquisitions')
  page.off('request', count)
  await assertCapture(host)
  assert.equal((await call(page, `/api/v1/acquisitions/tasks/${sample.id}`)).status, 'draft')
  assert.ok((await host.getByLabel('当前任务条件').textContent()).includes('2 / 0'))
  await finish(host, sample, 'acquisitions')
  await bench.getByRole('button', { name: '下一样品', exact: true }).click()
  await dialogFor(host).waitFor()
  assert.equal(await input(dialogFor(host), '任务名称').inputValue(), '任务页样品验证')
  await dialogFor(host).press('Escape'); assert.equal(await dialogFor(host).isVisible(), false)
  await back()
  result.checks.push('样品任务独立新建、无效输入零提交、取消与失败保留草稿、重试进入；创建不激发，采集时禁止返回，完成后下一样品入口正常')

  await tabs.getByRole('button', { name: '蒸发摄谱', exact: true }).click(); host = hostFor('evaporation-acquisition')
  dialog = await open(host); await fill(dialog, '任务名称', '任务页蒸发验证'); await fill(dialog, '采样次数', 4)
  await dialog.getByRole('button', { name: '取消', exact: true }).click()
  await tabs.getByRole('button', { name: '色散摄谱', exact: true }).click()
  await tabs.getByRole('button', { name: '蒸发摄谱', exact: true }).click()
  dialog = await open(host); assert.equal(await input(dialog, '采样次数').inputValue(), '4')
  await fill(dialog, '采样次数', 1); await fill(dialog, '空白次数', 0)
  await fill(dialog, '预激时间（秒）', 0); await fill(dialog, '采样周期 (秒)', .01)
  const evaporation = await create(dialog, 'acquisitions'); await assertCapture(host)
  assert.equal((await call(page, `/api/v1/acquisitions/tasks/${evaporation.id}`)).status, 'draft')
  await finish(host, evaporation, 'acquisitions'); await back()
  result.checks.push('建立摄谱保留三种切换，各自草稿保留，只有当前页面一组标题操作；蒸发新建后手动完成摄谱')

  await tabs.getByRole('button', { name: '色散摄谱', exact: true }).click(); host = hostFor('dispersion')
  dialog = await open(host); await fill(dialog, '采样次数', 1); await fill(dialog, '空白次数', 0)
  await fill(dialog, '预激时间（秒）', 0); await fill(dialog, '采样周期（秒）', .01)
  const dispersion = await create(dialog, 'dispersion'); await assertCapture(host)
  assert.equal((await call(page, `/api/v1/dispersion/tasks/${dispersion.id}`)).status, 'draft')
  await finish(host, dispersion, 'dispersion')
  const inspector = host.locator('.spectrum-inspector')
  const plot = inspector.locator('svg.spectrum-plot'); await plot.locator('.spectrum-line').waitFor()
  await inspector.getByRole('button', { name: '适合图像', exact: true }).click(); await page.waitForTimeout(120)
  const before = await plot.evaluate(e => ({ box: [e.clientWidth, e.clientHeight], viewBox: e.getAttribute('viewBox'), path: e.querySelector('.spectrum-line').getAttribute('d') }))
  await plot.hover({ position: { x: 150, y: 100 } }); await page.waitForTimeout(100)
  const after = await plot.evaluate(e => ({ box: [e.clientWidth, e.clientHeight], viewBox: e.getAttribute('viewBox'), path: e.querySelector('.spectrum-line').getAttribute('d') }))
  assert.deepEqual(after, before)
  await inspector.getByRole('button', { name: '横向放大', exact: true }).click()
  assert.notEqual(await plot.locator('.spectrum-line').getAttribute('d'), before.path)
  await inspector.getByRole('button', { name: '适合图像', exact: true }).click()
  result.checks.push('色散新建与当前采集分离，手动采集正常；悬停图框及曲线路径保持，横向缩放有效')

  const tasks = [['sample-acquisition', sample], ['evaporation-acquisition', evaporation], ['dispersion', dispersion]]
  for (const layout of [{ width: 1440, height: 1000, theme: 'light', density: 'comfortable' }, { width: 1060, height: 680, theme: 'dark', density: 'compact' }]) {
    const settings = await call(page, '/api/v1/settings')
    await call(page, '/api/v1/settings', { display: { ...settings.display, theme: layout.theme, density: layout.density } }, 'PATCH')
    await page.reload(); await page.getByTestId('workspace').waitFor()
    if (process.env.QA_CDP) await page.evaluate(({ width, height }) => window.__TAURI__.core.invoke('plugin:window|set_size', { value: { Logical: { width, height } } }), layout)
    else await page.setViewportSize({ width: layout.width, height: layout.height })
    for (const [mode, task] of tasks) {
      host = await go(mode)
      assert.equal(await host.locator('.spectroscopy-console').isVisible(), false)
      if (mode === 'dispersion') await page.screenshot({ path: path.join(output, `tasks-${layout.theme}.png`) })
      dialog = await open(host)
      const bounds = await dialog.boundingBox(); assert.ok(bounds.width > 0 && bounds.x >= 0 && bounds.x + bounds.width <= layout.width)
      if (mode === 'sample-acquisition') await page.screenshot({ path: path.join(output, `create-${layout.theme}.png`) })
      await dialog.getByRole('button', { name: '取消', exact: true }).click()
      await host.locator(`[data-task-id="${task.id}"]`).getByRole('button').click(); await assertCapture(host)
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false)
      const consoleBounds = await host.locator('.spectroscopy-console').boundingBox()
      result.layouts.push({ ...layout, mode, dialog: bounds, console: consoleBounds })
      if (mode === 'dispersion') await page.screenshot({ path: path.join(output, `capture-${layout.theme}.png`) })
    }
  }
  result.checks.push('三种摄谱均验证列表／新建弹窗／当前采集三状态；明暗密度与大小窗口无横向溢出')
  const curveEntry = (await call(page, '/api/v1/capabilities')).capabilities.flatMap(item => item.navigation_entries).find(item => item.page === 'dispersion' && item.view === 'curve')
  await navigate(page, curveEntry.group, curveEntry.label, '[data-testid="dispersion-curve-monitor"]')
  await bench.getByRole('button', { name: '打开色散文件', exact: true }).waitFor()
  assert.equal(await bench.getByRole('button', { name: '打开色散文件', exact: true }).count(), 1)
  result.checks.push('色散曲线制作及打开旧文件入口保持独立可达')
  const admin = await page.evaluate(() => sessionStorage.getItem('geospectrum.token'))
  const readOnlyTask = await call(page, '/api/v1/dispersion/tasks', { name: '只读权限检查草稿', frame_count: 1,
    dark_frame_count: 0, pre_excitation_seconds: 0 })
  const roles = await call(page, '/api/v1/roles')
  await call(page, '/api/v1/users', { username: 'capture-pages-viewer', password: 'viewer-correct-horse',
    role_ids: [roles.find(item => item.name === 'read_only_auditor').id] })
  const login = await call(page, '/api/v1/auth/login', { username: 'capture-pages-viewer', password: 'viewer-correct-horse' })
  await page.evaluate(token => sessionStorage.setItem('geospectrum.token', token), login.access_token)
  await page.reload(); await page.getByTestId('workspace').waitFor()
  await navigate(page, 'analysis-tests', '色散摄谱', '[data-testid="dispersion-page"]')
  assert.equal(await bench.getByRole('button', { name: '新建任务', exact: true }).isDisabled(), true)
  host = hostFor('dispersion')
  await host.locator(`[data-task-id="${readOnlyTask.id}"]`).getByRole('button').click()
  for (const name of ['试样摄谱', '预热摄谱', '暂停', '停止摄谱'])
    assert.equal(await host.getByRole('button', { name, exact: true }).isDisabled(), true)
  assert.equal(await host.getByRole('dialog').isVisible(), false)
  await back()
  await host.locator(`[data-task-id="${dispersion.id}"]`).getByRole('button').click()
  await host.locator('svg.spectrum-plot .spectrum-line').waitFor()
  await page.evaluate(token => sessionStorage.setItem('geospectrum.token', token), admin)
  result.checks.push('只读账户可查看已有任务与谱图，新建及所有激发／采集控制均禁用')
}
