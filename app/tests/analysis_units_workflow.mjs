import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import path from 'node:path'
import { call, navigate } from './contract_browser_support.mjs'

export async function checkAnalysisUnits(page, checks, output) {
  let method = await call(page, '/api/v1/methods', { name: '三种分析单位验证' })
  const input = JSON.parse(await readFile(path.join(process.cwd(), 'tests/fixtures/station17-line.json'), 'utf8'))
  input.wavelength_nm = Number(input.wavelength_nm.toFixed(4))
  input.actual_wavelength_nm = Number(input.actual_wavelength_nm.toFixed(4))
  input.standard_points.forEach((point) => { point.value *= 1000 })
  input.valid_range_min = 1
  input.valid_range_max = 5000
  method = await call(page, `/api/v1/methods/${method.id}/lines`, input)
  const lineId = method.changed_line_id
  method = await call(page, `/api/v1/methods/${method.id}/publish`, {})
  const originalHash = method.published_version.content_sha256
  const go = async (label) => {
    await navigate(page, 'methods', label, '.methods-page')
    const picker = page.getByLabel('选择编辑方法')
    await picker.locator(`option[value="${method.id}"]`).waitFor({ state: 'attached' })
    if (await picker.inputValue() !== String(method.id)) await picker.selectOption(String(method.id))
    return page.getByTestId('methods-page')
  }
  const saveMethod = async () => {
    const pending = page.waitForResponse((response) => response.url().endsWith(`/api/v1/methods/${method.id}`) && response.request().method() === 'PATCH')
    await page.getByRole('button', { name: '保存方法草稿', exact: true }).click()
    const response = await pending
    assert.equal(response.status(), 200)
    method = await response.json()
    await page.locator('.method-save-footer button.primary-button:enabled').waitFor()
  }
  let host = await go('方法管理与参数')
  const units = host.getByRole('combobox', { name: '分析单位', exact: true })
  for (const unit of ['ug/g', 'mg/g', '%']) assert.equal(await units.locator(`option[value="${unit}"]`).count(), 1)
  await units.selectOption('mg/g')
  await saveMethod()
  let line = method.version.lines.find((line) => line.id === lineId)
  assert.equal(line.unit, 'mg/g')
  assert.equal(line.standard_points[0].value, 1)
  assert.equal(line.valid_range_min, 0.001)
  assert.equal(line.decimal_places, 5)
  assert.equal(method.published_version.content_sha256, originalHash)
  checks.push('方法单位可明确选择三种；保存 mg/g 同步标准值、有效范围、小数位数，原发布哈希保持')

  host = await go('分析谱线')
  await host.locator('.spectral-line-card').filter({ has: page.locator(`strong[title="${input.element} ${input.wavelength_nm.toFixed(4)} nm"]`) }).click()
  const editor = host.locator('.spectral-editor-surface')
  const decimals = editor.locator('label.field').filter({ has: page.getByText('小数位数', { exact: true }) }).locator('input')
  await editor.getByRole('combobox', { name: '单位', exact: true }).selectOption('%')
  assert.equal(await editor.getByLabel('有效下限', { exact: true }).inputValue(), '0.0001')
  assert.equal(await editor.getByLabel('小数位数', { exact: true }).inputValue(), '6')
  assert.equal(await editor.locator('.standard-points-table tbody tr').first().locator('td').nth(2).locator('input').inputValue(), '0.1')
  let writes = 0
  const listener = (request) => { if (request.url().endsWith(`/lines/${lineId}`) && request.method() === 'PATCH') writes++ }
  page.on('request', listener)
  await decimals.fill('11')
  await decimals.blur()
  await editor.getByRole('button', { name: '保存谱线', exact: true }).click()
  assert.equal(writes, 0)
  await decimals.fill('6')
  await decimals.blur()
  const pending = page.waitForResponse((response) => response.url().endsWith(`/lines/${lineId}`) && response.request().method() === 'PATCH')
  await editor.getByRole('button', { name: '保存谱线', exact: true }).click()
  assert.equal((await pending).status(), 200)
  page.off('request', listener)
  const saved = await call(page, `/api/v1/methods/${method.id}/lines`)
  line = saved.lines.find((line) => line.id === lineId)
  assert.equal(line.unit, '%')
  assert.equal(line.standard_points[0].value, 0.1)
  checks.push('逐线切换 % 立即换算；0.0001 有效范围可保存，小数位数 11 零提交')
  await host.locator('.spectral-list-surface').getByRole('button', { name: '添加谱线', exact: true }).click()
  assert.equal(await editor.getByRole('combobox', { name: '单位', exact: true }).inputValue(), 'mg/g')
  checks.push('新谱线继承方法 mg/g，默认标准值与小数位数同步缩放')

  for (const [theme, width] of [['light', 1440], ['dark', 1060]]) {
    await call(page, '/api/v1/settings', { display: { theme } }, 'PATCH')
    await page.setViewportSize({ width, height: 1000 })
    await page.getByRole('button', { name: '刷新服务状态', exact: true }).click()
    await page.waitForFunction((theme) => document.documentElement.dataset.theme === theme, theme)
    host = await go('方法管理与参数')
    await host.getByRole('combobox', { name: '分析单位', exact: true }).scrollIntoViewIfNeeded()
    if (output) await page.screenshot({ path: path.join(output, `analysis-unit-${theme}.png`) })
  }
  checks.push('明暗主题、1440/1060 窗口下单位选择可见可用')
  method = await call(page, `/api/v1/methods/${method.id}/publish`, {})
  await call(page, `/api/v1/methods/${method.id}/open`, {})
  await page.reload()
  await page.getByTestId('workspace').waitFor()
  await navigate(page, 'analysis-tests', '样品分析', '.analysis-page')
  await page.locator('.analysis-run-list button').filter({ hasText: 'S17 完成批次' }).click()
  await page.getByRole('button', { name: '曲线图', exact: true }).click()
  await page.getByText('分析值 (%)', { exact: true }).waitFor()
  const ticks = await page.locator('.simple-axis-y-scale .simple-axis-tick').allTextContents()
  assert.ok(ticks.length >= 2 && ticks.some((tick) => Number(tick.trim()) > 0 && Number(tick.trim()) < 1), JSON.stringify(ticks))
  if (output) await page.screenshot({ path: path.join(output, 'percentage-curve.png') })
  await page.getByRole('button', { name: '样品结果', exact: true }).click()
  await page.getByText('0.000950 %', { exact: true }).waitFor()
  if (output) await page.screenshot({ path: path.join(output, 'percentage-result.png') })
  checks.push('固定强度黄金批次的百分曲线有小数刻度，样品结果显示 0.000950 %')
}
