import assert from 'node:assert/strict'
import { spawn, spawnSync } from 'node:child_process'
import { generateKeyPairSync } from 'node:crypto'
import { mkdir, mkdtemp, rm, writeFile } from 'node:fs/promises'
import { createRequire } from 'node:module'
import { createServer } from 'node:net'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { call, navigate } from './contract_browser_support.mjs'

const app = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const require = createRequire(import.meta.url)
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright')
const python = process.env.GEOSPECTRUM_PYTHON || 'python'
const testRoot = await mkdtemp(path.join(tmpdir(), 'geospectrum-deployment-access-'))
const children = []
const checks = []
const password = 'Isolated-Browser-Only!'
let browser

async function freePort() {
  const socket = createServer()
  await new Promise(resolve => socket.listen(0, '127.0.0.1', resolve))
  const port = socket.address().port
  await new Promise(resolve => socket.close(resolve))
  return port
}

function start(executable, args, cwd, env) {
  const child = spawn(executable, args, { cwd, windowsHide: true, env: { ...process.env, ...env } })
  let diagnostic = ''
  child.stdout.on('data', chunk => { diagnostic += chunk.toString() })
  child.stderr.on('data', chunk => { diagnostic += chunk.toString() })
  child.on('error', error => { diagnostic += error.message })
  children.push(child)
  return () => diagnostic
}

async function ready(url, diagnostic) {
  for (let attempt = 0; attempt < 150; attempt++) {
    try { if ((await fetch(url)).ok) return } catch {}
    await new Promise(resolve => setTimeout(resolve, 150))
  }
  throw new Error(`Service unavailable: ${url}\n${diagnostic()}`)
}

async function submitLogin(page, username) {
  await page.getByLabel('用户名', { exact: true }).fill(username)
  await page.getByLabel('密码', { exact: true }).fill(password)
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await page.getByTestId('workspace').waitFor()
}

