import assert from 'node:assert/strict'
import { call } from './contract_browser_support.mjs'

async function navigate(page, group, label, selector) {
  await page.locator(`[data-navigation-group="${group}"]`).focus()
  await page.locator(`[data-navigation-group="${group}"]`).press('ArrowRight')
  await page.getByRole('menuitem', {name:label}).press('Enter')
  await page.keyboard.press('Escape')
  await page.locator(selector).waitFor()
}

export async function checkOpenFileLayout(page, fixture, result, output) {
  const entries = [
    ['methods','方法管理与参数','.methods-page','methods'],
    ['analysis-tests','谱图查看','[data-testid="spectrum-viewer-page"]','spectra'],
    ['analysis-tests','样品分析','.analysis-workbench','analysis'],
    ['analysis-tests','色散曲线','[data-testid="dispersion-page"]','dispersion'],
    ['analysis-tests','蒸发曲线','[data-testid="evaporation-curves-page"]','evaporation'],
    ['data','重新计算','[data-testid="postprocessing-page"]','recalculate'],
    ['data','打印与导出','[data-testid="data-processing-page"]','reports'],
    ['tools','旧方法与配置迁移','[data-testid="legacy-migration-page"]','batch-methods'],
    ['tools','旧谱数据迁移','[data-testid="spectrum-migration-page"]','batch-spectra'],
    ['tools','旧结果迁移','[data-testid="result-migration-page"]','batch-results'],
    ['analysis-tests','样号与样品队列','.sample-queue-page','samples']
  ]
  const originalTheme=(await call(page,'/api/v1/settings')).display.theme
  result.openLayouts=[]
  for (const [width,height,theme] of [[1440,1000,'light'],[1060,680,'dark']]) {
    await call(page,'/api/v1/settings',{display:{theme}},'PATCH')
    await page.getByRole('button',{name:'刷新服务状态',exact:true}).click()
    await page.waitForFunction(theme=>document.documentElement.dataset.theme===theme,theme)
    if (process.env.QA_CDP) await page.evaluate(({width,height})=>window.__TAURI__.core.invoke('plugin:window|set_size',{value:{Logical:{width,height}}}),{width,height})
    else await page.setViewportSize({width,height})
    for (const [group,label,selector,purpose] of entries) {
      await page.waitForLoadState('networkidle')
      await navigate(page,group,label,selector)
      await page.waitForLoadState('networkidle')
      if (purpose === 'reports') await page.getByRole('tab',{name:'分析报告',exact:true}).click()
      const button=purpose==='samples' ? page.getByRole('button',{name:'打开样品号',exact:true})
        : page.locator(`.open-legacy-file[data-purpose="${purpose}"] > button`).filter({visible:true})
      await button.waitFor()
      await page.waitForFunction(purpose=>{const b=purpose==='samples'?[...document.querySelectorAll('.sample-queue-page button')].find(n=>n.textContent.includes('打开样品号')):document.querySelector(`.open-legacy-file[data-purpose="${purpose}"] > button`);return b && !b.disabled},purpose)
      const geometry=await button.evaluate(el=>{
        const b=el.getBoundingClientRect(),actions=el.closest('.file-actions'),a=actions?.getBoundingClientRect()
        const header=el.closest('.page-intro,.hero-row,.analysis-hero,.spectroscopy-header,.method-context-bar')
        const h=header?.getBoundingClientRect()
        return {w:innerWidth,doc:document.documentElement.scrollWidth,left:b.left,right:b.right,top:b.top,bottom:b.bottom,actions:!!actions,header:!!header,headerTop:h?.top,headerBottom:h?.bottom,headerRight:h?.right,actionsRight:a?.right,text:el.textContent}
      })
      assert.equal(geometry.actions,true,JSON.stringify({purpose,...geometry}))
      assert.equal(geometry.header,true,JSON.stringify({purpose,...geometry}))
      assert.ok(geometry.top>=geometry.headerTop-1 && geometry.bottom<=geometry.headerBottom+1,JSON.stringify({purpose,...geometry}))
      assert.ok(geometry.left>=0 && geometry.right<=geometry.w+1 && geometry.doc<=geometry.w+1,JSON.stringify({purpose,...geometry}))
      if(purpose === 'methods') assert.ok(Math.abs(geometry.headerRight-geometry.actionsRight)<=22,JSON.stringify(geometry))
      assert.ok(!geometry.text.includes('打开旧'))
      result.openLayouts.push({width,height,theme,purpose,...geometry})
      if (['methods','dispersion','recalculate','reports'].includes(purpose)) await page.screenshot({path:`${output}/open-${purpose}-${width}-${theme}.png`})
    }
  }
  await call(page,'/api/v1/settings',{display:{theme:originalTheme}},'PATCH')
  await page.getByRole('button',{name:'刷新服务状态',exact:true}).click()
  if (!process.env.QA_CDP) {
    await navigate(page,'analysis-tests','谱图查看','[data-testid="spectrum-viewer-page"]')
    const control=page.locator('[data-purpose="spectra"]')
    await control.getByRole('button',{name:'打开谱文件',exact:true}).click()
    const directory=await control.getByRole('textbox').inputValue()
    assert.ok(directory.endsWith('\\') || directory.endsWith('/'))
    assert.equal(directory,await page.evaluate(()=>localStorage.getItem('geospectrum.last-open-directory')))
    await control.getByRole('button',{name:'关闭文件打开面板'}).click()
    await navigate(page,'analysis-tests','样品分析','.analysis-workbench')
    await page.locator('[data-purpose="analysis"] > button').click()
    assert.equal(await page.locator('[data-purpose="analysis"] textarea').inputValue(),directory)
    await page.getByRole('button',{name:'关闭文件打开面板'}).click()
  }
  result.checks.push('11 个打开入口统一在标题栏操作区，1440/1060宽度及明暗主题无越界；浏览器路径入口共用最近目录')
}
