import assert from 'node:assert/strict'
import path from 'node:path'
import { call, navigate } from './contract_browser_support.mjs'

const defaultsPath = '/api/v1/analyses/intensity-output/defaults'
const choices = {
  save_intensity: true,
  print_intensity: true,
  print_to_text: true,
  save_positions: true,
}

export async function checkAnalysisCalculationOutput(page, fixture, folder, leaveReview = false) {
  const optionsPath = '/api/v1/analyses/options'
  const onlySave = { ...choices, print_intensity: false, print_to_text: false, save_positions: false }
  await call(page, '/api/v1/methods/current', { method_id: fixture.method_id })
  await call(page, defaultsPath, onlySave, 'PUT')
  const sample = (await call(page, optionsPath)).samples.find(item => item.id === fixture.sample_id)
  assert.ok(sample)
  await page.addInitScript(() => {
    const bridge = window.chrome.webview
    const post = bridge.postMessage
    window.analysisCalculationFiles = []
    window.analysisRestoreFileDialog = () => { bridge.postMessage = post }
    bridge.postMessage = function (message) {
      const request = typeof message === 'string' ? JSON.parse(message) : message
      if (request.cmd !== 'save_export_file') return post.call(bridge, message)
      window.analysisCalculationFiles.push(request.payload)
      if (request.payload.fileName.endsWith('.txt') && window.analysisFailNextTextSave) {
        window.analysisFailNextTextSave = false
        queueMicrotask(() => window.__TAURI_INTERNALS__.runCallback(request.error, '示例：文本保存失败'))
      } else {
        queueMicrotask(() => window.__TAURI_INTERNALS__.runCallback(request.callback, request.payload.fileName))
      }
    }
  })
  const host = page.locator('.analysis-legacy-page')
  const batch = host.getByLabel('选择分析批次', { exact: true })
  const calculation = page.getByRole('dialog', { name: '分析计算', exact: true })
  const curve = host.getByRole('heading', { name: '标准曲线', exact: true })
  const print = calculation.getByRole('checkbox', { name: '打印强度', exact: true })
  const text = calculation.getByRole('checkbox', { name: '打印到文本', exact: true })
  const save = calculation.getByRole('checkbox', { name: '保存强度', exact: true })
  const position = calculation.getByRole('checkbox', { name: '保存校正波长', exact: true })
  const remember = calculation.getByRole('checkbox', { name: '默认', exact: true })
  const confirm = calculation.getByRole('button', { name: '确定', exact: true })

  async function measure(name) {
    const run = await call(page, '/api/v1/analyses/runs', {
      name, acquisition_sample_ids: [sample.id], method_version_id: sample.method_version_id,
      calculation_profile: 'legacy_2_0_2', slow_mode: false,
    })
    await page.reload()
    await navigate(page, 'analysis-tests', '样品分析', '.analysis-legacy-page')
    await batch.locator(`option[value="${run.id}"]`).waitFor({ state: 'attached' })
    if (await batch.inputValue() !== String(run.id)) await batch.selectOption(String(run.id))
    await host.getByRole('button', { name: '开始测量', exact: true }).click()
    await calculation.waitFor()
    assert.equal(await curve.isVisible(), false)
    return run
  }

  const run = await measure('强度输出选项核对')
  const output = url => url.pathname.endsWith(`/analyses/runs/${run.id}/intensity-output`)
  let requests = 0
  let succeeded = false
  let allowOutput
  const released = new Promise(resolve => { allowOutput = resolve })
  const intercepted = async route => {
    requests++
    const body = route.request().postDataJSON()
    assert.deepEqual(body, choices)
    await released
    // Use the real sidecar for file bytes and the method draft. The print spooler is controlled.
    const response = await route.fetch({ postData: { ...body, print_intensity: false } })
    const result = await response.json()
    succeeded = response.ok()
    if (!succeeded) { await route.fulfill({ response }); return }
    assert.ok(result.method_draft)
    await route.fulfill({ response, json: {
      ...result, print_job: { status: 'queued' },
      files: [...result.files, { filename: 'printed.pdf', media_type: 'application/pdf', content_base64: 'JVBERg==' }],
    } })
  }
  await page.route(output, intercepted)
  assert.equal(await save.isChecked(), true)
  assert.equal(await remember.isChecked(), false)
  await print.check()
  await text.check()
  await position.check()
  await remember.check()
  await page.screenshot({ path: path.join(folder, 'analysis-calculation-outputs.png') })
  await page.evaluate(() => { window.analysisFailNextTextSave = true })
  await confirm.click()
  await calculation.getByRole('button', { name: '正在处理…', exact: true }).waitFor()
  assert.equal(await curve.isVisible(), false)
  await page.keyboard.press('Escape')
  assert.equal(await calculation.isVisible(), true)
  allowOutput()
  const error = calculation.getByRole('alert')
  await error.waitFor()
  assert.equal(succeeded, true, await error.textContent())
  assert.match(await error.textContent(), /文本保存失败/)
  await confirm.click()
  await curve.waitFor()
  assert.equal(requests, 1)
  const saved = await page.evaluate(() => window.analysisCalculationFiles)
  assert.deepEqual(saved.map(file => path.extname(file.fileName)), ['.json', '.txt', '.txt'])
  const intensity = JSON.parse(Buffer.from(saved[0].bytes).toString('utf8'))
  assert.equal(intensity.run_id, run.id)
  assert.match(Buffer.from(saved[2].bytes).toString('utf8'), /强度编号/)
  await page.unroute(output, intercepted)
  assert.deepEqual((await call(page, optionsPath)).intensity_output_defaults, choices)
  await page.screenshot({ path: path.join(folder, 'standard-curve-after-outputs.png') })

  const cancelled = await measure('默认选项与取消核对')
  for (const option of [print, text, save, position]) assert.equal(await option.isChecked(), true)
  assert.equal(await remember.isChecked(), false)
  await save.uncheck()
  await remember.check()
  await calculation.getByRole('button', { name: '取消', exact: true }).click()
  await calculation.waitFor({ state: 'hidden' })
  assert.equal(await curve.isVisible(), false)
  assert.deepEqual((await call(page, optionsPath)).intensity_output_defaults, choices)
  assert.equal(await page.evaluate(() => window.analysisCalculationFiles.length), 0)
  assert.equal((await call(page, '/api/v1/analyses/runs/' + cancelled.id)).status, 'completed')

  await measure('不输出直接计算核对')
  for (const option of [print, text, save, position]) await option.uncheck()
  const noOutput = []
  const observe = request => { if (request.url().endsWith('/intensity-output')) noOutput.push(request.url()) }
  page.on('request', observe)
  await confirm.click()
  await curve.waitFor()
  page.off('request', observe)
  assert.deepEqual(noOutput, [])
  if (leaveReview) {
    await call(page, defaultsPath, onlySave, 'PUT')
    await measure('手动审阅示例')
    await page.evaluate(() => window.analysisRestoreFileDialog())
    await page.screenshot({ path: path.join(folder, 'analysis-calculation-review.png') })
  }
  return [
    '五个选项及默认值正确，输出结束后才进入标准曲线',
    '真实 JSON、文本和波长草稿通过，打印经受控响应验证',
    '文件失败后续传剩余文件，未重复提交输出，处理中忽略 Esc',
    '取消不会保存默认值，全部取消勾选可直接打开曲线',
  ]
}
