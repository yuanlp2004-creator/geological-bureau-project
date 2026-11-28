import assert from 'node:assert/strict'
import path from 'node:path'
import { call, setWorkspaceTheme } from './contract_browser_support.mjs'

export async function checkPageHeading(page, label) {
  const heading=page.getByTestId('page-heading')
  await heading.getByRole('heading',{name:label,exact:true}).waitFor()
  const position=await heading.evaluate(node=>{
    const content=node.nextElementSibling
    const body=content.matches('.page-content') ? content : content.querySelector('.page-content')
    const inner=node.querySelector('.app-page-heading-inner')
    const rect=body.getBoundingClientRect(),top=node.getBoundingClientRect(),left=inner.getBoundingClientRect()
    const glyph=node.querySelector('.app-page-heading-icon > svg.page-title-glyph')
    const size=glyph?.getBoundingClientRect()
    const frame=glyph?.parentElement.getBoundingClientRect()
    return {inCard:Boolean(node.closest('.surface')),left:left.x,bodyLeft:rect.x+parseFloat(getComputedStyle(body).paddingLeft),bottom:top.bottom,bodyTop:rect.top,
      icon:size && size.width===22 && size.height===22 && frame.width===36 && frame.height===36 && glyph.getAttribute('aria-hidden')==='true'}
  })
  assert.ok(!position.inCard && position.icon && Math.abs(position.left-position.bodyLeft)<2 && position.bottom<=position.bodyTop+1,`${label}: main title belongs above the page body at its left edge ${JSON.stringify(position)}`)
  return position
}

export async function checkPageLayout(page, result, output) {
  const caps = await call(page,'/api/v1/capabilities')
  const entries = caps.capabilities.flatMap(item => item.navigation_entries)
  const methods = await call(page,'/api/v1/methods')
  const method = methods.find(item => item.status === 'active')
  assert.ok(method,'A published isolated method is required for navigation checks')
  await call(page,'/api/v1/methods/current',{method_id:method.id})
  await page.reload(); await page.getByTestId('workspace').waitFor()
  const originalTheme=await page.getByTestId('app-shell').getAttribute('data-theme')
  result.pageLayouts=[];result.gatedEntries=[]
  try {
    for (const [theme,width,height] of [['light',1440,1000],['dark',1060,680]]) {
      await setWorkspaceTheme(page,theme)
      if (theme === 'dark') {
        await page.reload();await page.getByTestId('workspace').waitFor()
        assert.equal(await page.evaluate(()=>document.documentElement.dataset.theme),theme)
        assert.equal(await page.getByRole('button',{name:'切换明暗主题',exact:true}).getAttribute('aria-pressed'),'true')
      }
      if(process.env.QA_CDP) await page.evaluate(({width,height})=>window.__TAURI__.core.invoke('plugin:window|set_size',{value:{Logical:{width,height}}}),{width,height})
      else await page.setViewportSize({width,height})
      await page.waitForFunction(width=>Math.abs(innerWidth-width)<2,width)
      for(const entry of entries) {
        // Each layout check starts from home so an unrelated workbench load does not gate navigation.
        await page.locator('[data-navigation-group="workspace"]').click()
        await page.getByTestId('workspace').waitFor()
        const trigger=page.locator(`[data-navigation-group="${entry.group}"]`)
        if(entry.group==='workspace') await trigger.click()
        else {
          await trigger.focus();await trigger.press('ArrowRight')
          const menu=page.getByRole('menuitem',{name:entry.label})
          if(await menu.getAttribute('aria-disabled')==='true') {
            result.gatedEntries.push({theme,key:entry.key});await page.keyboard.press('Escape');continue
          }
          await menu.click();await page.keyboard.press('Escape')
        }
        await page.waitForFunction(label=>document.querySelector('.breadcrumbs strong')?.textContent===label,entry.label)
        await page.locator('.page-content').first().waitFor()
        if(entry.page==='workspace') {
          assert.equal(await page.getByTestId('workspace').locator('.page-action-toolbar').count(),0)
          assert.equal(await page.getByRole('button',{name:'样品队列',exact:true}).count(),0)
          if(theme==='light') await page.screenshot({path:path.join(output,'workspace-no-redundant-shortcut.png'),fullPage:true})
        }
        const decorative=['dispersion','sample-acquisition','evaporation-acquisition','analysis'].includes(entry.page)
        if(!decorative) assert.equal(await page.locator('.main-area .page-content h1:visible').count(),0,entry.label)
        if(!decorative) {
          await checkPageHeading(page,entry.label)
        }
        if(['sample-acquisition','evaporation-acquisition'].includes(entry.page)) await page.getByRole('heading',{name:'摄谱工作台',exact:true}).waitFor()
        const designedPages=['settings','users','audit','migration','maintenance','help','evaporation-curves','samples','spectra','reports','postprocessing','acquisition']
        if(designedPages.includes(entry.page)) {
          await page.locator('.section-heading:visible').first().waitFor()
          const invalid=await page.locator('.section-heading:visible').evaluateAll(headings=>headings.filter(node=>!node.closest('.surface')||node.querySelector('svg,img')||!node.querySelector('h2')).length)
          assert.equal(invalid,0,`${entry.label}: card subtitles must stay plain and compact`)
        }
        const size=await page.evaluate(()=>({width:document.documentElement.clientWidth,scroll:document.documentElement.scrollWidth}))
        assert.equal(await page.evaluate(()=>document.documentElement.dataset.theme),theme)
        assert.ok(size.scroll<=size.width+1,`${entry.label}: horizontal overflow ${JSON.stringify(size)}`)
        assert.equal(await page.locator('.page-content .page-intro:visible, .page-content > .hero-row:visible').count(),0,`${entry.label}: old title gap`)
        const reflowPages=['users','audit','about','migration','maintenance','help','evaporation-curves','samples','spectra','reports','postprocessing']
        if(reflowPages.includes(entry.page)) {
          if(theme==='light') await page.waitForLoadState('networkidle')
          assert.equal(await page.locator('.main-area .page-content').first().locator(':scope > .page-action-toolbar:visible').count(),0,`${entry.label}: detached action row`)
          const misplaced=await page.locator('.main-area .page-content button:visible').evaluateAll(buttons=>buttons
            .filter(button=>/^(刷新|刷新数据|刷新中…|重新检测|重新诊断)$/.test(button.textContent.trim()))
            .filter(button=>!button.closest('.surface-heading,.task-context,.spectrum-query-panel,.queue-context,.output-workspace-toolbar,.product-header'))
            .map(button=>button.textContent.trim()))
          assert.deepEqual(misplaced,[],`${entry.label}: refresh outside its content context`)
          if(entry.page==='migration') {
            const header=page.locator('.migration-source-surface > .surface-heading')
            assert.equal(await header.locator('button:not([type="button"])').count(),0,`${entry.label}: header actions must not submit the migration form`)
          }
          if(theme==='light') await page.screenshot({path:path.join(output,`reflow-${entry.key}.png`),fullPage:true})
        }
        result.pageLayouts.push({theme,width,height,key:entry.key})
        if(entry.page==='spectra' && theme==='dark') await page.screenshot({path:path.join(output,'spectrum-no-module-title.png'),fullPage:true})
      }
    }
  } finally {
    await setWorkspaceTheme(page,originalTheme)
  }
  assert.ok(result.pageLayouts.some(item=>item.key==='tools.devices'))
  assert.ok(result.pageLayouts.some(item=>item.key==='analysis-tests.spectra'))
  result.checks.push('Reachable navigation pages fit both themes/window sizes; decorative main titles sit above the page at its left edge and cards keep plain subtitles')
}
