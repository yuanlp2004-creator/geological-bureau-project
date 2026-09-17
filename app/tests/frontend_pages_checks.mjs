import assert from 'node:assert/strict'

/** R5 checks share the isolated servers and authenticated browser from test:api. */
export async function checkPages(page, checks) {
  const entries = await page.evaluate(async () => {
    const { api } = await import('/src/api/index.ts')
    const { navigationEntries } = await import('/src/navigation.ts')
    const token = sessionStorage.getItem('geospectrum.token')
    return navigationEntries((await api.capabilities()).capabilities, (await api.me(token)).permissions)
  })
  async function navigate(entry) {
    assert.ok(entry, 'Expected navigation entry')
    if (entry.group === 'workspace') await page.locator('[data-navigation-group="workspace"]').click()
    else {
      const group = page.locator(`[data-navigation-group="${entry.group}"]`)
      if (await group.getAttribute('aria-expanded') !== 'true') await group.click()
      const button = page.getByRole('menuitem', { name: entry.label }).first()
      if (await button.getAttribute('aria-disabled') === 'true') return false
      await button.click()
      await page.keyboard.press('Escape')
    }
    await page.waitForFunction(() => !!document.querySelector('.page-content'))
    return true
  }
  const methods = entries.filter(e => e.page === 'methods')
  const lifecycle = methods.find(e => e.key === 'methods.lifecycle')
  assert.equal(methods.length, 3)
  for (const entry of methods) {
    assert.equal(await navigate(entry), true)
    await page.locator(`[data-testid="methods-page"][data-navigation-view="${entry.view || 'lifecycle'}"]`).waitFor()
  }
  await navigate(lifecycle)
  const selector = page.getByLabel('选择编辑方法')
  await selector.locator('option').first().waitFor({ state: 'attached' })
  const selectedId = Number(await selector.inputValue())
  assert.ok(selectedId > 0)
  await page.getByLabel('说明').fill('R5 browser saved description')
  const saved = page.waitForResponse(r => r.request().method() === 'PATCH' && r.url().endsWith(`/api/v1/methods/${selectedId}`))
  await page.getByRole('button', { name: '保存草稿', exact: true }).click()
  assert.equal((await saved).status(), 200)
  const before = await page.evaluate(async id => {
    const { api } = await import('/src/api/index.ts')
    return (await api.methods(sessionStorage.getItem('geospectrum.token'))).find(m => m.id === id)
  }, selectedId)
  assert.equal(before.description, 'R5 browser saved description')
  const numeric = page.getByLabel('预激发 (s)', { exact: true })
  await numeric.fill('')
  await numeric.press('Enter')
  await page.getByRole('button', { name: '保存草稿', exact: true }).click()
  assert.equal(await numeric.inputValue(), '')
  assert.equal(await numeric.evaluate(n => n.checkValidity()), false)
  const after = await page.evaluate(async id => {
    const { api } = await import('/src/api/index.ts')
    return (await api.methods(sessionStorage.getItem('geospectrum.token'))).find(m => m.id === id)
  }, selectedId)
  assert.equal(after.latest_version, before.latest_version)
  assert.equal(after.version.content_sha256, before.version.content_sha256)
  await numeric.fill('3')
  await numeric.press('Tab')
  await page.reload()
  await page.waitForFunction(() => !document.querySelector('.auth-form') && !!document.querySelector('.sidebar'))
  await navigate(lifecycle)
  await page.locator('[data-testid="methods-page"][data-navigation-view="conditions"]').waitFor()
  assert.equal(await page.getByLabel('说明').inputValue(), 'R5 browser saved description')
  checks.push('R5: three method views, real save/reload, blank numeric rejection without a new version')

  const visited = [], gated = []
  for (const name of ['migration','spectrum-migration','result-migration','spectra','samples','settings','about','users','audit','maintenance','help','acquisition','dispersion','sample-acquisition','hardware-acquisition','mercury-calibration','analysis','postprocessing','reports']) {
    const entry = entries.find(e => e.page === name)
    if (!entry) continue
    if (await navigate(entry)) {
      visited.push(name)
      assert.equal(await page.locator('.error-page').count(), 0)
      await page.locator('.page-content').first().waitFor()
    } else gated.push(name)
  }
  for (const expected of ['migration','spectrum-migration','result-migration','settings','about']) assert.ok(visited.includes(expected), expected)
  checks.push(`R5: page navigation mounted ${visited.join(', ')}; prerequisite gates retained for ${gated.join(', ') || 'none'}`)

  for (const [theme, width, height] of [['dark',1280,800],['light',1920,1080]]) {
    await page.evaluate(async theme => {
      const { api } = await import('/src/api/index.ts')
      await api.saveSettings(sessionStorage.getItem('geospectrum.token'), { display: { theme } })
    }, theme)
    await page.setViewportSize({ width, height })
    await page.reload()
    await page.waitForFunction(theme => document.documentElement.dataset.theme === theme, theme)
    await navigate(lifecycle)
    const layout = await page.evaluate(() => ({ width: innerWidth, scroll: document.documentElement.scrollWidth }))
    assert.ok(layout.scroll <= layout.width + 1, JSON.stringify({ theme, ...layout }))
  }
  checks.push('R5: real saved dark/light themes and 1280/1920 method layouts without window overflow')

  await page.evaluate(async () => {
    const { api } = await import('/src/api/index.ts')
    const token = sessionStorage.getItem('geospectrum.token')
    const roles = await api.roles(token)
    const readOnly = roles.find(role => role.name === 'read_only_auditor')
    await api.createUser(token, { username: 'r5-viewer', password: 'r5-viewer-pass', role_ids: [readOnly.id] })
  })
  const context = await page.context().browser().newContext()
  try {
    const viewer = await context.newPage()
    await viewer.goto(page.url())
    await viewer.evaluate(async () => {
      const { api } = await import('/src/api/index.ts')
      const result = await api.login('r5-viewer', 'r5-viewer-pass')
      sessionStorage.setItem('geospectrum.token', result.access_token)
    })
    await viewer.reload()
    await viewer.waitForFunction(() => !!sessionStorage.getItem('geospectrum.token') && !document.querySelector('.auth-form'))
    assert.equal(await viewer.locator('[data-navigation-group="methods"]').count(), 0)
    const status = await viewer.evaluate(async () => {
      const { api } = await import('/src/api/index.ts')
      try { await api.createMethod(sessionStorage.getItem('geospectrum.token'), { name: 'must-not-write' }) }
      catch(e) { return e.status }
    })
    assert.equal(status, 403)
  } finally { await context.close() }
  checks.push('R5: real read-only login, hidden method navigation and server-side write denial')
}
