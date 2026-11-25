import assert from 'node:assert/strict'
import path from 'node:path'
import { readFile } from 'node:fs/promises'
import { call, navigate } from './contract_browser_support.mjs'

export async function checkSampleWorkbook(page, output) {
  await navigate(page, 'analysis-tests', '样号与样品队列', '.sample-queue-page')
  const queuePage = page.locator('.sample-queue-page')
  const selection = queuePage.getByLabel(/^选择样品队列/)
  const queue = await call(page, '/api/v1/sample-queues', {
    name: 'Excel 流程验证',
    items: [{ pre_name: '0011', repeats: 1 }, { pre_name: '固定-02', repeats: 2 }],
    name_length: 20,
  })
  await queuePage.getByRole('button', { name: '刷新', exact: true }).click()
  await selection.selectOption(String(queue.id))
  const input = queuePage.getByLabel('样品名', { exact: true })
  const add = queuePage.getByRole('button', { name: '添加样品', exact: true })
  const waitForUpdate = () => page.waitForResponse(response => response.ok()
    && response.url().endsWith(`/sample-queues/${queue.id}`) && response.request().method() === 'PATCH')
  const append = async name => {
    if (name !== undefined) await input.fill(name)
    const update = waitForUpdate()
    await add.click()
    return (await update).json()
  }
  await queuePage.getByLabel('重复次数', { exact: true }).fill('3')
  const first = await append('A-0007')
  assert.equal(first.items[2].pre_name, 'A-0007')
  assert.equal(first.items[2].repeats, 3)
  assert.equal(await input.inputValue(), 'A-0008')
  await append()
  await append('手填-0004')
  assert.equal(await input.inputValue(), '手填-0005')
  const grid = queuePage.getByRole('region', { name: '样号表格' })
  const cell = (row, column = 0) => grid.locator(`[data-sample-cell="${row}:${column}"]`)
  await cell(4).click()
  const handle = grid.getByRole('button', { name: '拖动填充样号' })
  const origin = await handle.boundingBox()
  const destination = await cell(6).boundingBox()
  const update = waitForUpdate()
  await page.mouse.move(origin.x + origin.width / 2, origin.y + origin.height / 2)
  await page.mouse.down()
  await page.mouse.move(destination.x + destination.width / 2, destination.y + destination.height / 2, { steps: 8 })
  assert.equal(await grid.locator('[data-sample-fill-preview]').count(), 2)
  await page.mouse.up()
  const filled = await (await update).json()
  const names = ['0011', '固定-02', 'A-0007', 'A-0008', '手填-0004', '手填-0005', '手填-0006']
  assert.deepEqual(filled.items.map(item => item.pre_name), names)
  assert.deepEqual(filled.items.slice(0, 2).map(item => item.id), queue.items.map(item => item.id))

  const firstBox = await cell(0).boundingBox(), lastBox = await cell(1, 1).boundingBox()
  await page.mouse.move(firstBox.x + 10, firstBox.y + 10)
  await page.mouse.down()
  await page.mouse.move(lastBox.x + 10, lastBox.y + 10, { steps: 8 })
  await page.mouse.up()
  assert.equal(await grid.locator('[aria-pressed="true"]').count(), 4)
  const clipboard = await cell(0).evaluate(element => {
    const data = new DataTransfer()
    element.dispatchEvent(new ClipboardEvent('copy', { bubbles: true, cancelable: true, clipboardData: data }))
    return { text: data.getData('text/plain'), html: data.getData('text/html') }
  })
  assert.equal(clipboard.text, '0011\t\r\n固定-02\t')
  assert.match(clipboard.html, /mso-number-format.*0011/)
  await page.screenshot({ path: path.join(output, 'sample-grid-selection.png') })

  const pendingDownload = page.waitForEvent('download')
  await queuePage.getByRole('button', { name: '导出 Excel' }).click()
  const download = await pendingDownload
  assert.match(download.suggestedFilename(), /\.xlsx$/)
  const workbook = path.join(output, 'sample-browser-roundtrip.xlsx')
  await download.saveAs(workbook)
  const imported = page.waitForResponse(response => response.ok() && response.url().endsWith('/sample-queues/import'))
  await queuePage.locator('input[type=file]').setInputFiles(workbook)
  const result = await (await imported).json()
  assert.deepEqual(result.items.map(item => item.pre_name), names)
  assert.equal(result.name_length, 20)
  assert.equal(result.items[2].repeats, 3)
  return { queueId: queue.id, importedId: result.id, workbook }
}

