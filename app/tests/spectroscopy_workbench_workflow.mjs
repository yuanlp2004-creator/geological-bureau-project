import assert from 'node:assert/strict'
import path from 'node:path'
import { call, navigate } from './contract_browser_support.mjs'

// Real isolated APIs verify the common console, preserved drafts, and command/mode boundaries.
export async function checkSpectroscopyWorkbench(page, fixture, result, output) {
  const check = (message) => { result.checks.push(message); console.log(`PASS: ${message}`) }
  const modes = [
    ['sample-acquisition', '样品摄谱', 'sample-acquisition-page'],
    ['evaporation-acquisition', '蒸发摄谱', 'evaporation-acquisition-page'],
    ['dispersion', '色散摄谱', 'dispersion-page']
  ]
  await call(page, '/api/v1/methods/current', { method_id: fixture.method_id })
  await page.reload()
  await page.getByTestId('workspace').waitFor()
  const bench = page.getByTestId('spectroscopy-workbench')
  const tabs = bench.getByRole('navigation', { name: '摄谱方式' })
  const host = (kind) => page.getByTestId(modes.find((item) => item[0] === kind)[2])
  const settled = async () => {
    await page.waitForFunction(() => !document.querySelector('.spectroscopy-lock'))
  }
  const switchMode = async (kind, menu = false) => {
    const item = modes.find((item) => item[0] === kind)
    if (menu) await navigate(page, 'analysis-tests', item[1], `[data-testid="${item[2]}"]`)
    else await tabs.getByRole('button', { name: item[1], exact: true }).click()
    await host(kind).waitFor({ state: 'visible' })
    await settled()
    assert.equal(await bench.getAttribute('data-mode'), kind)
    assert.equal(await bench.getByTestId('spectroscopy-console').filter({ visible: true }).count(), 1)
    return host(kind)
  }
  const openForm = async (scope) => {
    const disclosure = scope.locator('.disclosure-toggle').first()
    if (await disclosure.getAttribute('aria-expanded') === 'false') await disclosure.click()
  }
  const field = (scope, label) => scope.locator('label.field').filter({ has: page.getByText(label, { exact: true }) }).locator('input')
  const fill = async (scope, label, value) => {
    const input = field(scope, label)
    await input.fill(String(value)); await input.blur()
  }
  const mutation = (url, method = 'POST') => page.waitForResponse((response) => response.url().endsWith(url) && response.request().method() === method)
  const configure = async (scope, name, burnCount = 2) => {
    await openForm(scope)
    const form = scope.locator('.acquisition-form')
    await fill(form, '任务名称', name)
    const advanced = form.locator('details').filter({ has: page.getByText('高级采集设置', { exact: true }) })
    if (await advanced.getAttribute('open') === null) await advanced.locator('summary').click()
    if (await form.getByLabel('激发参数与默认次数').count())
      await form.getByLabel('激发参数与默认次数').selectOption('custom')
    await fill(form, '采样次数', burnCount); await fill(form, '空白次数', 0)
    await fill(form, '预激时间（秒）', 0); await fill(form, '采样周期 (秒)', .01)
    await fill(form, '倒计时（秒）', 0)
    return form
  }
  const createAcquisition = async (scope) => {
    const pending = mutation('/api/v1/acquisitions/tasks')
    await scope.getByRole('button', { name: '创建任务', exact: true }).click()
    const response = await pending; assert.equal(response.status(), 201, await response.text())
    return response.json()
  }
  const control = async (scope, task, label, command, domain = 'acquisitions') => {
    const pending = mutation(`/api/v1/${domain}/tasks/${task.id}/${command}`)
    await scope.getByTestId('spectroscopy-console').getByRole('button', { name: label, exact: true }).click()
    const response = await pending; assert.equal(response.status(), 200)
    return response.json()
  }
  const finish = async (scope, task) => {
    let current = task
    for (let i = 0; i < 30 && current.status !== 'completed'; i++) current = await control(scope, task, '单步', 'step')
    assert.equal(current.status, 'completed'); assert.ok(current.result_sha256)
    await settled()
    return current
  }

  let sample = await switchMode('sample-acquisition', true)
  await bench.getByRole('heading', { name: '摄谱工作台', exact: true }).waitFor()
  const sampleForm = await configure(sample, '共用工作台样品', 3)
  await fill(sampleForm, '临时样号', 'SHARED01')
  await page.evaluate(() => { window.__workbenchIdentity = document.querySelector('[data-testid="spectroscopy-workbench"]') })
  let evaporation = await switchMode('evaporation-acquisition')
  const evaporationForm = await configure(evaporation, '独立蒸发草稿')
  assert.equal(await evaporationForm.getByText('样品队列', { exact: true }).count(), 0)
  assert.equal(await evaporationForm.getByText('已发布方法版本', { exact: true }).count(), 0)
  await fill(evaporationForm, '采样次数', '')
  let dispersion = await switchMode('dispersion', true)
  await openForm(dispersion)
  await fill(dispersion, '采样次数', 3)
  await fill(dispersion, '空白次数', 1)
  await fill(dispersion, '预激时间（秒）', 0)
  sample = await switchMode('sample-acquisition')
  assert.equal(await sampleForm.getByLabel('任务名称').inputValue(), '共用工作台样品')
  assert.equal(await sampleForm.getByLabel('临时样号', { exact: true }).inputValue(), 'SHARED01')
  assert.equal(await page.evaluate(() => window.__workbenchIdentity === document.querySelector('[data-testid="spectroscopy-workbench"]')), true)
  check('三个菜单/模式共用同一工作台与控制区；切换保留各自草稿')

  const sampleTask = await createAcquisition(sample)
  assert.equal(sampleTask.task_kind, 'sample'); assert.equal(sampleTask.sample_name, 'SHARED01')
  let release, arrived
  const arrival = new Promise((resolve) => { arrived = resolve })
  const gate = new Promise((resolve) => { release = resolve })
  const route = async (route) => { arrived(); await gate; await route.continue() }
  await page.route(`**/acquisitions/tasks/${sampleTask.id}/start`, route)
  const starting = mutation(`/api/v1/acquisitions/tasks/${sampleTask.id}/start`)
  await sample.getByTestId('spectroscopy-console').getByRole('button', { name: '开始', exact: true }).click()
  await arrival
  assert.equal(await tabs.getByRole('button', { name: '色散摄谱', exact: true }).isDisabled(), true)
  await navigate(page, 'analysis-tests', '色散摄谱', '[data-testid="spectroscopy-workbench"]')
  assert.equal(await bench.getAttribute('data-mode'), 'sample-acquisition')
  release(); assert.equal((await starting).status(), 200)
  await page.unroute(`**/acquisitions/tasks/${sampleTask.id}/start`, route)
  await control(sample, sampleTask, '暂停', 'pause')
  assert.equal(await tabs.getByRole('button', { name: '蒸发摄谱', exact: true }).isDisabled(), true)
  await control(sample, sampleTask, '继续', 'resume')
  await finish(sample, sampleTask)
  await sample.getByRole('heading', { name: '即时测量结果', exact: true }).waitFor()
  assert.equal(await sample.getByTestId('spectroscopy-console').getByRole('button', { name: '单步', exact: true }).isDisabled(), true)
  assert.equal(await sample.evaluate((node) => node.querySelector('[data-testid="spectroscopy-console"]').compareDocumentPosition(node.querySelector('[data-testid="acquisition-measurements"]')) & Node.DOCUMENT_POSITION_FOLLOWING), 4)
  check('样品实际模拟采集完成并产生结果哈希；请求未返回、运行与暂停时均阻止菜单/模式切换，完成后解锁')
  await openForm(sample)
  await fill(sampleForm, '采样次数', '')

  evaporation = await switchMode('evaporation-acquisition')
  assert.equal(await evaporationForm.getByLabel('任务名称').inputValue(), '独立蒸发草稿')
  assert.equal(await field(evaporationForm, '采样次数').inputValue(), '')
  let writes = 0
  const record = (request) => { if (request.url().endsWith('/api/v1/acquisitions/tasks') && request.method() === 'POST') writes++ }
  page.on('request', record)
  await evaporationForm.getByRole('button', { name: '创建任务', exact: true }).click()
  assert.equal(writes, 0); page.off('request', record)
  await fill(evaporationForm, '采样次数', 2)
  const save = mutation('/api/v1/acquisitions/defaults', 'PUT')
  await evaporationForm.getByRole('button', { name: '保存激发条件', exact: true }).click()
  assert.equal((await save).status(), 200, '隐藏的样品非法草稿不能阻止蒸发条件保存')
  const evaporationTask = await createAcquisition(evaporation)
  assert.equal(evaporationTask.task_kind, 'evaporation'); assert.equal(evaporationTask.method_id, null)
  assert.equal(evaporationTask.storage_mode, 'full_interval')
  assert.equal(evaporationTask.repeat_count, 1)
  const started = await control(evaporation, evaporationTask, '开始', 'start')
  await finish(evaporation, started)
  assert.equal(await evaporation.getByRole('button', { name: '标记区间', exact: true }).count(), 0)
  const frames = await call(page, `/api/v1/acquisitions/tasks/${evaporationTask.id}/frames`)
  assert.ok(frames.length > 0)
  assert.equal(await evaporation.getByRole('heading', { name: '即时测量结果', exact: true }).count(), 0)
  assert.equal(await evaporation.locator('.acquisition-task-list').getByText(sampleTask.name, { exact: true }).count(), 0)
  check('蒸发非法输入零写入；独立任务完成并保存全时帧，已移除手工区间标记，任务列表与样品结果隔离')

  dispersion = await switchMode('dispersion')
  assert.equal(await dispersion.getByLabel('采样次数', { exact: true }).inputValue(), '3')
  const creating = mutation('/api/v1/dispersion/tasks')
  await dispersion.getByRole('button', { name: '新建任务', exact: true }).click()
  const response = await creating; assert.equal(response.status(), 201)
  const dispersionTask = await response.json()
  await control(dispersion, dispersionTask, '开始', 'start', 'dispersion')
  await control(dispersion, dispersionTask, '暂停', 'pause', 'dispersion')
  await navigate(page, 'analysis-tests', '色散曲线', '[data-testid="spectroscopy-workbench"]')
  assert.equal(await dispersion.getAttribute('data-view'), 'capture', 'paused acquisition cannot enter curve editing')
  assert.equal(await tabs.getByRole('button', { name: '样品摄谱', exact: true }).isDisabled(), true)
  await control(dispersion, dispersionTask, '继续', 'resume', 'dispersion')
  await dispersion.getByTestId('spectroscopy-console').locator('.state-chip').filter({ hasText: '已完成' }).waitFor()
  await settled()
  await dispersion.locator('svg.spectrum-plot .spectrum-line').first().waitFor()
  const saved = await call(page, `/api/v1/dispersion/tasks/${dispersionTask.id}`)
  assert.equal(saved.burn_frames_captured, 3); assert.equal(saved.dark_frames_captured, 1)
  assert.equal(await dispersion.getByRole('heading', { name: '色散曲线版本管理', exact: true }).count(), 0)
  // Stop a second run through the same shared control, then verify switching is released.
  await openForm(dispersion)
  const second = mutation('/api/v1/dispersion/tasks')
  await dispersion.getByRole('button', { name: '新建任务', exact: true }).click()
  const stopTask = await (await second).json()
  await control(dispersion, stopTask, '开始', 'start', 'dispersion')
  const stopped = await control(dispersion, stopTask, '停止', 'stop', 'dispersion')
  assert.equal(stopped.status, 'stopped'); await settled()
  await switchMode('sample-acquisition')
  assert.ok(await sample.getByTestId('spectroscopy-console').getByRole('heading', { name: sampleTask.name, exact: true }).isVisible())
  check('色散共用控制、暂停继续、燃烧/暗帧完成与停止收尾通过；返回样品保留任务和谱图')

  for (const [theme, density, width, height] of [['light', 'comfortable', 1440, 1000], ['dark', 'compact', 1060, 1000], ['light', 'compact', 1060, 680]]) {
    if (!process.env.QA_CDP) await page.setViewportSize({ width, height })
    else await page.evaluate(({ width, height }) => window.__TAURI__.core.invoke('plugin:window|set_size', { value: { Logical: { width, height } } }), { width, height })
    await page.evaluate(({ theme, density }) => {
      document.documentElement.dataset.theme = theme; document.documentElement.dataset.density = density
      const shell = document.querySelector('.app-shell'); shell.dataset.theme = theme; shell.dataset.density = density
    }, { theme, density })
    for (const [mode] of modes) {
      const scope = await switchMode(mode)
      const disclosure = scope.locator('.disclosure-toggle').first()
      if (await disclosure.getAttribute('aria-expanded') === 'false') await disclosure.click()
      if (mode === 'dispersion') {
        const expand = scope.getByRole('button', { name: '展开列表', exact: true })
        if (await expand.count()) await expand.click()
        await scope.locator('.dispersion-task-list button').filter({ hasText: dispersionTask.name }).click()
      }
      const railButton = scope.getByRole('button', { name: width === 1060 ? '收起列表' : '展开列表', exact: true })
      if (await railButton.count()) await railButton.click()
      await page.evaluate(() => window.scrollTo(0, 0))
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
      assert.ok(overflow <= 1, `${mode} ${theme} horizontal overflow ${overflow}`)
      const console = scope.getByTestId('spectroscopy-console')
      await console.locator('.spectroscopy-setup').evaluate((node) => { node.scrollTop = 0 })
      const geometry = await console.evaluate((node) => {
        const bounds = (selector) => {
          const { x, y, width, height, bottom, right } = node.querySelector(selector).getBoundingClientRect()
          return { x, y, width, height, bottom, right }
        }
        const svg = node.querySelector('svg.spectrum-plot')
        const frame = svg?.querySelector('.plot-background')?.getBoundingClientRect()
        const plot = svg?.getBoundingClientRect()
        return { view: bounds('.spectroscopy-view'), operator: bounds('.spectroscopy-operator'),
          controls: bounds('.spectroscopy-controls'), setup: bounds('.spectroscopy-setup'),
          plotFill: frame && plot ? frame.height / plot.height : null }
      })
      assert.ok(geometry.view.right <= geometry.operator.x + 1, 'operator stays to the right of the spectrum')
      assert.ok(geometry.view.width > geometry.operator.width, 'spectrum remains the largest column')
      assert.ok(geometry.controls.bottom <= height, 'stop and capture controls remain in the viewport')
      assert.ok(geometry.plotFill > .5, 'curve uses the available plot height')
      await console.locator('.spectroscopy-setup').evaluate((node) => { node.scrollTop = node.scrollHeight })
      const afterScroll = await console.locator('.spectroscopy-controls').boundingBox()
      assert.ok(Math.abs(afterScroll.y - geometry.controls.y) <= 1, 'scrolling conditions never moves capture controls')
      await console.locator('.spectroscopy-setup').evaluate((node) => { node.scrollTop = 0 })
      const clipping = await console.locator('.spectroscopy-controls').evaluate((node) => node.scrollWidth - node.clientWidth)
      assert.ok(clipping <= 1, 'control buttons must wrap without clipping')
      result.layouts.push({ mode, theme, density, width, height, overflow, controlOverflow: clipping, geometry })
      await page.screenshot({ path: path.join(output, `${mode}-${width}-${height}-${theme}.png`) })
    }
  }
  check('三模式1440/1060宽及680高、明暗紧凑三栏通过；主图占主宽度与高度，条件独立滚动且控制区位置固定')
  await call(page, '/api/v1/settings', { display: { theme: 'light', density: 'comfortable' } }, 'PATCH')
  const admin = await page.evaluate(() => sessionStorage.getItem('geospectrum.token'))
  const roles = await call(page, '/api/v1/roles')
  await call(page, '/api/v1/users', { username: 'spectroscopy-viewer', password: 'viewer-correct-horse', role_ids: [roles.find((item) => item.name === 'read_only_auditor').id] })
  const login = await call(page, '/api/v1/auth/login', { username: 'spectroscopy-viewer', password: 'viewer-correct-horse' })
  await page.evaluate((token) => sessionStorage.setItem('geospectrum.token', token), login.access_token)
  await page.reload(); await page.getByTestId('workspace').waitFor()
  dispersion = await switchMode('dispersion', true)
  for (const label of ['开始', '连续采集', '单步', '暂停', '停止'])
    assert.equal(await dispersion.getByTestId('spectroscopy-console').getByRole('button', { name: label, exact: true }).isDisabled(), true)
  for (const label of ['样品摄谱', '蒸发摄谱'])
    assert.equal(await tabs.getByRole('button', { name: label, exact: true }).isDisabled(), true)
  await page.evaluate((token) => sessionStorage.setItem('geospectrum.token', token), admin)
  await page.reload(); await page.getByTestId('workspace').waitFor()
  check('只读角色不能创建或执行摄谱；当前方法前置条件在共用模式入口继续生效')
}
