// Run only against an isolated seed_bf02_browser.py fixture.
import assert from 'node:assert/strict'
import { pathToFileURL } from 'node:url'
import { mkdir, writeFile } from 'node:fs/promises'
assert.equal(process.env.QA_ISOLATED, '1')
const { chromium } = await import(pathToFileURL(process.env.PLAYWRIGHT_MODULE).href)
const browser = process.env.QA_CDP
  ? await chromium.connectOverCDP(process.env.QA_CDP)
  : await chromium.launch({ channel: 'msedge', headless: true })
const out = process.env.QA_OUTPUT
await mkdir(out, { recursive: true })
const observations = []
let page
try {
  if (process.env.QA_CDP) {
    for (let attempt = 0; attempt < 300 && !page; attempt++) {
      page = browser.contexts().flatMap((context) => context.pages())
        .find((candidate) => candidate.url().includes('tauri.localhost'))
      if (!page) await new Promise((resolve) => setTimeout(resolve, 100))
    }
    assert.ok(page, 'QA app must expose its rendered page before interaction')
  } else page = await browser.newPage({ viewport: { width: 1920, height: 1080 } })
  const errors = []
  page.on('pageerror', (e) => errors.push(e.message))
  if (!process.env.QA_CDP) await page.goto(process.env.QA_URL || 'http://127.0.0.1:5174')
  await page.getByLabel('用户名', { exact: true }).fill('qa_admin')
  await page.getByLabel('密码', { exact: true }).fill('QaTest-2026!')
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await page.locator('.workspace-page').waitFor()
  await page.locator('.quick-action').filter({ hasText: '方法管理' }).click()
  await page.getByLabel('选择编辑方法').waitFor()
  await page.waitForFunction(() =>
    Array.from(document.querySelector('select[aria-label="选择编辑方法"]')?.options ?? []).some((o) =>
      o.textContent.includes('S16 测试方法')
    )
  )
  const original = await page
    .getByLabel('选择编辑方法')
    .locator('option')
    .filter({ hasText: 'S16 测试方法' })
    .getAttribute('value')
  await page.getByLabel('选择编辑方法').selectOption(original)
  // The S16 calculation fixture has more decimal places than the modern UI step.
  for (const label of ['基线波长 (nm)', '实际基线波长 (nm)']) {
    const field = page.getByLabel(label, { exact: true })
    await field.fill(Number(await field.inputValue()).toFixed(4))
    await field.blur()
  }
  for (const width of process.env.QA_CDP ? [1440, 1060] : [1920, 1440, 1060]) {
    if (process.env.QA_CDP) {
      await page.evaluate((width) => window.__TAURI__.core.invoke('plugin:window|set_size', {
        value: { Logical: { width, height: 1000 } }
      }), width)
      await page.waitForFunction((width) => Math.abs(innerWidth - width) < 2, width)
    } else await page.setViewportSize({ width, height: 1000 })
    for (const dark of [false, true]) {
      await page.evaluate((dark) => {
        document.documentElement.dataset.theme = dark ? 'dark' : 'light'
        document.documentElement.dataset.density = dark ? 'compact' : 'comfortable'
      }, dark)
      const geometry = await page.locator('.method-geometry').boundingBox()
      const excitation = await page.locator('.method-excitation').boundingBox()
      const angles = await page.locator('.method-angle-selection').boundingBox()
      assert.ok(Math.abs(geometry.y - excitation.y) < 2, 'Related parameter groups share the row')
      assert.ok(Math.abs(geometry.height - excitation.height) < 2, 'Parameter panels have equal height')
      assert.ok(excitation.x > geometry.x + geometry.width, 'Excitation uses the second column')
      assert.ok(angles.y >= geometry.y + geometry.height && Math.abs(angles.x - geometry.x) < 2,
        'Angles occupy a separate row below both panels')
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), 'No parameter viewport overflow')
      observations.push({ view: 'parameters', width, dark, geometry, excitation, angles,
        desktop: Boolean(process.env.QA_CDP), devicePixelRatio: await page.evaluate(() => devicePixelRatio) })
      await page.screenshot({ path: `${out}/parameters-${width || 'desktop'}-${dark ? 'dark' : 'light'}.png`, fullPage: true })
    }
  }
  await page.locator('.method-editor-tabs button').filter({ hasText: '分析谱线' }).click()
  await page.locator('.spectral-line-card').first().waitFor()
  for (const width of process.env.QA_CDP ? [null] : [1920, 1280, 1060]) {
    if (width) await page.setViewportSize({ width, height: width === 1920 ? 1080 : 720 })
    for (const dark of [false, true]) {
      await page.evaluate((dark) => {
        document.documentElement.dataset.theme = dark ? 'dark' : 'light'
        document.documentElement.dataset.density = dark ? 'compact' : 'comfortable'
      }, dark)
      const list = await page.locator('.spectral-list-surface').boundingBox()
      const editor = await page.locator('.spectral-editor-surface').boundingBox()
      const context = await page.locator('.method-context-bar').boundingBox()
      assert.ok(Math.abs(list.y - editor.y) < 2, 'List and editor must start at the same height')
      assert.ok(editor.width > list.width * 1.7, 'Editor must dominate width')
      assert.ok(context.height < 170, 'Toolbar must stay compact')
      assert.ok(
        await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1),
        'No viewport overflow'
      )
      observations.push({ width: width || 'desktop', dark, list, editor, context })
      await page.screenshot({ path: `${out}/methods-${width || 'desktop'}-${dark ? 'dark' : 'light'}.png` })
    }
  }
  await page.getByRole('button', { name: '收起清单', exact: true }).click()
  assert.equal(await page.locator('.spectral-list-surface').isVisible(), false)
  await page.getByRole('button', { name: '展开谱线清单', exact: true }).click()
  assert.equal(await page.locator('.spectral-list-surface').isVisible(), true)
  await page.getByRole('button', { name: '新建方法', exact: true }).click()
  const name = `UI布局${Date.now().toString().slice(-6)}`
  await page.getByLabel('新方法名称').fill(name)
  await page.getByRole('button', { name: '确认', exact: true }).click()
  await page.waitForFunction(
    (name) =>
      document.querySelector('select[aria-label="选择编辑方法"]')?.selectedOptions[0]?.textContent.includes(name),
    name
  )
  const created = await page.getByLabel('选择编辑方法').inputValue()
  assert.notEqual(created, original)
  await page.locator('.method-editor-tabs button').filter({ hasText: '方法管理与参数' }).click()
  await page.getByLabel('说明', { exact: true }).fill('布局回归草稿')
  await Promise.all([
    page.waitForResponse((r) => r.request().method() === 'POST' && r.url().endsWith(`/methods/${created}/save`) && r.ok()),
    page.getByRole('button', { name: '保存', exact: true }).click()
  ])
  await page.getByLabel('选择编辑方法').selectOption(original)
  await page.getByLabel('选择编辑方法').selectOption(created)
  await page.waitForFunction(() => document.querySelector('.method-field-grid textarea')?.value === '布局回归草稿')
  const errorSettings = page.locator('.method-error-settings')
  assert.equal(await page.locator('details.method-error-settings').count(), 0)
  const threshold = errorSettings.locator('.field').filter({ hasText: /^重复摄谱最大允许误差/ }).locator('input')
  await threshold.fill('3.5')
  await threshold.blur()
  assert.equal(await threshold.isVisible(), true, 'Error controls stay expanded')
  await threshold.fill('')
  let hiddenWrites = 0
  const hiddenListener = (r) => {
    if (r.method() === 'POST' && r.url().endsWith('/save')) hiddenWrites++
  }
  page.on('request', hiddenListener)
  await page.getByRole('button', { name: '保存', exact: true }).click()
  assert.equal(await threshold.isVisible(), true, 'Invalid field remains visible')
  assert.equal(await threshold.inputValue(), '')
  assert.equal(await threshold.evaluate((el) => document.activeElement === el), true)
  assert.equal(hiddenWrites, 0, 'Invalid error field causes zero writes')
  page.off('request', hiddenListener)
  await threshold.fill('3.5')
  await threshold.blur()
  await Promise.all([
    page.waitForResponse((r) => r.request().method() === 'POST' && r.url().endsWith(`/methods/${created}/save`) && r.ok()),
    page.getByRole('button', { name: '保存', exact: true }).click()
  ])
  await page.getByLabel('选择编辑方法').selectOption(original)
  await page.getByLabel('选择编辑方法').selectOption(created)
  await page.waitForFunction(() => document.querySelector('.method-error-settings input')?.value === '3.5')
  assert.equal(await threshold.inputValue(), '3.5', 'Expanded values save and reload with the whole method')
  const frame = page
    .locator('.field')
    .filter({ hasText: /^采样次数/ })
    .locator('input')
  await frame.fill('')
  let writes = 0
  const listener = (r) => {
    if (r.method() === 'POST' && r.url().endsWith('/save')) writes++
  }
  page.on('request', listener)
  await page.getByRole('button', { name: '保存', exact: true }).click()
  assert.equal(await frame.inputValue(), '')
  assert.equal(await frame.evaluate((el) => el.checkValidity()), false)
  assert.equal(await frame.evaluate((el) => document.activeElement === el), true)
  assert.equal(writes, 0)
  page.off('request', listener)
  await page.getByLabel('选择编辑方法').selectOption(original)
  await page.locator('.method-editor-tabs button').filter({ hasText: '分析谱线' }).click()
  if (!process.env.QA_CDP) await page.setViewportSize({ width: 1920, height: 1080 })
  await page.evaluate(() => {
    document.documentElement.dataset.theme = 'light'
    document.documentElement.dataset.density = 'comfortable'
  })
  await page.locator('.spectral-line-card').first().waitFor()
  await page.screenshot({ path: `${out}/method-layout-final.png` })
  if (process.env.QA_CDP) {
    await page.evaluate(() => window.__TAURI__.core.invoke('plugin:window|set_size', {
      value: { Logical: { width: 1440, height: 1000 } }
    }))
    await page.waitForFunction(() => Math.abs(innerWidth - 1440) < 2)
    await page.locator('.method-editor-tabs button').filter({ hasText: '方法管理与参数' }).click()
    for (const label of ['基线波长 (nm)', '实际基线波长 (nm)']) {
      const field = page.getByLabel(label, { exact: true })
      await field.fill(Number(await field.inputValue()).toFixed(4))
      await field.blur()
    }
    await page.screenshot({ path: `${out}/parameters-final.png`, fullPage: true })
  }
  assert.deepEqual(errors, [])
  await writeFile(
    `${out}/result.json`,
    JSON.stringify(
      {
        status: 'passed',
        observations,
        checks: [
          'single local sidebar',
          'fold/unfold',
          'create and select',
          'save persistence',
          'compact parameter groups',
          'expanded error controls and persistence',
          'invalid error field focused with zero writes',
          'invalid numeric zero writes',
          'no page errors'
        ]
      },
      null,
      2
    )
  )
  console.log(JSON.stringify({ status: 'passed', observations }))
} finally {
  if (process.env.QA_CDP) await (page ?? browser.contexts()[0]?.pages()[0])?.evaluate(
    () => window.__TAURI__.core.invoke('plugin:window|close')
  ).catch(() => {})
  await browser.close()
}
