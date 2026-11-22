import assert from 'node:assert/strict'
import path from 'node:path'
import {call as rawCall,navigate} from './contract_browser_support.mjs'
import {checkMethodSave} from './method_save_workflow.mjs'
import {checkDeviceDebug} from './device_debug_workflow.mjs'
import {checkUsersRoles} from './users_roles_workflow.mjs'
import {checkDataOutput} from './intensity_output_workflow.mjs'

async function call(page,url,body,method=body===undefined?'GET':'POST'){
  for(let attempt=0;;attempt++){
    try{return await rawCall(page,url,body,method)}
    catch(error){if(method!=='GET'||attempt>=2||!String(error).includes('Failed to fetch'))throw error;await page.waitForTimeout(200)}
  }
}

export async function checkOtherPageButtons(page,fixture,result,output){
  const check=text=>{result.checks.push(text);console.log(`PASS: ${text}`)}
  const entries=(await call(page,'/api/v1/capabilities')).capabilities.flatMap(item=>item.navigation_entries)
  const verifyEntry=async entry=>{
    if(['dispersion','sample-acquisition','evaporation-acquisition'].includes(entry.page)&&entry.view!=='curve')
      await page.locator('.spectroscopy-modes button[aria-current="page"]').filter({hasText:entry.label}).waitFor()
    else await page.getByRole('heading',{name:entry.label,exact:true}).first().waitFor()
  }
  const go=async (name,view,selector='.page-content')=>{
    await page.waitForFunction(()=>![...document.querySelectorAll('.spectroscopy-modes button')].some(button=>button.disabled))
    const entry=entries.find(item=>item.page===name&&(!view||item.view===view));assert.ok(entry,`${name}/${view}`)
    if(entry.group==='workspace')await page.locator('[data-navigation-group="workspace"]').click()
    else await navigate(page,entry.group,entry.label,selector)
    if(entry.page!=='workspace')await verifyEntry(entry)
    return page.locator(selector).filter({visible:true})
  }
  await call(page,'/api/v1/methods/current',{method_id:fixture.method_id})
  await page.reload();await page.getByTestId('workspace').waitFor()
  const visited=[]
  for(const entry of entries){
    await page.waitForFunction(()=>![...document.querySelectorAll('.spectroscopy-modes button')].some(button=>button.disabled))
    if(entry.group==='workspace')await page.locator('[data-navigation-group="workspace"]').click()
    else {
      await navigate(page,entry.group,entry.label,'.page-scroll-region')
      await verifyEntry(entry)
    }
    visited.push({key:entry.key,label:entry.label,page:entry.page,view:entry.view})
    // Let the entered page publish its loading/session guard before checking the next destination.
    await page.waitForTimeout(250)
  }
  result.pages=visited
  check(`${visited.length}个已注册入口逐页打开；按钮声明与页面/后端调用链对应归档`)

  await go('settings',null,'[data-testid="settings"]')
  const settings=page.getByTestId('settings'),directory=settings.getByLabel('备份目录',{exact:true})
  const initial=await directory.inputValue(),chosen='C:\\按钮验证\\归档\\备份'
  if(process.env.QA_CDP){
    await page.evaluate(value=>{
      const bridge=window.chrome.webview,original=bridge.postMessage
      window.__directoryOriginal=original
      bridge.postMessage=function(message){const command=typeof message==='string'?JSON.parse(message):message
        if(command.cmd==='select_backup_directory'){queueMicrotask(()=>window.__TAURI_INTERNALS__.runCallback(command.callback,value));return}
        return original.call(bridge,message)}
    },chosen)
  }else page.once('dialog',dialog=>dialog.accept(chosen))
  await settings.getByTitle('选择目录',{exact:true}).click()
  await page.waitForFunction(value=>document.querySelector('[data-testid="settings"] input')?.value===value,chosen)
  assert.equal(await directory.inputValue(),chosen)
  await page.getByRole('button',{name:'刷新服务状态',exact:true}).click()
  await page.waitForFunction(()=>!document.querySelector('.topbar .spin'))
  assert.equal(await directory.inputValue(),chosen)
  await page.screenshot({path:path.join(output,'settings-directory-draft.png'),fullPage:true})
  if(process.env.QA_CDP)await page.evaluate(()=>{const bridge=window.chrome.webview;bridge.postMessage=window.__directoryOriginal})
  else page.once('dialog',dialog=>dialog.dismiss())
  // A cancelled native selection is checked with the same bridge; no OS picker is opened in QA.
  if(process.env.QA_CDP)await page.evaluate(()=>{const bridge=window.chrome.webview,original=bridge.postMessage
    bridge.postMessage=function(message){const command=typeof message==='string'?JSON.parse(message):message
      if(command.cmd==='select_backup_directory'){queueMicrotask(()=>window.__TAURI_INTERNALS__.runCallback(command.callback,null));return}
      return original.call(bridge,message)}})
  await settings.getByTitle('选择目录',{exact:true}).click()
  await page.waitForFunction(()=>!document.querySelector('button[title="选择目录"]')?.disabled)
  assert.equal(await directory.inputValue(),chosen)
  if(process.env.QA_CDP)await page.evaluate(()=>{window.chrome.webview.postMessage=window.__directoryOriginal})
  assert.equal((await call(page,'/api/v1/settings')).directories.backups,initial)
  check('备份目录选择保留完整含中文路径；取消保持草稿；选择动作不自动保存')

  await go('samples',null,'.sample-queue-page')
  let host=page.locator('.sample-queue-page')
  await host.getByLabel('选择样品队列').selectOption(String(fixture.queue_id))
  await host.locator(`[data-sample-id="${fixture.queue_item_ids[1]}"]`).click()
  const input=host.getByLabel('样品名',{exact:true})
  await input.fill('INSERT')
  let response=page.waitForResponse(r=>r.url().includes(`/sample-queues/${fixture.queue_id}`)&&r.request().method()==='PATCH')
  await host.getByRole('button',{name:'插入样品',exact:true}).click();assert.equal((await response).status(),200)
  let queue=await call(page,`/api/v1/sample-queues/${fixture.queue_id}`)
  assert.deepEqual(queue.items.map(item=>item.pre_name),['QUEUEA','INSERT','QUEUEB'])
  await input.fill('102');await input.press('Enter')
  await page.waitForFunction(()=>[...document.querySelectorAll('[data-sample-id]')].some(node=>node.textContent.includes('102')))
  queue=await call(page,`/api/v1/sample-queues/${fixture.queue_id}`)
  assert.equal(queue.items.at(-1).pre_name,'102')
  const failSam=route=>route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({detail:'SAM导出故障验证'})})
  await page.route('**/api/v1/sample-queues/*/export*',failSam)
  await host.getByRole('button',{name:'导出 SAM',exact:true}).click()
  await page.getByText('SAM导出故障验证',{exact:true}).waitFor()
  assert.ok(await host.getByRole('button',{name:'导出 SAM',exact:true}).isEnabled())
  assert.equal((await call(page,`/api/v1/sample-queues/${fixture.queue_id}`)).items.length,4)
  await page.unroute('**/api/v1/sample-queues/*/export*',failSam)
  check('样号插入作用于当前光标之前；回车连续录入保留；SAM导出失败可见且队列不变')

  await go('sample-acquisition',null,'[data-testid="sample-acquisition-page"]')
  host=page.locator('[data-testid="sample-acquisition-page"]')
  await host.locator(`[data-task-id="${fixture.queue_task_id}"]`).getByRole('button',{name:'进入摄谱',exact:true}).click()
  const consoleHost=host.getByTestId('spectroscopy-console')
  await consoleHost.getByRole('button',{name:'插入样品',exact:true}).click()
  let dialog=host.getByRole('dialog',{name:'预录样号',exact:true})
  await dialog.waitFor()
  await dialog.getByLabel('选择样品队列').locator(`option[value="${fixture.queue_id}"]`).waitFor({state:'attached'})
  assert.equal(await dialog.getByLabel('选择样品队列').inputValue(),String(fixture.queue_id))
  assert.equal(await host.getByRole('dialog',{name:/新建/}).count(),0)
  await dialog.getByRole('button',{name:'关闭',exact:true}).click()
  const select=consoleHost.getByLabel('样品编号',{exact:true})
  const pendingBefore=await select.locator('optgroup option').count();assert.ok(pendingBefore>0)
  await consoleHost.getByRole('button',{name:'清除待测样号',exact:true}).click()
  assert.equal(await select.locator('optgroup option').count(),0)
  assert.equal(await select.inputValue(),'')
  assert.equal((await call(page,`/api/v1/sample-queues/${fixture.queue_id}`)).items.length,4)
  assert.equal((await call(page,'/api/v1/acquisitions/tasks')).some(item=>item.id===fixture.queue_task_id),true)
  check('摄谱插入打开当前队列的样号表；清除移走本次待测列表，保存队列/任务/已采数据保持')

  await go('postprocessing','recalculate','[data-testid="postprocessing-page"]')
  host=page.getByTestId('postprocessing-page')
  let section=host.locator('.postprocessing-recalculation-surface .postprocessing-list-section').first()
  const countSelected=section.locator('input[type="checkbox"]:checked')
  await section.locator('input[type="checkbox"]').first().waitFor()
  await section.getByRole('button',{name:'全选',exact:true}).click();const selectedCount=await countSelected.count();assert.ok(selectedCount>0)
  await section.getByRole('button',{name:'全选',exact:true}).click();assert.equal(await countSelected.count(),selectedCount)
  await section.getByRole('button',{name:'反选',exact:true}).click();assert.equal(await countSelected.count(),0)
  assert.equal(await host.getByText('旧记录区间查看与 EDT 转换',{exact:true}).count(),0)
  await go('prepared-import',null,'[data-testid="prepared-import-page"]')
  host=page.getByTestId('prepared-import-page')
  await host.getByLabel('导入蒸发文件',{exact:true}).waitFor()
  assert.equal(await host.getByRole('button',{name:'全部选择',exact:true}).count(),1)
  check('重算来源全选幂等、反选翻转；EDT导入移至独立工具入口，完整转换见prepared_import_workflow')

  await go('analysis',null,'.analysis-page')
  host=page.locator('.analysis-page')
  await host.locator('.analysis-run-list button').filter({hasText:'S17 完成批次'}).click()
  const runId=fixture.review_run_id
  let run=await call(page,`/api/v1/analyses/runs/${runId}/quality/recalculate`,{})
  const line=run.curves.lines[0]
  await call(page,`/api/v1/analyses/runs/${runId}/curves/${line.line_id}/actions`,{action:'set_active',point_index:line.workspace.points[0].point_index,active:false,reason:'按钮停用验证'})
  await page.getByRole('button',{name:'刷新',exact:true}).first().click()
  await host.locator('.analysis-run-list button').filter({hasText:'S17 完成批次'}).click()
  response=page.waitForResponse(r=>r.url().includes('/actions')&&r.request().method()==='POST')
  await host.getByRole('button',{name:'全部还原',exact:true}).click()
  const restoreResponse=await response
  assert.equal(restoreResponse.request().postDataJSON().restore_activation,false)
  run=await restoreResponse.json()
  assert.equal(run.curves.lines[0].workspace.points[0].active,false)
  await page.screenshot({path:path.join(output,'curve-restore-disabled.png'),fullPage:true})
  check('曲线全部还原恢复原始强度，停用点保持停用；兼容API默认仍保留')
  const measuredRun=await call(page,`/api/v1/analyses/runs/${fixture.run_id}`)
  await host.locator('.analysis-run-list button').filter({hasText:measuredRun.name}).click()
  await host.getByRole('button',{name:'谱图与测量',exact:true}).click()
  const spectrum=host.getByRole('region',{name:'分析完整谱图'})
  await spectrum.locator('svg.spectrum-plot .spectrum-line').waitFor()
  const range=()=>spectrum.locator('svg.spectrum-plot').getAttribute('aria-label')
  const yTicks=()=>spectrum.locator('.plot-tick-label[text-anchor="end"]').allTextContents()
  await spectrum.getByRole('button',{name:'纵向放大',exact:true}).click();const zoomed=await yTicks()
  await spectrum.getByRole('button',{name:'适合图像',exact:true}).click();assert.deepEqual(await yTicks(),zoomed)
  await spectrum.getByRole('button',{name:'纵向还原',exact:true}).click();assert.notDeepEqual(await yTicks(),zoomed)
  check('分析谱图适合图像只还原横向，纵向还原独立有效')

  await checkMethodSave(page,fixture,result,output)
  await checkDataOutput(page,fixture,result,output)
  await go('maintenance',null,'[data-testid="maintenance-page"]')
  host=page.getByTestId('maintenance-page')
  response=page.waitForResponse(r=>r.url().includes('/backups')&&r.request().method()==='POST')
  await host.getByRole('button',{name:'创建备份',exact:true}).click();assert.equal((await response).status(),200)
  await host.getByRole('button',{name:'校验',exact:true}).first().click()
  await page.getByText('备份校验通过',{exact:true}).waitFor()
  check('维护备份与校验按钮实际生成并验证隔离数据库副本')
  await checkDeviceDebug(page,fixture,result,output)
  let auth=await call(page,'/api/v1/auth/login',{username:'spec-gap-operator',password:'correct-horse'})
  await page.evaluate(token=>sessionStorage.setItem('geospectrum.token',token),auth.access_token)
  await page.reload();await page.getByTestId('workspace').waitFor()
  // New account/role controls have no old-software counterpart; validate the existing permission behavior.
  await checkUsersRoles(page,fixture,result,output)
  auth=await call(page,'/api/v1/auth/login',{username:'spec-gap-operator',password:'correct-horse'})
  await page.evaluate(token=>sessionStorage.setItem('geospectrum.token',token),auth.access_token)
  await page.reload();await page.getByTestId('workspace').waitFor()
  check('方法生命周期、设备调试/汞灯安全收尾、用户角色与只读权限复用既有真实UI回归通过')

  for(const [theme,width,height] of [['light',1440,1000],['dark',1060,720]]){
    if(process.env.QA_CDP)await page.evaluate(value=>window.__TAURI__.core.invoke('plugin:window|set_size',{value:{Logical:value}}),{width,height})
    else await page.setViewportSize({width,height})
    await call(page,'/api/v1/settings',{display:{theme,density:'compact'}},'PATCH')
    await page.reload();await page.getByTestId('workspace').waitFor()
    await go('samples',null,'.sample-queue-page')
    assert.equal(await page.evaluate(()=>document.documentElement.dataset.theme),theme)
    await page.screenshot({path:path.join(output,`other-buttons-${theme}.png`),fullPage:true})
    result.layouts.push({theme,width,height})
  }
}
