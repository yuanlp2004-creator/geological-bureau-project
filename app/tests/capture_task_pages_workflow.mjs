import assert from 'node:assert/strict'
import path from 'node:path'
import { readFile } from 'node:fs/promises'
import { call, navigate } from './contract_browser_support.mjs'

export async function checkTaskActionGeometry(host, taskId, canDelete) {
  const row = host.locator(`[data-task-id="${taskId}"]`)
  const open = row.locator('.task-open')
  const remove = row.locator('.task-delete')
  await open.waitFor()
  const read = () => row.evaluate(node => {
    const actions = node.querySelector('.spectroscopy-task-actions')
    const rect = el => el.getBoundingClientRect()
    const center = el => rect(el).left + rect(el).width / 2
    const deleteButton = actions.querySelector('.task-delete')
    const anchor = rect(actions)
    const columns = getComputedStyle(actions).gridTemplateColumns.split(' ').map(parseFloat)
    return {
      heading: center(node.closest('table').querySelector('th .spectroscopy-task-actions > span')),
      open: center(actions.querySelector('.task-open')),
      delete: deleteButton ? center(deleteButton) : null,
      secondTrack: deleteButton ? anchor.right - columns[1] / 2 : null,
    }
  })
  const geometry = await read()
  assert.ok(Math.abs(geometry.heading - geometry.open) <= 1, JSON.stringify(geometry))
  assert.equal(await remove.count(), Number(canDelete))
  if (canDelete) {
    assert.ok(Math.abs(geometry.delete - geometry.secondTrack) <= 1, JSON.stringify(geometry))
    await open.press('Tab')
    assert.equal(await remove.evaluate(el => el === document.activeElement), true)
    assert.deepEqual(await read(), geometry)
  }
  return geometry
}

