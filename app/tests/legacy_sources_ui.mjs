// Run only against a fresh, isolated browser backend with fixture copies.
import assert from 'node:assert/strict'
import { mkdir, writeFile } from 'node:fs/promises'
import path from 'node:path'
import { pathToFileURL } from 'node:url'
import { call, navigate } from './contract_browser_support.mjs'

assert.equal(process.env.QA_ISOLATED, '1')
assert.ok(process.env.QA_SOURCE_DIR)
const source = process.env.QA_SOURCE_DIR
const output = process.env.QA_OUTPUT
const { chromium } = await import(pathToFileURL(process.env.PLAYWRIGHT_MODULE).href)
const browser = await chromium.launch({ channel: 'msedge', headless: true })
await mkdir(output, { recursive: true })

try {
  const page = await browser.newPage({ viewport: { width: 1060, height: 760 } })
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  page.on('dialog', dialog => dialog.accept())
  await page.goto(process.env.QA_URL)
  const account = { username: 'migration_qa', password: 'Migration-QA-2026!' }
  await page.getByLabel('用户名', { exact: true }).waitFor()
  await call(page, '/api/v1/auth/bootstrap', account)
  await page.reload()
  await page.getByLabel('用户名', { exact: true }).fill(account.username)
  await page.getByLabel('密码', { exact: true }).fill(account.password)
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await navigate(page, 'tools', '旧数据迁移', '[data-testid="migration-workspace"]')

  const workspace = page.getByTestId('migration-workspace')
  const tabs = workspace.getByRole('tab')
  assert.deepEqual(await tabs.allTextContents(), ['方法与配置', '谱图数据', '分析结果'])
  const methodTab = workspace.getByRole('tab', { name: '方法与配置', exact: true })
  const paths = [
    ['方法库 · DIRECT.MTD', 'DIRECT.MTD'],
    ['设备配置 · DIRECT.CFG', 'DIRECT.CFG'],
    ['软件选项 · DIRECT.OPT', 'DIRECT.OPT']
  ]
  const methodPanel = page.getByTestId('legacy-migration-page')
  await methodPanel.getByText('Jet 读取器就绪', { exact: true }).waitFor()
  assert.equal(await methodPanel.getByText('32 位读取通道', { exact: true }).count(), 0)
  for (const [label, file] of paths)
    await methodPanel.getByLabel(label, { exact: true }).fill(path.join(source, file))
  await methodTab.press('ArrowRight')
  await workspace.getByRole('tab', { name: '谱图数据', exact: true }).press('Home')
  for (const [label, file] of paths)
    assert.equal(await methodPanel.getByLabel(label, { exact: true }).inputValue(), path.join(source, file))
  await methodPanel.locator('.migration-paths').scrollIntoViewIfNeeded()
  await methodPanel.locator('.migration-source-surface').screenshot({ path: path.join(output, 'manual-paths.png'), scale: 'css' })

  const stage = (endpoint, submit) => Promise.all([
    page.waitForResponse(response => response.url().endsWith(`/${endpoint}/stage`) && response.request().method() === 'POST'),
    submit.click()
  ]).then(([response]) => response)
  const opt = methodPanel.getByLabel('软件选项 · DIRECT.OPT', { exact: true })
  const missing = path.join(source, 'missing.OPT')
  await opt.fill(missing)
  assert.equal((await stage('legacy-migration', methodPanel.getByRole('button', { name: '只读暂存并校验' }))).status(), 422)
  assert.equal(await opt.inputValue(), missing)
  assert.equal((await call(page, '/api/v1/methods')).length, 0)
  await opt.fill(path.join(source, 'DIRECT.OPT'))

  const cases = [
    { label: '方法与配置', testId: 'legacy-migration-page', endpoint: 'legacy-migration', submitLabel: '只读暂存并校验' },
    { label: '谱图数据', testId: 'spectrum-migration-page', endpoint: 'spectrum-migration', submitLabel: '只读暂存并校验', input: '谱文件路径', file: 'sample.cdt' },
    { label: '分析结果', testId: 'result-migration-page', endpoint: 'result-migration', submitLabel: '暂存解析', input: '文件路径', file: 'result.dat' }
  ]
  for (const item of cases) {
    await workspace.getByRole('tab', { name: item.label, exact: true }).click()
    const panel = page.getByTestId(item.testId)
    await panel.getByRole('button', { name: '选择旧版目录', exact: true }).waitFor()
    assert.equal(await panel.getByText('指定其他目录', { exact: true }).count(), 0)
    assert.equal(await panel.getByText('读取通道技术详情', { exact: true }).count(), 0)
    if (item.input) await panel.getByLabel(item.input, { exact: true }).fill(path.join(source, item.file))
    const staged = await stage(item.endpoint, panel.getByRole('button', { name: item.submitLabel, exact: true }))
    assert.ok(staged.ok(), await staged.text())
    assert.equal((await staged.json()).status, 'staged')
    const [committed] = await Promise.all([
      page.waitForResponse(response => response.url().endsWith(`/${item.endpoint}/commit`)),
      panel.getByRole('button', { name: '原子提交', exact: true }).click()
    ])
    assert.ok(committed.ok(), await committed.text())
    assert.equal((await committed.json()).status, 'committed')
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth))
  }

  const admin = await page.evaluate(() => sessionStorage.getItem('geospectrum.token'))
  for (const [permission, label] of [
    ['migration.read', '方法与配置'], ['spectrum-migration.read', '谱图数据'], ['result-migration.read', '分析结果']
  ]) {
    const role = await call(page, '/api/v1/roles', { name: permission, permission_keys: [permission] })
    const user = { username: `only-${role.id}`, password: account.password }
    await call(page, '/api/v1/users', { ...user, role_ids: [role.id] })
    const login = await call(page, '/api/v1/auth/login', user)
    await page.evaluate(token => sessionStorage.setItem('geospectrum.token', token), login.access_token)
    await page.reload()
    await navigate(page, 'tools', '旧数据迁移', '[data-testid="migration-workspace"]')
    assert.deepEqual(await workspace.getByRole('tab').allTextContents(), [label])
    assert.ok(await workspace.getByRole('button', { name: /^(只读暂存并校验|暂存解析)$/ }).isDisabled())
    await page.evaluate(token => sessionStorage.setItem('geospectrum.token', token), admin)
    await page.reload()
    await page.getByTestId('workspace').waitFor()
  }
  assert.deepEqual(errors, [])
  await writeFile(path.join(output, 'results.json'), JSON.stringify({ reports: cases.map(({ endpoint }) => endpoint), errors }))
  console.log('PASS: three tabs, manually entered paths, invalid OPT, staged and committed all formats, role limits')
} finally {
  await browser.close()
}
