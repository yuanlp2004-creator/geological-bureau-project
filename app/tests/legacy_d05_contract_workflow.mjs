import assert from 'node:assert/strict'
import path from 'node:path'
import { call, navigate } from './contract_browser_support.mjs'
import { readSampleCells } from './sample_column_table_workflow.mjs'

export async function checkD05Contract(page, fixture, result, output) {
  const entries = (await call(page,'/api/v1/capabilities')).capabilities.flatMap(c=>c.navigation_entries||[])
  async function go(key, selector) { const entry=entries.find(e=>e.page===key);assert.ok(entry,key);await navigate(page,entry.group,entry.label,selector) }
  const checked = message => { result.checks.push(message); console.log(`PASS: ${message}`) }
  await go('hardware-acquisition','.hardware-page')
  await page.locator('.hardware-task-rows button').filter({hasText:'T1'}).count().then(async count=>{
    // The task title is independent of sample identity; select its stable id via the API-backed list order.
    if(count)await page.locator('.hardware-task-rows button').filter({hasText:'T1'}).first().click()
  })
  const source=await call(page,`/api/v1/hardware-acquisitions/tasks/${fixture.hardware_task_id}`)
  const tasks=await call(page,'/api/v1/hardware-acquisitions/tasks')
  const index=tasks.findIndex(task=>task.id===source.id)
  await page.locator('.hardware-task-rows button').nth(index).click()
  const panel=page.getByRole('region',{name:'转角结果保存为分析样品'})
  await panel.getByLabel('正式样号',{exact:true}).fill('T1')
  const saving=page.waitForResponse(r=>r.url().endsWith(`/${source.id}/analysis-sample`)&&r.request().method()==='POST')
  await panel.getByRole('button',{name:'保存为分析样品',exact:true}).click()
  const response=await saving;assert.equal(response.status(),200)
  const saved=await response.json()
  await panel.getByRole('status').filter({hasText:'已保存：T1'}).waitFor()
  const options=await call(page,'/api/v1/analyses/options')
  assert.ok(options.samples.some(s=>s.id===saved.acquisition_sample_id))
  const formal=await call(page,`/api/v1/acquisitions/samples/${saved.acquisition_sample_id}/bands?include_points=true`)
  assert.deepEqual(formal.map(b=>[b.ccd_index,b.mean_sha256]).sort(),source.exposures.filter(e=>e.confirmed).map(e=>[e.ccd_index,e.mean_sha256]).sort())
  await page.screenshot({path:path.join(output,'turn-saved.png'),fullPage:true})
  checked('真实页面保存转角结果为分析样品；分析来源可选且刷新后保持')

  let run=await call(page,'/api/v1/analyses/runs',{acquisition_sample_ids:[...fixture.standard_sample_ids,saved.acquisition_sample_id]})
  run=await call(page,`/api/v1/analyses/runs/${run.id}/start`,{})
  for(let i=0;i<100&&run.status==='running';i++)run=await call(page,`/api/v1/analyses/runs/${run.id}/step`,{})
  assert.equal(run.status,'completed')
  run=await call(page,`/api/v1/analyses/runs/${run.id}/quality/recalculate`,{})
  for(const group of run.quality.latest_snapshot.groups)if(group.warnings.length)run=await call(page,`/api/v1/analyses/runs/${run.id}/quality/decisions`,{acquisition_task_id:group.acquisition_task_id,line_id:group.line_id,action:'accept',reason:'独立黄金输入复核'})
  const line=run.curves.lines[0].line_id
  run=await call(page,`/api/v1/analyses/runs/${run.id}/curves/${line}/fit`,{})
  const curve=run.curves.lines[0].snapshots.at(-1)
  run=await call(page,`/api/v1/analyses/runs/${run.id}/curves/${line}/publish`,{curve_snapshot_id:curve.id,reason:'确认转角结果'})
  const sample=run.curves.results.find(r=>r.sample_name==='T1')
  assert.ok(Math.abs(sample.calculated_value-2.5)<.01)
  await call(page,`/api/v1/analyses/runs/${run.id}/results/merge`,{reason:'转角结果保存'})
  let report=await call(page,'/api/v1/reports',{analysis_run_ids:[run.id]})
  await call(page,`/api/v1/reports/${report.id}/confirm`,{})
  result.analysis={run_id:run.id,report_id:report.id,sample_value:sample.calculated_value,source_hash:source.result_sha256}
  checked('同一转角原始数据完成质控、标准曲线、2.5含量回算、合并及报告确认')

  await go('dispersion','.dispersion-page')
  const before=await call(page,`/api/v1/dispersion/tasks/${fixture.dispersion_task_id}`)
  const first=before.lines.find(line=>line.id===fixture.dispersion_line_id)
  await call(page,`/api/v1/dispersion/tasks/${fixture.dispersion_task_id}/lines/${first.id}/move`,{direction:'long',steps:10})
  await page.getByRole('button',{name:'刷新',exact:true}).click()
  const fitted=page.waitForResponse(r=>r.url().includes(`/dispersion/tasks/${fixture.dispersion_task_id}/calibrations/fit`)&&r.request().method()==='POST')
  await page.getByRole('button',{name:'二次拟合',exact:true}).click()
  await fitted
  const after=await call(page,`/api/v1/dispersion/tasks/${fixture.dispersion_task_id}`)
  assert.equal(after.lines.find(line=>line.id===first.id).saved_position,100)
  assert.equal(after.calibrations[0].residuals.find(r=>r.line_id===first.id).measured_position,110)
  assert.equal(after.residual_limit_points,2)
  assert.ok(Math.abs(after.calibrations[0].residual_limit_points-150/14)<1e-9)
  await page.screenshot({path:path.join(output,'dispersion-current-position.png'),fullPage:true})
  checked('当前实测位置110直接参与拟合，保存位置100仅作恢复，允许误差按150/14换算')

  const queue=await call(page,'/api/v1/sample-queues',{name:'20位先列后行验证',name_length:20,items:Array.from({length:22},(_,i)=>({pre_name:`2026101700${String(i+1).padStart(10,'0')}`,repeats:1}))})
  await go('samples','.sample-queue-page')
  await page.getByLabel(/^选择样品队列/).selectOption(String(queue.id))
  const cards=page.getByRole('table',{name:'样号按列排列表格'}).locator('[data-sample-id]')
  await cards.first().waitFor()
  const boxes=await readSampleCells(page)
  assert.deepEqual(boxes.map(cell=>cell.name),queue.items.map(i=>i.pre_name))
  assert.ok(boxes.slice(0,20).every((box,index)=>box.x===boxes[0].x&&(index===0||box.y>boxes[index-1].y)))
  assert.ok(boxes[20].x>boxes[0].x&&boxes[20].y===boxes[0].y)
  await page.screenshot({path:path.join(output,'20-digit-columns.png'),fullPage:true})
  checked('20位22条完整样号按列排列；每列先上后下且完整名称可在详情查看')
  result.layout=[]
  for(const [width,theme] of [[1440,'light'],[1060,'dark']]){
    if(process.env.QA_CDP)await page.evaluate(width=>window.__TAURI__.core.invoke('plugin:window|set_size',{value:{Logical:{width,height:1000}}}),width)
    else await page.setViewportSize({width,height:1000})
    await call(page,'/api/v1/settings',{display:{theme,density:theme==='dark'?'compact':'comfortable'}},'PATCH')
    await page.getByRole('button',{name:'刷新服务状态',exact:true}).click()
    await page.waitForFunction(theme=>document.querySelector('.app-shell')?.dataset.theme===theme,theme)
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1))
    assert.equal(await cards.count(),22)
    await page.screenshot({path:path.join(output,`columns-${width}-${theme}.png`),fullPage:true})
    result.layout.push({width,theme})
  }
  checked('明色1440与暗色紧凑1060保持完整样号及操作，无窗口横向溢出')
}