export async function checkCaptureTaskPages(page, result, output) {
  const bench = page.getByTestId('spectroscopy-workbench')
  const tabs = bench.getByRole('navigation', { name: '摄谱方式' })
  const modes = [['sample-acquisition', '样品摄谱'], ['evaporation-acquisition', '蒸发摄谱'], ['dispersion', '色散摄谱']]
  const method = await call(page, '/api/v1/methods', { name: `摄谱QA${Date.now().toString(36)}`, conditions: {
    exposure_mode: 'simple_mean', selected_ccds: [0], frame_count: 2, dark_frame_count: 0,
    pre_excitation_seconds: 1, sampling_period_seconds: 1,
    angle_exposures: [{ angle_deg: 0, storage_mode: 'averaged', start_frame: 1, end_frame: 2 }]
  } })
  const line = JSON.parse(await readFile(new URL('./fixtures/station17-line.json', import.meta.url), 'utf8'))
  await call(page, `/api/v1/methods/${method.id}/lines`, line)
  await call(page, `/api/v1/methods/${method.id}/publish`, {})
  await call(page, '/api/v1/methods/current', { method_id: method.id })
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
    assert.equal(await host.locator('.spectroscopy-task-dialog[open]').count(), 0)
    assert.equal(await host.locator('.spectroscopy-setup .acquisition-form, .spectroscopy-setup .dispersion-setup').count(), 0)
    assert.equal(await host.getByRole('button', { name: '任务详情', exact: true }).count(), 0)
    assert.equal(await host.getByRole('button', { name: '谱图读数', exact: true }).count(), 0)
    assert.equal(await host.getByRole('button', { name: '试样摄谱', exact: true }).isVisible(), true)
  }
  const create = async (dialog, domain) => {
    const sample = await dialog.locator('.sample-number-form').count() > 0
    const endpoint = sample ? '/api/v1/acquisitions/sample-sessions' : domain === 'dispersion' ? '/api/v1/dispersion/capture-sessions' : '/api/v1/acquisitions/evaporation-sessions'
    const response = page.waitForResponse(r => new URL(r.url()).pathname === endpoint && r.request().method() === 'POST')
    await dialog.getByRole('button', { name: '确定', exact: true }).click()
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
    await host.locator('.legacy-capture-desk[data-status="completed"]').waitFor()
  }

  // Select non-first sources in their owning pages, then reload to verify persistence.
  const device = await call(page, '/api/v1/devices/profiles', { name: `当前设备${Date.now().toString(36)}` })
  await navigate(page, 'tools', '设备调试', '.device-debug-page')
  await page.getByRole('tab', { name: '设备参数', exact: true }).click()
  const profileSelect = page.locator('.device-profile-select select')
  await profileSelect.locator(`option[value="${device.id}"]`).waitFor({ state: 'attached' })
  let selectedResponse = page.waitForResponse(r => r.request().method() === 'PUT' && r.url().endsWith('/devices/current'))
  await profileSelect.selectOption(String(device.id)); assert.equal((await selectedResponse).status(), 200)
  await call(page, '/api/v1/sample-queues', { name: '其他样号表', items: [{ pre_name: 'OTHER', repeats: 1 }] })
  const queue = await call(page, '/api/v1/sample-queues', { name: '当前预录样号表', name_length: 20,
    items: [{ pre_name: 'A1234567890123456789', repeats: 1 }, { pre_name: 'S1', repeats: 2 }] })
  await navigate(page, 'analysis-tests', '样号与样品队列', '.sample-queue-page')
  const queueSelect = page.locator('.sample-queue-page label.field').filter({ has: page.getByText('选择样品队列', { exact: true }) }).locator('select')
  await queueSelect.locator(`option[value="${queue.id}"]`).waitFor({ state: 'attached' })
  selectedResponse = page.waitForResponse(r => r.request().method() === 'PUT' && r.url().endsWith('/sample-queues/current'))
  await queueSelect.selectOption(String(queue.id)); assert.equal((await selectedResponse).status(), 200)
  await page.reload(); await page.getByTestId('workspace').waitFor()
  assert.equal((await call(page, '/api/v1/devices/current')).id, device.id)
  assert.equal((await call(page, '/api/v1/sample-queues/current')).id, queue.id)
  let host = await go('sample-acquisition')
  let dialog = await open(host)
  assert.equal(await dialog.locator('input:not([type="hidden"]),select,textarea').count(), 1)
  await fill(dialog, '样品摄谱编号', '')
  assert.equal(await dialog.getByRole('button', { name: '确定', exact: true }).isDisabled(), true)
  await fill(dialog, '样品摄谱编号', '当前方法_本次数据编号_20261105_1630')
  await dialog.getByRole('button', { name: '取消', exact: true }).click()
  dialog = await open(host)
  assert.equal(await input(dialog, '样品摄谱编号').inputValue(), '当前方法_本次数据编号_20261105_1630')
  let sampleBody
  const observe = request => { if (request.method() === 'POST' && request.url().endsWith('/acquisitions/sample-sessions')) sampleBody = request.postDataJSON() }
  page.on('request', observe)
  await page.route('**/api/v1/acquisitions/sample-sessions', route => route.fulfill({ status: 503, contentType: 'application/json',
    body: JSON.stringify({ detail: { code: 'QA_RETRY', message: '模拟新建失败' } }) }))
  await dialog.getByRole('button', { name: '确定', exact: true }).click()
  await dialog.getByRole('alert').waitFor()
  assert.equal(await input(dialog, '样品摄谱编号').inputValue(), '当前方法_本次数据编号_20261105_1630')
  await page.unroute('**/api/v1/acquisitions/sample-sessions')
  const sample = await create(dialog, 'acquisitions')
  page.off('request', observe)
  assert.deepEqual(sampleBody, { name: '当前方法_本次数据编号_20261105_1630' })
  assert.equal(sample.name, sampleBody.name); assert.equal(sample.device_profile_id, device.id)
  assert.equal(sample.method_id, method.id); assert.equal(sample.queue_id, queue.id)
  assert.equal(sample.sample_name, queue.items[0].pre_name); assert.equal(sample.name_length, 20)
  assert.equal(sample.burn_frame_count, 2); assert.equal(sample.dark_frame_count, 0)
  assert.equal(sample.sampling_period_seconds, 1); assert.equal(sample.storage_mode, 'averaged')
  assert.deepEqual(sample.ccd_indices, [0])
  await assertCapture(host)
  await finish(host, sample, 'acquisitions')
  const nextResponse = page.waitForResponse(r => r.request().method() === 'POST' && r.url().endsWith('/acquisitions/tasks'))
  await bench.getByRole('button', { name: '下一样品', exact: true }).click()
  const next = await (await nextResponse).json()
  assert.equal(next.name, sample.name); assert.equal(next.sample_name, 'S1'); assert.equal(next.repeat_count, 2)
  assert.equal(next.method_id, sample.method_id); assert.equal(next.device_profile_id, device.id)
  assert.equal(await dialogFor(host).isVisible(), false)
  await back()
  result.checks.push('样品新建只有编号；设备与样号表从所属页面选择并持久化，方法与采集条件来自当前方法；取消／失败保留输入，下一样品不再重复填写编号')

  const defaultsBefore = (await call(page, '/api/v1/settings')).preliminary
  await tabs.getByRole('button', { name: '蒸发摄谱', exact: true }).click(); host = hostFor('evaporation-acquisition')
  dialog = await open(host)
  assert.equal(await dialog.locator('input').count(), 6); assert.equal(await dialog.locator('select').count(), 0)
  await fill(dialog, '蒸发曲线名', '任务页蒸发验证'); await fill(dialog, '采样次数', 2)
  await fill(dialog, '空白次数', 0); await fill(dialog, '预激时间（秒）', 2); await fill(dialog, '采样周期（秒）', 1.25)
  await dialog.getByLabel('保存激发条件', { exact: true }).check()
  await dialog.getByRole('button', { name: '取消', exact: true }).click()
  assert.deepEqual((await call(page, '/api/v1/settings')).preliminary, defaultsBefore)
  await tabs.getByRole('button', { name: '色散摄谱', exact: true }).click()
  await tabs.getByRole('button', { name: '蒸发摄谱', exact: true }).click()
  dialog = await open(host)
  assert.equal(await input(dialog, '蒸发曲线名').inputValue(), '任务页蒸发验证')
  await page.route('**/api/v1/acquisitions/evaporation-sessions', route => route.fulfill({ status: 503,
    contentType: 'application/json', body: JSON.stringify({ detail: { code: 'QA_RETRY', message: '模拟蒸发创建失败' } }) }))
  await dialog.getByRole('button', { name: '确定', exact: true }).click()
  await dialog.getByRole('alert').waitFor()
  assert.deepEqual((await call(page, '/api/v1/settings')).preliminary, defaultsBefore)
  assert.equal(await input(dialog, '蒸发曲线名').inputValue(), '任务页蒸发验证')
  await page.unroute('**/api/v1/acquisitions/evaporation-sessions')
  const evaporation = await create(dialog, 'acquisitions'); await assertCapture(host)
  assert.deepEqual(evaporation.ccd_indices, [0]); assert.equal(evaporation.device_profile_id, device.id)
  const savedDefaults = (await call(page, '/api/v1/settings')).preliminary
  assert.deepEqual(savedDefaults.evaporation, { pre_excitation_seconds: 2, sampling_period_seconds: 1.25, frame_count: 2, dark_frame_count: 0 })
  assert.deepEqual(savedDefaults.dispersion, defaultsBefore.dispersion)
  assert.equal((await call(page, `/api/v1/acquisitions/tasks/${evaporation.id}`)).status, 'draft')
  await finish(host, evaporation, 'acquisitions'); await back()
  result.checks.push('蒸发只显示旧版四项激发参数、保存复选框与曲线名；取消／失败不改默认，勾选成功后只保存蒸发条件，设备与方法布局自动沿用')

  await tabs.getByRole('button', { name: '色散摄谱', exact: true }).click(); host = hostFor('dispersion')
  dialog = await open(host)
  assert.equal(await dialog.locator('input').count(), 6); assert.equal(await dialog.locator('select').count(), 0)
  await fill(dialog, '色散曲线名', '任务页色散验证'); await fill(dialog, '采样次数', 1); await fill(dialog, '空白次数', 0)
  await fill(dialog, '预激时间（秒）', 1); await fill(dialog, '采样周期（秒）', 1)
  assert.equal(await dialog.getByLabel('保存激发条件', { exact: true }).isChecked(), false)
  const dispersion = await create(dialog, 'dispersion'); await assertCapture(host)
  assert.equal(dispersion.name, '任务页色散验证'); assert.equal(dispersion.device_profile_id, device.id)
  assert.deepEqual(dispersion.ccd_indices, device.ccd_indices)
  assert.deepEqual((await call(page, '/api/v1/settings')).preliminary, savedDefaults)
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

  const tasks = [
    ['sample-acquisition', next],
    ['evaporation-acquisition', await call(page, '/api/v1/acquisitions/tasks', { task_kind: 'evaporation', name: '蒸发操作布局验收' })],
    ['dispersion', await call(page, '/api/v1/dispersion/tasks', { name: '色散操作布局验收' })]
  ]
  const logs = await call(page, '/api/v1/logs?limit=500')
  for (const task of [sample, evaporation]) {
    const messages = (await call(page, `/api/v1/acquisitions/tasks/${task.id}`)).messages
    for (const message of messages) assert.ok(logs.some(event => event.details?.source === 'acquisition'
      && event.details.task_id === task.id && event.details.message_id === message.id && event.message === message.message),
      `统一信息记录缺少任务 ${task.id} 的 ${message.code}`)
  }
  const information = page.getByTestId('runtime-messages')
  if (await information.getByRole('button', { name: '展开信息记录', exact: true }).count())
    await information.getByRole('button', { name: '展开信息记录', exact: true }).click()
  await information.getByRole('tab', { name: /常规信息/ }).click()
  await information.getByLabel('过滤信息记录', { exact: true }).fill('全部采集完成')
  await information.locator('.runtime-message-row').first().waitFor()
  await information.getByLabel('过滤信息记录', { exact: true }).fill('')
  await information.getByRole('button', { name: '收起信息记录', exact: true }).click()
  result.checks.push('样品与蒸发全部采集消息进入已有统一信息记录，完成消息可直接查看')
  for (const layout of [{ width: 1440, height: 1000, theme: 'light', density: 'comfortable' }, { width: 1060, height: 680, theme: 'dark', density: 'compact' }]) {
    const settings = await call(page, '/api/v1/settings')
    await call(page, '/api/v1/settings', { display: { ...settings.display, theme: layout.theme, density: layout.density } }, 'PATCH')
    await page.reload(); await page.getByTestId('workspace').waitFor()
    if (process.env.QA_CDP) await page.evaluate(({ width, height }) => window.__TAURI__.core.invoke('plugin:window|set_size', { value: { Logical: { width, height } } }), layout)
    else await page.setViewportSize({ width: layout.width, height: layout.height })
    for (const [mode, task] of tasks) {
      host = await go(mode)
      assert.equal(await host.locator('.spectroscopy-console').isVisible(), false)
      assert.equal(await host.locator('.acquisition-record-review, .acquisition-rename, .acquisition-measurements, .acquisition-messages').count(), 0)
      await checkTaskActionGeometry(host, task.id, true)
      if (mode === 'dispersion') await page.screenshot({ path: path.join(output, `tasks-${layout.theme}.png`) })
      dialog = await open(host)
      assert.equal(await dialog.locator('input').count(), mode === 'sample-acquisition' ? 1 : 6)
      assert.equal(await dialog.locator('select').count(), 0)
      if (mode !== 'sample-acquisition') await page.screenshot({ path: path.join(output, `preliminary-${mode}-${layout.theme}.png`) })
      const bounds = await dialog.boundingBox(); assert.ok(bounds.width > 0 && bounds.x >= 0 && bounds.x + bounds.width <= layout.width)
      if (mode !== 'sample-acquisition') {
        const fill = await dialog.evaluate(node => {
          const container = node.querySelector('.spectroscopy-task-fields'), body = node.querySelector('.preliminary-capture-fields')
          const style = getComputedStyle(container)
          return { actual: body.getBoundingClientRect().width, available: container.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight) }
        })
        assert.ok(Math.abs(fill.actual - fill.available) <= 1, JSON.stringify(fill))
      }
      if (mode === 'sample-acquisition') await page.screenshot({ path: path.join(output, `create-${layout.theme}.png`) })
      await dialog.getByRole('button', { name: '取消', exact: true }).click()
      await host.locator(`[data-task-id="${task.id}"]`).getByRole('button', { name: '进入摄谱', exact: true }).click(); await assertCapture(host)
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
  const viewer = `capture-viewer-${Date.now().toString(36)}`
  await call(page, '/api/v1/users', { username: viewer, password: 'viewer-correct-horse',
    role_ids: [roles.find(item => item.name === 'read_only_auditor').id] })
  const login = await call(page, '/api/v1/auth/login', { username: viewer, password: 'viewer-correct-horse' })
  await page.evaluate(token => sessionStorage.setItem('geospectrum.token', token), login.access_token)
  await page.reload(); await page.getByTestId('workspace').waitFor()
  await navigate(page, 'analysis-tests', '色散摄谱', '[data-testid="dispersion-page"]')
  assert.equal(await bench.getByRole('button', { name: '新建任务', exact: true }).isDisabled(), true)
  host = hostFor('dispersion')
  await checkTaskActionGeometry(host, readOnlyTask.id, false)
  await host.locator(`[data-task-id="${readOnlyTask.id}"]`).getByRole('button', { name: '进入摄谱', exact: true }).click()
  for (const name of ['试样摄谱', '预热摄谱', '停止摄谱'])
    assert.equal(await host.getByRole('button', { name, exact: true }).isDisabled(), true)
  assert.equal(await host.getByRole('button', { name: '暂停', exact: true }).count(), 0)
  assert.equal(await host.getByRole('dialog').isVisible(), false)
  await back()
  await host.locator(`[data-task-id="${dispersion.id}"]`).getByRole('button', { name: '查看谱图', exact: true }).click()
  await page.getByTestId('spectrum-viewer-page').locator('svg.spectrum-plot .spectrum-line').first().waitFor()
  await page.evaluate(token => sessionStorage.setItem('geospectrum.token', token), admin)
  result.checks.push('只读账户可查看已有任务与谱图，新建及所有激发／采集控制均禁用')
}
