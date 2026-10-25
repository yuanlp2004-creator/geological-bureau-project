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
