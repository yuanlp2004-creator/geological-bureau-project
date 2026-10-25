import assert from 'node:assert/strict'
import { createWriteStream } from 'node:fs'
import { mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises'
import { createServer } from 'node:net'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { spawn, spawnSync } from 'node:child_process'
import { call, navigate } from './contract_browser_support.mjs'
import { leaveLegacyCapture } from './legacy_desk_test_support.mjs'

const app = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const work = path.join(app, '.local/diagnostics/legacy-capture-20261023')
const output = process.env.QA_LAYOUT_OUTPUT || path.join(work, 'browser')
await mkdir(output, { recursive: true })
const { chromium } = await import(pathToFileURL(path.join(process.env.PLAYWRIGHT_MODULE_PATH ||
  'C:/Users/Leo/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright', 'index.mjs')).href)
const result = { status: 'failed', checks: [], layouts: [], errors: [] }
const children = [], logs = []
let data, browser, page
const delay = ms => new Promise(resolve => setTimeout(resolve, ms))
async function port() {
  const server = createServer(); await new Promise(resolve => server.listen(0, '127.0.0.1', resolve))
  const value = server.address().port; await new Promise(resolve => server.close(resolve)); return value
}
function start(command, args, cwd, env, name) {
  const log = createWriteStream(path.join(output, `${name}.log`)); logs.push(log)
  const child = spawn(command, args, { cwd, env: { ...process.env, ...env }, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'] })
  child.stdout.pipe(log, { end: false }); child.stderr.pipe(log, { end: false }); children.push(child); return child
}
async function ready(url, child) {
  for (let i = 0; i < 240; i++) {
    assert.equal(child.exitCode, null, 'QA server exited early')
    try { if ((await fetch(url)).ok) return } catch {}
    await delay(100)
  }
  throw new Error(`QA server timed out: ${url}`)
}
async function task(base, id, predicate) {
  for (let i = 0; i < 160; i++) {
    const current = await call(page, `${base}/${id}`)
    assert.ok(!['failed', 'stopped'].includes(current.status), JSON.stringify(current.failure_message))
    if (predicate(current)) return current
    await delay(100)
  }
  throw new Error(`Task ${id} did not reach expected state`)
}
async function command(host, label, suffix) {
  const pending = page.waitForResponse(response => new URL(response.url()).pathname.endsWith(suffix)
    && response.request().method() === 'POST')
  await host.getByRole('button', { name: label, exact: true }).click()
  const response = await pending
  assert.equal(response.status(), 200, await response.text())
  return response.json()
}
async function go(mode, name) {
  await leaveLegacyCapture(page)
  const label = { sample: '样品摄谱', evaporation: '蒸发摄谱', dispersion: '色散摄谱' }[mode]
  const selector = mode === 'dispersion' ? '[data-testid="dispersion-page"][data-view="capture"]' : `[data-testid="${mode}-acquisition-page"]`
  await navigate(page, 'analysis-tests', label, selector)
  const host = page.locator(selector)
  if (name) await host.locator('.spectroscopy-task-list tr').filter({ hasText: name }).getByRole('button').click()
  for (const removed of ['单步', '连续采集', '停止连续', '开始'])
    assert.equal(await host.locator('.spectroscopy-controls').getByRole('button', { name: removed, exact: true }).count(), 0)
  assert.equal(await host.getByRole('button', { name: '试样摄谱', exact: true }).count(), 1)
  assert.equal(await host.getByRole('button', { name: '预热摄谱', exact: true }).count(), 1)
  return host
}
async function resize(layout) {
  if (process.env.QA_CDP) await page.evaluate(async ({ width, height }) =>
    window.__TAURI__.core.invoke('plugin:window|set_size', { value: { Logical: { width, height } } }), layout)
  else await page.setViewportSize({ width: layout.width, height: layout.height })
  await page.evaluate(({ theme }) => { document.documentElement.dataset.theme = theme }, layout)
}
async function screenshot(host, name) {
  for (const layout of [{ width: 1440, height: 1000, theme: 'light' }, { width: 1060, height: 680, theme: 'dark' }]) {
    await resize(layout)
    const bounds = await host.locator('.spectroscopy-controls').evaluate(el => {
      const box = el.getBoundingClientRect()
      return { control_width: box.width, right: box.right, bottom: box.bottom,
        overflow: document.documentElement.scrollWidth > innerWidth + 1 }
    })
    assert.equal(bounds.overflow, false)
    assert.ok(bounds.control_width > 0 && bounds.right <= layout.width + 1 && bounds.bottom <= layout.height)
    result.layouts.push({ name, ...layout, ...bounds })
    await page.screenshot({ path: path.join(output, `${name}-${layout.theme}.png`) })
    await host.locator('.spectroscopy-controls').screenshot({ path: path.join(output, `${name}-controls-${layout.theme}.png`) })
  }
  await resize({ width: 1440, height: 1000, theme: 'light' })
}
try {
  if (process.env.QA_CDP) {
    browser = await chromium.connectOverCDP(process.env.QA_CDP)
    for (let i = 0; i < 400 && !page; i++) {
      for (const candidate of browser.contexts().flatMap(context => context.pages()))
        if (await candidate.getByRole('heading', { name: '登录工作台' }).isVisible().catch(() => false)) { page = candidate; break }
      if (!page) await delay(100)
    }
    assert.ok(page, 'QA desktop renderer did not load')
  } else {
    data = await mkdtemp(path.join(tmpdir(), 'geospectrum-legacy-capture-'))
    const seeded = spawnSync('python', ['-X', 'utf8', 'tests/seed_s24_ui.py', data], { cwd: app, windowsHide: true, encoding: 'utf8' })
    assert.equal(seeded.status, 0, seeded.stderr)
    const backend = `http://127.0.0.1:${await port()}`, url = `http://127.0.0.1:${await port()}`
    await ready(`${backend}/health`, start('python', ['-m', 'uvicorn', 'backend.main:app', '--host', '127.0.0.1', '--port', new URL(backend).port], app, { SPECTRUM_DATA_DIR: data }, 'backend'))
    await ready(url, start(process.execPath, [path.join(app, 'frontend/node_modules/vite/bin/vite.js'), 'preview', '--host', '127.0.0.1', '--port', new URL(url).port, '--strictPort'], path.join(app, 'frontend'), { VITE_API_TARGET: backend }, 'preview'))
    browser = await chromium.launch({ headless: true, channel: 'msedge' })
    page = await browser.newPage({ viewport: { width: 1440, height: 1000 } }); await page.goto(url)
  }
  page.setDefaultTimeout(20000)
  page.on('pageerror', error => result.errors.push(error.message))
  await page.getByLabel('用户名', { exact: true }).fill('qa_admin')
  await page.getByLabel('密码', { exact: true }).fill('QaTest-2026!')
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await page.getByTestId('workspace').waitFor()
  if (process.env.QA_CDP) await page.evaluate(() => window.__TAURI__.core.invoke('plugin:window|hide'))
  const method = await call(page, '/api/v1/methods', { name: '手动激发验证', conditions: {
    exposure_mode: 'simple_mean', frame_count: 2,
    angle_exposures: [{ angle_deg: 0, storage_mode: 'averaged', start_frame: 1, end_frame: 2 }]
  } })
  const line = JSON.parse(await readFile(path.join(app, 'tests/fixtures/station17-line.json'), 'utf8'))
  await call(page, `/api/v1/methods/${method.id}/lines`, line)
  const published = await call(page, `/api/v1/methods/${method.id}/publish`, {})
  await call(page, `/api/v1/methods/${method.id}/open`, {})
  const queue = await call(page, '/api/v1/sample-queues', { name: '人工逐次摄谱', items: [{ pre_name: 'A001', repeats: 2 }, { pre_name: 'A002', repeats: 1 }] })
  const base = '/api/v1/acquisitions/tasks'
  const sample = await call(page, base, { name: '人工重复样品', method_id: method.id, method_version: published.current_version,
    queue_id: queue.id, queue_item_id: queue.items[0].id, burn_frame_count: 2, dark_frame_count: 1, pre_excitation_seconds: 0, sampling_period_seconds: 0.01 })
  await page.reload(); await page.locator('[data-navigation-group="analysis-tests"]').waitFor()
  let host = await go('sample', sample.name)
  const warmup = await command(host, '预热摄谱', `/${sample.id}/preheat`)
  const heated = await task(base, warmup.id, task => task.status === 'completed')
  await host.locator('.legacy-capture-desk[data-status="completed"]').waitFor()
  assert.equal(heated.sample_kind, 'preheat'); assert.equal(heated.samples[0].bands.length, 0)
  assert.equal((await call(page, `${base}/${sample.id}`)).status, 'draft')
  await screenshot(host, 'sample-preheat')
  result.checks.push('预热按钮自动完成独立摄谱，显示谱图，正式样品与重复计数保持')
  await command(host, '试样摄谱', `/${sample.id}/start`)
  const first = await task(base, sample.id, task => task.status === 'between_repeats')
  await host.locator('.legacy-capture-desk[data-status="between_repeats"]').waitFor()
  assert.equal(first.completed_repeats, 1); assert.equal(first.samples.length, 1)
  await delay(1000)
  assert.equal((await call(page, `${base}/${sample.id}`)).samples.length, 1)
  await screenshot(host, 'sample-waiting')
  await command(host, '试样摄谱', `/${sample.id}/start`)
  const final = await task(base, sample.id, task => task.status === 'completed')
  assert.equal(final.completed_repeats, 2); assert.equal(final.samples[0].result_sha256, first.samples[0].result_sha256)
  const linked = await call(page, `/api/v1/sample-queues/${queue.id}`)
  assert.equal(linked.items[0].spectrum_hash, final.result_sha256); assert.equal(linked.items[1].spectrum_hash, null)
  result.checks.push('每次点击只完成一次重复，等待时不自动激发；二次手动摄谱完成并关联队列，下一样品不自动启动')

  const evaporation = await call(page, base, { name: '人工蒸发摄谱', task_kind: 'evaporation', burn_frame_count: 2,
    dark_frame_count: 1, pre_excitation_seconds: 0, sampling_period_seconds: 0.01 })
  await page.reload(); await page.locator('[data-navigation-group="analysis-tests"]').waitFor()
  host = await go('evaporation', evaporation.name)
  const evapWarmup = await command(host, '预热摄谱', `/${evaporation.id}/preheat`)
  const evapHeat = await task(base, evapWarmup.id, task => task.status === 'completed')
  assert.equal(evapHeat.sample_kind, 'preheat'); assert.equal(evapHeat.samples[0].bands.length, 0)
  await host.locator('.legacy-capture-desk[data-status="completed"]').waitFor()
  await command(host, '试样摄谱', `/${evaporation.id}/start`)
  const evapFinal = await task(base, evaporation.id, task => task.status === 'completed')
  assert.equal(evapFinal.completed_repeats, 1); assert.ok(evapFinal.samples[0].bands.length)
  await host.locator('.legacy-capture-desk[data-status="completed"]').waitFor(); await screenshot(host, 'evaporation-completed')
  result.checks.push('蒸发预热不生成正式谱带，试样摄谱一次自动保存完整实验')

  const dispersionBase = '/api/v1/dispersion/tasks'
  const dispersion = await call(page, dispersionBase, { name: '人工色散摄谱', frame_count: 2, dark_frame_count: 1, pre_excitation_seconds: 0 })
  await page.reload(); await page.locator('[data-navigation-group="analysis-tests"]').waitFor()
  host = await go('dispersion', dispersion.name)
  const toolbarGeometry = () => host.locator('.legacy-main-toolbar').evaluate(element => {
    const outer = element.getBoundingClientRect()
    return [...element.querySelectorAll('button')].map(button => { const r = button.getBoundingClientRect();
      return { name: button.getAttribute('aria-label'), x: r.x - outer.x, y: r.y - outer.y, width: r.width, height: r.height } })
  })
  const formalToolbar = await toolbarGeometry()
  const dispWarmup = await command(host, '预热摄谱', `/${dispersion.id}/preheat`)
  const dispHeat = await task(dispersionBase, dispWarmup.id, task => task.status === 'completed')
  assert.equal(dispHeat.condition.preheat, true); assert.equal(dispHeat.calibrations.length, 0)
  await host.locator('.legacy-capture-desk[data-status="completed"]').waitFor()
  const preheatToolbar = await toolbarGeometry()
  assert.deepEqual(preheatToolbar.map(button => button.name), formalToolbar.map(button => button.name))
  for (let index = 0; index < formalToolbar.length; index++) {
    for (const key of ['x', 'y', 'width', 'height']) assert.ok(Math.abs(formalToolbar[index][key] - preheatToolbar[index][key]) <= .5)
  }
  for (const name of ['增加谱线', '删除所选谱线', '校正谱线', '拟合曲线']) {
    assert.equal(await host.getByRole('button', { name, exact: true }).isVisible(), true)
    assert.equal(await host.getByRole('button', { name, exact: true }).isDisabled(), true)
  }
  const preheatDesk = await host.locator('.spectroscopy-console').boundingBox()
  await page.screenshot({ path: path.join(output, 'dispersion-preheat-buttons.png'), clip: { x: preheatDesk.x, y: preheatDesk.y, width: preheatDesk.width, height: 180 } })
  await page.screenshot({ path: path.join(output, 'dispersion-preheat.png') })
  result.layouts.push({ name: 'dispersion-preheat-toolbar', width: 1440, height: 1000, theme: 'light', formalToolbar, preheatToolbar })
  await command(host, '试样摄谱', `/${dispersion.id}/start`)
  await task(dispersionBase, dispersion.id, task => task.status === 'completed')
  await host.locator('.legacy-capture-desk[data-status="completed"]').waitFor(); await screenshot(host, 'dispersion-completed')
  result.checks.push('色散预热与正式摄谱分开，点击一次自动完成；三个入口均无单步和连续采集')

  const stoppedTask = await call(page, base, { name: '停止竞态检查', method_id: method.id, burn_frame_count: 20,
    dark_frame_count: 1, pre_excitation_seconds: 0, sampling_period_seconds: 0.01 })
  await page.reload(); await page.locator('[data-navigation-group="analysis-tests"]').waitFor()
  host = await go('sample', stoppedTask.name)
  let release, captured
  const held = new Promise(resolve => { release = resolve }), seen = new Promise(resolve => { captured = resolve })
  const pattern = `**/acquisitions/tasks/${stoppedTask.id}/step?*`
  await page.route(pattern, async route => {
    const response = await route.fetch(); captured(); await held; await route.fulfill({ response })
  })
  await command(host, '试样摄谱', `/${stoppedTask.id}/start`); await seen
  const stopping = command(host, '停止摄谱', `/${stoppedTask.id}/stop`)
  await delay(200); release(); await stopping; await page.unroute(pattern)
  const stopped = await call(page, `${base}/${stoppedTask.id}`)
  assert.equal(stopped.status, 'stopped'); assert.equal(stopped.result_sha256, null)
  assert.ok((await call(page, `${base}/${stoppedTask.id}/frames`)).length > 0)
  await delay(500); assert.equal((await call(page, `${base}/${stoppedTask.id}`)).status, 'stopped')
  result.checks.push('帧响应延迟时停止仍可收尾，原始帧保留，停止后没有自动继续')
  assert.deepEqual(result.errors, [])
  result.status = 'passed'
} catch (error) {
  result.error = error.stack
  if (page) await page.screenshot({ path: path.join(output, 'failure.png') }).catch(() => {})
  process.exitCode = 1
} finally {
  await writeFile(path.join(output, 'result.json'), JSON.stringify(result, null, 2))
  if (process.env.QA_CDP && page) await page.evaluate(() => window.__TAURI__.core.invoke('plugin:window|close')).catch(() => {})
  await browser?.close().catch(() => {})
  for (const child of children) if (child.exitCode === null) {
    child.kill(); await new Promise(resolve => { child.once('exit', resolve); setTimeout(resolve, 3000) })
  }
  for (const log of logs) log.end()
  if (data) {
    assert.equal(path.dirname(path.resolve(data)), path.resolve(tmpdir()))
    assert.ok(path.basename(data).startsWith('geospectrum-legacy-capture-'))
    await rm(data, { recursive: true, force: true, maxRetries: 5 })
  }
  console.log(JSON.stringify({ status: result.status, checks: result.checks.length, layouts: result.layouts.length, error: result.error }))
}
