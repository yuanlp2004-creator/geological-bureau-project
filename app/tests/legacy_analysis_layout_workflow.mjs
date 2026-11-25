import assert from 'node:assert/strict'
import { waitForSpectrumInk, assertSpectrumCleared, spectrumCanvasSnapshot } from './legacy_desk_test_support.mjs'
import path from 'node:path'
import {call,navigate} from './contract_browser_support.mjs'

async function openAnalysisAction(plot, name) {
  const page = plot.page()
  const hit = plot.locator('svg.spectrum-plot > .plot-background')
  if (await hit.count()) {
    await hit.click({ button: 'right', position: { x: 10, y: 35 } })
    await page.getByRole('menu', { name: '谱图菜单', exact: true })
      .getByRole('menuitem', { name: '分析操作', exact: true }).click()
  } else {
    await plot.click({ button: 'right', position: { x: 10, y: 70 } })
  }
  await page.getByRole('menuitem', { name, exact: true }).click()
}

export async function checkAnalysisCanvasRetry(plot, reading) {
  const page = plot.page()
  await waitForSpectrumInk(plot)
  await page.route(reading, route => route.fulfill({
    status: 503, contentType: 'application/json', body: JSON.stringify({ detail: '核对失败重试' }),
  }))
  try {
    await openAnalysisAction(plot, '重新读取谱图')
    await plot.getByRole('alert').filter({ hasText: '核对失败重试' }).waitFor()
    await assertSpectrumCleared(plot)
  } finally {
    await page.unroute(reading)
  }
  await plot.getByRole('button', { name: '重新读取谱图', exact: true }).click()
  assert.deepEqual((await waitForSpectrumInk(plot)).corner, [255, 255, 255, 255])
}

export async function checkAnalysisStripPan(plot) {
  const page = plot.page()
  const button = name => plot.getByRole('button', { name, exact: true })
  const strip = plot.locator('.legacy-grayscale')
  const range = async () => [
    Number(await strip.getAttribute('data-x-min')),
    Number(await strip.getAttribute('data-x-max')),
  ]
  const drag = async box => {
    const y = box.y + box.height / 2
    await page.mouse.move(box.x + box.width * .55, y)
    await page.mouse.down()
    await page.mouse.move(box.x + box.width * .65, y, { steps: 4 })
    await page.mouse.up()
  }
  const painted = await waitForSpectrumInk(plot)
  const [start, end] = await range()
  await button('横向放大').click()
  const zoomed = await waitForSpectrumInk(plot, { after: painted.seq, xSpanBelow: end - start })
  await button('滚动工具').click()
  const before = await range()
  await drag(await strip.locator(':scope > rect').boundingBox())
  await waitForSpectrumInk(plot, { after: zoomed.seq })
  const panned = await spectrumCanvasSnapshot(plot)
  assert.notEqual(panned.xStart, before[0])
  assert.deepEqual([panned.xStart, panned.xEnd], await range())
  await drag(await plot.locator('.plot-background').boundingBox())
  assert.deepEqual(await spectrumCanvasSnapshot(plot), panned)
  await button('适合图像').click()
  await button('十字线').click()
}

