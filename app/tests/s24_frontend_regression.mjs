// Isolated database only. Seed with seed_bf02_browser.py; never use user data.
import assert from 'node:assert/strict';
import { pathToFileURL } from 'node:url';
import { mkdir, writeFile, readFile } from 'node:fs/promises';
assert.equal(process.env.QA_ISOLATED, '1');
const { chromium } = await import(pathToFileURL(process.env.PLAYWRIGHT_MODULE).href);
const browser = process.env.QA_CDP ? await chromium.connectOverCDP(process.env.QA_CDP) : await chromium.launch({channel:'msedge', headless:true});
const out = process.env.QA_OUTPUT;
await mkdir(out, {recursive:true});
const observations = [];
let page;
try {
  page = process.env.QA_CDP ? browser.contexts()[0].pages().find(p => p.url().includes('tauri.localhost')) : await browser.newPage({viewport:{width:1920,height:1080}});
  const errors=[]; page.on('pageerror', e => errors.push(e.message));
  if (!process.env.QA_CDP) await page.goto(process.env.QA_URL || 'http://127.0.0.1:5174');
  await page.getByLabel('用户名',{exact:true}).fill('qa_admin');
  await page.getByLabel('密码',{exact:true}).fill('QaTest-2026!');
  await page.getByRole('button',{name:'登录',exact:true}).click();
  await page.locator('.workspace-page').waitFor();
  const token=await page.evaluate(()=>sessionStorage.getItem('geospectrum.token'));
  const runtime=process.env.QA_CDP ? await page.evaluate(()=>window.__TAURI__.core.invoke('runtime_config')) : null;
  const headers={Authorization:`Bearer ${token}`, ...(runtime ? {'X-GeoSpectrum-Process-Key':runtime.process_key} : {})};
  const call=async(path,data,method='POST')=>{
    const response=await page.request.fetch(new URL(`/api/v1${path}`,runtime?.api_base || page.url()).href,{headers,method,data});
    assert.ok(response.ok(),`${path}: ${await response.text()}`);
    return response.status()===204 ? null : response.json();
  };
  const caps=await call('/capabilities',undefined,'GET');
  const entries=caps.capabilities.flatMap(c=>c.navigation_entries || []);
  await call('/methods/1/open');
  await page.reload(); await page.locator('.workspace-page').waitFor();
  const navigate=async(pageKey,view)=>{
    const entry=entries.find(e=>e.page===pageKey && (view===undefined || e.view===view));
    assert.ok(entry,pageKey);
    await page.mouse.move(900,75); await page.keyboard.press('Escape');
    await page.locator(`[data-navigation-group="${entry.group}"]`).click();
    if(entry.group!=='workspace') await page.getByRole('menuitem').filter({has:page.locator('strong').filter({hasText:new RegExp(`^${entry.label}$`)})}).click();
    await page.mouse.move(900,75); await page.keyboard.press('Escape');
    await page.locator('.breadcrumbs strong').filter({hasText:entry.label}).waitFor();
    await page.waitForTimeout(150);
    await page.waitForLoadState('networkidle');
  };
  const capture=async(key)=>{
    await page.evaluate(()=>scrollTo(0,0));
    const geometry=await page.evaluate(()=>({width:innerWidth,height:innerHeight,dpr:devicePixelRatio,scroll:document.documentElement.scrollWidth,overflow:[...document.querySelectorAll('.remaining-page *')].filter(e=>{const r=e.getBoundingClientRect(); return r.width>0 && r.right>innerWidth+2 && !e.closest('[class*="table"], .analysis-matrix, [hidden]')}).slice(0,8).map(e=>e.className)}));
    observations.push({key,...geometry});
    await page.screenshot({path:`${out}/${key}.png`});
    assert.ok(geometry.scroll<=geometry.width+1,`${key}: window overflow ${JSON.stringify(geometry)}`);
  };
  // Every formal page and internal analysis/postprocessing view at 1080p.
  const pages=[['sample-acquisition'],['samples'],['acquisition'],['analysis','raw'],['analysis','quality'],['analysis','curve'],['postprocessing','interval'],['postprocessing','recalculate-export'],['reports'],['dispersion'],['hardware-acquisition'],['mercury-calibration'],['migration'],['spectrum-migration'],['result-migration'],['settings'],['users'],['audit'],['maintenance'],['help'],['about']];
  for(const [key,view] of pages){await navigate(key,view); await capture(`${key}-${view||'main'}`);}
  console.log('PASS: all remaining pages and subviews reachable');
  if(process.env.QA_CAPTURE_ONLY === '1'){await writeFile(`${out}/results.json`,JSON.stringify({observations,errors},null,2));await browser.close();process.exit(0);}
  // Queue -> task creation: invalid input and server failure preserve draft.
  await navigate('samples');
  await page.getByRole('button',{name:'新建队列',exact:true}).click();
  const name=`UI回归${Date.now()}`;
  await page.getByLabel('队列名称',{exact:true}).fill(name);
  await page.getByLabel('样品名',{exact:true}).fill('UI24');
  await page.getByLabel('重复次数',{exact:true}).fill('2');
  const [queueResponse]=await Promise.all([page.waitForResponse(r=>r.request().method()==='POST'&&r.url().endsWith('/sample-queues')&&r.ok()),page.getByRole('button',{name:'创建队列',exact:true}).click()]);
  const queueId=String((await queueResponse.json()).id);
  await page.locator('.sample-table-wrap tbody tr').waitFor();
  await navigate('sample-acquisition');
  await page.waitForFunction(id=>[...document.querySelectorAll('.acquisition-create select option')].some(o=>o.value===id&&o.textContent.startsWith('UI回归')),queueId);
  const form=page.locator('.acquisition-create');
  if(!await form.isVisible()) await page.getByRole('button',{name:'建立采集任务',exact:true}).click();
  await form.getByLabel('任务名称',{exact:true}).fill(name);
  await form.getByLabel(/^已发布方法版本/).selectOption('1:1');
  await form.getByLabel(/^样品队列/).selectOption(queueId);
  await form.getByLabel(/^预录样品/).selectOption({index:1});
  assert.equal(await form.getByLabel('重复次数（来自队列）').inputValue(),'2');
  assert.ok(await form.getByLabel('重复次数（来自队列）').isDisabled());
  await form.getByLabel(/^燃烧帧/).fill('');
  let writes=0; const listener=r=>{if(r.method()==='POST'&&r.url().endsWith('/acquisitions/tasks'))writes++};
  page.on('request',listener);
  await form.getByRole('button',{name:'创建任务',exact:true}).click();
  assert.equal(writes,0); page.off('request',listener);
  await form.getByLabel(/^燃烧帧/).fill('2');
  await page.route('**/api/v1/acquisitions/tasks',route=>route.request().method()==='POST' ? route.fulfill({status:422,contentType:'application/json',body:JSON.stringify({code:'qa_rejected',message:'隔离测试：创建失败，请保留输入'})}) : route.continue());
  await form.getByRole('button',{name:'创建任务',exact:true}).click();
  await page.locator('.toast.error').waitFor();
  assert.equal(await form.getByLabel('任务名称',{exact:true}).inputValue(),name);
  await page.getByRole('button',{name:'建立采集任务',exact:true}).click();
  assert.ok(!await form.isVisible());
  await page.getByRole('button',{name:'建立采集任务',exact:true}).click();
  assert.equal(await form.getByLabel('任务名称',{exact:true}).inputValue(),name);
  await page.unroute('**/api/v1/acquisitions/tasks');
  const [created]=await Promise.all([page.waitForResponse(r=>r.request().method()==='POST'&&r.url().endsWith('/acquisitions/tasks')&&r.ok()),form.getByRole('button',{name:'创建任务',exact:true}).click()]);
  let task=await created.json(); await form.waitFor({state:'hidden'});
  await page.getByRole('button',{name:'收起列表',exact:true}).click();
  assert.ok(!await page.locator('.acquisition-task-list').isVisible());
  await page.getByRole('button',{name:'开始',exact:true}).click();
  await page.locator('.acquisition-monitor .state-chip').filter({hasText:/倒计时|预激发|燃烧/}).waitFor();
  await page.getByRole('button',{name:'暂停',exact:true}).click();
  await page.getByRole('button',{name:'继续',exact:true}).waitFor();
  await capture('sample-paused-collapsed');
  await page.getByRole('button',{name:'展开列表',exact:true}).click();
  await page.getByRole('button',{name:'继续',exact:true}).click();
  for(let i=0;i<30;i++){
    task=await call(`/acquisitions/tasks/${task.id}`,undefined,'GET');
    if(['completed','failed','stopped'].includes(task.status))break;
    await page.getByRole('button',{name:'单步',exact:true}).click();
    await page.waitForLoadState('networkidle');
  }
  assert.equal(task.status,'completed'); assert.equal(task.completed_repeats,2);
  await capture('sample-completed');
  console.log('PASS: queue repeats, zero writes on invalid input, failure preservation, collapse, pause/resume, completed acquisition');
  // Core analysis continues through the actual UI using the independent golden input.
  await navigate('analysis','raw');
  if(!await page.locator('.analysis-create').isVisible())await page.getByRole('button',{name:'建立分析运行',exact:true}).click();
  for (const checkbox of await page.locator('.analysis-sample-groups input[type="checkbox"]').all()) await checkbox.uncheck();
  await page.locator('.analysis-sample-groups label').filter({hasText:'S16-A'}).locator('input').check();
  await page.locator('.analysis-switch input').uncheck();
  await page.getByRole('button',{name:'建立并锁定输入',exact:true}).click();
  await page.locator('.analysis-create').waitFor({state:'hidden'});
  let [response]=await Promise.all([page.waitForResponse(r=>r.url().endsWith('/start')&&r.request().method()==='POST'),page.getByRole('button',{name:'开始',exact:true}).click()]);
  let run=await response.json();
  for(let i=0;i<30&&run.status==='running';i++){
    [response]=await Promise.all([page.waitForResponse(r=>r.url().endsWith('/step')&&r.request().method()==='POST'),page.getByRole('button',{name:'推进一条谱线',exact:true}).click()]);run=await response.json();
  }
  assert.equal(run.status,'completed');
  for(const view of ['raw','quality','curve']){await navigate('analysis',view);await capture(`analysis-data-${view}`);}
  await navigate('analysis','quality');
  await page.locator('.analysis-run-list button').filter({hasText:'S17 完成批次'}).first().click();
  await page.locator('.analysis-status-row h2').filter({hasText:/^S17 完成批次$/}).waitFor();
  await page.getByRole('button',{name:'重新统计',exact:true}).click();
  await page.waitForLoadState('networkidle');
  await page.locator('.analysis-view-tabs').getByRole('button',{name:'曲线图',exact:true}).click();
  await page.getByRole('button',{name:'重新拟合',exact:true}).click();
  await page.getByRole('button',{name:/^发布快照 #/}).click();
  await capture('analysis-fitted-curve');
  const curveAlignment=await page.locator('svg[aria-label="标准曲线"]').evaluate(svg=>{const points=[...svg.querySelectorAll('circle')];const box=svg.getBoundingClientRect();const map=el=>{const p=svg.createSVGPoint();p.x=Number(el.getAttribute('cx'));p.y=Number(el.getAttribute('cy'));return p.matrixTransform(svg.getScreenCTM())};const first=map(points[0]),last=map(points[points.length-1]);return Math.max(Math.abs(first.x-box.left),Math.abs(first.y-box.bottom),Math.abs(last.x-box.right),Math.abs(last.y-box.top))});
  assert.ok(curveAlignment<1,`standard curve axis mismatch ${curveAlignment}px`);
  await page.locator('.analysis-view-tabs').getByRole('button',{name:'样品结果',exact:true}).click();
  await page.getByRole('button',{name:'合并并保存',exact:true}).click();
  await page.locator('.merge-history article').first().waitFor();
  await navigate('reports');
  if(!await page.locator('.report-builder').isVisible())await page.getByRole('button',{name:'选择来源并建立报告',exact:true}).click();
  for(const checkbox of await page.locator('.report-run-row input').all())await checkbox.uncheck();
  await page.locator('.report-run-row').filter({hasText:'S17 完成批次'}).first().locator('input').check();
  await page.getByRole('button',{name:'建立报告版本',exact:true}).click();
  await page.locator('.report-summary').waitFor();
  await page.getByRole('button',{name:'预览',exact:true}).click();
  await page.locator('.report-preview-modal iframe').waitFor();
  await capture('report-preview');
  await page.locator('.report-preview-modal').getByRole('button',{name:'关闭',exact:true}).click();
  await page.getByRole('button',{name:'确认报告',exact:true}).click();
  await page.getByLabel('输出目录',{exact:true}).fill(`${out}/report-output`);
  const [exported]=await Promise.all([page.waitForResponse(r=>/\/reports\/\d+\/exports$/.test(r.url())&&r.request().method()==='POST'),page.getByRole('button',{name:'PDF',exact:true}).click()]);
  assert.ok(exported.ok(),await exported.text());
  const pdf=await readFile((await exported.json()).path);assert.equal(pdf.subarray(0,5).toString(),'%PDF-');
  console.log('PASS: analysis, quality/curve context and axes, report creation, preview and PDF output');
  // Calibration and device safety use the existing deterministic adapters only.
  const hardware=await call('/hardware-acquisitions/tasks',{name:'UI转角安全回归',turns:[{angle_deg:10,wavelength_nm:280,priority:1,key_band:true}]});
  await navigate('hardware-acquisition');
  await page.getByRole('button',{name:'启动',exact:true}).click();
  await page.getByRole('button',{name:'收起列表',exact:true}).click();
  await capture('hardware-running-collapsed');
  const [stopResponse]=await Promise.all([page.waitForResponse(r=>r.url().endsWith(`/hardware-acquisitions/tasks/${hardware.id}/stop`)&&r.request().method()==='POST'),page.getByRole('button',{name:'安全停止',exact:true}).click()]);
  const stopped=await stopResponse.json();
  assert.ok(['stopped','safety_stopped'].includes(stopped.status),JSON.stringify(stopped));
  const mercuryOptions=await call('/mercury-calibrations/options',undefined,'GET');
  const session=await call('/mercury-calibrations/sessions',{name:'UI汞灯校准回归',line_ids:mercuryOptions.reference_lines.slice(0,4).map(x=>x.id),stabilization_frames:2,simulator_offset_points:6});
  await navigate('mercury-calibration');
  const [mercuryStarted]=await Promise.all([page.waitForResponse(r=>r.url().endsWith(`/mercury-calibrations/sessions/${session.id}/start`)&&r.request().method()==='POST'),page.getByRole('button',{name:'启动',exact:true}).click()]);
  let mercuryState=await mercuryStarted.json();
  for(let i=0;i<20&&['stabilizing','acquiring'].includes(mercuryState.status);i++){
    const [stepped]=await Promise.all([page.waitForResponse(r=>r.url().endsWith(`/mercury-calibrations/sessions/${session.id}/step`)&&r.request().method()==='POST'),page.getByRole('button',{name:'单步',exact:true}).click()]);
    mercuryState=await stepped.json();
  }
  assert.equal(mercuryState.status,'ready');
  await page.getByRole('button',{name:'应用建议',exact:true}).click();
  await page.getByRole('button',{name:'回滚',exact:true}).click();
  await page.waitForLoadState('networkidle');
  await capture('mercury-applied-rollback');
  if(await page.getByRole('button',{name:'安全停止',exact:true}).isEnabled())await page.getByRole('button',{name:'安全停止',exact:true}).click();
  await navigate('dispersion');
  if(!await page.locator('.dispersion-setup').isVisible())await page.getByRole('button',{name:'新建任务与采集条件',exact:true}).click();
  await page.getByRole('button',{name:'新建任务',exact:true}).click();
  await page.locator('.dispersion-setup').waitFor({state:'hidden'});
  await page.getByRole('button',{name:'开始',exact:true}).click();
  await page.getByRole('button',{name:'暂停',exact:true}).click();
  await capture('dispersion-paused');
  await page.getByRole('button',{name:'停止',exact:true}).click();
  assert.ok(await page.getByRole('button',{name:'二次拟合',exact:true}).isDisabled());
  await navigate('acquisition');
  await page.getByRole('button',{name:'连接诊断',exact:true}).click();
  await page.getByRole('button',{name:'开始',exact:true}).click();
  await page.locator('.curve-path').waitFor();
  if(await page.getByRole('button',{name:'十字线',exact:true}).getAttribute('aria-pressed')!=='true')await page.getByRole('button',{name:'十字线',exact:true}).click();
  const chart=page.locator('.curve-frame .simple-chart-plot svg');
  const bounds=await chart.boundingBox();
  await page.mouse.move(bounds.x+bounds.width/2,bounds.y+bounds.height/2);
  await page.getByTestId('acquisition-hover-readout').waitFor();
  const mapping=await page.getByTestId('acquisition-crosshair-x').evaluate(el=>{const svg=el.ownerSVGElement;const p=svg.createSVGPoint();p.x=Number(el.getAttribute('x1'));p.y=0;const r=p.matrixTransform(svg.getScreenCTM());const b=svg.getBoundingClientRect();return Math.abs(r.x-(b.x+b.width/2))});
  assert.ok(mapping<3,`debug pointer mapping ${mapping}px`);
  await page.getByRole('button',{name:'停止',exact:true}).click();
  await page.getByRole('button',{name:'断开',exact:true}).click();
  await capture('debug-stopped');
  await navigate('maintenance');
  await page.getByLabel('备份目录',{exact:true}).fill(`${out}/backups`);
  await page.getByRole('button',{name:'创建备份',exact:true}).click();
  await page.locator('.maintenance-row').first().waitFor();
  await page.locator('.maintenance-row').first().getByRole('button',{name:'校验',exact:true}).click();
  await page.waitForLoadState('networkidle');
  await capture('maintenance-verified');
  console.log('PASS: hardware stop, mercury apply/rollback, dispersion pause/stop, debug pointer, isolated backup verification');
  for(const width of (process.env.QA_CDP ? [null] : [1280,1060])){
    if(width)await page.setViewportSize({width,height:width===1060?680:720});
    for(const dark of [false,true]){
      await page.evaluate(dark=>{document.documentElement.dataset.theme=dark?'dark':'light';document.documentElement.dataset.density=dark?'compact':'comfortable'},dark);
      for(const key of ['sample-acquisition','acquisition','analysis','reports','dispersion','hardware-acquisition','mercury-calibration','postprocessing','settings','users','help']){
        await navigate(key);await capture(`${key}-${width||'desktop'}-${dark?'dark':'light'}`);
      }
    }
  }
  assert.deepEqual(errors,[]);
  await writeFile(`${out}/results.json`,JSON.stringify({observations,errors},null,2));
  console.log(`PASS: ${observations.length} layout states; no page errors`);
} catch(error) {
  if(page)await page.screenshot({path:`${out}/failure.png`}).catch(()=>{});
  await writeFile(`${out}/partial-results.json`,JSON.stringify(observations,null,2));
  throw error;
} finally { await browser.close(); }
