import assert from 'node:assert/strict'
import path from 'node:path'
import { writeFile } from 'node:fs/promises'
import { call, navigate } from './contract_browser_support.mjs'

export async function checkDataOutput(page, fixture, result, output) {
  const mark = (id,message) => { result.checks.push({id,message}); console.log(`PASS ${id}: ${message}`) }
  await navigate(page,'data','打印与导出','[data-testid="data-processing-page"]')
  const host=page.getByTestId('data-processing-page'),report=host.getByTestId('reports-page')
  assert.deepEqual(await host.getByRole('tab').allTextContents(),['分析报告','强度数据'])
  assert.equal(await host.getByRole('button',{name:'重算与已迁移结果导出',exact:true}).count(),0)
  mark(1,'两个输出页签保留，已移除重算与迁移结果导出入口')
  await call(page,`/api/v1/analyses/runs/${fixture.run_id}/results/merge`,{reason:'output windows QA'})
  await host.getByRole('button',{name:'刷新',exact:true}).click()
  const run=await call(page,`/api/v1/analyses/runs/${fixture.run_id}`)
  await navigate(page,'analysis-tests','样品分析','.analysis-page')
  await page.locator('.analysis-run-list button').filter({hasText:run.name}).click()
  await navigate(page,'data','打印与导出','[data-testid="reports-page"]')
  await report.getByTestId('report-current-source').filter({hasText:run.name}).waitFor()
  await report.getByLabel('报告编号（可选）').fill('WINDOWS-OUTPUT-QA')
  await host.getByRole('tab',{name:'强度数据',exact:true}).click()
  for(const empty of await host.getByTestId('analysis-intensity-output').locator('.empty-state').all())assert.ok((await empty.boundingBox()).height<=90)
  await host.screenshot({path:path.join(output,'output-intensity-empty.png')})
  await host.getByRole('tab',{name:'分析报告',exact:true}).click()
  assert.equal(await report.getByLabel('报告编号（可选）').inputValue(),'WINDOWS-OUTPUT-QA')
  const creating=page.waitForResponse(r=>/\/api\/v1\/reports$/.test(r.url()) && r.request().method()==='POST')
  await report.getByRole('button',{name:'建立报告版本',exact:true}).click()
  fixture.report_id=(await (await creating).json()).id
  await report.getByRole('button',{name:'预览',exact:true}).click()
  await report.getByRole('dialog').getByRole('button',{name:'关闭',exact:true}).click()
  await report.getByRole('button',{name:'确认报告',exact:true}).click()
  await report.getByRole('button',{name:'PDF',exact:true}).waitFor()
  // Only the main automated workflow intercepts the Save As boundary. The native
  // desktop suite reloads the page and exercises actual Windows dialogs separately.
  await page.evaluate(()=>{
    window.__outputFiles=[]
    window.__captureOutput=true
    const create=URL.createObjectURL
    window.__nativeOutputOriginals={createObjectURL:create,fetch:window.fetch,postMessage:window.chrome?.webview?.postMessage}
    URL.createObjectURL=function(blob){void blob.text().then(text=>window.__outputFiles.push(text));return create.call(URL,blob)}
    if(window.__TAURI__?.core){
      const bridge=window.chrome.webview,post=bridge.postMessage
      bridge.postMessage=function(message){const data=typeof message==='string'?JSON.parse(message):message
        if(data.cmd==='save_export_file' && window.__captureOutput){window.__outputFiles.push(new TextDecoder().decode(new Uint8Array(data.payload.bytes)));queueMicrotask(()=>window.__TAURI_INTERNALS__.runCallback(data.callback,`QA/${data.payload.fileName}`));return}
        return post.call(bridge,message)}
      const fetch=window.fetch
      window.fetch=function(input,init){const url=new URL(typeof input==='string'?input:input.url,location.href)
        if(url.hostname==='ipc.localhost' && url.pathname==='/save_export_file' && window.__captureOutput){const args=JSON.parse(init.body);window.__outputFiles.push(new TextDecoder().decode(new Uint8Array(args.bytes)));return Promise.resolve(new Response(JSON.stringify(`QA/${args.fileName}`),{status:200,headers:{'Content-Type':'application/json','Tauri-Response':'ok'}}))}
        return fetch.call(window,input,init)}
    }
  })
  for(const format of ['Excel','PDF']){
    const response=page.waitForResponse(r=>r.url().endsWith('/exports') && r.request().method()==='POST')
    await report.getByRole('button',{name:format,exact:true}).click()
    const res=await response;assert.equal(res.status(),200,await res.text())
    assert.equal(res.request().postDataJSON().download,true)
    const file=await res.json(),bytes=Buffer.from(file.content_base64,'base64')
    assert.equal(file.status,'prepared');assert.equal(file.path,null)
    assert.ok(format==='PDF'?bytes.subarray(0,4).toString()==='%PDF':bytes.toString().includes('Workbook'))
  }
  await page.waitForFunction(()=>window.__outputFiles.length>=2)
  assert.equal(await report.getByRole('button',{name:'文本',exact:true}).count(),0)
  assert.equal(await report.getByRole('button',{name:'CSV',exact:true}).count(),0)
  mark(2,'报告建立/预览/确认保留，Excel/PDF真实内容接入统一保存边界，取消保存不记为已保存')

  await host.getByRole('tab',{name:'强度数据',exact:true}).click()
  const intensity=host.getByTestId('analysis-intensity-output')
  await intensity.getByLabel('分析批次',{exact:true}).selectOption(String(fixture.run_id))
  await intensity.locator('.intensity-table-scroll tbody tr').first().waitFor()
  await intensity.getByRole('button',{name:'预览',exact:true}).click()
  const dialog=intensity.getByRole('dialog')
  await dialog.locator('iframe').contentFrame().getByRole('columnheader',{name:'强度编号',exact:true}).waitFor()
  await dialog.screenshot({path:path.join(output,'intensity-preview.png')})
  await dialog.getByRole('button',{name:'关闭',exact:true}).click()
  assert.equal(await intensity.getByRole('button',{name:'文本',exact:true}).count(),0)
  assert.equal(await intensity.getByRole('checkbox').count(),0)
  let expected
  for(const format of ['Excel','PDF']){
    const pending=page.waitForResponse(r=>r.url().endsWith('/intensity-output') && r.request().postDataJSON().export_format)
    await intensity.getByRole('button',{name:format,exact:true}).click()
    const res=await pending;assert.equal(res.status(),200,await res.text())
    const body=res.request().postDataJSON();assert.equal(body.print_intensity,false);assert.equal(body.print_to_text,false);assert.equal(body.save_intensity,false)
    const out=await res.json();assert.equal(out.files.length,1);assert.equal(out.print_job,null)
    if(expected)assert.deepEqual(out.table,expected);else expected=out.table
    const data=Buffer.from(out.files[0].content_base64,'base64')
    assert.ok(format==='PDF'?data.subarray(0,4).toString()==='%PDF':data.toString().includes('强度编号') && data.toString().includes('峰值'))
  }
  await page.waitForFunction(()=>window.__outputFiles.length>=4)
  mark(3,'强度Excel/PDF输出完整真实峰值/背景表，预览保留，不依赖文本/JSON或旧文件')

  const endpoint='**/api/v1/analyses/runs/*/intensity-output'
  let release,entered
  const gate=new Promise(resolve=>release=resolve),started=new Promise(resolve=>entered=resolve)
  await page.route(endpoint,async route=>{entered();await gate;await route.continue()},{times:1})
  await intensity.getByRole('button',{name:'Excel',exact:true}).click();await started
  await page.waitForFunction(()=>document.querySelector('[aria-label="分析批次"]')?.disabled===true)
  release()
  await page.waitForFunction(()=>document.querySelector('[aria-label="分析批次"]')?.disabled===false)
  await intensity.getByLabel('分析批次',{exact:true}).selectOption('')
  await page.route(endpoint,route=>route.fulfill({status:409,contentType:'application/json',body:JSON.stringify({detail:{message:'QA 强度矩阵不完整'}})}),{times:1})
  await intensity.getByLabel('分析批次',{exact:true}).selectOption(String(fixture.run_id))
  await intensity.getByRole('alert').waitFor()
  assert.equal(await intensity.getByRole('button',{name:'PDF',exact:true}).isDisabled(),true)
  assert.equal(await intensity.locator('.intensity-table-scroll').count(),0)
  await intensity.getByLabel('分析批次',{exact:true}).selectOption('')
  await intensity.getByLabel('分析批次',{exact:true}).selectOption(String(fixture.run_id))
  await intensity.locator('.intensity-table-scroll tbody tr').first().waitFor()
  mark(4,'输出中锁定批次，强度读取失败清空旧表并禁用输出，重选可恢复')

  const printers=await call(page,'/api/v1/analyses/printers')
  assert.ok(printers.printers.some(p=>p.name==='Microsoft Print to PDF'))
  await intensity.getByLabel('Windows 打印机',{exact:true}).selectOption('Microsoft Print to PDF')
  let printBody
  await page.route(endpoint,async route=>{printBody=route.request().postDataJSON();await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({files:[],print_job:{status:'cancelled'}})})},{times:1})
  await intensity.getByRole('button',{name:'打印',exact:true}).click()
  await page.getByText('已取消 Windows 打印',{exact:true}).waitFor()
  assert.equal(printBody.printer_name,'Microsoft Print to PDF');assert.equal(printBody.print_intensity,true)
  assert.equal(await intensity.getByLabel('分析批次',{exact:true}).inputValue(),String(fixture.run_id))
  mark(5,'打印使用真实系统打印机列表，指定打印机传入后端，取消反馈不会误报成功')

  await navigate(page,'data','重新计算','[data-testid="data-processing-page"]')
  assert.equal(await host.getByRole('heading',{name:'确切版本重算',exact:true}).count(),1)
  const processing=host.getByTestId('postprocessing-page')
  assert.equal(await processing.locator(':scope > .hero-row').count(),0)
  const originalTheme=(await call(page,'/api/v1/settings')).display.theme
  result.recalculationLayouts=[]
  for(const [width,height,theme] of [[1440,1000,'light'],[1060,680,'light'],[1060,1000,'dark']]){
    await call(page,'/api/v1/settings',{display:{theme}},'PATCH')
    await page.getByRole('button',{name:'刷新服务状态',exact:true}).click()
    if(process.env.QA_CDP)await page.evaluate(({width,height})=>window.__TAURI__.core.invoke('plugin:window|set_size',{value:{Logical:{width,height}}}),{width,height})
    else await page.setViewportSize({width,height})
    const geometry=await host.evaluate(el=>{
      const page=el.querySelector('[data-testid="postprocessing-page"]'),style=getComputedStyle(page),hero=el.querySelector(':scope > .hero-row'),first=page.querySelector('.postprocessing-legacy-tools'),heading=page.querySelector('.postprocessing-recalculation-surface .surface-heading')
      const controls=[...heading.querySelectorAll('h2,button')].map(n=>({top:n.getBoundingClientRect().top,bottom:n.getBoundingClientRect().bottom}))
      return {gap:first.getBoundingClientRect().top-hero.getBoundingClientRect().bottom,padding:style.padding,doc:document.documentElement.scrollWidth,w:innerWidth,controls}
    })
    assert.ok(geometry.gap>=0 && geometry.gap<=16,JSON.stringify(geometry))
    assert.equal(geometry.padding,'0px')
    assert.ok(geometry.doc<=geometry.w+1,JSON.stringify(geometry))
    assert.ok(Math.max(...geometry.controls.map(c=>c.top))<Math.min(...geometry.controls.map(c=>c.bottom)),JSON.stringify(geometry))
    const file=`recalculate-${width}-${height}-${theme}.png`
    await host.screenshot({path:path.join(output,file)});result.recalculationLayouts.push({width,height,theme,file,...geometry})
  }
  await call(page,'/api/v1/settings',{display:{theme:originalTheme}},'PATCH')
  await page.getByRole('button',{name:'刷新服务状态',exact:true}).click()
  const refresh=page.waitForResponse(r=>r.url().includes('/postprocessing/recalculation-options') && r.status()===200)
  await host.getByRole('button',{name:'刷新数据',exact:true}).click()
  await refresh
  await navigate(page,'data','打印与导出','[data-testid="data-processing-page"]')
  await host.getByRole('tab',{name:'强度数据',exact:true}).click()
  assert.equal(await intensity.getByLabel('分析批次',{exact:true}).inputValue(),String(fixture.run_id))
  mark(6,'重新计算和迁移工具保留，移除输出区域后两个页签状态仍保持')

  if(await toggle.getAttribute('aria-expanded')==='true'){await host.getByRole('tab',{name:'分析报告',exact:true}).click();await toggle.click()}
  result.layouts=[]
  for(const [width,height,theme] of [[1440,1000,'light'],[1060,680,'light'],[1060,1000,'dark']]){
    await call(page,'/api/v1/settings',{display:{theme,density:'comfortable'}},'PATCH')
    await page.getByRole('button',{name:'刷新服务状态',exact:true}).click()
    if(process.env.QA_CDP)await page.evaluate(({width,height})=>window.__TAURI__.core.invoke('plugin:window|set_size',{value:{Logical:{width,height}}}),{width,height})
    else await page.setViewportSize({width,height})
    for(const tab of ['分析报告','强度数据']){
      await host.getByRole('tab',{name:tab,exact:true}).click()
      const panel=tab==='分析报告'?report:intensity
      const geometry=await panel.evaluate(el=>({doc:document.documentElement.scrollWidth,w:innerWidth,gap:[...el.querySelectorAll('.surface')].find(n=>n.getClientRects().length).getBoundingClientRect().top-document.querySelector('.postprocessing-view-tabs').getBoundingClientRect().bottom,controls:[...el.querySelectorAll('button,input,select')].filter(n=>n.getClientRects().length).map(n=>({left:n.getBoundingClientRect().left,right:n.getBoundingClientRect().right}))}))
      assert.ok(geometry.doc<=geometry.w+1,JSON.stringify(geometry));assert.ok(geometry.gap<=90,JSON.stringify(geometry))
      assert.ok(geometry.controls.every(c=>c.left>=-1 && c.right<=geometry.w+1))
      const file=`output-${tab==='分析报告'?'report':'intensity'}-${width}-${height}-${theme}.png`
      await host.screenshot({path:path.join(output,file)});result.layouts.push({width,height,theme,tab,file,...geometry})
    }
  }
  mark(7,'主体上移、空白压缩，两个页签的1440/1060宽度、680高度及明暗主题无横向越界')
  await writeFile(path.join(output,'output-checks.json'),JSON.stringify(result,null,2))
}
