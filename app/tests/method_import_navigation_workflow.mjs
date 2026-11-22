import assert from 'node:assert/strict'

// Regression for the partial method snapshot that previously unmounted the app.
export async function checkMethodImportNavigation(page, result) {
  const navigate = async (group, label, selector) => {
    const trigger = page.locator(`[data-navigation-group="${group}"]`)
    if (await trigger.getAttribute('aria-expanded') !== 'true') await trigger.click()
    await page.getByRole('menuitem').filter({has: page.getByText(label, {exact: true})}).click()
    await page.keyboard.press('Escape'); await page.mouse.move(900, 500)
    await page.locator(selector).waitFor()
  }
  let missing = null
  await page.route(/\/api\/v1\/methods$/, async route => {
    if (route.request().method() !== 'GET') return route.continue()
    const response = await route.fetch(), data = await response.json()
    if (missing) for (const method of data) if (method.version?.conditions) delete method.version.conditions[missing]
    return route.fulfill({response, json: data})
  })
  try {
    for (const field of [null, 'angle_exposures', 'selected_ccds']) {
      missing = field
      await navigate('tools', '导入预备摄谱文件', '[data-testid="prepared-import-page"]')
      await navigate('methods', '方法管理与参数', '[data-testid="methods-page"]')
      const methodPage = page.getByTestId('methods-page')
      if (field) {
        await methodPage.getByRole('alert').filter({hasText: '方法参数不完整'}).waitFor()
        assert.equal(await methodPage.getByRole('button', {name: '保存', exact: true}).isDisabled(), true)
      } else {
        await methodPage.getByRole('heading', {name: '转角与存储方式', exact: true}).waitFor()
        const options = await methodPage.getByLabel('选择编辑方法', {exact: true}).locator('option').count()
        assert.ok(options > 0)
      }
      assert.ok(await page.locator('[data-navigation-group="tools"]').isVisible())
      result.checks.push(field ? `缺失${field}时显示提示并保留导航，保存被阻止` : '完整方法正常显示参数及转角配置')
    }
    missing = null
    await page.getByTestId('methods-page').getByRole('button', {name: '重新读取方法', exact: true}).click()
    await page.getByRole('heading', {name: '转角与存储方式', exact: true}).waitFor()
    result.checks.push('不完整记录恢复后重新读取正常，无需重启应用')
    for (const label of ['分析谱线', '预览与打印', '方法管理与参数']) {
      await navigate('tools', '导入预备摄谱文件', '[data-testid="prepared-import-page"]')
      await navigate('methods', label, '[data-testid="methods-page"]')
      assert.ok(await page.locator('[data-navigation-group="methods"]').isVisible())
    }
    result.checks.push('导入页往返三个方法入口，应用和导航持续可用')
    await navigate('data', '重新计算', '[data-testid="postprocessing-page"]')
    const reference = await page.getByLabel('计算模式').evaluate(element => {
      const style = getComputedStyle(element)
      return {family: style.fontFamily, size: style.fontSize, height: style.height, radius: style.borderRadius}
    })
    await navigate('tools', '导入预备摄谱文件', '[data-testid="prepared-import-page"]')
    const controlStyles = await page.getByTestId('prepared-import-page').locator('.prepared-file-row input, .prepared-file-row select').evaluateAll(elements =>
      elements.map(element => {
        const style = getComputedStyle(element)
        return {family: style.fontFamily, size: style.fontSize, height: style.height, radius: style.borderRadius}
      }))
    assert.equal(controlStyles.length, 5)
    assert.ok(controlStyles.every(style => style.family === reference.family && style.size === reference.size &&
      style.height === reference.height && style.radius === reference.radius), JSON.stringify({reference, controlStyles}))
    result.checks.push('导入页五个表单控件的字体、字号、高度及圆角与重新计算一致')
    result.typography = {reference, controlStyles}
  } finally {
    await page.unroute(/\/api\/v1\/methods$/)
  }
}
