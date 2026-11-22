export async function leaveLegacyCapture(page) {
  const close = page.getByRole('button', { name: '关闭色散处理窗口', exact: true })
  if (await close.isVisible().catch(() => false)) await close.click()
  const end = page.locator('.legacy-capture-desk:visible').getByRole('button', { name: '结束', exact: true })
  if (await end.isVisible().catch(() => false)) await end.click()
}
export async function openSpectrumReadout(scope) {
  const page = scope.page(), dialog = scope.locator('.spectrum-observer-dialog')
  if (await dialog.isVisible()) return
  await page.locator('.legacy-window-caption:visible').click({ button: 'right' })
  await page.getByRole('menuitem', { name: '谱图点位与视野', exact: true }).click()
  await dialog.waitFor()
}
export async function closeSpectrumReadout(scope) {
  const close = scope.getByRole('button', { name: '关闭谱图读数', exact: true })
  if (await close.isVisible()) await close.click()
}

export async function openViewerFiles(scope, dispersion = false) {
  const title = dispersion ? '选择色散文件' : '选择谱文件'
  await scope.locator('.legacy-view-rail > header').first().click({ button: 'right' })
  await scope.page().getByRole('menuitem', { name: title, exact: true }).click()
  const dialog = scope.getByRole('dialog', { name: title, exact: true })
  await dialog.waitFor()
  return dialog
}

export async function selectViewerFile(scope, group, dispersion = false) {
  const dialog = await openViewerFiles(scope, dispersion)
  const select = dialog.getByLabel(dispersion ? '色散数据文件' : '当前谱文件')
  await select.locator(`option[value=${JSON.stringify(group)}]`).waitFor({ state: 'attached' })
  if (await select.inputValue() === group) await dialog.getByRole('button', {
    name: dispersion ? '关闭选择色散文件' : '关闭选择谱文件', exact: true
  }).click()
  else await select.selectOption(group)
  await dialog.waitFor({ state: 'hidden' })
}

export async function openViewerPlotAction(scope, name) {
  const chart = scope.locator('svg.spectrum-plot .plot-background').first()
  await chart.click({ button: 'right', position: { x: 40, y: 35 }, force: true })
  await scope.page().getByRole('menu', { name: '谱图菜单', exact: true })
    .getByRole('menuitem', { name, exact: true }).click()
}
