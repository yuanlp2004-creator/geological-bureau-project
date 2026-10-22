import assert from 'node:assert/strict'
import path from 'node:path'
import {call,navigate} from './contract_browser_support.mjs'

export async function checkCurrentReport(page,result,output){
  const host=page.getByTestId('reports-page'),source=host.getByTestId('report-current-source')
  const create=host.getByRole('button',{name:'建立报告版本',exact:true})
  const native=!!process.env.QA_CDP
  const paths=['测试15-5_20190421_1842.dat','测试15-5_20260529_0805.dat'].map(name=>path.join(process.cwd(),'..','Spec Source','Bin','DATA',name))
  async function open(file,{cancel=false,fail=false}={}){
    const control=page.locator('.open-legacy-file[data-purpose="reports"]')
    await control.locator(':scope > button').waitFor()
    const pending=cancel?null:page.waitForResponse(r=>r.url().endsWith('/legacy-migration/open-file')&&r.request().postDataJSON()?.purpose==='reports')
    if(native){
      await page.evaluate(paths=>{
        window.__currentReportPaths=paths
        if(window.__currentReportPicker)return
        window.__currentReportPicker=true
        const bridge=window.chrome.webview,post=bridge.postMessage
        bridge.postMessage=function(message){
          const data=typeof message==='string'?JSON.parse(message):message
          if(data.cmd==='select_legacy_files'){queueMicrotask(()=>window.__TAURI_INTERNALS__.runCallback(data.callback,window.__currentReportPaths));return}
          return post.call(bridge,message)
        }
        const fetch=window.fetch
        window.fetch=function(input,init){
          const url=new URL(typeof input==='string'?input:input.url,location.href)
          if(url.hostname==='ipc.localhost'&&url.pathname==='/select_legacy_files')return Promise.resolve(new Response(JSON.stringify(window.__currentReportPaths),{status:200,headers:{'Content-Type':'application/json','Tauri-Response':'ok'}}))
          return fetch.call(window,input,init)
        }
      },cancel?[]:[file])
      await control.getByRole('button',{name:'打开报告文件',exact:true}).click()
    }else{
      await control.getByRole('button',{name:'打开报告文件',exact:true}).click()
      if(cancel)await control.getByRole('button',{name:'关闭文件打开面板',exact:true}).click()
      else{
        await control.getByRole('textbox').fill(file)
        await control.getByRole('button',{name:'打开并保存',exact:true}).click()
      }
    }
    if(cancel)return
    const response=await pending
    if(fail){assert.ok(response.status()>=400);await control.getByRole('alert').waitFor();return}
    assert.equal(response.status(),200,await response.text())
    await source.getByText(path.basename(file),{exact:true}).waitFor()
    await page.waitForFunction(()=>!document.querySelector('.open-legacy-file[data-purpose="reports"] > button')?.disabled)
    return response.json()
  }
  assert.equal(await source.count(),0)
  assert.equal(await create.isDisabled(),true)
  assert.equal(await host.locator('.report-run-row').count(),0)
  assert.equal(await host.getByRole('checkbox').count(),0)
  assert.equal(await host.getByText('报告来源',{exact:true}).count(),0)
  result.checks.push('报告页初始无自动来源、无候选和全选控件，未打开数据不能建立')

  await navigate(page,'analysis-tests','样品分析','.analysis-page')
  await page.locator('.analysis-run-list button').filter({hasText:'旧数据测试｜01'}).click()
  await navigate(page,'data','打印与导出','[data-testid="reports-page"]')
  await source.filter({hasText:'旧数据测试｜01'}).waitFor()
  const runs=await call(page,'/api/v1/analyses/runs'),run=runs.find(r=>r.name.startsWith('旧数据测试｜01'))
  async function build(prefix){
    await host.getByLabel('报告编号（可选）',{exact:true}).fill(`${prefix}-${Date.now()}`)
    const pending=page.waitForResponse(r=>r.url().endsWith('/api/v1/reports')&&r.request().method()==='POST')
    await create.click();const response=await pending
    assert.equal(response.status(),201,await response.text())
    const detail=await response.json()
    await host.locator('.report-summary').getByText(`${detail.report_number} v${detail.version}`,{exact:true}).waitFor()
    return {detail,payload:response.request().postDataJSON()}
  }
  const analysis=await build('QA-CURRENT-ANALYSIS')
  assert.deepEqual(analysis.payload.analysis_run_ids,[run.id]);assert.ok(!analysis.payload.legacy_result_ids)
  await host.screenshot({path:path.join(output,'current-analysis.png')})
  result.checks.push('样品分析打开的批次自动带入，建立请求仅含该运行一个ID')

  const first=await open(paths[0])
  assert.equal(await host.locator('.report-summary').count(),0)
  assert.equal(await host.locator('.report-run-row').count(),0)
  assert.equal(await host.getByRole('checkbox').count(),0)
  assert.equal(await host.getByLabel('旧结果单位',{exact:true}).count(),0)
  assert.equal(await create.isEnabled(),true)
  const dat=await build('QA-CURRENT-DAT')
  assert.deepEqual(dat.payload.analysis_run_ids,[]);assert.deepEqual(dat.payload.legacy_result_ids,first.record_ids)
  assert.equal(dat.detail.model.source_kind,'legacy_dat');assert.equal(dat.detail.model.rows.length,270)
  assert.ok(!('legacy_unit' in dat.payload))
  assert.ok(dat.detail.model.rows.every(row=>row.unit===''))
  assert.ok(dat.detail.model.provenance_note.includes('原文件未记录单位'))
  await host.getByRole('button',{name:'预览',exact:true}).click()
  await host.getByRole('dialog').locator('iframe').contentFrame().getByText('原文件未记录单位',{exact:false}).first().waitFor()
  await host.getByRole('dialog').getByRole('button',{name:'关闭',exact:true}).click()
  await host.getByRole('button',{name:'确认报告',exact:true}).click()
  await page.waitForFunction(()=>document.querySelector('.report-output .state-chip')?.textContent.includes('confirmed'))
  result.checks.push('打开DAT无单位填写框可直接建立，270行原值保持空单位且预览如实说明')
  await host.screenshot({path:path.join(output,'current-dat.png')})

  const second=await open(paths[1])
  assert.notDeepEqual(second.record_ids,first.record_ids)
  assert.ok(!(await source.innerText()).includes(path.basename(paths[0])))
  assert.equal(await host.getByLabel('旧结果单位',{exact:true}).count(),0)
  assert.equal(await host.locator('.report-summary').count(),0)
  await host.getByLabel('报告编号（可选）',{exact:true}).fill('取消或失败仍保留的编号')
  await open(paths[0],{cancel:true})
  assert.ok((await source.innerText()).includes(path.basename(paths[1])))
  assert.equal(await host.getByLabel('报告编号（可选）',{exact:true}).inputValue(),'取消或失败仍保留的编号')
  await open(paths[1]+'.missing.dat',{fail:true})
  assert.ok((await source.innerText()).includes(path.basename(paths[1])))
  assert.equal(await host.getByLabel('报告编号（可选）',{exact:true}).inputValue(),'取消或失败仍保留的编号')
  result.checks.push('打开另一文件替换当前来源并清空旧详情；取消和失败保留来源与草稿')

  await page.getByTestId('data-processing-page').getByRole('tab',{name:'强度数据',exact:true}).click()
  await page.getByTestId('data-processing-page').getByRole('tab',{name:'分析报告',exact:true}).click()
  assert.ok((await source.innerText()).includes(path.basename(paths[1])))
  await navigate(page,'analysis-tests','样品分析','.analysis-page')
  await page.locator('.analysis-run-list button').filter({hasText:'旧数据测试｜03'}).click()
  await navigate(page,'data','打印与导出','[data-testid="reports-page"]')
  await source.filter({hasText:'旧数据测试｜03'}).waitFor()
  assert.equal(await create.isDisabled(),true)
  result.checks.push('页签往返保持当前文件；打开未完成批次会替换来源并阻止建立报告')
  await open(paths[0])
  result.layouts=[]
  for(const [width,height] of [[1440,1000],[1060,680]]){
    if(native)await page.evaluate(({width,height})=>window.__TAURI__.core.invoke('plugin:window|set_size',{value:{Logical:{width,height}}}),{width,height})
    else await page.setViewportSize({width,height})
    const geometry=await host.locator('.report-builder').evaluate(el=>({width:innerWidth,doc:document.documentElement.scrollWidth,height:el.getBoundingClientRect().height,controls:[...el.querySelectorAll('input,select,button')].map(n=>({left:n.getBoundingClientRect().left,right:n.getBoundingClientRect().right}))}))
    assert.ok(geometry.doc<=geometry.width+1,JSON.stringify(geometry))
    assert.ok(geometry.controls.every(c=>c.left>=0&&c.right<=geometry.width+1),JSON.stringify(geometry))
    result.layouts.push({width,height,...geometry})
    if(width===1060)await host.screenshot({path:path.join(output,'current-dat-narrow.png')})
  }
  result.checks.push('宽/窄实际布局无横向越界，只有当前文件摘要及报告设置')
}