export async function checkAnalysisSampleWorkbook(page, output, { captureTaskId, methodId }) {
  const entries = [{ name: '0007', repeats: 2 }, { name: '', repeats: 0 }, { name: '=A+1', repeats: 1 }]
  const queueUrl = '/api/v1/sample-queues'
  const queue = await call(page, queueUrl, { name: '预录与分析 Excel 互读', name_length: 20,
    items: entries.map(item => ({ pre_name: item.name, repeats: item.repeats })) })
  await navigate(page, 'analysis-tests', '样品摄谱', '[data-testid="sample-acquisition-page"]')
  await page.locator(`[data-task-id="${captureTaskId}"]`).getByRole('button', { name: '进入摄谱' }).click()
  await page.getByRole('button', { name: '录入样品编号' }).click()
  const prerecord = page.getByRole('dialog', { name: '预录样号' })
  await prerecord.getByLabel(/^选择样品队列/).selectOption(String(queue.id))
  const downloadWorkbook = async (dialog, filename) => {
    const pending = page.waitForEvent('download')
    await dialog.getByRole('button', { name: '导出 Excel', exact: true }).click()
    const download = await pending
    assert.match(download.suggestedFilename(), /\.xlsx$/)
    const file = path.join(output, filename)
    await download.saveAs(file)
    return file
  }
  const importedFile = await downloadWorkbook(prerecord, 'analysis-from-prerecord.xlsx')
  await prerecord.getByRole('button', { name: '关闭', exact: true }).click()

  const sampleIds = []
  for (let index = 0; index < 4; index++) {
    const task = await call(page, '/api/v1/acquisitions/tasks', { task_kind: 'sample', name: `工作簿谱带 ${index + 1}`,
      sample_name: `原始${index + 1}`, sample_kind: 'normal', method_id: methodId, repeat_count: 1, seed: 72 + index })
    const endpoint = `/api/v1/acquisitions/tasks/${task.id}`
    let state = await call(page, endpoint + '/start', {})
    for (let steps = 0; steps < 8 && state.status !== 'completed'; steps++) {
      state = await call(page, endpoint + '/step', {})
    }
    assert.equal(state.status, 'completed')
    sampleIds.push(state.samples[0].id)
  }
  const method = await call(page, '/api/v1/methods/current')
  const runs = '/api/v1/analyses/runs'
  const original = await call(page, runs, { name: '预录名单在分析页核对', acquisition_sample_ids: sampleIds,
    method_version_id: method.referenced_version.id })
  const before = await call(page, runs)
  await navigate(page, 'analysis-tests', '样品分析', '.analysis-legacy-page')
  const selector = page.getByLabel('选择分析批次', { exact: true })
  await selector.selectOption(String(original.id))
  const open = () => page.getByRole('button', { name: '录入样品编号', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: '输入样号', exact: true })
  const cell = position => dialog.getByRole('button', { name: `样号位置 ${position}`, exact: true })
  const openFile = async () => {
    const pending = page.waitForResponse(response => response.ok() && response.url().endsWith('/sample-numbers/read'))
    await dialog.locator('input[type=file]').setInputFiles(importedFile)
    assert.deepEqual((await (await pending).json()).entries, entries)
    await cell(1).filter({ hasText: '0007' }).waitFor()
    assert.equal(await cell(1).getAttribute('title'), '0007 · 重复 2 次')
    assert.equal(await cell(2).innerText(), '空样')
    assert.equal(await cell(3).innerText(), '=A+1')
  }
  await open()
  await openFile()
  await dialog.getByRole('button', { name: '退出', exact: true }).click()
  await dialog.waitFor({ state: 'hidden' })
  assert.deepEqual(await call(page, runs), before)
  assert.deepEqual(await call(page, runs + '/' + original.id), original)

  await open()
  assert.equal(await cell(1).innerText(), '原始1')
  await openFile()
  const confirmed = page.waitForResponse(response => response.status() === 201 && response.url().endsWith(runs))
  await dialog.getByRole('button', { name: '确定', exact: true }).click()
  const copy = await (await confirmed).json()
  await dialog.waitFor({ state: 'hidden' })
  assert.notEqual(copy.id, original.id)
  assert.deepEqual(copy.input_snapshot.sample_numbering.entries, entries)
  assert.deepEqual(copy.samples.map(item => item.acquisition_sample_id), [sampleIds[0], sampleIds[1], sampleIds[3]])
  assert.deepEqual(await call(page, runs + '/' + original.id), original)
  await selector.selectOption(String(copy.id))
  await open()
  await page.screenshot({ path: path.join(output, 'analysis-sample-workbook.png') })
  const exportedFile = await downloadWorkbook(dialog, 'analysis-to-prerecord.xlsx')
  const exportedBytes = await readFile(exportedFile)
  const restored = await call(page, queueUrl + '/import', {
    filename: '分析返回预录样号.xlsx', content_base64: exportedBytes.toString('base64'),
  })
  assert.deepEqual(restored.items.map(item => ({ name: item.pre_name, repeats: item.repeats })), entries)
  assert.ok(await dialog.getByRole('button', { name: '保存样品号', exact: true }).isEnabled())
  await dialog.getByRole('button', { name: '退出', exact: true }).click()
  return { originalRunId: original.id, confirmedRunId: copy.id, entries, sourceSampleIds: sampleIds }
}
