import assert from 'node:assert/strict'
import path from 'node:path'
import { call, navigate } from './contract_browser_support.mjs'

// 在隔离浏览器或冻结 QA 桌面上验证同一条角色授权主流程。
export async function checkUsersRoles(page, fixture, result, output) {
  const rolesBefore = await call(page, '/api/v1/roles')
  const manifest = await call(page, '/api/v1/capabilities')
  const entry = manifest.capabilities.flatMap(item => item.navigation_entries || []).find(item => item.page === 'users')
  const go = () => navigate(page, entry.group, entry.label, '.auth-page')
  const selected = async () => (await page.locator('[data-permission-key]:checked').evaluateAll(nodes => nodes.map(node => node.dataset.permissionKey))).sort()
  const sorted = values => [...new Set(values)].sort()
  const analyst = rolesBefore.find(role => role.name === 'analyst')
  const auditor = rolesBefore.find(role => role.name === 'read_only_auditor')
  await go()
  await page.getByRole('button', { name: '刷新', exact: true }).waitFor()
  await page.waitForFunction(() => document.querySelectorAll('.auth-role-card').length === 4)
  assert.equal(await page.locator('.auth-page .disclosure-toggle').count(), 0)
  assert.equal(await page.getByRole('button', { name: '查阅角色与权限' }).count(), 0)
  result.checks.push('Default view shows four role summaries and ordinary section actions')

  for (const [theme, density, width] of [
    ['light', 'comfortable', 1440], ['dark', 'compact', 1060],
    ['light', 'compact', 1060], ['dark', 'comfortable', 1440]
  ]) {
    if (process.env.QA_CDP) {
      await page.evaluate(width => window.__TAURI__.core.invoke('plugin:window|set_size', { value: { Logical: { width, height: 1000 } } }), width)
      await page.waitForFunction(width => Math.abs(innerWidth - width) < 2, width)
    } else await page.setViewportSize({ width, height: 1000 })
    await call(page, '/api/v1/settings', { display: { theme, density } }, 'PATCH')
    await page.getByRole('button', { name: '刷新服务状态', exact: true }).click()
    await page.waitForFunction(({ theme, density }) => document.documentElement.dataset.theme === theme
      && document.querySelector('.app-shell')?.dataset.theme === theme
      && document.querySelector('.app-shell')?.dataset.density === density, { theme, density })
    for (const expanded of [false, true]) {
      if (expanded) {
        await page.getByRole('button', { name: '创建用户', exact: true }).click()
        await page.getByRole('button', { name: '自定义角色', exact: true }).click()
      }
      const layout = await page.evaluate(() => {
        const boxes = [...document.querySelectorAll('.auth-role-card, .permission-group, .user-create-form .field, .role-template-fields .field')]
          .filter(node => node.checkVisibility()).map(node => {
            const r = node.getBoundingClientRect()
            return { x: r.x, y: r.y, width: r.width, right: r.right, kind: node.className }
          })
        return { overflow: document.documentElement.scrollWidth > innerWidth + 1, width: innerWidth,
          theme: document.querySelector('.app-shell').dataset.theme, density: document.querySelector('.app-shell').dataset.density, boxes }
      })
      assert.equal(layout.overflow, false)
      assert.equal(layout.theme, theme)
      assert.equal(layout.density, density)
      assert.ok(layout.boxes.every(box => box.x >= 0 && box.right <= width + 1 && box.width >= 120))
      const cards = layout.boxes.filter(box => box.kind === 'auth-role-card')
      assert.ok(Math.abs(cards[0].y - cards[1].y) < 2 && cards[0].right < cards[1].x, 'Role summaries use two columns')
      if (expanded) {
        const fields = layout.boxes.filter(box => box.kind === 'field')
        assert.ok(fields.slice(0, 3).every(box => Math.abs(box.y - fields[0].y) < 2), 'New-user short fields share a row')
        assert.ok(Math.abs(fields[3].y - fields[4].y) < 2, 'Template and new role name share a row')
      }
      result.layouts.push({ width, theme, density, expanded, ...layout })
      if (theme === 'light' && width === 1440 || theme === 'dark' && width === 1060) {
        await page.screenshot({ path: path.join(output, `users-${width}-${theme}-${expanded ? 'expanded' : 'default'}.png`), fullPage: true })
      }
      if (expanded) {
        await page.getByRole('button', { name: '收起创建用户', exact: true }).click()
        await page.getByRole('button', { name: '收起自定义角色', exact: true }).click()
      }
    }
  }
  result.checks.push('Eight layouts: real light/dark settings, both densities, 1060/1440 widths, forms closed/open')
  await page.getByRole('button', { name: '自定义角色', exact: true }).click()
  assert.equal(await page.getByLabel('角色权限模板').inputValue(), String(analyst.id))
  assert.deepEqual(await selected(), sorted(analyst.permission_keys))
  await page.getByLabel('角色权限模板').selectOption('')
  assert.deepEqual(await selected(), [])
  await page.getByLabel('角色权限模板').selectOption(String(auditor.id))
  assert.deepEqual(await selected(), sorted(auditor.permission_keys))
  result.checks.push('Template copies exact keys, including default analyst and explicit blank')

  const usersGroup = page.getByRole('checkbox', { name: '整组选取：用户管理', exact: true })
  await usersGroup.check()
  const group = usersGroup.locator('xpath=ancestor::fieldset')
  await group.locator('summary').click()
  await page.getByRole('checkbox', { name: '用户管理：编辑', exact: true }).uncheck()
  assert.equal(await usersGroup.evaluate(node => node.indeterminate), true)
  const methodsGroup = page.getByRole('checkbox', { name: '整组选取：方法与谱线', exact: true })
  await methodsGroup.check()
  await methodsGroup.uncheck()
  const expected = sorted([...auditor.permission_keys, 'users.read'])
  assert.deepEqual(await selected(), expected)
  await page.getByLabel('新角色名称', { exact: true }).fill('analyst')
  await page.getByRole('button', { name: '收起自定义角色', exact: true }).click()
  await page.getByRole('button', { name: '自定义角色', exact: true }).click()
  assert.equal(await page.getByLabel('新角色名称', { exact: true }).inputValue(), 'analyst')
  assert.deepEqual(await selected(), expected)
  const failed = page.waitForResponse(response => response.url().endsWith('/api/v1/roles') && response.request().method() === 'POST')
  await page.getByRole('button', { name: '创建角色', exact: true }).click()
  assert.equal((await failed).status(), 409)
  await page.getByRole('button', { name: '创建角色', exact: true }).waitFor({ state: 'visible' })
  assert.equal(await page.getByLabel('新角色名称', { exact: true }).inputValue(), 'analyst')
  assert.deepEqual(await selected(), expected)
  assert.equal((await call(page, '/api/v1/roles')).length, rolesBefore.length)
  result.checks.push('Group toggle, partial selection, collapse and duplicate-name failure preserve exact draft')

  const roleName = '专项只读复核'
  await page.getByLabel('新角色名称', { exact: true }).fill(roleName)
  const saved = page.waitForResponse(response => response.url().endsWith('/api/v1/roles') && response.request().method() === 'POST')
  await page.getByRole('button', { name: '创建角色', exact: true }).click()
  assert.equal((await saved).status(), 201)
  await page.getByRole('button', { name: '自定义角色', exact: true }).waitFor()
  const rolesAfter = await call(page, '/api/v1/roles')
  const role = rolesAfter.find(item => item.name === roleName)
  assert.deepEqual(sorted(role.permission_keys), expected)
  for (const previous of rolesBefore) assert.deepEqual(rolesAfter.find(item => item.id === previous.id), previous)
  result.checks.push('Custom role saves exactly the selected keys; all source roles remain unchanged')

  await page.getByRole('button', { name: '创建用户', exact: true }).click()
  await page.getByLabel('用户名', { exact: true }).fill('permission_qa')
  await page.getByLabel('初始密码', { exact: true }).fill('QaTest-2026!')
  await page.getByLabel('新用户角色').selectOption(String(role.id))
  await page.getByRole('button', { name: '收起创建用户', exact: true }).click()
  await page.getByRole('button', { name: '创建用户', exact: true }).click()
  assert.equal(await page.getByLabel('用户名', { exact: true }).inputValue(), 'permission_qa')
  assert.equal(await page.getByLabel('新用户角色').inputValue(), String(role.id))
  const created = page.waitForResponse(response => response.url().endsWith('/api/v1/users') && response.request().method() === 'POST')
  await page.locator('.user-create-form').getByRole('button', { name: '创建用户', exact: true }).click()
  assert.equal((await created).status(), 201)
  const user = (await call(page, '/api/v1/users')).find(item => item.username === 'permission_qa')
  assert.deepEqual(user.role_ids, [role.id])
  const audit = await call(page, '/api/v1/audit')
  assert.ok(audit.some(item => item.action === 'role.permission.change' && item.target_id === role.id))
  assert.ok(audit.some(item => item.action === 'user.create' && item.target_id === user.id))
  const auth = await call(page, '/api/v1/auth/login', { username: 'permission_qa', password: 'QaTest-2026!' })
  assert.deepEqual(sorted(auth.user.permissions), expected)
  await page.evaluate(token => sessionStorage.setItem('geospectrum.token', token), auth.access_token)
  await page.reload()
  await page.getByTestId('workspace').waitFor()
  await go()
  await page.waitForFunction(() => document.querySelectorAll('.auth-role-card').length === 5)
  assert.equal(await page.getByRole('button', { name: '创建用户', exact: true }).count(), 0)
  assert.equal(await page.getByRole('button', { name: '自定义角色', exact: true }).count(), 0)
  assert.equal(await page.locator('.role-create-form, .user-create-form').count(), 0)
  const forbidden = await page.evaluate(async () => {
    const config = window.__TAURI__?.core ? await window.__TAURI__.core.invoke('runtime_config') : null
    const headers = { 'Content-Type': 'application/json', Authorization: `Bearer ${sessionStorage.getItem('geospectrum.token')}`,
      ...(config ? { 'X-GeoSpectrum-Process-Key': config.process_key } : {}) }
    const response = await fetch(`${config?.api_base || ''}/api/v1/users`, { method: 'POST', headers,
      body: JSON.stringify({ username: 'forbidden', password: 'QaTest-2026!', role_ids: [] }) })
    return response.status
  })
  assert.equal(forbidden, 403)
  result.checks.push('User receives the selected role, audit exists, read-only UI and server deny unauthorized account creation')
}
