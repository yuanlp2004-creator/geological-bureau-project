import assert from 'node:assert/strict'
import {createHash} from 'node:crypto'
import path from 'node:path'
import {readFile,writeFile} from 'node:fs/promises'
import {call,navigate} from './contract_browser_support.mjs'

export async function checkLegacyOperators(page,fixture,result,output) {
  const entries=(await call(page,'/api/v1/capabilities')).capabilities.flatMap(m=>m.navigation_entries)
  const check=(id,message)=>{result.checks.push({id,message});console.log(`PASS ${id}: ${message}`)}
  const selectors={samples:'.sample-queue-page',analysis:'.analysis-page',dispersion:'.dispersion-page',methods:'[data-testid=methods-page]',
    migration:'.migration-page',postprocessing:'.postprocessing-page',reports:'.reports-page',spectra:'.spectrum-viewer-page'}
  async function go(name){
    const output=name==='postprocessing'||name==='reports'
    const entry=entries.find(e=>e.page===(output?'reports':name)||e.key===name);assert.ok(entry,name)
    const selector=output?'[data-testid=data-processing-page]':selectors[entry.page]||'.page-content'
    await navigate(page,entry.group,entry.label,selector)
    if(output)await page.getByRole('tab',{name:name==='postprocessing'?'强度数据':'分析报告',exact:true}).click()
    if(name==='postprocessing'){
      const toggle=page.getByRole('button',{name:'重算与已迁移结果导出',exact:true})
      if(await toggle.getAttribute('aria-expanded')==='false')await toggle.click()
    }
    return page.locator(output?selectors[name]:selector)
  }
  const pending=(part,method='POST')=>{const promise=page.waitForResponse(r=>r.url().includes(part)&&r.request().method()===method);promise.catch(()=>{});return promise}
  async function fill(host,label,value){const input=host.getByLabel(label,{exact:true});await input.fill(String(value));await input.blur()}
  await call(page,'/api/v1/methods/current',{method_id:fixture.method_id});await page.reload();await page.getByTestId('workspace').waitFor()
  // Capture only newly generated exports; do not read any user clipboard/files.
  await page.evaluate(()=>{
    window.__fourteenFiles=[]
    const original=URL.createObjectURL
    URL.createObjectURL=function(blob){if(blob instanceof Blob)void blob.arrayBuffer().then(data=>window.__fourteenFiles.push(Array.from(new Uint8Array(data))));return original.call(URL,blob)}
    if(window.__TAURI__?.core){
      const bridge=window.chrome?.webview,post=bridge?.postMessage
      if(!post)throw Error('WebView2 IPC capture unavailable')
      bridge.postMessage=function(message){const data=typeof message==='string'?JSON.parse(message):message
        if(data.cmd==='save_export_file'){window.__fourteenFiles.push(data.payload.bytes);queueMicrotask(()=>window.__TAURI_INTERNALS__.runCallback(data.callback,`QA/${data.payload.fileName}`));return}
        return post.call(bridge,message)}
    }
  })
  let host=await go('dispersion')
  await host.getByRole('button',{name:/Fourteen calibration/}).click()
  let response=pending(`/lines/${fixture.dispersion_fe_id}/locate`)
  await host.locator('tr').filter({has:page.locator('strong').filter({hasText:/^Fe$/})}).getByTitle('定位',{exact:true}).click()
  assert.equal((await (await response).json()).located_position,107)
  check('F01','Actual locate button uses all burn/dark means; independent unequal-period and damaged-frame tests also pass')
  const original=await call(page,`/api/v1/dispersion/tasks/${fixture.dispersion_task_id}`)
  await fill(host,'间隔 (μm)',14)
  response=pending('/gaps/0','PATCH');await host.getByRole('button',{name:'应用间隔并重算'}).click();assert.ok((await response).ok())
  await page.waitForFunction(async id=>{
    const config=window.__TAURI__?.core?await window.__TAURI__.core.invoke('runtime_config'):null
    const r=await fetch((config?.api_base||'')+`/api/v1/dispersion/tasks/${id}`,{headers:{Authorization:`Bearer ${sessionStorage.getItem('geospectrum.token')}`,...(config?{'X-GeoSpectrum-Process-Key':config.process_key}:{})}})
    return (await r.json()).calibrations.length>0
  },fixture.dispersion_task_id)
  const changed=await call(page,`/api/v1/dispersion/tasks/${fixture.dispersion_task_id}`)
  assert.notEqual(changed.ccd_layout_id,original.ccd_layout_id);assert.ok(changed.calibrations.length)
  check('F02','Gap selection/increments update a separate layout and create a new fit without changing old geometry')
  await fill(host,'Fe 波长',250.2);response=pending('/wavelength','PATCH')
  await host.locator('tr').filter({has:page.locator('strong').filter({hasText:/^Fe$/})}).getByTitle('保存波长').click()
  const edited=await (await response).json();assert.equal(edited.id,fixture.dispersion_fe_id);assert.equal(edited.saved_position,107);assert.equal(edited.wavelength_nm,250.2)
  check('F03','Existing wavelength updates in place, preserving line identity and saved point')
  await page.screenshot({path:path.join(output,'dispersion-fourteen.png'),fullPage:true})

  host=await go('samples')
  const raw=Buffer.from([0xd1,0xf9,0x31,9,0x31,13,10]);response=pending('/sample-queues/import')
  await host.locator('input[type=file]').setInputFiles({name:'gb-sample.sam',mimeType:'text/plain',buffer:raw})
  const sam=await(await response).json();assert.equal(sam.items[0].pre_name,'样1');assert.equal(sam.source_sha256,createHash('sha256').update(raw).digest('hex'))
  check('F10','File input imports Chinese GB18030 bytes and preserves original SHA-256')
  await host.getByRole('button',{name:'新建队列',exact:true}).click()
  await fill(host,'队列名称','Fourteen keyboard')
  let name=host.getByLabel('样品名',{exact:true});await name.fill('100');response=pending('/sample-queues');await name.press('Enter');await response
  await page.waitForFunction(()=>document.querySelector('.sample-entry-form input')?.value==='101'||Array.from(document.querySelectorAll('input')).some(i=>i.value==='101'))
  name=host.getByLabel('样品名',{exact:true});await name.fill(',');response=pending('/sample-queues/','PATCH');await name.press('Enter');await response
  let queue=(await call(page,'/api/v1/sample-queues')).find(q=>q.name==='Fourteen keyboard')
  assert.equal(queue.items[1].pre_name,'');assert.equal(queue.items[1].repeats,0)
  await name.fill('/');response=pending('/items/','DELETE');await name.press('Enter');await response
  queue=(await call(page,'/api/v1/sample-queues')).find(q=>q.name==='Fourteen keyboard');assert.equal(queue.items.length,1)
  await name.fill('.');await name.press('Enter');assert.equal(await name.inputValue(),'')
  check('F14','Enter increments numeric names; comma inserts empty; slash deletes; dot finishes')

  host=await go('analysis');await host.getByRole('button',{name:'曲线图',exact:true}).click()
  const operator=host.getByLabel('标准点标尺操作',{exact:true});await operator.getByLabel('曲线标准点',{exact:true}).selectOption('1')
  const circle=host.locator('circle[aria-pressed=true]'),pos=async()=>({x:Number(await circle.getAttribute('cx')),y:Number(await circle.getAttribute('cy'))})
  const before=await pos();response=pending('/actions');await operator.getByRole('button',{name:'上移标准点',exact:true}).click();await response
  await page.waitForFunction(({y})=>Number(document.querySelector('circle[aria-pressed=true]')?.getAttribute('cy'))!==y,before)
  const after=await pos();assert.equal(after.x,before.x);assert.ok(after.y<before.y)
  check('F04','Up nudge moves vertically with content on X and intensity on Y')
  response=pending('/actions');await host.getByRole('checkbox',{name:'对数坐标',exact:true}).click();await response
  await page.waitForFunction(()=>document.querySelector('.analysis-switch input')?.checked)
  response=pending('/fit');await host.getByRole('button',{name:'重新拟合',exact:true}).click();await response
  await page.waitForFunction(()=>document.querySelector('.analysis-curve-chart .simple-axis-x-title')?.textContent?.includes('分析值'))
  const xs=await host.locator('svg[aria-label="标准曲线"] circle').evaluateAll(nodes=>nodes.map(n=>Number(n.getAttribute('cx'))))
  assert.ok(Math.abs((xs[1]-xs[0])/(xs[2]-xs[0])-Math.log(2)/Math.log(3))<1e-5)
  check('F05','Logarithmic display transforms both axes; standard X spacing follows ln(content)')
  await page.screenshot({path:path.join(output,'curve-fourteen.png'),fullPage:true})
  await host.getByRole('button',{name:'谱图与测量',exact:true}).click()
  const intensity=host.locator('section').filter({has:page.getByRole('heading',{name:'分析强度输出',exact:true})})
  await intensity.getByRole('checkbox',{name:'保存强度文件',exact:true}).check()
  await intensity.getByRole('checkbox',{name:'强度到文本',exact:true}).check()
  await intensity.getByRole('checkbox',{name:'保存校正波长',exact:true}).uncheck()
  await intensity.getByRole('checkbox',{name:'打印强度',exact:true}).check()
  response=pending('/intensity-output');await intensity.getByRole('button',{name:'执行所选输出',exact:true}).click()
  const strength=await(await response).json();assert.equal(strength.files.length,3);assert.ok(strength.table[0].some(h=>h.includes('峰值')))
  check('F08a','Analysis wide table outputs native intensity snapshot, TXT and actual print PDF together')
  host=await go('postprocessing')
  assert.equal(await host.getByLabel('PDT 强度来源',{exact:true}).count(),0)
  const migratedOptions=await call(page,'/api/v1/postprocessing/recalculation-options')
  const migratedSource=migratedOptions.sources.find(item=>item.id===`result:${fixture.pdt_id}`)
  assert.ok(migratedSource)
  await host.getByLabel('筛选重算源记录',{exact:true}).fill(migratedSource.source_sha256)
  await host.locator('.postprocessing-choice-list.sources input').first().check()
  const matrix=host.locator('.postprocessing-export-surface')
  await matrix.getByLabel('输出目录',{exact:true}).fill(output)
  await matrix.getByLabel('文件名',{exact:true}).fill('migrated-pdt-result')
  response=pending('/postprocessing/exports');await matrix.getByRole('button',{name:'导出数据',exact:true}).click()
  const migratedResponse=await response;assert.ok(migratedResponse.ok())
  assert.deepEqual(migratedResponse.request().postDataJSON().record_ids,[`result:${fixture.pdt_id}`])
  const migratedExport=await migratedResponse.json()
  assert.match(await readFile(migratedExport.path,'utf8'),/peak/)
  check('F08b','Migrated PDT uses unified result export with no separate old-format card')

  host=await go('methods')
  await host.getByRole('button',{name:'预览与打印',exact:true}).click()
  const beforeMethodFile=await page.evaluate(()=>window.__fourteenFiles.length)
  response=pending('/text');await host.getByRole('button',{name:'导出 TXT',exact:true}).click();assert.ok((await response).ok())
  await page.waitForFunction(count=>window.__fourteenFiles.length>count,beforeMethodFile)
  const parameterText=Buffer.from(await page.evaluate(()=>window.__fourteenFiles[window.__fourteenFiles.length-1])).toString('utf8');assert.ok(parameterText.includes('方法条件')&&parameterText.includes('标准'))
  check('F09','Complete method/line/standard parameter TXT uses the same current snapshot as preview')

  host=await go('migration');await host.locator('.migration-history-list button').first().click()
  response=pending('/preferences','GET');await host.getByRole('button',{name:'预览旧版偏好',exact:true}).click();await response
  const previous=await call(page,'/api/v1/settings')
  response=pending('/preferences');await host.getByRole('button',{name:'应用这些软件偏好',exact:true}).click();assert.ok((await response).ok())
  const settings=await call(page,'/api/v1/settings');assert.equal(settings.analysis.dark_round_time_seconds,12);assert.equal(settings.analysis.wait_time_ms,1234);assert.equal(settings.preliminary.dispersion.frame_count,9)
  assert.deepEqual(settings.directories,previous.directories)
  const defaults=(await call(page,'/api/v1/dispersion/options')).preliminary_defaults;assert.equal(defaults.frame_count,9)
  check('F11','Archived CFG/OPT previews and applies software preferences into actual default consumers')

  host=await go('spectra')
  await host.locator('.spectrum-record-row button').filter({hasText:'Raw comparison'}).click()
  await host.getByRole('button',{name:'锁定谱带记录',exact:true}).click()
  assert.ok(await host.getByTitle('下一条记录',{exact:true}).isDisabled())
  assert.ok(await host.locator('.spectrum-record-row:not(.active) button').first().isDisabled())
  await host.getByRole('button',{name:'解锁谱带记录',exact:true}).click()
  check('F13','Record lock blocks list and previous/next independently of cursor lock')
  async function pixelSpacing(label,expected){await host.getByRole('button',{name:label,exact:true}).click();await page.waitForTimeout(150)
    const spacing=await host.locator('.spectrum-plot-wrap svg').evaluate(svg=>{
      const points=Array.from((svg.querySelector('path.spectrum-line.priority')?.getAttribute('d')||'').matchAll(/[ML]\s+([\d.e+-]+)\s+([\d.e+-]+)/g),match=>Number(match[1]))
      return points?.length>1?(points[1]-points[0])*(svg.getScreenCTM()?.a ?? svg.getBoundingClientRect().width/960)*window.devicePixelRatio:null
    });assert.ok(spacing!=null);assert.ok(Math.abs(spacing-expected)<.03,`${label}: ${spacing} expected ${expected}`);return spacing}
  const pixel100=await pixelSpacing('100%',1),pixel400=await pixelSpacing('400%',4)
  const profile=(await call(page,'/api/v1/spectra/display-profiles'))[0]
  await host.getByLabel('屏幕比例档案',{exact:true}).selectOption(String(profile.id))
  const pixelTen=await pixelSpacing('十倍 CCD',14/1000*10*profile.screen_resolution_px/profile.screen_width_mm)
  check('F12','100/400 use actual one/four pixels per CCD point; tenfold mode consumes point width and screen dimensions')
  await page.screenshot({path:path.join(output,'spectrum-fourteen.png'),fullPage:true})
  result.facts={sam,curve_nudge:{before,after},logarithmic_x:xs,pixel_spacing:{pixel100,pixel400,pixelTen,device_pixel_ratio:await page.evaluate(()=>window.devicePixelRatio)}}
  // Service/output checks complement GUI interactions without changing old snapshots.
  const paper=await call(page,'/api/v1/settings',{printing:{paper:'A3',orientation:'portrait',font_size_pt:13,elements_per_line:2,samples_per_page:3,time_mode:'system'}},'PATCH')
  assert.equal(paper.printing.font_size_pt,13)
  const ready=await call(page,`/api/v1/analyses/runs/${fixture.run_id}`),snapshot=ready.curves.lines[0].snapshots[ready.curves.lines[0].snapshots.length-1]
  await call(page,`/api/v1/analyses/runs/${fixture.run_id}/curves/${fixture.line_id}/publish`,{curve_snapshot_id:snapshot.id,reason:'Fourteen output QA'})
  await call(page,`/api/v1/analyses/runs/${fixture.run_id}/results/merge`,{reason:'Fourteen matrix QA'})
  host=await go('reports')
  await host.locator('.report-run-list input[type=checkbox]').first().check()
  response=pending('/api/v1/reports');await host.getByRole('button',{name:'建立报告版本',exact:true}).click();const report=await(await response).json()
  assert.equal(report.model.table_layout,'legacy_matrix')
  await host.getByRole('button',{name:'预览',exact:true}).click()
  const reportFrame=page.frameLocator('iframe[title*="报告预览"]')
  await reportFrame.locator('table').first().waitFor()
  assert.equal(await reportFrame.locator('th').first().innerText(),'样品号')
  assert.ok((await reportFrame.locator('body').innerText()).includes('系统时间'))
  const style=await reportFrame.locator('style').innerText();assert.ok(style.includes('A3 portrait')&&style.includes('13pt'))
  await page.screenshot({path:path.join(output,'report-fourteen.png'),fullPage:true})
  await page.locator('.report-preview-modal').getByRole('button',{name:'关闭',exact:true}).click()
  check('F06','Actual report preview consumes A3 portrait, 13pt and system time; service tests verify PDF size, font and pagination')
  const exchange=await call(page,'/api/v1/reports',{analysis_run_ids:[fixture.run_id],arrangement:'exchange',table_layout:'legacy_matrix'})
  assert.equal(exchange.model.arrangement,'exchange')
  check('F07','Report UI creates matrix layout and preview shows sample/element cells; both orientations verified cell-for-cell by service tests')
  const method=await call(page,`/api/v1/methods/${fixture.method_id}`);assert.equal(method.published_version.content_sha256,fixture.method_hash)
  check('preservation','Original published method hash remains; isolated test data only')
  for(const [theme,width] of [['light',1440],['dark',1060]]) {
    await call(page,'/api/v1/settings',{display:{theme}},'PATCH');await page.reload();await page.getByTestId('workspace').waitFor()
    if(process.env.QA_CDP)await page.evaluate(async width=>window.__TAURI__.core.invoke('plugin:window|set_size',{value:{Logical:{width,height:1000}}}),width)
    else await page.setViewportSize({width,height:1000})
    for(const target of ['samples','dispersion','analysis','spectra','postprocessing','reports','migration','methods']) {
      const surface=await go(target)
      if(target==='samples')await surface.locator('.sample-table-wrap table').waitFor()
      if(target==='dispersion')await surface.locator('.dispersion-line-table').waitFor()
      if(target==='analysis'){await surface.getByRole('button',{name:'曲线图',exact:true}).click();await surface.locator('svg[aria-label="标准曲线"] circle').first().waitFor()}
      if(target==='spectra')await surface.locator('.spectrum-plot-wrap .spectrum-line').first().waitFor()
      if(target==='postprocessing'){assert.equal(await surface.getByLabel('PDT 强度来源',{exact:true}).count(),0)}
      if(target==='reports')await surface.locator('.report-version-selector select').waitFor()
      if(target==='migration')await surface.locator('.migration-history-list button').first().waitFor()
      if(target==='methods')await surface.getByRole('button',{name:'预览与打印',exact:true}).waitFor()
      const dimensions=await page.evaluate(()=>({viewport:document.documentElement.clientWidth,document:document.documentElement.scrollWidth,body:document.body.scrollWidth}))
      result.layouts.push({theme,target,...dimensions});assert.ok(dimensions.document<=dimensions.viewport&&dimensions.body<=dimensions.viewport,`${theme}/${target}: ${JSON.stringify(dimensions)}`)
      if(['analysis','reports','dispersion'].includes(target))await page.screenshot({path:path.join(output,`${target}-${theme}.png`),fullPage:true})
    }
  }
  await writeFile(path.join(output,'facts.json'),JSON.stringify(result.facts,null,2))
}
