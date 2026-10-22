import assert from 'node:assert/strict'

// Verify the restored workspace, existing navigation and saved themes in browser or desktop.
export async function checkWorkspacePrerequisites(page) {
 const workspace=page.getByTestId('workspace')
 await workspace.getByRole('heading',{name:'尚未选择运行方法',exact:true}).waitFor()
 await workspace.getByText('等待选择',{exact:true}).waitFor()
 await workspace.getByRole('heading',{name:'常用入口',exact:true}).waitFor()
 assert.equal(await workspace.locator('.workspace-flow-entry').count(),0)
 assert.equal(await workspace.locator('.workspace-technical-details').count(),0)
 await workspace.getByRole('heading',{name:'服务通道',exact:true}).waitFor()
}

export async function checkWorkspaceLayout(page,call,output) {
 const checks=[]
 await page.locator('[data-navigation-group="workspace"]').click()
 await page.getByTestId('workspace').waitFor()
 const workspace=page.getByTestId('workspace')
 assert.equal(await workspace.getByText('等待选择',{exact:true}).count(),0)
 await workspace.getByRole('button',{name:'样品队列',exact:true}).click()
 await page.locator('.sample-queue-page').waitFor()
 await page.locator('[data-navigation-group="workspace"]').click()
 await workspace.waitFor()
 await workspace.getByRole('button',{name:/方法管理 版本、条件与当前方法/}).click()
 await page.getByTestId('methods-page').waitFor()
 await page.locator('[data-navigation-group="workspace"]').click()
 await workspace.waitFor()
 checks.push('restored method, messages and side-column layout; original sample-queue and method entries navigate correctly')
 for(const [theme,density] of [['light','comfortable'],['dark','compact']]){
  await call(page,'/api/v1/settings',{display:{theme,density}},'PATCH')
  await page.getByRole('button',{name:'刷新服务状态',exact:true}).click()
  await page.waitForFunction(({theme,density})=>document.documentElement.dataset.theme===theme&&document.documentElement.dataset.density===density,{theme,density})
  for(const width of [1060,1440,1920]){
   await page.setViewportSize({width,height:900})
   const geometry=await page.evaluate(()=>({viewport:innerWidth,scroll:document.documentElement.scrollWidth}))
   assert.ok(geometry.scroll<=geometry.viewport+1,JSON.stringify(geometry))
   await page.screenshot({path:output+`/workspace-${theme}-${width}.png`,fullPage:true})
  }
 }
 checks.push('1060/1440/1920 viewports in actual saved light/comfortable and dark/compact themes have no window overflow')
 const desktop=await page.evaluate(()=> '__TAURI__' in window)
 assert.ok((await workspace.locator('.protocol-surface').innerText()).includes(desktop?'桌面程序':'浏览器预览'))
 await workspace.getByText('10 秒刷新',{exact:true}).waitFor()
 assert.equal(await page.getByText('构建中',{exact:true}).count(),0)
 checks.push('original diagnostics remain visible with factual runtime environment and ten-second message refresh')

 return checks
}