try {
  const data = path.join(testRoot, 'data')
  const { privateKey, publicKey } = generateKeyPairSync('ed25519')
  const privateKeyFile = path.join(testRoot, 'isolated-test.pem')
  await writeFile(privateKeyFile, privateKey.export({ type: 'pkcs8', format: 'pem' }))
  const key = publicKey.export({ type: 'spki', format: 'der' }).subarray(-32).toString('base64')
  const environment = { SPECTRUM_DATA_DIR: data, GEOSPECTRUM_ACTIVATION_PUBLIC_KEY: key, PYTHONUTF8: '1' }
  const seed = spawnSync(python, ['-B', '-c',
    'import json,sys; from pathlib import Path; from backend.db import Database; from tests.test_s16_analysis import _seed; print(json.dumps(_seed(Database(Path(sys.argv[1]) / "geospectrum.sqlite3"), complete_conditions=True)))',
    data], { cwd: app, env: { ...process.env, ...environment }, encoding: 'utf8', windowsHide: true })
  assert.equal(seed.status, 0, seed.stderr)
  const [version, samples] = JSON.parse(seed.stdout)
  const backendUrl = `http://127.0.0.1:${await freePort()}`
  const frontendPort = await freePort()
  const origin = `http://127.0.0.1:${frontendPort}`
  const backend = start(python, ['-B', '-m', 'uvicorn', 'backend.main:app', '--host', '127.0.0.1',
    '--port', new URL(backendUrl).port, '--no-access-log'], app, environment)
  await ready(`${backendUrl}/health`, backend)
  const frontend = path.join(app, 'frontend')
  const vite = start(process.execPath, [path.join(frontend, 'node_modules/vite/bin/vite.js'),
    '--host', '127.0.0.1', '--port', String(frontendPort), '--strictPort'], frontend, { VITE_API_TARGET: backendUrl })
  await ready(origin, vite)

  browser = await chromium.launch({ channel: 'msedge', headless: true })
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
  const admin = await context.newPage()
  const errors = []
  admin.on('response', async response => {
    if (response.status() >= 400 && response.url().startsWith(origin))
      errors.push(`${response.status()} ${new URL(response.url()).pathname}`)
  })
  admin.on('pageerror', error => errors.push(error.message))
  await admin.goto(origin)
  await admin.getByLabel('用户名', { exact: true }).fill('isolation-admin')
  await admin.getByLabel('密码', { exact: true }).fill(password)
  await admin.getByLabel('确认密码').fill(password)
  await admin.getByRole('button', { name: '创建管理员', exact: true }).click()
  await admin.getByRole('heading', { name: '登录工作台' }).waitFor()
  await submitLogin(admin, 'isolation-admin')

  try {
    await navigate(admin, 'help', '关于软件', '[data-testid="about-software"]')
  } catch (error) {
    throw new Error(`Navigation failed: ${errors.join('; ')}\n${(await admin.locator('body').innerText()).slice(0, 600)}`, { cause: error })
  }
  const activation = admin.getByRole('region', { name: '软件激活' })
  await activation.getByText('待激活', { exact: true }).waitFor()
  for (const days of [1, 2]) {
    const signed = path.join(testRoot, `activation-${days}.json`)
    const signing = spawnSync(python, ['-B', 'tools/sign_activation.py', '--private-key', privateKeyFile,
      '--installation-id', await activation.getByLabel('安装标识').inputValue(),
      '--expires-at', new Date(Date.now() + 86400000 * days).toISOString(), '--output', signed],
    { cwd: app, encoding: 'utf8', windowsHide: true })
    assert.equal(signing.status, 0, signing.stderr)
    const response = admin.waitForResponse(response => response.url().endsWith('/api/v1/activation')
      && response.request().method() === 'PUT')
    await activation.getByLabel('导入激活或续期文件').setInputFiles(signed)
    assert.equal((await response).status(), 200)
    await activation.getByText('已激活', { exact: true }).waitFor()
  }
  checks.push('管理员界面依次导入隔离首份授权和续期文件')

  const sharing = admin.getByRole('region', { name: '模块远程诊断' })
  await sharing.getByText('诊断已关闭', { exact: true }).waitFor()
  await sharing.getByRole('button', { name: '开启诊断共享' }).click()
  await sharing.getByText('诊断已开启', { exact: true }).waitFor()
  const firstCheckedAt = (await call(admin, '/api/v1/support/session')).checked_at
  await sharing.getByRole('button', { name: '刷新共享快照' }).click()
  await sharing.getByText('共享快照已更新').waitFor()
  assert.notEqual((await call(admin, '/api/v1/support/session')).checked_at, firstCheckedAt)
  await sharing.getByRole('button', { name: '结束诊断共享' }).click()
  await sharing.getByText('诊断已关闭', { exact: true }).waitFor()
  checks.push('管理员界面开启、刷新并结束远程诊断')

  await navigate(admin, 'system', '用户与权限', '.auth-page')
  const roles = await call(admin, '/api/v1/roles')
  assert.equal(roles.length, 4)
  await admin.getByRole('button', { name: '自定义角色', exact: true }).click()
  const analyst = roles.find(role => role.name === 'analyst')
  await admin.getByLabel('角色权限模板').selectOption(String(analyst.id))
  const methodGroup = admin.getByRole('checkbox', { name: '整组选取：方法与谱线' }).locator('xpath=ancestor::fieldset')
  await methodGroup.locator('summary').click()
  await admin.getByRole('checkbox', { name: '方法与谱线：新增、编辑与删除', exact: true }).check()
  for (const [group, label] of [['分析与标准曲线', '测量与分析'], ['蒸发与样品摄谱', '执行样品与蒸发摄谱']]) {
    const field = admin.getByRole('checkbox', { name: `整组选取：${group}` }).locator('xpath=ancestor::fieldset')
    await field.locator('summary').click()
    assert.equal(await admin.getByRole('checkbox', { name: `${group}：${label}` }).isChecked(), true)
  }
  await admin.getByLabel('新角色名称', { exact: true }).fill('复核岗位')
  const createRole = admin.waitForResponse(response => response.url().endsWith('/api/v1/roles')
    && response.request().method() === 'POST')
  await admin.getByRole('button', { name: '创建角色', exact: true }).click()
  const custom = await (await createRole).json()
  assert.deepEqual(custom.permission_keys.sort(), [...analyst.permission_keys, 'methods.write'].sort())
  for (const [username, role] of [['custom-qa', custom], ['analyst-qa', analyst],
    ['auditor-qa', roles.find(role => role.name === 'read_only_auditor')]]) {
    await call(admin, '/api/v1/users', { username, password, role_ids: [role.id] })
  }
  const method = (await call(admin, '/api/v1/methods')).find(item => item.name === 'S16 测试方法')
  await call(admin, '/api/v1/methods/current', { method_id: method.id })
  const analysis = await call(admin, '/api/v1/analyses/runs', {
    name: '隔离测量', method_version_id: version, acquisition_sample_ids: samples.slice(0, 1)
  })
  const capture = await call(admin, '/api/v1/acquisitions/tasks', {
    name: '隔离摄谱', task_kind: 'sample', sample_name: '隔离摄谱',
    method_id: method.id, method_version: 1, ccd_indices: [0],
    pre_excitation_seconds: 0, burn_frame_count: 2, dark_frame_count: 1
  })
  checks.push('管理员按分析员模板从界面创建第五种角色，并单独增加方法增删权限')

  for (const [username, canWrite, canExecute] of [['custom-qa', true, true], ['analyst-qa', false, true], ['auditor-qa', false, false]]) {
    const isolated = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
    const page = await isolated.newPage()
    await page.goto(origin)
    await submitLogin(page, username)
    await page.locator('[data-navigation-group="analysis-tests"]').waitFor()
    const shortcuts = page.getByRole('navigation', { name: '常用快捷方式' })
    assert.equal(await shortcuts.getByRole('button', { name: '新建方法', exact: true }).count(), Number(canWrite))
    if (canWrite) {
      await shortcuts.getByRole('button', { name: '新建方法', exact: true }).click()
      await page.getByLabel('新方法名称').fill('权限复核方法')
      const created = page.waitForResponse(response => response.request().method() === 'POST'
        && response.url().endsWith('/api/v1/methods'))
      await page.locator('.method-composer').getByRole('button', { name: '确认' }).click()
      const creation = await created
      assert.equal(creation.status(), 201)
      const newMethod = await creation.json()
      await page.locator('.method-composer').waitFor({ state: 'hidden' })
      const remove = page.getByTitle('删除方法', { exact: true })
      await remove.waitFor()
      page.once('dialog', dialog => dialog.accept())
      const deleted = page.waitForResponse(response => response.request().method() === 'DELETE'
        && response.url().endsWith(`/api/v1/methods/${newMethod.id}`))
      await remove.click()
      assert.equal((await deleted).status(), 200)
    }
    const analysisShortcut = shortcuts.getByRole('button', { name: '样品分析', exact: true })
    const captureShortcut = shortcuts.getByRole('button', { name: '样品摄谱', exact: true })
    if (canExecute) {
      await analysisShortcut.click()
      const measure = page.getByRole('button', { name: '开始测量', exact: true })
      await measure.waitFor()
      await page.waitForFunction(({ runId }) => document.querySelector('select[aria-label="选择分析批次"]')?.value === String(runId), { runId: analysis.id })
      assert.equal(await measure.isEnabled(), true)
      await captureShortcut.click()
      const captureRow = page.getByRole('row').filter({ hasText: capture.name })
      await captureRow.getByRole('button', { name: '进入摄谱' }).click()
      const startCapture = page.locator('[data-testid="spectroscopy-console"] [data-command="start"]')
      await startCapture.waitFor()
      assert.equal(await startCapture.isEnabled(), true)
    } else {
      assert.equal(await analysisShortcut.isEnabled(), false)
      assert.equal(await captureShortcut.isEnabled(), false)
    }
    await navigate(page, 'help', '关于软件', '[data-testid="about-software"]')
    assert.equal(await page.getByRole('region', { name: '软件激活' }).count(), 0)
    assert.equal(await page.getByRole('region', { name: '模块远程诊断' }).count(), 0)
    await isolated.close()
  }
  checks.push('三个隔离浏览器账户复核方法增删、测量与摄谱控件及管理入口权限')
  if (process.env.QA_ACCESS_OUTPUT) {
    await mkdir(process.env.QA_ACCESS_OUTPUT, { recursive: true })
    await writeFile(path.join(process.env.QA_ACCESS_OUTPUT, 'browser-verification.json'),
      JSON.stringify({ status: 'passed', transport: 'Edge + Vite + isolated FastAPI', checks }, null, 2))
  }
  console.log(JSON.stringify({ status: 'passed', checks }))
} finally {
  await browser?.close()
  for (const child of children.reverse()) {
    if (child.exitCode === null) child.kill()
  }
  await rm(testRoot, { recursive: true, force: true, maxRetries: 8, retryDelay: 250 })
}
