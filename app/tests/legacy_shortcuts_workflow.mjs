import assert from 'node:assert/strict'
import path from 'node:path'
import { call } from './contract_browser_support.mjs'

// Run only with an isolated database, through either Vite or the packaged WebView2.
export async function checkLegacyShortcuts(page, result, output) {
  const bar = page.getByRole('navigation', { name: '常用快捷方式' })
  const button = name => bar.getByRole('button', { name, exact: true })
  const check = text => { result.checks.push(text); console.log(`PASS: ${text}`) }
  const home = async () => {
    await page.locator('[data-navigation-group="workspace"]').click()
    await page.getByTestId('workspace').waitFor()
  }
  const reload = async () => {
    await page.reload(); await page.getByTestId('workspace').waitFor()
    await button('样品分析').waitFor()
  }
  await button('样品分析').waitFor()
  assert.equal(await bar.getByRole('button').count(), 8)
  const labels = await bar.getByRole('button').evaluateAll(buttons => buttons.map(button => ({
    text: button.textContent.trim(), name: button.getAttribute('aria-label'), hint: button.parentElement.title
  })))
  assert.ok(labels.every(button => button.text === '' && button.name && button.hint.includes(button.name)))
  const icons = await bar.locator('img').evaluateAll(items => items.map(img => ({
    loaded: img.complete && img.naturalWidth === 256 && img.naturalHeight === 256,
    transparent: img.alt === '', pixelated: getComputedStyle(img).imageRendering
  })))
  assert.ok(icons.every(img => img.loaded && img.transparent && img.pixelated === 'auto'))
  check('Eight Qwen-redrawn 256px icons load with smooth scaling, icon-only buttons, hover titles and accessible names')

  const current = await call(page, '/api/v1/methods/current')
  const currentUrl = /\/api\/v1\/methods\/current$/
  const noMethod = route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ...current, method_id: null }) })
  await page.route(currentUrl, noMethod); await reload()
  assert.equal(await button('样品摄谱').isDisabled(), true)
  assert.equal(await button('样品分析').isDisabled(), true)
  assert.ok((await button('样品摄谱').locator('..').getAttribute('title')).includes('请先选择'))
  assert.equal(await button('预录样号').isDisabled(), true)
  assert.equal(await button('打开方法').isEnabled(), true)
  await page.unroute(currentUrl, noMethod); await reload()
  check('Missing current method disables queue, capture and analysis with reasons; method selection remains available')

  const mutations = []
  const observe = request => {
    if (['POST', 'PUT', 'DELETE'].includes(request.method()) && !request.url().includes('/auth/') &&
      !request.url().endsWith('/methods/reference-offset'))
      mutations.push(`${request.method()} ${new URL(request.url()).pathname}`)
  }
  page.on('request', observe)
  await button('新建方法').click()
  await page.locator('.method-composer').waitFor()
  const composerName = page.locator('.method-composer input')
  await composerName.fill('QA-kept-draft')
  await button('新建方法').click()
  assert.equal(await composerName.inputValue(), 'QA-kept-draft')
  await page.locator('.method-composer').getByRole('button', { name: '取消', exact: true }).click()
  await home(); await button('新建方法').click()
  await page.locator('.method-composer').waitFor()
  await page.locator('.method-composer').getByRole('button', { name: '取消', exact: true }).click()
  check('New method opens the existing form from another page and repeated clicks preserve its draft')

  await home(); await button('方法另存为').click()
  await page.locator('.method-composer').waitFor()
  assert.ok((await composerName.inputValue()).endsWith('-副本'))
  await page.locator('.method-composer').getByRole('button', { name: '取消', exact: true }).click()
  const description = page.locator('.method-identity textarea')
  const previousDescription = await description.inputValue()
  await description.fill('QA unsaved shortcut check')
  await page.locator('.method-context-status .version-chip').filter({ hasText: '待保存' }).waitFor()
  await button('方法另存为').click()
  await page.getByText('请先保存当前修改，再另存为', { exact: true }).waitFor()
  assert.equal(await page.locator('.method-composer').count(), 0)
  assert.equal(await description.inputValue(), 'QA unsaved shortcut check')
  await description.fill(previousDescription)
  check('Save as waits for loaded method state and refuses unsaved edits without discarding them')

  await button('分析谱线').click()
  await page.waitForFunction(() => document.querySelector('.methods-page')?.dataset.navigationView === 'lines')
  assert.equal(await button('分析谱线').getAttribute('aria-current'), 'page')
  await button('方法参数').click()
  await page.getByRole('heading', { name: '基本信息', exact: true }).waitFor()
  await description.fill('QA tab draft')
  await button('分析谱线').click(); await button('方法参数').click()
  assert.equal(await description.inputValue(), 'QA tab draft')
  await description.fill(previousDescription)
  await button('打开方法').click()
  await page.getByRole('dialog', { name: '打开方法', exact: true }).waitFor()
  await page.getByRole('button', { name: '取消打开方法', exact: true }).click()
  check('Parameters and lines open exact views, preserve edits, and Open immediately opens the method chooser')

  for (const [name, selector] of [['预录样号', '.sample-queue-page'], ['样品摄谱', '.spectroscopy-workbench'], ['样品分析', '.analysis-page']]) {
    await button(name).click(); await page.locator(selector).waitFor()
    assert.equal(await button(name).getAttribute('aria-current'), 'page')
  }
  assert.deepEqual(mutations, [])
  page.off('request', observe)
  check('Preparation, capture and analysis open existing workspaces without creating or starting tasks')

  result.layouts = []
  for (const [theme, density] of [['light', 'comfortable'], ['dark', 'compact']]) {
    await call(page, '/api/v1/settings', { display: { theme, density } }, 'PATCH')
    await page.getByRole('button', { name: '刷新服务状态', exact: true }).click()
    await page.waitForFunction(({ theme, density }) => document.documentElement.dataset.theme === theme &&
      document.documentElement.dataset.density === density, { theme, density })
    for (const [width, height] of [[1440, 1000], [1060, 680]]) {
      if (process.env.QA_CDP) await page.evaluate(({ width, height }) => window.__TAURI__.core.invoke('plugin:window|set_size', {
        value: { Logical: { width, height } }
      }), { width, height })
      else await page.setViewportSize({ width, height })
      await home()
      await page.evaluate(() => scrollTo(0, 0))
      const geometry = await bar.evaluate(el => ({ width: innerWidth, height: innerHeight,
        documentWidth: document.documentElement.scrollWidth, barWidth: el.clientWidth, barScrollWidth: el.scrollWidth,
        buttonHeight: el.querySelector('button').getBoundingClientRect().height,
        tops: [...el.querySelectorAll('button')].map(b => b.getBoundingClientRect().top),
        bottom: el.getBoundingClientRect().bottom }))
      assert.ok(geometry.documentWidth <= geometry.width + 1 && geometry.barScrollWidth <= geometry.barWidth + 1, JSON.stringify(geometry))
      assert.equal(new Set(geometry.tops).size, 1)
      assert.ok(geometry.bottom <= 100 && geometry.buttonHeight >= 32, JSON.stringify(geometry))
      const file = `shortcuts-${width}-${height}-${theme}-${density}.png`
      await page.screenshot({ path: path.join(output, file) })
      if (width === 1440 && theme === 'light') {
        const region = await bar.boundingBox()
        const lastGroup = await bar.getByRole('group').last().boundingBox()
        await page.screenshot({ path: path.join(output, 'icon-strip.png'),
          clip: { x: region.x, y: region.y, width: lastGroup.x + lastGroup.width - region.x + 16, height: region.height } })
        await page.screenshot({ path: path.join(output, 'quick-access.png'),
          clip: { x: region.x, y: 0, width: region.width, height: region.y + region.height + 4 } })
      }
      result.layouts.push({ file, ...geometry })
    }
  }
  check('Four light/dark, comfortable/compact, wide/minimum-window layouts keep all eight buttons visible in one row')

  await button('样品分析').click()
  await page.locator('.analysis-run-list button').first().click()
  await page.locator('.analysis-workbench:not(.analysis-preparing)').waitFor()
  await page.evaluate(() => scrollTo(0, 0))
  const analysisBounds = await page.locator('.analysis-workbench').evaluate(el => {
    const bounds = el.getBoundingClientRect()
    return { top: bounds.top, bottom: bounds.bottom, height: innerHeight }
  })
  assert.ok(analysisBounds.top >= 90 && analysisBounds.bottom <= analysisBounds.height + 1, JSON.stringify(analysisBounds))
  await page.screenshot({ path: path.join(output, 'analysis-with-shortcuts.png') })
  result.analysisBounds = analysisBounds
  check('An existing analysis workspace fits below the new header at minimum window height')

  await page.getByRole('button', { name: '退出登录', exact: true }).click()
  const login = async (username, password) => {
    await page.getByLabel('用户名', { exact: true }).fill(username)
    await page.getByLabel('密码', { exact: true }).fill(password)
    await page.getByRole('button', { name: '登录', exact: true }).click()
    await page.getByTestId('workspace').waitFor()
  }
  await login(process.env.QA_READ_USERNAME, process.env.QA_PASSWORD)
  await button('方法参数').waitFor()
  assert.equal(await button('新建方法').count(), 0)
  assert.equal(await button('方法另存为').count(), 0)
  assert.equal(await button('打开方法').count(), 0)
  assert.equal(await bar.getByRole('button').count(), 5)
  await button('分析谱线').click(); await page.getByTestId('methods-page').waitFor()
  await page.getByRole('button', { name: '退出登录', exact: true }).click()
  await login(process.env.QA_LIMITED_USERNAME, process.env.QA_PASSWORD)
  await page.getByRole('button', { name: '刷新服务状态', exact: true }).click()
  await page.waitForFunction(() => !document.querySelector('.topbar .spin'))
  assert.equal(await bar.getByRole('button').count(), 0)
  check('Actual limited accounts hide unauthorized actions and omit inaccessible destinations')
}
