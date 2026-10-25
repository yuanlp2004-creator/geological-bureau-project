import assert from 'node:assert/strict'
import { readFile, writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import path from 'node:path'
import { call, navigate } from './contract_browser_support.mjs'
import { readSampleCells } from './sample_column_table_workflow.mjs'

// 在真实 Web 或桌面页面中验证即时结果、20 位先列后行、后命名与在途删除。
export async function checkContractAdditions(page, output) {
  const checks = []
  const line = JSON.parse(await readFile(fileURLToPath(new URL('./fixtures/station17-line.json', import.meta.url)), 'utf8'))
  const method = await call(page, '/api/v1/methods', { name: '合同新增三项验证' })
  await call(page, `/api/v1/methods/${method.id}/lines`, line)
  const published = await call(page, `/api/v1/methods/${method.id}/publish`, {})
  await call(page, `/api/v1/methods/${method.id}/open`, {})
  const queue = await call(page, '/api/v1/sample-queues', { name: '合同20位队列', name_length: 20,
    items: Array.from({ length: 22 }, /* 生成按录入序号的完整20位样号。 */ (_, i) => ({ pre_name: `2026100300${String(i + 1).padStart(10, '0')}`, repeats: 1 })) })
  await page.reload()
  await page.getByTestId('workspace').waitFor()
  await navigate(page, 'analysis-tests', '样号与样品队列', '.sample-queue-page')
  const samplesPage = page.locator('.sample-queue-page')
  await samplesPage.getByLabel(/^选择样品队列/).selectOption(String(queue.id))
  const rows = samplesPage.getByRole('table', { name: '样号按列排列表格' }).locator('[data-sample-id]')
  await rows.first().waitFor()
  assert.equal(await rows.count(), 22)
  const boxes = await readSampleCells(page)
  assert.deepEqual(boxes.map(cell => cell.name), queue.items.map(item => item.pre_name))
  assert.ok(boxes.slice(0, 20).every((box, index) => box.x === boxes[0].x && (index === 0 || box.y > boxes[index - 1].y)))
  assert.ok(boxes[20].x > boxes[0].x && boxes[20].y === boxes[0].y)
  const shorter = page.waitForResponse(/* 等待服务端拒绝截断。 */ (r) => r.url().endsWith(`/sample-queues/${queue.id}`) && r.request().method() === 'PATCH')
  await samplesPage.getByLabel(/^样号长度/).selectOption('12')
  assert.equal((await shorter).status(), 422)
  assert.equal(await samplesPage.getByLabel(/^样号长度/).inputValue(), '20')
  await page.screenshot({ path: path.join(output, 'contract-columns.png'), fullPage: true })
  checks.push('20位样号持久、先列后行排列，12位切换拒绝截断')

  await navigate(page, 'analysis-tests', '样品摄谱', '[data-testid="sample-acquisition-page"]')
  const acquisitionPage = page.getByTestId('sample-acquisition-page')
  await acquisitionPage.getByLabel(/^已发布方法版本/).locator(`option[value="${published.id}:${published.current_version}"]`).waitFor({ state: 'attached' })
  if (await acquisitionPage.locator('.acquisition-task-rows button.active').count()) {
    await acquisitionPage.locator('button[aria-expanded="false"]').filter({ hasText: '建立采集任务' }).waitFor()
    await acquisitionPage.locator('.disclosure-toggle').filter({ hasText: /建立.*任务/ }).click()
  }
  await acquisitionPage.getByLabel(/^已发布方法版本/).selectOption(`${published.id}:${published.current_version}`)
  await acquisitionPage.getByLabel(/^样号长度/).selectOption('20')
  await acquisitionPage.getByLabel('临时样号', { exact: true }).fill(queue.items[0].pre_name)
  await acquisitionPage.getByText('高级采集设置', { exact: true }).click()
  await acquisitionPage.getByLabel(/^激发参数与默认次数/).selectOption('custom')
  await acquisitionPage.getByLabel('采样次数', { exact: true }).fill('8')
  await acquisitionPage.getByLabel('空白次数', { exact: true }).fill('1')
  await acquisitionPage.getByLabel('预激时间（秒）', { exact: true }).fill('0')
  const creating = page.waitForResponse(/* 捕获真实新建任务。 */ (r) => r.url().endsWith('/acquisitions/tasks') && r.request().method() === 'POST')
  await acquisitionPage.getByRole('button', { name: '创建任务', exact: true }).click()
  const task = await (await creating).json()
  assert.equal(task.name_length, 20)
  const stepping = page.waitForResponse(/* 等待真实采样次数。 */ (r) => new URL(r.url()).pathname.endsWith(`/tasks/${task.id}/step`))
  await acquisitionPage.getByRole('button', { name: '试样摄谱', exact: true }).click()
  await stepping
  const measurements = acquisitionPage.getByTestId('acquisition-measurements')
  await page.waitForFunction(/* 等待首帧的真实数值上屏。 */ () => [...document.querySelectorAll('[data-testid="acquisition-measurements"] tbody tr')]
    .some(/* 检查峰强度非占位。 */ (row) => row.children[3]?.textContent !== '—'))
  const live = await call(page, `/api/v1/acquisitions/tasks/${task.id}/measurements`)
  assert.ok(live.rows.some(/* 当前采样次数必须生成强度。 */ (row) => typeof row.peak_height === 'number' && row.complete === false))
  checks.push('摄谱未完成时的真实强度与峰位即时上屏')
  await page.screenshot({ path: path.join(output, 'contract-measurements.png'), fullPage: true })

  let releaseStep, stepSeen
  const seen = new Promise(/* 记录已发送的自动步进。 */ (resolve) => { stepSeen = resolve })
  const held = new Promise(/* 控制真实响应的释放时机。 */ (resolve) => { releaseStep = resolve })
  await page.route(`**/api/v1/acquisitions/tasks/${task.id}/step?*`, /* 仅延迟真实响应，不伪造测量。 */ async (route) => {
    const response = await route.fetch()
    stepSeen()
    await held
    await route.fulfill({ response })
  })
  await seen
  const discardedResponse = page.waitForResponse(/* 等待唯一删除请求。 */ (r) => r.url().endsWith(`/tasks/${task.id}/discard`))
  await measurements.getByRole('button', { name: '删除异常样品（能量不足）', exact: true }).click()
  releaseStep()
  const discarded = await (await discardedResponse).json()
  assert.equal(discarded.status, 'stopped')
  assert.ok(discarded.samples.every(/* 所有重复移出可用样品。 */ (sample) => sample.discarded))
  await page.unroute(`**/api/v1/acquisitions/tasks/${task.id}/step?*`)
  assert.deepEqual((await call(page, `/api/v1/acquisitions/tasks/${task.id}/measurements`)).rows, [])
  checks.push('单次摄谱在途响应期间删除等待收尾，停止并移除异常样品')

  const createToggle = acquisitionPage.locator('.disclosure-toggle').filter({ hasText: /建立.*任务/ })
  if (await createToggle.getAttribute('aria-expanded') === 'false') await createToggle.click()
  await acquisitionPage.getByLabel('采样次数', { exact: true }).fill('1')
  await acquisitionPage.getByLabel('空白次数', { exact: true }).fill('0')
  const completedCreating = page.waitForResponse(/* 捕获正式名称测试任务。 */ (r) => r.url().endsWith('/acquisitions/tasks') && r.request().method() === 'POST')
  await acquisitionPage.getByRole('button', { name: '创建任务', exact: true }).click()
  let completed = await (await completedCreating).json()
  completed = await call(page, `/api/v1/acquisitions/tasks/${completed.id}/start`, {})
  while (completed.status !== 'completed') completed = await call(page, `/api/v1/acquisitions/tasks/${completed.id}/step`, {})
  await acquisitionPage.getByRole('button', { name: '刷新', exact: true }).click()
  const renamedName = '20261003009999999999'
  await acquisitionPage.getByTestId('acquisition-rename').locator('summary').click()
  await acquisitionPage.getByLabel('采集后样号长度', { exact: true }).selectOption('20')
  await acquisitionPage.getByPlaceholder('完整采集后输入正式样号').fill(renamedName)
  const renaming = page.waitForResponse(/* 验证完整名称保存。 */ (r) => r.url().endsWith('/rename') && r.request().method() === 'POST')
  await acquisitionPage.getByRole('button', { name: '保存名称', exact: true }).click()
  const renamed = await (await renaming).json()
  assert.equal(renamed.sample_name, renamedName)
  assert.equal(renamed.samples[0].result_sha256, completed.samples[0].result_sha256)
  checks.push('20位采集后命名与谱带哈希保持')
  checks.push(...await checkContractClosure(page, output))
  await writeFile(path.join(output, 'contract-additions.json'), JSON.stringify({ checks, task_id: task.id }, null, 2))
  return checks
}

// 在同一隔离页面执行方法区间、完整谱图、管理样适配及重新发布的真实链。
async function checkContractClosure(page, output) {
  const checks = []
  const line = JSON.parse(await readFile(fileURLToPath(new URL('./fixtures/station17-line.json', import.meta.url)), 'utf8'))
  const method = await call(page, '/api/v1/methods', { name: '合同软件闭环验证' })
  await call(page, `/api/v1/methods/${method.id}/lines`, line)
  await call(page, `/api/v1/methods/${method.id}`, { conditions: { frame_count: 4, dark_frame_count: 0,
    angle_exposures: [
      { angle_deg: 10, start_frame: 2, end_frame: 3, storage_mode: 'averaged' },
      { angle_deg: 20, start_frame: 3, end_frame: 4, storage_mode: 'full_interval' },
      { angle_deg: 30, start_frame: 1, end_frame: 2, storage_mode: 'averaged' }
    ] } }, 'PATCH')
  const published = await call(page, `/api/v1/methods/${method.id}/publish`, {})
  const ids = []
  for (let index = 0; index < 5; index++) {
    let task = await call(page, '/api/v1/acquisitions/tasks', {
      method_id: method.id, method_version: published.current_version, use_method_intervals: true,
      sample_name: index < 4 ? `S${index + 1}` : '管理样', sample_kind: index < 4 ? 'standard' : 'test',
      management_sample: index === 4, seed: 101 + index, pre_excitation_seconds: 0,
      repeat_count: index === 4 ? 2 : 1
    })
    task = await call(page, `/api/v1/acquisitions/tasks/${task.id}/start`, {})
    for (let step = 0; step < 50 && task.status !== 'completed'; step++)
      task = await call(page, `/api/v1/acquisitions/tasks/${task.id}/step`, {})
    assert.equal(task.status, 'completed')
    assert.ok(task.samples[0].bands.every(/* 检查每个角度只有配置区间的两帧进入结果。 */ band => band.burn_frame_count === 2))
    assert.deepEqual(task.samples[0].bands.map(/* 验证混合保存方式保留每个 CCD 的模式。 */ band => band.storage_mode),
      ['averaged', 'averaged', 'full_interval', 'averaged', 'averaged'])
    ids.push(...task.samples.map(/* 收集已固化采集输入。 */ sample => sample.id))
  }
  checks.push('方法逐转角区间实际进入样品谱带，平均与全区间混合保存')
  let run = await call(page, '/api/v1/analyses/runs', { acquisition_sample_ids: ids, slow_mode: false })
  run = await call(page, `/api/v1/analyses/runs/${run.id}/start`, {})
  for (let step = 0; step < 100 && run.status === 'running'; step++)
    run = await call(page, `/api/v1/analyses/runs/${run.id}/step`, {})
  assert.equal(run.status, 'completed')
  run = await call(page, `/api/v1/analyses/runs/${run.id}/quality/recalculate`, {})
  for (const group of run.quality.latest_snapshot.groups) {
    if (group.warnings.length) run = await call(page, `/api/v1/analyses/runs/${run.id}/quality/decisions`, {
      acquisition_task_id: group.acquisition_task_id, line_id: group.line_id, action: 'accept', reason: '软件验收复核重复预警' })
  }
  const lineId = run.curves.lines[0].line_id
  run = await call(page, `/api/v1/analyses/runs/${run.id}/curves/${lineId}/fit`, {})
  const oldHash = run.curves.lines[0].snapshots[0].result_sha256
  await navigate(page, 'analysis-tests', '样品分析', '.analysis-page')
  await page.locator('.analysis-run-list button').filter({ hasText: run.name }).first().click()
  await page.getByRole('button', { name: '谱图与测量', exact: true }).click()
  const plot = page.getByRole('region', { name: '分析完整谱图' })
  await plot.getByTestId('spectrum-plot').waitFor()
  const full = await call(page, `/api/v1/analyses/runs/${run.id}/spectra/0`)
  await plot.getByLabel('读取点位', { exact: true }).fill('901')
  assert.ok((await plot.getByLabel('任意点强度').innerText()).includes(full.bands[0].mean_points[900].toFixed(6)))
  const before = await plot.locator('path[data-curve-id]').first().getAttribute('d')
  await plot.getByRole('button', { name: '横向放大', exact: true }).click()
  const horizontal = await plot.locator('path[data-curve-id]').first().getAttribute('d')
  assert.notEqual(horizontal, before)
  await plot.getByRole('button', { name: '纵向放大', exact: true }).click()
  assert.notEqual(await plot.locator('path[data-curve-id]').first().getAttribute('d'), horizontal)
  await page.screenshot({ path: path.join(output, 'closure-analysis-spectrum.png'), fullPage: true })
  checks.push('分析页任意 CCD 点值读取及独立横纵缩放')
  await page.getByRole('button', { name: '标准点', exact: true }).click()
  const panel = page.getByLabel('管理样适配')
  await panel.getByLabel(/^给定含量/).fill('2.5')
  const adapting = page.waitForResponse(/* 等待真实适配结果。 */ response => response.url().endsWith('/actions') && response.request().method() === 'POST')
  await panel.getByRole('button', { name: '适配并保存标准强度', exact: true }).click()
  const adaptationResponse = await adapting
  run = await adaptationResponse.json()
  assert.equal(adaptationResponse.status(), 200, JSON.stringify(run))
  assert.equal(run.curves.lines[0].control_adaptations.length, 1)
  assert.equal(run.curves.lines[0].snapshots[0].result_sha256, oldHash)
  await page.screenshot({ path: path.join(output, 'closure-management-adaptation.png'), fullPage: true })
  run = await call(page, `/api/v1/analyses/runs/${run.id}/curves/${lineId}/fit`, {})
  const snapshot = run.curves.lines[0].snapshots.at(-1)
  run = await call(page, `/api/v1/analyses/runs/${run.id}/curves/${lineId}/publish`, { curve_snapshot_id: snapshot.id })
  const management = run.curves.results.find(/* 查询新曲线上的管理样浓度。 */ item => item.sample_name === '管理样' && item.curve_snapshot_id === snapshot.id)
  assert.ok(Math.abs(management.calculated_value - 2.5) < 0.0001)
  checks.push('管理样采集、质控、页面适配、留存修正及新曲线发布回算')
  let turns = await call(page, '/api/v1/hardware-acquisitions/tasks', { method_id: method.id, method_version: published.current_version })
  turns = await call(page, `/api/v1/hardware-acquisitions/tasks/${turns.id}/start`, {})
  for (let step = 0; step < 50 && turns.status !== 'completed'; step++)
    turns = await call(page, `/api/v1/hardware-acquisitions/tasks/${turns.id}/step`, {})
  assert.equal(turns.status, 'completed')
  assert.equal(turns.exposures.filter(/* 只统计已确认结果。 */ item => item.confirmed).length, 5)
  checks.push('自动转角完整方法计划与逐帧区间结果确认')
  return checks
}
