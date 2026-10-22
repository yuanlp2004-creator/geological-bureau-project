import assert from 'node:assert/strict'
import path from 'node:path'
import { call, navigate } from './contract_browser_support.mjs'

export async function checkSettingsHeader(page, result, output) {
  const check=text=>{result.checks.push(text);console.log(`PASS: ${text}`)}
  const open=()=>navigate(page,'system','软件设置','[data-testid="settings"]')
  for(const [theme,density] of [['light','comfortable'],['dark','compact']]) {
    const settings=await call(page,'/api/v1/settings')
    await call(page,'/api/v1/settings',{display:{...settings.display,theme,density}},'PATCH')
    await page.reload();await page.getByTestId('workspace').waitFor();await open()
    await page.waitForFunction(theme=>document.documentElement.dataset.theme===theme,theme)
    for(const [width,height] of [[1440,1000],[1060,680]]) {
      if(process.env.QA_CDP) await page.evaluate(({width,height})=>window.__TAURI__.core.invoke('plugin:window|set_size',{value:{Logical:{width,height}}}),{width,height})
      else await page.setViewportSize({width,height})
      await page.waitForFunction(width=>Math.abs(innerWidth-width)<2,width)
      const header=page.getByTestId('page-heading')
      await header.getByTestId('settings-save').waitFor()
      assert.equal(await header.getByRole('button',{name:'恢复默认',exact:true}).count(),1)
      assert.equal(await header.getByText('保存后生效',{exact:true}).count(),1)
      assert.equal(await page.getByTestId('settings').locator('.page-action-toolbar').count(),0)
      const rects=await header.evaluate(node=>{
        const title=node.querySelector('.app-page-heading-title').getBoundingClientRect(),actions=node.querySelector('.app-page-heading-actions').getBoundingClientRect()
        return {title:{left:title.left,right:title.right,center:title.y+title.height/2},actions:{left:actions.left,right:actions.right,center:actions.y+actions.height/2},width:document.documentElement.clientWidth,scroll:document.documentElement.scrollWidth}
      })
      assert.ok(rects.title.right<=rects.actions.left && Math.abs(rects.title.center-rects.actions.center)<2,`Title and actions must share one row: ${JSON.stringify(rects)}`)
      assert.ok(rects.scroll<=rects.width+1 && rects.actions.right<=rects.width,`Header overflow: ${JSON.stringify(rects)}`)
      result.layouts.push({theme,density,width,height})
      if((theme==='light'&&width===1440)||(theme==='dark'&&width===1060))await page.screenshot({path:path.join(output,`settings-header-${theme}.png`),fullPage:true})
    }
  }
  check('Settings title, saved-state badge, Reset and Save share one row in both window sizes and themes')
  const directory=page.getByTestId('settings').getByLabel('备份目录',{exact:true})
  const before=await call(page,'/api/v1/settings')
  await directory.fill('qa-header-backups')
  const rejected=async route=>route.request().method()==='PATCH'?route.fulfill({status:409,contentType:'application/json',body:JSON.stringify({detail:'QA header save rejected'})}):route.continue()
  await page.route('**/api/v1/settings',rejected)
  await page.getByTestId('settings-save').click()
  await page.getByText('QA header save rejected',{exact:true}).waitFor()
  assert.equal(await directory.inputValue(),'qa-header-backups')
  assert.deepEqual(await call(page,'/api/v1/settings'),before)
  await page.unroute('**/api/v1/settings',rejected)
  check('Save failure retains the settings draft without changing persisted values')
  const saved=page.waitForResponse(response=>response.url().endsWith('/api/v1/settings')&&response.request().method()==='PATCH')
  await page.getByTestId('settings-save').click();assert.equal((await saved).status(),200)
  assert.equal((await call(page,'/api/v1/settings')).directories.backups,'qa-header-backups')
  check('The header Save button still persists the original page fields through the real API')
  const reset=page.waitForResponse(response=>response.url().endsWith('/api/v1/settings/reset'))
  await page.getByTestId('page-heading').getByRole('button',{name:'恢复默认',exact:true}).click()
  assert.equal((await reset).status(),200)
  const defaults=await call(page,'/api/v1/settings')
  await page.waitForFunction(expected=>document.querySelector('[data-testid="settings"] .settings-layout input')?.value===expected,defaults.directories.backups)
  check('The header Reset button restores defaults and refreshes the settings form')
  await page.locator('[data-navigation-group="workspace"]').click();await page.getByTestId('workspace').waitFor()
  assert.equal(await page.getByTestId('settings-save').count(),0)
  assert.equal(await page.getByTestId('page-heading').getByRole('button').count(),0)
  check('Leaving Settings removes its header controls without leaking actions into another page')
}
