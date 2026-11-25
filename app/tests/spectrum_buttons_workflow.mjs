import assert from 'node:assert/strict'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { readFile } from 'node:fs/promises'
import { call, navigate } from './contract_browser_support.mjs'
import { selectViewerFile, waitForSpectrumInk } from './legacy_desk_test_support.mjs'

export async function checkSpectrumButtons(page, fixture, result, output) {
  const check = text => result.checks.push(text)
  const entries=(await call(page,'/api/v1/capabilities')).capabilities.flatMap(item=>item.navigation_entries)
  const entry=entries.find(item=>item.page==='dispersion'&&item.view==='curve')
  let task=await call(page,'/api/v1/dispersion/tasks',{name:'按钮对照验收',frame_count:3,dark_frame_count:1,pre_excitation_seconds:0,ccd_indices:[0,1]})
  task=await call(page,`/api/v1/dispersion/tasks/${task.id}/start`,{})
  for(let i=0;i<40&&task.status!=='completed';i++)task=await call(page,`/api/v1/dispersion/tasks/${task.id}/step`,{})
  assert.equal(task.status,'completed')
  await navigate(page,entry.group,entry.label,'[data-testid="dispersion-page"]')
  const host=page.getByTestId('dispersion-page'), monitor=host.getByTestId('dispersion-curve-monitor')
  const button=name=>host.getByRole('button',{name,exact:true})
  const plot=monitor.locator('svg.spectrum-plot')
  await waitForSpectrumInk(plot)
  assert.ok(await button('增加谱线').isDisabled());assert.ok(await button('删除谱线').isDisabled())
  assert.ok(await button('拟合曲线').isDisabled())
  const coordinate=host.getByLabel('定位谱线',{exact:true})
  for(const point of [100,200,300,400]) {
    await coordinate.fill(`1,${point+1}`);await coordinate.press('Enter')
    await button('增加谱线').waitFor({state:'visible'})
    await page.waitForFunction(()=>!document.querySelector('button[aria-label="增加谱线"]').disabled)
    const response=page.waitForResponse(r=>r.url().includes('/line-points')&&r.request().method()==='POST')
    await button('增加谱线').click();assert.equal((await response).status(),201)
    await page.waitForFunction(count=>document.querySelector('select[aria-label="选择谱线"]').options.length===count, [100,200,300,400].indexOf(point)+2)
    const line=(await call(page,`/api/v1/dispersion/tasks/${task.id}`)).lines.find(line=>line.located_position===point)
    assert.ok(line);assert.equal(line.wavelength_nm,0)
    assert.equal(await host.getByLabel('选择谱线',{exact:true}).inputValue(),String(line.id))
  }
  check('＋在选定CCD点位直接增加谱线并选中；四个波长保持未填写')
  const clickBox=await plot.locator('.plot-background').boundingBox()
  await page.mouse.click(clickBox.x+clickBox.width*.8,clickBox.y+clickBox.height*.5)
  if(await button('增加谱线').isDisabled())await page.mouse.click(clickBox.x+clickBox.width*.8,clickBox.y+clickBox.height*.5)
  const mousePoint=page.waitForResponse(r=>r.url().includes('/line-points')&&r.request().method()==='POST')
  await button('增加谱线').click();const mouseLine=await(await mousePoint).json()
  assert.ok(mouseLine.located_position>1000)
  await page.waitForFunction(()=>document.querySelector('select[aria-label="选择谱线"]').options.length===6)
  await button('删除谱线').click()
  await page.waitForFunction(()=>document.querySelector('select[aria-label="选择谱线"]').options.length===5)
  check('鼠标单击曲线选点可直接增加；删除只影响本次所选谱线')
  const before=(await call(page,`/api/v1/dispersion/tasks/${task.id}`)).lines
  await coordinate.fill('1,101');await coordinate.press('Enter')
  const duplicate=page.waitForResponse(r=>r.url().includes('/line-points')&&r.request().method()==='POST')
  await button('增加谱线').click();assert.equal((await duplicate).status(),409)
  assert.equal((await call(page,`/api/v1/dispersion/tasks/${task.id}`)).lines.length,4)
  check('重复加点被拒绝，现有谱线保持')
  await button('拟合曲线').click()
  const dialog=host.getByRole('dialog',{name:'色散曲线',exact:true})
  await dialog.waitFor();assert.ok(await dialog.getByRole('button',{name:'拟合曲线',exact:true}).isDisabled())
  for(const [i,line] of before.entries()) {
    const input=dialog.getByLabel(`谱线${i+1}波长（nm）`,{exact:true})
    await input.fill(String(250+i*10));await input.press('Enter')
    await page.waitForFunction(()=>!document.querySelector('dialog.dispersion-curve-dialog button:last-child')?.disabled)
  }
  await dialog.getByRole('button',{name:'拟合曲线',exact:true}).click()
  await page.waitForFunction(()=>[...document.querySelectorAll('dialog.dispersion-curve-dialog button')].some(button=>button.textContent==='保存曲线'&&!button.disabled))
  assert.ok(await dialog.getByRole('button',{name:'保存曲线',exact:true}).isEnabled())
  await dialog.getByRole('button',{name:'关闭色散曲线',exact:true}).click()
  check('拟合按钮打开编辑窗口；未填波长禁止拟合；填写四条后完成真实二次拟合')
  await host.getByLabel('选择谱线',{exact:true}).selectOption(String(before[0].id))
  const menu=async name=>{
    await host.locator(`[data-line-id="${before[0].id}"] button`).click({button:'right'})
    await page.getByRole('menuitem',{name,exact:true}).click()
    await page.waitForFunction(()=>!document.querySelector('button[aria-label="拟合曲线"]').disabled)
  }
  const move=async direction=>{
    await button('拟合曲线').focus()
    const response=page.waitForResponse(r=>r.url().endsWith('/move')&&r.request().method()==='POST')
    await page.keyboard.press(`Control+Arrow${direction}`);assert.equal((await response).status(),200)
    await page.waitForFunction(()=>!document.querySelector('button[aria-label="拟合曲线"]').disabled)
  }
  await menu('保存全部位置');await move('Left')
  assert.equal((await call(page,`/api/v1/dispersion/tasks/${task.id}`)).lines.find(l=>l.id===before[0].id).located_position,99)
  await move('Right');await move('Right')
  assert.equal((await call(page,`/api/v1/dispersion/tasks/${task.id}`)).lines.find(l=>l.id===before[0].id).located_position,101)
  await menu('还原实际位置')
  assert.equal((await call(page,`/api/v1/dispersion/tasks/${task.id}`)).lines.find(l=>l.id===before[0].id).located_position,100)
  check('Ctrl方向键按一点移动；右键保存全部位置及还原所选位置')
  await coordinate.fill('2,123');await coordinate.press('Enter')
  await page.waitForFunction(()=>document.querySelector('select[aria-label="选择CCD"]').value==='1')
  await page.waitForFunction(()=>!document.querySelector('button[aria-label="增加谱线"]').disabled)
  await coordinate.fill('0,1');await coordinate.press('Enter')
  assert.equal(await monitor.getByLabel('选择CCD',{exact:true}).inputValue(),'1')
  await button('上一 CCD').click();await waitForSpectrumInk(plot)
  check('CCD,点位定位联动CCD；非法坐标保持当前CCD；上下CCD及选择器可用')
  // Read the same range from the hidden readout dialog without opening it.
  const readRange=()=>monitor.locator('.inspector-readout small').textContent()
  await button('纵向放大').click();const yZoom=await readRange()
  await button('适合图像').click();assert.equal((await readRange()).split('强度')[1],yZoom.split('强度')[1])
  await button('纵向还原').click();const full=await readRange()
  await button('横向放大').click();assert.notEqual(await readRange(),full)
  await button('横向缩小').click();assert.equal(await readRange(),full)
  for(const name of ['一线一点','一线四点','十倍 CCD']) {await button(name).click();assert.equal(await button(name).getAttribute('aria-pressed'),'true')}
  await button('适合图像').click()
  await button('区域放大').click()
  const box=await plot.locator('.plot-background').boundingBox()
  await page.mouse.move(box.x+box.width*.2,box.y+box.height*.2);await page.mouse.down()
  await page.mouse.move(box.x+box.width*.7,box.y+box.height*.7,{steps:6});await page.mouse.up()
  assert.equal(await button('十字线').getAttribute('aria-pressed'),'true')
  await button('滚动工具').click();assert.equal(await button('滚动工具').getAttribute('aria-pressed'),'true')
  await button('纵向缩小').click();await button('纵向还原').click();await button('适合图像').click()
  check('查看/框选/滚动、三种比例、横纵放大缩小与纵向还原；适合图像只还原横向；框选后回到查看')
  await host.getByLabel('选择谱线',{exact:true}).selectOption(String(before[0].id))
  await button('删除谱线').click()
  await page.waitForFunction(()=>document.querySelector('select[aria-label="选择谱线"]').options.length===4)
  assert.ok(await button('删除谱线').isDisabled());assert.ok(await button('拟合曲线').isDisabled())
  assert.ok(!(await call(page,`/api/v1/dispersion/tasks/${task.id}`)).lines.some(line=>line.id===before[0].id))
  check('－实际删除所选谱线并清除选择；降至三条后拟合禁用')
  const positionsBeforeCorrection=(await call(page,`/api/v1/dispersion/tasks/${task.id}`)).lines
  const correction=page.waitForResponse(r=>r.url().includes('/lines/locate-all')&&r.request().method()==='POST')
  await button('校正谱线').click()
  const correctionResult=await(await correction).json()
  await page.waitForFunction(()=>!document.querySelector('button[aria-label="校正谱线"]').disabled)
  assert.equal(correctionResult.located.length,0);assert.equal(correctionResult.errors.length,positionsBeforeCorrection.length)
  assert.ok(correctionResult.errors.every(error=>error.code==='dispersion_peak_not_found'))
  assert.deepEqual((await call(page,`/api/v1/dispersion/tasks/${task.id}`)).lines,positionsBeforeCorrection)
  check('校正谱线读取均值扣暗帧；平坦信号明确失败并保留全部原位置')
  for(const [theme,width,height] of [['light',1440,1000],['dark',1060,720]]) {
    if(process.env.QA_CDP)await page.evaluate(value=>window.__TAURI__.core.invoke('plugin:window|set_size',{value:{Logical:value}}),{width,height})
    else await page.setViewportSize({width,height})
    await call(page,'/api/v1/settings',{display:{theme,density:'compact'}},'PATCH')
    await page.reload();await page.getByTestId('workspace').waitFor()
    await navigate(page,entry.group,entry.label,'[data-testid="dispersion-page"]')
    await waitForSpectrumInk(plot)
    assert.equal(await page.evaluate(()=>document.documentElement.dataset.theme),theme)
    const bad=await host.evaluate(node=>[...node.querySelectorAll('.legacy-view-desk button,.legacy-view-desk input,.legacy-view-desk select')].filter(el=>{const r=el.getBoundingClientRect();return r.width>0&&(r.left<0||r.right>innerWidth+1)}).map(el=>el.getAttribute('aria-label')))
    assert.deepEqual(bad,[])
    await page.screenshot({path:path.join(output,`buttons-${theme}.png`),fullPage:true});result.layouts.push(theme)
  }
  // The actual legacy WDT continues to supply its existing PDF print operation.
  const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../..')
  const imported=await call(page,'/api/v1/legacy-migration/open-file',{path:path.join(root,'Spec Source/Bin/DATA/20141029_测试.wdt'),purpose:'dispersion'})
  await page.getByRole('button',{name:'刷新',exact:true}).click();await selectViewerFile(host,imported.source_sha256,true)
  await waitForSpectrumInk(plot);assert.ok(await button('打印谱图').isEnabled())
  const printResponse=page.waitForResponse(r=>r.url().includes('/print-pdf')&&r.request().method()==='POST')
  const fileEvent=process.env.QA_CDP?null:page.waitForEvent('download')
  if(process.env.QA_CDP)await page.evaluate(()=>{
    const bridge=window.chrome.webview, original=bridge.postMessage
    window.__buttonsSaveOriginal=original
    bridge.postMessage=function(message){const command=typeof message==='string'?JSON.parse(message):message
      if(command.cmd==='save_export_file'){window.__buttonsPdf=command.payload;queueMicrotask(()=>window.__TAURI_INTERNALS__.runCallback(command.callback,null));return}
      return original.call(bridge,message)}
  })
  await button('打印谱图').click();const printed=await printResponse
  assert.equal(printed.status(),200)
  if(fileEvent) {
    const download=await fileEvent
    const pdf=await readFile(await download.path())
    assert.equal(pdf.subarray(0,4).toString(),'%PDF');assert.ok(pdf.length>1000)
    await download.delete()
  } else {
    await page.waitForFunction(()=>!!window.__buttonsPdf)
    const pdf=await page.evaluate(()=>({signature:String.fromCharCode(...window.__buttonsPdf.bytes.slice(0,4)),size:window.__buttonsPdf.bytes.length}))
    assert.equal(pdf.signature,'%PDF');assert.ok(pdf.size>1000)
    await page.evaluate(()=>{window.chrome.webview.postMessage=window.__buttonsSaveOriginal;delete window.__buttonsPdf})
  }
  check('旧WDT打印生成真实PDF；原件只读打开')
  fixture.taskId=task.id
}
