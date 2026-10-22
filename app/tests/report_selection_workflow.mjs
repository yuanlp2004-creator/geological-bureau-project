import assert from 'node:assert/strict'
import path from 'node:path'
import {call,navigate} from './contract_browser_support.mjs'

// 使用真实列表摘要与详情，覆盖已有报告选择、失败恢复及乱序返回。
export async function checkReportSelection(page,result,output){
  const host=page.getByTestId('reports-page'),selector=host.locator('.report-version-selector select')
  const reports=await call(page,'/api/v1/reports')
  assert.ok(reports.length>=4)
  assert.ok(reports.every(report=>!('model' in report)))
  const selected=[]
  for(const report of reports){
    const detail=await call(page,`/api/v1/reports/${report.id}`)
    assert.ok(detail.model.rows.length)
    await selector.selectOption(String(report.id))
    await host.locator('.report-summary').getByText(`${report.report_number} v${report.version}`,{exact:true}).waitFor()
    assert.ok((await host.locator('.report-summary').innerText()).includes(`${detail.model.rows.length} 行`))
    await host.getByRole('button',{name:'预览',exact:true}).click()
    const dialog=host.getByRole('dialog'),frame=dialog.locator('iframe').contentFrame()
    await frame.getByText(report.report_number,{exact:false}).first().waitFor()
    await frame.getByText(detail.model.rows[0].sample_name,{exact:true}).first().waitFor()
    if(detail.model.source_kind==='legacy_dat'){
      await frame.getByText(detail.model.rows[0].unit || '原文件未记录单位',{exact:false}).first().waitFor()
      assert.equal(detail.model.rows[0].wavelength_nm,null)
      await dialog.screenshot({path:path.join(output,'dat-preview.png')})
    }
    await dialog.getByRole('button',{name:'关闭',exact:true}).click()
    selected.push({id:report.id,number:report.report_number,rows:detail.model.rows.length,kind:detail.model.source_kind||'analysis'})
  }
  assert.ok(selected.some(r=>r.kind==='legacy_dat'))
  result.selected_reports=selected
  result.checks.push('逐个选择并预览全部真实已有报告，含DAT空波长/无方法字段')

  const [a,b]=reports
  const detailA=await call(page,`/api/v1/reports/${a.id}`)
  let release,entered,handled
  const gate=new Promise(resolve=>release=resolve),started=new Promise(resolve=>entered=resolve),done=new Promise(resolve=>handled=resolve)
  const endpoint=`**/api/v1/reports/${a.id}`
  await page.route(endpoint,async route=>{entered();await gate;try{await route.fulfill({json:detailA})}finally{handled()}},{times:1})
  await selector.selectOption(String(a.id));await started
  try{
    await host.getByRole('status').filter({hasText:'正在加载报告详情'}).waitFor()
    assert.equal(await host.getByRole('button',{name:'PDF',exact:true}).isDisabled(),true)
    assert.equal(await host.getByRole('button',{name:'预览',exact:true}).count(),0)
    assert.equal(await host.locator('.report-summary').count(),0)
    await selector.selectOption(String(b.id))
    await host.locator('.report-summary').getByText(`${b.report_number} v${b.version}`,{exact:true}).waitFor()
  }finally{release();await done}
  await page.unroute(endpoint)
  await page.waitForTimeout(100)
  assert.equal(await selector.inputValue(),String(b.id))
  assert.ok((await host.locator('.report-summary').innerText()).includes(b.report_number))
  result.checks.push('慢加载清空旧报告并禁用输出，快速切换时旧响应不能覆盖新选择')

  await page.route(endpoint,route=>route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({detail:{message:'QA 报告详情暂不可用'}})}),{times:1})
  await selector.selectOption(String(a.id))
  await host.getByRole('alert').filter({hasText:'报告详情加载失败'}).waitFor()
  assert.equal(await host.getByRole('button',{name:'Excel',exact:true}).isDisabled(),true)
  assert.equal(await host.getByRole('button',{name:'预览',exact:true}).count(),0)
  await host.getByRole('button',{name:'重试',exact:true}).click()
  await host.locator('.report-summary').getByText(`${a.report_number} v${a.version}`,{exact:true}).waitFor()
  assert.equal(await host.getByRole('alert').count(),0)
  result.checks.push('详情失败保留工作区和选择、禁用输出，重试恢复')

  await page.evaluate(()=>{
    window.__selectionExports=[]
    if(window.__TAURI__?.core){
      const bridge=window.chrome.webview,post=bridge.postMessage
      bridge.postMessage=function(message){
        const data=typeof message==='string'?JSON.parse(message):message
        if(data.cmd==='save_export_file'){
          window.__selectionExports.push({fileName:data.payload.fileName,bytes:data.payload.bytes.length})
          queueMicrotask(()=>window.__TAURI_INTERNALS__.runCallback(data.callback,`QA/${data.payload.fileName}`));return
        }
        return post.call(bridge,message)
      }
      const fetch=window.fetch
      window.fetch=function(input,init){
        const url=new URL(typeof input==='string'?input:input.url,location.href)
        if(url.hostname==='ipc.localhost'&&url.pathname==='/save_export_file'){
          const args=JSON.parse(init.body);window.__selectionExports.push({fileName:args.fileName,bytes:args.bytes.length})
          return Promise.resolve(new Response(JSON.stringify(`QA/${args.fileName}`),{status:200,headers:{'Content-Type':'application/json','Tauri-Response':'ok'}}))
        }
        return fetch.call(window,input,init)
      }
    }
  })
  result.exports=[]
  for(const report of [reports.find(r=>r.status==='confirmed'&&r.source_run_ids.length===0),reports.find(r=>r.status==='confirmed'&&r.source_run_ids.length>0)]){
    assert.ok(report)
    const exportDetail=await call(page,`/api/v1/reports/${report.id}`)
    await selector.selectOption(String(report.id))
    await host.locator('.report-summary').getByText(`${report.report_number} v${report.version}`,{exact:true}).waitFor()
    for(const format of ['Excel','PDF']){
      assert.equal(await host.getByRole('button',{name:format,exact:true}).isEnabled(),true)
      const pending=page.waitForResponse(r=>r.url().endsWith(`/reports/${report.id}/exports`)&&r.request().method()==='POST')
      await host.getByRole('button',{name:format,exact:true}).click()
      const response=await pending;assert.equal(response.status(),200)
      const file=await response.json(),bytes=Buffer.from(file.content_base64,'base64')
      assert.ok(format==='PDF'?bytes.subarray(0,4).toString()==='%PDF':bytes.toString().includes('Workbook'))
      result.exports.push({report_id:report.id,format,byte_length:bytes.length,unit:exportDetail.model.rows[0].unit})
      await page.waitForFunction(()=>!document.querySelector('.report-export .primary-button')?.disabled)
    }
  }
  if(process.env.QA_CDP)assert.equal(await page.evaluate(()=>window.__selectionExports.length),4)
  result.checks.push('已有DAT与分析报告的Excel/PDF按钮均输出正确报告内容；保存边界隔离')

  const previewEndpoint=`**/api/v1/reports/${b.id}/preview`
  let releasePreview,previewEntered,previewHandled
  const previewGate=new Promise(r=>releasePreview=r),previewStarted=new Promise(r=>previewEntered=r),previewDone=new Promise(r=>previewHandled=r)
  await selector.selectOption(String(b.id))
  await host.locator('.report-summary').getByText(`${b.report_number} v${b.version}`,{exact:true}).waitFor()
  await page.route(previewEndpoint,async route=>{previewEntered();await previewGate;try{await route.fulfill({body:'<p>obsolete-preview</p>',contentType:'text/html'})}finally{previewHandled()}},{times:1})
  await host.getByRole('button',{name:'预览',exact:true}).click();await previewStarted
  try{await selector.selectOption(String(a.id))}finally{releasePreview();await previewDone}
  await page.unroute(previewEndpoint)
  await host.locator('.report-summary').getByText(`${a.report_number} v${a.version}`,{exact:true}).waitFor()
  assert.equal(await host.getByRole('dialog').count(),0)
  await page.getByTestId('data-processing-page').getByRole('tab',{name:'强度数据',exact:true}).click()
  await page.getByTestId('data-processing-page').getByRole('tab',{name:'分析报告',exact:true}).click()
  assert.equal(await selector.inputValue(),String(a.id))
  await host.screenshot({path:path.join(output,'report-selected.png')})
  result.checks.push('切换报告取消过期预览，往返强度页保持当前报告')

  await navigate(page,'analysis-tests','样品分析','.analysis-page')
  await page.locator('.analysis-run-list button').filter({hasText:'旧数据测试｜01'}).click()
  await navigate(page,'data','打印与导出','[data-testid="reports-page"]')
  await host.getByTestId('report-current-source').filter({hasText:'旧数据测试｜01'}).waitFor()
  const number=`QA-SELECT-${Date.now()}`
  await host.getByLabel('报告编号（可选）',{exact:true}).fill(number)
  const creating=page.waitForResponse(r=>r.url().endsWith('/api/v1/reports')&&r.request().method()==='POST')
  await host.getByRole('button',{name:'建立报告版本',exact:true}).click()
  const createdResponse=await creating;assert.equal(createdResponse.status(),201)
  const created=await createdResponse.json()
  await host.locator('.report-summary').getByText(`${number} v${created.version}`,{exact:true}).waitFor()
  await host.getByRole('button',{name:'确认报告',exact:true}).click()
  await page.waitForFunction(()=>document.querySelector('.report-output .state-chip')?.textContent.includes('confirmed'))
  await page.getByTestId('data-processing-page').getByRole('button',{name:'刷新',exact:true}).click()
  await selector.selectOption(String(a.id))
  await host.locator('.report-summary').getByText(`${a.report_number} v${a.version}`,{exact:true}).waitFor()
  await selector.selectOption(String(created.id))
  await host.locator('.report-summary').getByText(`${number} v${created.version}`,{exact:true}).waitFor()
  await host.getByRole('button',{name:'预览',exact:true}).click()
  await host.getByRole('dialog').locator('iframe').contentFrame().getByText(number,{exact:false}).first().waitFor()
  await host.getByRole('dialog').getByRole('button',{name:'关闭',exact:true}).click()
  result.checks.push('新建、确认、刷新后重选并预览新报告保持正常；只写隔离库')
}
