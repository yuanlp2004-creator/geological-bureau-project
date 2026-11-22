import assert from 'node:assert/strict'
import path from 'node:path'
import { call, navigate } from './contract_browser_support.mjs'

// Run against a signed-in isolated database, in the browser or packaged desktop.
export async function checkSettingsCleanup(page, result, output) {
  const check = text => result.checks.push(text)
  let diagnosticRequests = 0
  const countRequest = request => { if (new URL(request.url()).pathname === '/api/v1/diagnostics') diagnosticRequests++ }
  page.on('request', countRequest)
  try {
    const capabilities = await call(page, '/api/v1/capabilities')
    const entries = capabilities.capabilities.flatMap(item => item.navigation_entries)
    assert.ok(entries.every(entry => entry.page !== 'settings'))
    assert.equal(await page.getByText('软件设置', { exact: true }).count(), 0)
    const original = await call(page, '/api/v1/settings')
    assert.equal(original.display.theme, 'light')
    assert.equal(original.display.density, 'comfortable')
    assert.equal(original.display.show_status_bar, true)
    assert.deepEqual(original.logging, { level: 'info', max_bytes: 5242880, retention_days: 30 })
    assert.equal(original.time.timezone, 'Asia/Shanghai')
    check('导航和工作台无软件设置入口；历史界面、日志和时区偏好不影响默认行为')

    const openMaintenance = () => navigate(page, 'system', '备份与维护', '[data-testid="maintenance-page"]')
    await openMaintenance()
    const host = page.getByTestId('maintenance-page')
    await host.getByRole('button', { name: '创建备份', exact: true }).waitFor()
    await page.waitForFunction(() => !document.querySelector('[data-testid="maintenance-page"] .primary-button')?.disabled)
    assert.equal(await host.getByText('系统诊断', { exact: true }).count(), 0)
    assert.equal(await host.getByText('保留天数', { exact: true }).count(), 0)
    const directory = host.getByLabel('备份目录', { exact: true })
    assert.equal(await directory.inputValue(), original.directories.backups)
    await directory.fill('settings-cleanup-backups')
    const rejectBackup = route => route.request().method() === 'POST'
      ? route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: '备份暂时不可用（验证）' }) }) : route.continue()
    await page.route('**/api/v1/backups', rejectBackup)
    try {
      await host.getByRole('button', { name: '创建备份', exact: true }).click()
      await page.getByText('备份暂时不可用（验证）', { exact: true }).waitFor()
      assert.equal(await directory.inputValue(), 'settings-cleanup-backups')
    } finally { await page.unroute('**/api/v1/backups', rejectBackup) }
    const backupResponse = page.waitForResponse(response => response.url().endsWith('/api/v1/backups') && response.request().method() === 'POST')
    await host.getByRole('button', { name: '创建备份', exact: true }).click()
    const backup = await (await backupResponse).json()
    assert.equal(backup.verification.integrity, 'ok')
    const row = host.locator('.maintenance-row').filter({ hasText: backup.backup_path })
    await row.waitFor()
    await row.getByRole('button', { name: '校验', exact: true }).click()
    await page.getByText('备份校验通过', { exact: true }).waitFor()
    assert.deepEqual(await call(page, '/api/v1/settings'), original)
    check('备份页无诊断和日志设置；目录草稿在失败后保留，重试备份及校验成功且不改分析参数')

    await navigate(page, 'tools', '设备调试', '[data-testid="device-debug-page"]')
    await page.getByRole('tab', { name: '软件参数', exact: true }).click()
    const wait = page.getByLabel('暂停等待时间（ms）', { exact: true })
    await wait.fill('240')
    const rejectSettings = route => route.request().method() === 'PATCH'
      ? route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: '分析参数暂时不可用（验证）' }) }) : route.continue()
    await page.route('**/api/v1/settings', rejectSettings)
    try {
      await page.getByRole('button', { name: '保存软件参数', exact: true }).click()
      await page.getByText('分析参数暂时不可用（验证）', { exact: true }).waitFor()
      assert.equal(await wait.inputValue(), '240')
      assert.deepEqual(await call(page, '/api/v1/settings'), original)
    } finally { await page.unroute('**/api/v1/settings', rejectSettings) }
    const save = page.waitForResponse(response => response.url().endsWith('/api/v1/settings') && response.request().method() === 'PATCH')
    await page.getByRole('button', { name: '保存软件参数', exact: true }).click()
    const saved = await save
    assert.equal(saved.status(), 200)
    assert.deepEqual(Object.keys(saved.request().postDataJSON()), ['analysis'])
    const afterAnalysis = await call(page, '/api/v1/settings')
    assert.equal(afterAnalysis.analysis.wait_time_ms, 240)
    assert.deepEqual(afterAnalysis, { ...original, analysis: { ...original.analysis, wait_time_ms: 240 } })
    check('四项分析参数保留；保存失败保留草稿，重试只提交分析参数且不覆盖其他设置')

    await page.getByRole('tab', { name: '设备参数', exact: true }).click()
    const screen = page.getByLabel('屏幕宽度（cm）', { exact: true })
    await screen.fill('51')
    await page.getByRole('button', { name: '保存设备参数', exact: true }).click()
    await page.getByText('设备参数已保存，重新连接设备后使用新参数', { exact: true }).waitFor()
    const afterScreen = await call(page, '/api/v1/settings')
    assert.equal(afterScreen.display.screen_width_mm, 510)
    assert.deepEqual(afterScreen.analysis, afterAnalysis.analysis)
    assert.deepEqual(afterScreen.printing, original.printing)
    assert.deepEqual(afterScreen.directories, original.directories)
    check('屏幕校准仍可保存；分析参数、备份目录与打印偏好保持')

    for (const [width, height] of [[1440, 1000], [1060, 680]]) {
      if (process.env.QA_CDP) await page.evaluate(({ width, height }) => window.__TAURI__.core.invoke('plugin:window|set_size', { value: { Logical: { width, height } } }), { width, height })
      else await page.setViewportSize({ width, height })
      await page.waitForFunction(width => Math.abs(innerWidth - width) < 2, width)
      await openMaintenance()
      const layout = await page.evaluate(() => ({ width: innerWidth, scroll: document.documentElement.scrollWidth }))
      assert.ok(layout.scroll <= layout.width + 1, JSON.stringify(layout))
      result.layouts.push({ width, height, ...layout })
      if (output) await page.screenshot({ path: path.join(output, `maintenance-${width}.png`), fullPage: true })
    }
    await page.reload(); await page.getByTestId('workspace').waitFor()
    assert.equal(await page.getByText('软件设置', { exact: true }).count(), 0)
    assert.deepEqual(await call(page, '/api/v1/settings'), afterScreen)
    await openMaintenance()
    assert.equal(diagnosticRequests, 0)
    check('大小窗口无横向溢出，刷新后参数保持；全流程不请求系统诊断')
  } finally { page.off('request', countRequest) }
}
