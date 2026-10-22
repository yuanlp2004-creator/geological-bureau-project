import assert from 'node:assert/strict'
import path from 'node:path'
import { call, navigate } from './contract_browser_support.mjs'

/** Use only an isolated QA database with the seeded administrator. */
export async function checkMethodSave(page, fixture, result, output) {
  const entry = (await call(page, '/api/v1/capabilities')).capabilities
    .flatMap(module => module.navigation_entries ?? []).find(item => item.key === 'methods.lifecycle')
  await navigate(page, entry.group, entry.label, '.methods-page')
  const host = page.locator('.methods-page')
  const selector = host.getByLabel('选择编辑方法')
  for (const name of ['保存草稿', '发布', '设为当前', '复制']) {
    assert.equal(await host.getByRole('button', { name, exact: true }).count(), 0)
  }
  for (const title of ['暂停方法', '恢复方法']) assert.equal(await host.getByTitle(title, { exact: true }).count(), 0)
  const select = async id => {
    await selector.selectOption(String(id))
    await page.waitForFunction(id => document.querySelector('select[aria-label="选择编辑方法"]')?.value === String(id), id)
  }
  const save = async (id, status = 200) => {
    const pending = page.waitForResponse(r => r.request().method() === 'POST' && r.url().endsWith(`/api/v1/methods/${id}/save`))
    await host.getByRole('button', { name: '保存', exact: true }).click()
    const response = await pending
    assert.equal(response.status(), status, await response.text())
    await host.getByRole('button', { name: '保存', exact: true }).waitFor({ state: 'visible' })
    await page.waitForFunction(() => ![...document.querySelectorAll('.method-actions button')].find(b => b.textContent.trim() === '保存')?.disabled)
    return response.json()
  }
  await host.getByRole('button', { name: '新建方法', exact: true }).click()
  await host.getByLabel('新方法名称').fill('保存操作验证')
  await host.getByRole('button', { name: '确认', exact: true }).click()
  await host.locator('.method-identity input').waitFor()
  await page.waitForFunction(() => document.querySelector('.method-field-grid input')?.value === '保存操作验证')
  const id = Number(await selector.inputValue())
  await host.getByLabel('说明', { exact: true }).fill('统一保存后的有效方法')
  await host.getByLabel('预激时间 (s)', { exact: true }).fill('4')
  let saveRequests = 0, oldWrites = 0
  const writes = request => {
    if (request.method() === 'POST' && request.url().endsWith(`/methods/${id}/save`)) saveRequests++
    if (request.url().endsWith(`/methods/${id}/publish`) || request.method() === 'PATCH' && request.url().endsWith(`/methods/${id}`)) oldWrites++
  }
  page.on('request', writes)
  let release
  const gate = new Promise(resolve => { release = resolve })
  const routePattern = `**/api/v1/methods/${id}/save`
  await page.route(routePattern, async route => { await gate; await route.continue() })
  const saving = save(id)
  await host.getByLabel('预激时间 (s)', { exact: true }).waitFor({ state: 'visible' })
  await page.waitForFunction(() => document.querySelector('.method-actions button.primary-button')?.disabled)
  assert.equal(await host.locator('.method-identity input').isDisabled(), true)
  assert.equal(await host.getByRole('button', { name: '新建方法', exact: true }).isDisabled(), true)
  await host.getByRole('button', { name: '保存', exact: true }).evaluate(button => { button.click(); button.click() })
  release()
  let saved = await saving
  await page.unroute(routePattern)
  assert.equal(saved.version.state, 'published')
  assert.equal(saved.version.conditions.pre_excitation_seconds, 4)
  assert.equal(saved.description, '统一保存后的有效方法')
  assert.equal(saveRequests, 1)
  assert.equal(oldWrites, 0)
  page.off('request', writes)
  await host.getByRole('button', { name: '使用方法', exact: true }).click()
  await page.waitForFunction(() => document.querySelector('.method-context-status .current-chip'))
  assert.equal((await call(page, '/api/v1/methods/current')).method_id, id)
  const original = saved.published_version
  const task = await call(page, '/api/v1/acquisitions/tasks', { method_id: id, method_version: original.version })
  await host.getByLabel('预激时间 (s)', { exact: true }).fill('5')
  saved = await save(id)
  assert.equal((await call(page, '/api/v1/methods/current')).version, saved.current_version)
  assert.deepEqual((await call(page, `/api/v1/methods/${id}/versions`)).find(v => v.id === original.id), original)
  assert.equal((await call(page, `/api/v1/acquisitions/tasks/${task.id}`)).method_version_id, original.id)
  result.checks.push('Single save request publishes valid edits; repeated clicks blocked; open selects method; current updates while old task/version stay unchanged')

  const before = await call(page, `/api/v1/methods/${id}/versions`)
  const pre = host.getByLabel('预激时间 (s)', { exact: true })
  await pre.fill('')
  let invalidWrites = 0
  const count = request => { if (request.method() === 'POST' && request.url().endsWith(`/methods/${id}/save`)) invalidWrites++ }
  page.on('request', count)
  await host.getByRole('button', { name: '保存', exact: true }).click()
  assert.equal(await pre.inputValue(), '')
  assert.equal(invalidWrites, 0)
  page.off('request', count)
  assert.deepEqual(await call(page, `/api/v1/methods/${id}/versions`), before)
  await pre.fill('5')
  await call(page, '/api/v1/methods', { name: '保存重名验证' })
  await host.locator('.method-identity input').fill('保存重名验证')
  await save(id, 409)
  assert.equal(await host.locator('.method-identity input').inputValue(), '保存重名验证')
  assert.deepEqual(await call(page, `/api/v1/methods/${id}/versions`), before)
  await host.locator('.method-identity input').fill('保存操作验证')
  await pre.fill('6')
  await call(page, `/api/v1/methods/${id}`, { conditions: { pre_excitation_seconds: 8 } }, 'PATCH')
  const concurrent = await call(page, `/api/v1/methods/${id}/versions`)
  await save(id, 409)
  assert.equal(await pre.inputValue(), '6')
  assert.deepEqual(await call(page, `/api/v1/methods/${id}/versions`), concurrent)
  await host.getByRole('button', { name: '刷新', exact: true }).click()
  await page.waitForFunction(() => document.querySelector('.method-excitation input:not([type=checkbox])')?.value === '8')
  saved = await save(id)
  result.checks.push('Invalid numeric input causes zero writes; duplicate-name and stale-version refusals preserve local input and database versions')

  const oldVersions = await call(page, `/api/v1/methods/${id}/versions`)
  await call(page, `/api/v1/methods/${id}/pause`, {})
  await host.getByRole('button', { name: '刷新', exact: true }).click()
  await host.getByRole('button', { name: '使用方法', exact: true }).waitFor()
  await host.getByRole('button', { name: '使用方法', exact: true }).click()
  await page.waitForFunction(() => !document.querySelector('.method-context-status .issue-chip'))
  assert.equal((await call(page, '/api/v1/methods/current')).status, 'active')
  assert.deepEqual(await call(page, `/api/v1/methods/${id}/versions`), oldVersions)
  await host.getByRole('button', { name: '另存为', exact: true }).click()
  await host.getByLabel('新方法名称').fill('另存方法验证')
  await host.getByRole('button', { name: '确认', exact: true }).click()
  await page.waitForFunction(() => document.querySelector('.method-field-grid input')?.value === '另存方法验证')
  const copyId = Number(await selector.inputValue())
  assert.notEqual(copyId, id)
  const copy = await save(copyId)
  assert.deepEqual(copy.version.conditions, saved.version.conditions)
  assert.deepEqual(await call(page, `/api/v1/methods/${id}/versions`), oldVersions)
  assert.equal((await call(page, '/api/v1/methods/current')).method_id, id)
  result.checks.push('Open reenables an existing paused method without rewriting history; Save As preserves source versions and current selection')

  await select(id)
  for (const [width, theme] of [[1440, 'light'], [1060, 'dark']]) {
    if (process.env.QA_CDP) {
      await page.evaluate(width => window.__TAURI__.core.invoke('plugin:window|set_size', { value: { Logical: { width, height: 1000 } } }), width)
    } else await page.setViewportSize({ width, height: 1000 })
    await page.evaluate(theme => { document.documentElement.dataset.theme = theme; document.documentElement.dataset.density = theme === 'dark' ? 'compact' : 'comfortable' }, theme)
    await host.evaluate(node => node.scrollIntoView({ block: 'start' }))
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1))
    await page.screenshot({ path: path.join(output, `method-save-${width}-${theme}.png`), fullPage: true })
    result.layouts.push({ width, theme, method_save: true, desktop: Boolean(process.env.QA_CDP) })
  }
  const adminToken = await page.evaluate(() => sessionStorage.getItem('geospectrum.token'))
  const readonly = await call(page, '/api/v1/roles', {
    name: 'method_save_reader', permission_keys: ['methods.read', 'settings.read', 'runtime-events.read']
  })
  await call(page, '/api/v1/users', { username: 'save_auditor', password: 'QaTest-2026!', role_ids: [readonly.id] })
  const login = await call(page, '/api/v1/auth/login', { username: 'save_auditor', password: 'QaTest-2026!' })
  await page.evaluate(token => sessionStorage.setItem('geospectrum.token', token), login.access_token)
  await page.reload()
  await page.getByTestId('workspace').waitFor()
  await navigate(page, entry.group, entry.label, '.methods-page')
  for (const name of ['保存', '保存方法', '另存为', '新建方法', '使用方法']) {
    assert.equal(await host.getByRole('button', { name, exact: true }).count(), 0)
  }
  assert.equal(await host.getByTitle('删除方法', { exact: true }).count(), 0)
  result.checks.push('Readonly method view exposes no mutation controls; light/wide and dark/narrow layouts keep the simplified operations visible without overflow')
  await page.evaluate(token => sessionStorage.setItem('geospectrum.token', token), adminToken)
  await page.reload()
  await page.getByTestId('workspace').waitFor()
  await navigate(page, entry.group, entry.label, '.methods-page')
  await select(id)
}