export async function checkLegacyAnalysisLayout(page,result,output){
 const check=text=>{result.checks.push(text);console.log(`PASS ${text}`)}
 const method=(await call(page,'/api/v1/methods')).find(m=>m.name==='S16 测试方法')
 await call(page,'/api/v1/methods/current',{method_id:method.id});await page.reload();await page.getByTestId('workspace').waitFor()
 const options=await call(page,'/api/v1/analyses/options'),samples=options.samples.filter(s=>s.method_id===method.id)
 let run=await call(page,'/api/v1/analyses/runs',{name:'旧版样品分析核对-'+Date.now(),acquisition_sample_ids:samples.map(s=>s.id),method_version_id:samples[0].method_version_id,calculation_profile:'modern_v1',slow_mode:false})
 const original=structuredClone(run)
 await navigate(page,'analysis-tests','样品分析','.analysis-legacy-page')
 const host=page.locator('.analysis-legacy-page'),plot=host.locator('.analysis-desk-spectrum'),top=host.getByRole('toolbar',{name:'样品分析工具',exact:true})
 await waitForSpectrumInk(plot)
 const header=host.locator('.analysis-header-actions')
 assert.deepEqual(await header.getByRole('button').allTextContents(),['打开样品文件'])
 assert.equal(await header.locator('select').count(),1)
 for(const label of ['分析设置','分析结果','收起列表','展开列表','刷新'])assert.equal(await header.getByRole('button',{name:label,exact:true}).count(),0)
 const icons=locator=>locator.locator('[data-spectroscopy-icon]').evaluateAll(nodes=>nodes.map(n=>n.dataset.spectroscopyIcon))
 assert.deepEqual(await icons(top),['sample-input','reference-correction','line-correction','measure','pause','close'])
 assert.deepEqual(await icons(host.getByRole('toolbar',{name:'分析样品列表操作'})),['sample-list-input','sample-list-clear','record-lock'])
 assert.deepEqual(await icons(plot.getByRole('toolbar',{name:'图像查看工具'})),['previous-band','next-band','previous-ccd','next-ccd','select-ccd','crosshair','box-zoom','pan','fit','scale-1','scale-4','scale-10','zoom-x-in','zoom-x-out','zoom-y-in','zoom-y-out','reset-y','print'])
 const toolIcons = host.locator('.legacy-view-desk img[data-spectroscopy-icon]')
 assert.equal(await toolIcons.count(), 27)
 await toolIcons.evaluateAll(images => Promise.all(images.map(icon => icon.decode())))
 assert.ok(await toolIcons.evaluateAll(images => images.every(icon =>
   icon.naturalWidth === 256 && icon.naturalHeight === 256 && getComputedStyle(icon).imageRendering === 'auto'
 )))
 const positions=await host.evaluate(el=>{const rect=s=>el.querySelector(s).getBoundingClientRect().toJSON();return {top:rect('.analysis-desk-top'),rail:rect('.analysis-sample-rail'),tools:rect('.legacy-observation-toolbar'),chart:rect('.legacy-spectrum-visual'),grid:rect('.legacy-view-table-wrap')}})
 assert.ok(positions.top.bottom<=positions.tools.top+1&&positions.rail.right<=positions.chart.left&&positions.tools.bottom<=positions.chart.top&&positions.grid.top>positions.rail.top)
 check('27个工具位置加载重绘的256×256图标并平滑缩放，两排及左右相对位置正确')
 const menu = label => openAnalysisAction(plot, label)
 async function current(){return call(page,`/api/v1/analyses/runs/${await header.locator('select').inputValue()}`)}
 await top.getByRole('button',{name:'录入样品编号',exact:true}).click()
 const names=page.getByRole('dialog',{name:'输入样号',exact:true})
 assert.equal(await names.getByRole('heading',{name:'分析设置',exact:true}).count(),0)
 const input=names.getByRole('textbox',{name:'样号输入',exact:true})
 const repeats=names.getByRole('textbox',{name:'重复摄谱',exact:true})
 const cell=position=>names.getByRole('button',{name:`样号位置 ${position}`,exact:true})
 async function enterNames(prefix){
  for(let position=1;position<=samples.length;position++){
   await cell(position).click();await input.fill(prefix+position)
   await repeats.fill('1');await input.press('Enter')
  }
 }
 assert.equal(await names.getByRole('columnheader').count(),11)
 const firstName=await cell(1).innerText()
 await cell(1).click();await input.fill('核对编号1')
 await repeats.fill('');await repeats.press('Enter')
 assert.equal(await repeats.inputValue(),'')
 assert.equal(await cell(1).innerText(),firstName)
 await repeats.press('ArrowUp');assert.equal(await repeats.inputValue(),'1')
 await repeats.press('ArrowUp');assert.equal(await repeats.inputValue(),'2')
 await repeats.press('ArrowDown');assert.equal(await repeats.inputValue(),'1')
 await repeats.press('Enter');assert.equal(await cell(1).innerText(),'核对编号1')
 await enterNames('核对编号')
 const createPattern=/\/api\/v1\/analyses\/runs$/
 const fail=route=>route.request().method()==='POST'?route.fulfill({status:409,contentType:'application/json',body:JSON.stringify({detail:'编号保存冲突'})}):route.continue()
 await page.route(createPattern,fail);const failed=page.waitForResponse(r=>createPattern.test(r.url())&&r.request().method()==='POST');await names.getByRole('button',{name:'确定',exact:true}).click();assert.equal((await failed).status(),409)
 await page.waitForFunction(()=>!document.querySelector('dialog[aria-label="输入样号"] button[type="submit"]').disabled)
 assert.equal(await cell(1).innerText(),'核对编号1');await page.unroute(createPattern,fail)
 await names.getByRole('button',{name:'确定',exact:true}).click();await names.waitFor({state:'hidden'});await waitForSpectrumInk(plot);run=await current()
 assert.ok(run.samples.every(s=>s.sample_name.startsWith('核对编号')));assert.deepEqual(await call(page,`/api/v1/analyses/runs/${original.id}`),original)
 await host.getByRole('button',{name:'清除样品编号',exact:true}).click();await page.waitForFunction(()=>[...document.querySelectorAll('.analysis-sample-rail tbody tr')].every(row=>row.lastElementChild.textContent==='?'))
 run=await current();assert.ok(run.samples.every(s=>s.sample_name===''));assert.equal(await top.getByRole('button',{name:'开始测量',exact:true}).isDisabled(),true)
 await host.getByRole('button',{name:'录入列表样品编号',exact:true}).click()
 await enterNames('最终编号')
 await names.getByRole('button',{name:'确定',exact:true}).click();await names.waitFor({state:'hidden'});await waitForSpectrumInk(plot);run=await current()
 check('顶部和左侧编号按钮均打开真实编号表；失败保留草稿，清除后编号为空且禁止测量，历史运行保持')
 const before=await call(page,`/api/v1/analyses/runs/${run.id}/spectra/0`),wave=before.bands[0].wavelengths_nm[100]
 await host.getByLabel('定位分析谱线').fill(String(wave));await host.getByLabel('定位分析谱线').press('Enter');await plot.getByLabel('谱图同步读数').filter({hasText:'坐标：101'}).waitFor()
 const max=Number(await plot.locator('.legacy-grayscale').getAttribute('data-x-max'))
 await plot.getByRole('button',{name:'横向放大',exact:true}).click();assert.ok(Number(await plot.locator('.legacy-grayscale').getAttribute('data-x-max'))<max)
 await plot.getByRole('button',{name:'适合图像',exact:true}).click();assert.equal(Number(await plot.locator('.legacy-grayscale').getAttribute('data-x-max')),2048)
 await host.locator('.analysis-sample-rail tbody tr').nth(1).click();await plot.locator('.legacy-spectrum-banner').filter({hasText:'记录号：[2]'}).waitFor();await waitForSpectrumInk(plot)
 await host.getByRole('button',{name:'锁定谱带记录',exact:true}).click();assert.equal(await plot.getByRole('button',{name:'上一谱带',exact:true}).isDisabled(),true);assert.equal(await host.getByLabel('选择分析谱线').isDisabled(),false);assert.equal(await plot.getByLabel('选择CCD',{exact:true}).isDisabled(),false)
 await host.getByRole('button',{name:'解锁谱带记录',exact:true}).click();await plot.getByRole('button',{name:'上一谱带',exact:true}).click();await plot.locator('.legacy-spectrum-banner').filter({hasText:'记录号：[1]'}).waitFor()
 await checkAnalysisStripPan(plot)
 const versionsBefore=await call(page,`/api/v1/methods/${method.id}/versions`)
 for(const [label,count] of [['校参考线',1],['校正谱线',before.lines.length]]){
  const pending=page.waitForResponse(r=>r.url().endsWith('/spectra/0/calibration')&&r.request().method()==='GET')
  await top.getByRole('button',{name:label,exact:true}).click();assert.equal((await pending).status(),200)
  await page.waitForFunction(()=>!document.querySelector('[aria-label="校正谱线"]').disabled)
  await menu('校线结果');const dialog=page.getByRole('dialog',{name:label,exact:true});assert.equal(await dialog.locator('tbody tr').count(),count);await dialog.getByRole('button',{name:'关闭',exact:true}).click()
 }
 assert.deepEqual(await call(page,`/api/v1/methods/${method.id}/versions`),versionsBefore)
 check('定位、缩放、谱带切换及锁定动作正确；校线直接计算采用实测位置，两种范围准确且不改写方法')
 await page.evaluate(()=>{
  window.__analysisSave=null;const bridge=window.chrome.webview,post=bridge.postMessage;window.__analysisPost=post
  bridge.postMessage=function(message){const d=typeof message==='string'?JSON.parse(message):message;if(d.cmd==='save_export_file'){window.__analysisSave={size:d.payload.bytes.length,signature:d.payload.bytes.slice(0,5)};queueMicrotask(()=>window.__TAURI_INTERNALS__.runCallback(d.callback,null));return}return post.call(bridge,message)}
 })
 const printing=page.waitForResponse(r=>r.url().endsWith(`/analyses/runs/${run.id}/spectra/0/print`));await plot.getByRole('button',{name:'打印谱图',exact:true}).click();assert.equal((await printing).status(),200);await page.waitForFunction(()=>window.__analysisSave)
 assert.deepEqual((await page.evaluate(()=>window.__analysisSave)).signature,[37,80,68,70,45]);await page.evaluate(()=>{window.chrome.webview.postMessage=window.__analysisPost})
 check('打印图标生成同源真实PDF，并通过公共保存入口处理取消')
 const reading=new RegExp(`/analyses/runs/${run.id}/spectra/0(?:\\?|$)`)
 await checkAnalysisCanvasRetry(plot, reading)
 await host.getByRole('button',{name:'隐藏样品列表',exact:true}).click();assert.equal(await host.locator('.analysis-sample-rail').count(),0);await menu('显示样品列表');await host.locator('.analysis-sample-rail').waitFor()
 check('失败清图并能重试；关闭列表可经操作菜单恢复，不增加顶部按钮')
 let steps=0;const stepPattern=new RegExp(`/analyses/runs/${run.id}/step$`)
 await page.route(stepPattern,async route=>{steps++;await new Promise(r=>setTimeout(r,300));await route.continue()})
 await top.getByRole('button',{name:'开始测量',exact:true}).click();await page.waitForFunction(()=>!document.querySelector('[aria-label="暂停测量"]').disabled);await top.getByRole('button',{name:'暂停测量',exact:true}).click();await page.waitForFunction(()=>!document.querySelector('[aria-label="继续测量"]')?.disabled)
 const pausedAt=steps;await page.waitForTimeout(500);assert.equal(steps,pausedAt);await top.getByRole('button',{name:'继续测量',exact:true}).click();await page.waitForFunction(()=>document.querySelector('[aria-label="选择分析批次"]')?.selectedOptions[0]?.textContent.includes('已完成'));await page.unroute(stepPattern)
 assert.equal((await current()).status,'completed');await menu('曲线与分析结果');const review=page.locator('.analysis-inline-review')
 await review.getByRole('heading',{name:'标准曲线',exact:true}).waitFor()
 assert.equal(await page.locator('dialog[open]').count(),0)
 for(const label of ['曲线图','标准点','样品结果']){await review.getByRole('button',{name:label,exact:true}).click();assert.equal(await review.locator('.analysis-view-tabs .active').innerText(),label)}
 await review.getByRole('button',{name:'返回谱图',exact:true}).click()
 await host.locator('.analysis-desk-spectrum').waitFor()
 check('开始、暂停和继续可完成分析；原曲线、标准点和结果通过操作菜单可用')
 result.layouts=[]
 for(const [width,height] of [[1440,1000],[1060,680]]){
  await page.evaluate(({width,height})=>window.__TAURI__.core.invoke('plugin:window|set_size',{value:{Logical:{width,height}}}),{width,height});await page.waitForTimeout(200)
  const layout=await host.evaluate(el=>{const board=el.querySelector('.legacy-spectrum-visual'),rail=el.querySelector('.analysis-sample-rail'),tools=el.querySelector('.legacy-observation-toolbar'),top=el.querySelector('.analysis-desk-top');return {width:innerWidth,height:innerHeight,scroll:document.documentElement.scrollWidth,blue:getComputedStyle(board).backgroundColor,cyan:getComputedStyle(el.querySelector('.legacy-spectrum-banner')).backgroundColor,leftBeforeChart:rail.getBoundingClientRect().right<board.getBoundingClientRect().left,topBeforeTools:top.getBoundingClientRect().bottom<=tools.getBoundingClientRect().top+1,plotHeight:el.querySelector('.spectrum-plot').getBoundingClientRect().height,footerGap:rail.getBoundingClientRect().bottom-el.querySelector('.legacy-view-footer').getBoundingClientRect().bottom}})
  layout.white = (await waitForSpectrumInk(plot)).corner
  assert.equal(layout.blue,'rgb(168, 201, 235)');assert.equal(layout.cyan,'rgb(0, 255, 255)');assert.deepEqual(layout.white, [255, 255, 255, 255]);assert.ok(layout.leftBeforeChart&&layout.topBeforeTools&&layout.plotHeight>=140&&layout.scroll<=width+1&&layout.footerGap<=1,JSON.stringify(layout));result.layouts.push(layout)
  await page.screenshot({path:path.join(output,`analysis-${width}.png`)})
 }
 await page.evaluate(()=>window.__TAURI__.core.invoke('plugin:window|set_size',{value:{Logical:{width:1440,height:1000}}}))
 check('两种桌面尺寸蓝底、青色标题、白色曲线区及相对位置正确，间距保持本批修改前设置')
 result.runId=run.id
}
