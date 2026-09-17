/** R4 browser integration: isolated API server, real downloads, and a controlled Tauri bridge. */
import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { spawn, spawnSync } from 'node:child_process'
import { createServer } from 'node:net'
import { mkdtemp, mkdir, readFile, rm, writeFile } from 'node:fs/promises'
import { createWriteStream } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const require = createRequire(import.meta.url)
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright')
const app = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const output = process.env.API_BROWSER_OUTPUT || path.join(app, '.local/test-runs/api-browser')
await mkdir(output, { recursive: true })
const data = await mkdtemp(path.join(tmpdir(), 'geospectrum-r4-'))
const children = [], logs = [], checks = []
let browser, activePage

async function freePort() {
  const server = createServer()
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve))
  const port = server.address().port
  await new Promise(resolve => server.close(resolve))
  return port
}

function start(command, args, cwd, env, name) {
  const log = createWriteStream(path.join(output, `${name}.log`))
  logs.push(log)
  const child = spawn(command, args, { cwd, env: { ...process.env, ...env }, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'] })
  child.stdout.pipe(log, { end: false }); child.stderr.pipe(log, { end: false })
  child.on('error', error => { child.launchError = error })
  children.push(child)
  return child
}

async function ready(url, child) {
  for (let attempt = 0; attempt < 150; attempt++) {
    if (child.launchError) throw child.launchError
    if (child.exitCode !== null) throw new Error(`Test server exited: ${url}`)
    try { if ((await fetch(url)).ok) return } catch {}
    await new Promise(resolve => setTimeout(resolve, 100))
  }
  throw new Error(`Test server timed out: ${url}`)
}

try {
  const backendPort = await freePort(), frontendPort = await freePort()
  const backendUrl = `http://127.0.0.1:${backendPort}`, url = `http://127.0.0.1:${frontendPort}`
  const backend = start(process.env.GEOSPECTRUM_PYTHON || 'python', ['-m', 'uvicorn', 'backend.main:app', '--host', '127.0.0.1', '--port', String(backendPort)], app, { SPECTRUM_DATA_DIR: data }, 'backend')
  await ready(`${backendUrl}/health`, backend)
  const vite = start(process.execPath, [path.join(app, 'frontend/node_modules/vite/bin/vite.js'), '--host', '127.0.0.1', '--port', String(frontendPort), '--strictPort'], path.join(app, 'frontend'), { VITE_API_TARGET: backendUrl }, 'vite')
  await ready(url, vite)
  browser = await chromium.launch({ headless: true, channel: process.env.PLAYWRIGHT_CHANNEL || 'msedge' })
  const context = await browser.newContext({ acceptDownloads: true })
  const page = await context.newPage()
  activePage = page
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  await page.goto(url)
  await page.getByRole('heading', { name: '初始化本地管理员' }).waitFor()
  await page.getByLabel('用户名', { exact: true }).fill('r4-admin')
  await page.getByLabel('密码', { exact: true }).fill('r4-test-password')
  await page.getByLabel('确认密码', { exact: true }).fill('r4-test-password')
  await page.getByRole('button', { name: '创建管理员' }).click()
  await page.getByRole('heading', { name: '登录工作台' }).waitFor()
  await page.getByLabel('密码', { exact: true }).fill('wrong-password')
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await page.getByText('用户名或密码错误', { exact: true }).waitFor()
  await page.getByLabel('密码', { exact: true }).fill('r4-test-password')
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await page.waitForFunction(() => !!sessionStorage.getItem('geospectrum.token') && !document.querySelector('.auth-form'))
  checks.push('real UI bootstrap, invalid password and successful login')

  const business = await page.evaluate(async () => {
    const boundary = await import('/src/api/index.ts')
    const token = sessionStorage.getItem('geospectrum.token')
    const created = await boundary.api.createMethod(token, { name: 'R4-browser-method' })
    const methods = await boundary.api.methods(token)
    const settings = await boundary.api.methodPrintSettings(token)
    const pdf = await boundary.api.methodPdf(token, created.id, null, settings)
    window.__r4Pdf = pdf.blob
    let badSettings
    try { await boundary.api.saveSettings(token, { display: { density: 'invalid' } }) }
    catch (e) { badSettings = { typed: e instanceof boundary.ApiError, status: e.status, code: e.code } }
    let noPicker
    try { await boundary.selectLegacyDirectory() } catch(e) { noPicker = e.message }
    return { listed: methods.some(m => m.id === created.id), pdfSize: pdf.blob.size, pageCount: pdf.pageCount,
      pdfHeader: await pdf.blob.slice(0, 5).text(), badSettings, noPicker, ws: await boundary.eventSocketUrl(token) }
  })
  assert.equal(business.listed, true)
  assert.ok(business.pdfSize > 100 && business.pageCount > 0)
  assert.equal(business.pdfHeader, '%PDF-')
  assert.deepEqual(business.badSettings, { typed: true, status: 422, code: 'request_validation_failed' })
  assert.match(business.noPicker, /浏览器模式/)
  assert.ok(business.ws.startsWith(`ws://127.0.0.1:${frontendPort}/ws/events?access_token=`))
  checks.push('real method create/list/PDF response; structured 422; browser directory fallback; WebSocket URL')

  for (const kind of ['pdf', 'csv']) {
    const downloadPromise = page.waitForEvent('download')
    await page.evaluate(async kind => {
      const { saveFile } = await import('/src/api/index.ts')
      const blob = kind === 'pdf' ? window.__r4Pdf : new Blob(['样品,数值\nA,1\n'], { type: 'text/csv' })
      await saveFile(blob, `r4.${kind}`)
    }, kind)
    const download = await downloadPromise
    assert.equal(download.suggestedFilename(), `r4.${kind}`)
    const bytes = await readFile(await download.path())
    if (kind === 'pdf') assert.equal(bytes.subarray(0, 5).toString(), '%PDF-')
    else assert.equal(bytes.toString('utf8'), '样品,数值\nA,1\n')
  }
  checks.push('real browser PDF and UTF-8 CSV downloads with byte verification')
  if (process.argv.includes('--pages')) {
    const { checkPages } = await import('./frontend_pages_checks.mjs')
    await checkPages(page, checks)
  }

  await page.route('**/api/v1/settings', route => route.fulfill({ status: 502, contentType: 'text/plain', body: 'temporary upstream failure' }))
  const plainError = await page.evaluate(async () => {
    const { api, ApiError } = await import('/src/api/index.ts')
    try { await api.settings(sessionStorage.getItem('geospectrum.token')) }
    catch(e) { return { typed: e instanceof ApiError, status: e.status, message: e.message } }
  })
  assert.deepEqual(plainError, { typed: true, status: 502, message: 'temporary upstream failure' })
  await page.unroute('**/api/v1/settings')
  const browserFailure = await page.evaluate(async () => {
    const { api } = await import('/src/api/index.ts')
    const nativeFetch = window.fetch
    let attempts = 0
    window.fetch = async () => { attempts++; throw new TypeError('browser connection failure') }
    try { await api.health() } catch(e) { return { attempts, message: e.message } }
    finally { window.fetch = nativeFetch }
  })
  assert.deepEqual(browserFailure, { attempts: 1, message: 'browser connection failure' })
  const logout = await page.evaluate(async () => {
    const { api, ApiError } = await import('/src/api/index.ts')
    const token = sessionStorage.getItem('geospectrum.token')
    const empty = await api.logout(token)
    try { await api.me(token) } catch(e) { return { empty: empty === undefined, status: e.status, typed: e instanceof ApiError } }
  })
  assert.deepEqual(logout, { empty: true, status: 401, typed: true })
  await page.reload()
  await page.getByRole('heading', { name: '登录工作台' }).waitFor()
  assert.equal(await page.evaluate(() => sessionStorage.getItem('geospectrum.token')), null)
  checks.push('plain HTTP error, no browser retry, 204 logout, 401 rejection and UI session recovery')
  assert.deepEqual(errors, [])

  // Controlled bridge tests exercise client/native command mapping, not an actual OS dialog.
  const desktop = await browser.newContext()
  await desktop.addInitScript(() => {
    window.__r4NativeCalls = []
    window.__TAURI__ = { core: { invoke: async (command, args) => {
      window.__r4NativeCalls.push({ command, args })
      if (command === 'runtime_config') return { api_base: location.origin, process_key: 'r4-desktop-key' }
      if (window.__r4NativeError) throw new Error('native operation failed')
      return window.__r4NativeResult ?? null
    } } }
  })
  const nativePage = await desktop.newPage()
  await nativePage.goto(url)
  await nativePage.getByRole('heading', { name: '登录工作台' }).waitFor()
  const result = await nativePage.evaluate(async () => {
    const boundary = await import('/src/api/index.ts')
    const nativeFetch = window.fetch
    let retries = 0, header
    window.fetch = async (input, init) => {
      header = init.headers['X-GeoSpectrum-Process-Key']
      if (++retries < 3) throw new TypeError('test transient connection failure')
      return nativeFetch(input, init)
    }
    try { await boundary.api.health() } finally { window.fetch = nativeFetch }
    const ws = await boundary.eventSocketUrl('sample token')
    const cancelDirectory = await boundary.selectLegacyDirectory()
    const cancelSave = await boundary.savePdfFile(new Blob(['%PDF-test']), 'test.pdf')
    window.__r4NativeResult = 'C:\\selected'
    const selected = await boundary.selectLegacyDirectory()
    window.__r4NativeError = true
    let failure
    try { await boundary.selectLegacyDirectory() } catch(e) { failure = e.message }
    return { header, retries, ws, cancelDirectory, cancelSave, selected, failure, calls: window.__r4NativeCalls }
  })
  assert.equal(result.header, 'r4-desktop-key')
  assert.equal(result.retries, 3)
  assert.equal(new URL(result.ws).searchParams.get('process_key'), 'r4-desktop-key')
  assert.equal(new URL(result.ws).searchParams.get('access_token'), 'sample token')
  assert.equal(result.cancelDirectory, null)
  assert.equal(result.cancelSave, null)
  assert.equal(result.selected, 'C:\\selected')
  assert.equal(result.failure, 'native operation failed')
  assert.equal(result.calls.filter(c => c.command === 'runtime_config').length, 1)
  const saved = result.calls.find(c => c.command === 'save_export_file')
  assert.deepEqual(saved.args, { fileName: 'test.pdf', contentType: 'application/pdf', bytes: [...Buffer.from('%PDF-test')] })
  checks.push('controlled Tauri bridge: shared handshake, key, retry, file bytes, picker/save cancellation and failure')
  await writeFile(path.join(output, 'result.json'), JSON.stringify({ status: 'passed', checks, nativeDialogTested: false }, null, 2))
  console.log(JSON.stringify({ status: 'passed', checks, nativeDialogTested: false }, null, 2))
} catch (error) {
  if (activePage) {
    await writeFile(path.join(output, 'failure.html'), await activePage.content()).catch(() => {})
    await activePage.screenshot({ path: path.join(output, 'failure.png') }).catch(() => {})
  }
  throw error
} finally {
  if (browser) await browser.close().catch(() => {})
  for (const child of children.reverse()) {
    if (child.exitCode !== null || !child.pid) continue
    if (process.platform === 'win32') spawnSync('taskkill', ['/PID', String(child.pid), '/T', '/F'], { windowsHide: true, stdio: 'ignore' })
    else child.kill('SIGTERM')
  }
  logs.forEach(log => log.end())
  assert.equal(path.dirname(path.resolve(data)), path.resolve(tmpdir()))
  assert.ok(path.basename(data).startsWith('geospectrum-r4-'))
  await rm(data, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 })
}
