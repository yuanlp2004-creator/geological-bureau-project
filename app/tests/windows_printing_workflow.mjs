import assert from 'node:assert/strict'
import path from 'node:path'
import { writeFile } from 'node:fs/promises'
import { call, navigate } from './contract_browser_support.mjs'

export async function checkWindowsPrinting(page, fixture, result, output) {
  const mark = message => { result.checks.push(message); console.log(`PASS: ${message}`) }
  const entries = (await call(page, '/api/v1/capabilities')).capabilities.flatMap(item => item.navigation_entries)
  const entry = entries.find(item => item.key === 'methods.print-preview')
  assert.ok(entry)
  const open = async () => {
    await navigate(page, entry.group, entry.label, '[data-testid="method-print-panel"]')
    const panel = page.getByTestId('method-print-panel')
    await panel.getByRole('button', { name: '检查连接', exact: true }).waitFor()
    return panel
  }
  let panel = await open()
  const printers = (await call(page, '/api/v1/method-print/printers')).printers
  assert.ok(printers.some(item => item.name === 'Microsoft Print to PDF'))
  assert.ok(printers.every(item => item.name !== 'geospectrum-pdf' && item.system))
  assert.ok(!(await panel.innerText()).includes('可自动验收'))
  await panel.getByLabel('打印机', { exact: true }).selectOption('Microsoft Print to PDF')
  const paper = panel.getByLabel('纸张', { exact: true })
  await paper.locator('option[value="win:11:1480:2100"]').waitFor({ state: 'attached' })
  assert.ok(await paper.locator('option').count() > 20)
  assert.deepEqual(await panel.getByLabel('字体大小 (pt)', { exact: true }).locator('option').allTextContents(), ['9','10','11','12','13'])
  mark('系统打印机与驱动纸张列表，旧版五档字号，无应用虚拟打印机')

  await paper.selectOption('win:11:1480:2100')
  await panel.getByLabel('方向', { exact: true }).selectOption('landscape')
  await panel.getByLabel('字体大小 (pt)', { exact: true }).selectOption('13')
  await panel.getByRole('button', { name: '保存默认值', exact: true }).click()
  await page.getByText('打印机、纸张、方向、边距与版式默认值已保存', { exact: true }).waitFor()
  const saved = await call(page, '/api/v1/method-print/settings')
  assert.equal(saved.paper, 'win:11:1480:2100')
  assert.equal(saved.font_size_pt, 13)
  assert.equal(saved.orientation, 'landscape')
  await page.reload()
  await page.getByTestId('workspace').waitFor()
  panel = await open()
  assert.equal(await panel.getByLabel('纸张', { exact: true }).inputValue(), saved.paper)
  assert.equal(await panel.getByLabel('字体大小 (pt)', { exact: true }).inputValue(), '13')
  mark('A5横向与13pt保存并重载保持')

  const jobsBefore = await call(page, `/api/v1/methods/${fixture.method_id}/print-jobs`)
  await panel.getByRole('button', { name: '检查连接', exact: true }).click()
  await page.getByText('已接通 Microsoft Print to PDF；未提交打印任务', { exact: true }).waitFor()
  assert.deepEqual(await call(page, `/api/v1/methods/${fixture.method_id}/print-jobs`), jobsBefore)
  const probe = await call(page, '/api/v1/method-print/check-connection', saved)
  assert.equal(probe.connected, true)
  assert.equal(probe.submitted, false)
  assert.equal(probe.paper_id, 11)
  assert.equal(probe.orientation, 2)
  result.driver = probe
  mark('真实Microsoft驱动连接、纸型方向验证；零任务提交')

  for (const [theme, width] of [['light',1440],['dark',1060]]) {
    await call(page, '/api/v1/settings', { display: { theme } }, 'PATCH')
    await page.reload()
    await page.getByTestId('workspace').waitFor()
    if (process.env.QA_CDP) await page.evaluate(async width => {
      const api = window.__TAURI__.core
      await api.invoke('plugin:window|set_size', { value: { Logical: { width, height:1000 } } })
    }, width)
    else await page.setViewportSize({ width, height:1000 })
    panel = await open()
    await page.waitForFunction(() => { const paper = document.querySelector('[aria-label="纸张"]'); return paper && !paper.disabled })
    await page.screenshot({ path:path.join(output, `printing-${theme}.png`), fullPage:true })
  }
  mark('明暗主题、1440与1060窗口检查')

  if (process.env.QA_NATIVE_PRINT === '1') {
    await panel.getByLabel('纸张', { exact:true }).selectOption('A4')
    await panel.getByLabel('方向', { exact:true }).selectOption('portrait')
    await panel.getByRole('button', { name:'打印', exact:true }).click()
    await writeFile(path.join(output, 'native-started.json'), JSON.stringify({ started:true }))
    await page.getByText('已取消 Windows 打印', { exact:true }).waitFor({ timeout:240000 })
    await panel.getByText('已取消', { exact:true }).waitFor()
    const jobs = (await call(page, `/api/v1/methods/${fixture.method_id}/print-jobs`)).jobs
    assert.equal(jobs[0].error_code, 'print_cancelled')
    assert.equal(jobs[0].status, 'failed')
    assert.equal(jobs[0].output_path, null)
    mark('冻结EXE打开原生Microsoft PDF保存窗口，取消回传且无成功打印记录')
  }
}
