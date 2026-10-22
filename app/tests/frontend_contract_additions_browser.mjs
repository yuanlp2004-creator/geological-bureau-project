import { createHash } from 'node:crypto'
import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { spawn, spawnSync } from 'node:child_process'
import { createServer } from 'node:net'
import { mkdtemp, mkdir, rm, cp, readdir, readFile, stat } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const app = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const frontend = path.join(app, 'frontend')
const require = createRequire(path.join(frontend, 'package.json'))
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright')
const data = await mkdtemp(path.join(tmpdir(), 'geospectrum-contract-'))
const output = path.join(app, '.local/test-runs/contract-sync-20261007')
await mkdir(output, { recursive: true })
const python = path.join(app, '.local/build-venv/Scripts/python.exe')
const children = []
let browser, page

// 使用独立回环端口，避免接管用户已有服务。
/* 处理队列数据或界面操作。 */ async function freePort() {
  const server = createServer()
  await new Promise(/* 处理当前数据或异步事件并返回结果。 */ resolve => server.listen(0, '127.0.0.1', resolve))
  const port = server.address().port
  await new Promise(/* 处理当前数据或异步事件并返回结果。 */ (resolve) => server.close(resolve))
  return port
}

// 直接启动目标进程，隐藏窗口，并保留启动失败原因。
/* 处理队列数据或界面操作。 */ function start(command, args, cwd, extraEnv) {
  const process = spawn(command, args, { cwd, windowsHide: true, env: { ...globalThis.process.env, ...extraEnv }, stdio: ['ignore', 'pipe', 'pipe'] })
  process.diagnostic = ''
  process.stdout.on(
    'data',
    /* 处理当前数据或异步事件并返回结果。 */ (chunk) => {
      process.diagnostic += chunk.toString()
    }
  )
  process.stderr.on(
    'data',
    /* 处理当前数据或异步事件并返回结果。 */ (chunk) => {
      process.diagnostic += chunk.toString()
    }
  )
  process.on(
    'error',
    /* 处理当前数据或异步事件并返回结果。 */ (error) => {
      process.launchError = error
    }
  )
  children.push(process)
  return process
}

// 等待当前测试服务，超时或启动失败明确报错。
/* 处理队列数据或界面操作。 */ async function ready(url, child) {
  for (let attempt = 0; attempt < 150; attempt++) {
    if (child.launchError) throw child.launchError
    if (child.exitCode !== null) throw new Error(child.diagnostic)
    try {
      if ((await fetch(url)).ok) return
    } catch {}
    await new Promise(/* 处理当前数据或异步事件并返回结果。 */ resolve => setTimeout(resolve, 100))
  }
  throw new Error(`Service not ready: ${url}\n${child.diagnostic}`)
}

// 使用源导航菜单进入当前已接入页面。
/* 处理队列数据或界面操作。 */ async function navigate(group, label, testId) {
  const trigger = page.locator(`[data-navigation-group="${group}"]`)
  if ((await trigger.getAttribute('aria-expanded')) !== 'true') await trigger.click()
  await page.getByRole('menuitem', { name: label }).click()
  await page.keyboard.press('Escape')
  await page.getByTestId(testId).waitFor()
}

try {
  const backendPort = await freePort(),
    frontendPort = await freePort()
  const env = { SPECTRUM_DATA_DIR: path.join(data, 'data'), PYTHONPYCACHEPREFIX: path.join(data, 'cache'), PYTHONUTF8: '1', PYTHONDONTWRITEBYTECODE: '1' }
  const backend = start(python, ['-B', '-m', 'uvicorn', 'backend.main:app', '--host', '127.0.0.1', '--port', String(backendPort), '--no-access-log'], app, env)
  await ready(`http://127.0.0.1:${backendPort}/health`, backend)
  const vite = start(process.execPath, [path.join(frontend, 'node_modules/vite/bin/vite.js'), '--host', '127.0.0.1', '--port', String(frontendPort), '--strictPort'], frontend, { VITE_API_TARGET: `http://127.0.0.1:${backendPort}` })
  const origin = `http://127.0.0.1:${frontendPort}`
  await ready(origin, vite)
  browser = await chromium.launch({ channel: 'msedge', headless: true })
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, acceptDownloads: true })
  page = await context.newPage()
  page.setDefaultTimeout(15000)
  const failures = [],
    requests = []
  page.on('pageerror', /* 处理当前数据或异步事件并返回结果。 */ error => failures.push(error.message))
  page.on(
    'request',
    /* 处理当前数据或异步事件并返回结果。 */ (request) => {
      if (request.url().startsWith(origin)) requests.push(new URL(request.url()).pathname)
    }
  )
  await page.goto(origin)
  await page.getByLabel('用户名', { exact: true }).fill('method-admin')
  await page.getByLabel('密码', { exact: true }).fill('method-password')
  await page.getByLabel('确认密码', { exact: true }).fill('method-password')
  await page.getByRole('button', { name: '创建管理员', exact: true }).click()
  await page.getByRole('heading', { name: '登录工作台' }).waitFor()
  await page.getByLabel('用户名', { exact: true }).fill('method-admin')
  await page.getByLabel('密码', { exact: true }).fill('method-password')
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await page.getByTestId('workspace').waitFor()

  const workspaceChecks = process.argv.includes('--workspace') ? await import('./frontend_workspace_rebuild_checks.mjs') : null
  if (workspaceChecks) await workspaceChecks.checkWorkspacePrerequisites(page)
  const { checkContractAdditions } = await import('./contract_additions_workflow.mjs')
  console.log(await checkContractAdditions(page, output))
  if (workspaceChecks) {
    const { call } = await import('./contract_browser_support.mjs')
    console.log(await workspaceChecks.checkWorkspaceLayout(page, call, output))
  }
  assert.deepEqual(failures, [])
  console.log('PASS: real contract additions UI and API.')
} catch (error) {
  for (const child of children)
    console.error('Test service:', child.exitCode, child.diagnostic.slice(-1800).replace(/access_token=[^" ]+/g, 'access_token=[redacted]'))
  if (page)
    await page.screenshot({ path: path.join(output, 'failure.png'), fullPage: true })
      .catch(/* 处理当前数据或异步事件并返回结果。 */ () => {})
  throw error
} finally {
  if (browser) await browser.close()
  for (const child of children.reverse()) {
    if (child.exitCode !== null) continue
    const exited = new Promise(/* 处理当前数据或异步事件并返回结果。 */ resolve => child.once('exit', resolve))
    child.kill()
    await exited
  }
  assert.ok(path.resolve(data).startsWith(path.resolve(tmpdir()) + path.sep), 'Cleanup must stay within the temporary directory')
  await rm(data, { recursive: true, force: true })
}
