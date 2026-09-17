// Isolated fixture only: seed_bf02_browser.py followed by the S10 seed_database fixture.
// QA_ISOLATED=1 is required; QA_CDP optionally exercises the packaged WebView2.
import assert from 'node:assert/strict';
import { pathToFileURL, fileURLToPath } from 'node:url';
import { mkdir, writeFile } from 'node:fs/promises';
assert.equal(process.env.QA_ISOLATED, '1', 'Explicit isolated test environment required');
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE ? pathToFileURL(process.env.PLAYWRIGHT_MODULE).href : 'playwright');
const out = process.env.QA_OUTPUT || fileURLToPath(new URL('../.local/tmp/s23-verification/', import.meta.url));
await mkdir(out, {recursive:true});
const browser = process.env.QA_CDP
  ? await chromium.connectOverCDP(process.env.QA_CDP)
  : await chromium.launch({channel:'msedge',headless:true});
const observations=[];
try {
 const page=process.env.QA_CDP ? browser.contexts()[0].pages().find(p=>p.url().includes('tauri.localhost')) : await browser.newPage({viewport:{width:1920,height:1080}});
 assert.ok(page);
 const errors=[];
 page.on('pageerror',e=>errors.push(e.message));
 if (!process.env.QA_CDP) await page.goto(process.env.QA_URL || 'http://127.0.0.1:5174');
 await page.getByLabel('用户名',{exact:true}).fill('qa_admin');
 await page.getByLabel('密码',{exact:true}).fill('QaTest-2026!');
 await page.getByRole('button',{name:'登录',exact:true}).click();
 await page.locator('.workspace-page').waitFor();
 const token=await page.evaluate(()=>sessionStorage.getItem('geospectrum.token'));
 const runtime=process.env.QA_CDP ? await page.evaluate(()=>window.__TAURI__.core.invoke('runtime_config')) : null;
 const headers={Authorization:`Bearer ${token}`,...(runtime?{'X-GeoSpectrum-Process-Key':runtime.process_key}:{})};
 const call=async (path,data,method='POST')=>{
  const r=await page.request.fetch(new URL(`/api/v1${path}`,runtime?.api_base||page.url()).href,{headers,method,data});
  assert.ok(r.ok(),await r.text());
  return r.status()===204 ? null : r.json();
 };
 const methods=await call('/methods',undefined,'GET');
 assert.ok(methods.some(x=>x.name==='S16 测试方法'),'S16 isolated seed missing');
 await call('/methods/1/open');
 await page.reload();
 await page.locator('.workspace-page').waitFor();
 const navigate=async name=>{
  await page.mouse.move(900,90);
  await page.keyboard.press('Escape');
  if(name==='home') {await page.getByRole('button',{name:'工作台',exact:true}).click(); await page.locator('.workspace-page').waitFor();}
  if(name==='methods') {await page.locator('.workspace-method').click(); await page.locator('.method-action-bar').waitFor();}
  if(name==='spectrum') {
   await page.getByRole('button',{name:'分析测试',exact:true}).click();
   await page.getByRole('menuitem').filter({hasText:'谱图查看'}).click();
   await page.mouse.move(900,90); await page.keyboard.press('Escape');
   await page.locator('.navigation-panel').waitFor({state:'hidden'});
   await page.locator('.spectrum-line').first().waitFor();
  }
 };
 const capture=async name=>{
  await page.screenshot({path:`${out}/${name}.png`});
 };
 const checkLayout=async name=>{
  const size=await page.evaluate(()=>({width:innerWidth,height:innerHeight,dpr:devicePixelRatio,scrollWidth:document.documentElement.scrollWidth,theme:document.documentElement.dataset.theme,density:document.documentElement.dataset.density}));
  assert.ok(size.scrollWidth<=size.width+1,`${name}: document overflow ${JSON.stringify(size)}`);
  observations.push({name,...size});
 };
 const theme=async (theme,density)=>{
  await page.evaluate(({theme,density})=>{document.documentElement.dataset.theme=theme;document.documentElement.dataset.density=density;},{theme,density});
 };
 for(const size of (process.env.QA_CDP ? [null] : [{width:1920,height:1080},{width:1280,height:720},{width:2560,height:1440},{width:3840,height:2160}])) {
  if(size) await page.setViewportSize(size);
  for(const name of ['home','methods','spectrum']) {
   await navigate(name);
   await theme('light','comfortable');
   await checkLayout(`${name}-${size?.width||'desktop'}-light`);
   if(!size||[1920,1280].includes(size.width)) await capture(`${name}-${size?.width||'desktop'}-light`);
   await theme('dark','compact');
   await checkLayout(`${name}-${size?.width||'desktop'}-dark-compact`);
   if(!size||size.width===1920) await capture(`${name}-${size?.width||'desktop'}-dark`);
  }
 }
 if(!process.env.QA_CDP) await page.setViewportSize({width:1280,height:720});
 await theme('light','comfortable');
 await navigate('methods');
 await page.locator('.method-editor-tabs button').filter({hasText:'分析谱线'}).click();
 await page.locator('.spectral-line-card').filter({hasText:'Cu'}).click();
 await page.locator('.detectability-card.checking').waitFor({state:'hidden'});
 await checkLayout('method-lines-minimum');
 await capture('method-lines-minimum');
 await page.locator('.method-editor-tabs button').filter({hasText:'预览与打印'}).click();
 await page.locator('.print-workbench').waitFor();
 await checkLayout('method-print-minimum');
 await page.locator('.method-editor-tabs button').filter({hasText:'方法条件'}).click();
 // The numerical golden fixture intentionally stores more precision than UI step=0.0001.
 // Normalize these two editing values so this check exercises only the blank frame field.
 await page.getByLabel('参考波长 (nm)',{exact:true}).fill('252.2');
 await page.getByLabel('实际参考波长 (nm)',{exact:true}).fill('252.2');
 const invalid=page.locator('.field').filter({hasText:/^采集帧数/}).locator('input');
 await invalid.fill('');
 let writes=0;
 const count=r=>{if(r.method()==='PATCH'&&/\/api\/v1\/methods\/\d+$/.test(new URL(r.url()).pathname))writes++;};
 page.on('request',count);
 await page.locator('.method-save-footer button').click();
 assert.equal(await invalid.inputValue(),'');
 assert.equal(writes,0,'Invalid field must not write a method');
 assert.equal(await invalid.evaluate(el=>el.checkValidity()),false);
 assert.equal(await invalid.evaluate(el=>document.activeElement===el),true,'Validation must focus the invalid frame count');
 await capture('method-invalid-number');
 await invalid.fill('10');
 page.off('request',count);
 await navigate('spectrum');
 await page.locator('.spectrum-record-row').filter({hasText:'Raw sample'}).locator('button').click();
 await page.locator('.spectrum-line[data-curve-id="raw:1"]').waitFor();
 const plot=page.getByTestId('spectrum-plot');
 await plot.scrollIntoViewIfNeeded();
 await checkLayout('raw-spectrum-minimum');
 const point=await plot.evaluate(svg=>{
  const values=[...svg.querySelector('.spectrum-line').getAttribute('d').matchAll(/[ML] ([\d.-]+) ([\d.-]+)/g)];
  const x=Number(values[3][1]), y=Number(values[3][2]);
  const screen=new DOMPoint(x,y).matrixTransform(svg.getScreenCTM());
  return {x,y,screenX:screen.x,screenY:screen.y};
 });
 await page.mouse.move(point.screenX,point.screenY);
 await page.locator('.plot-cursor').waitFor();
 const cursorX=Number(await page.locator('.plot-cursor').getAttribute('cx'));
 assert.ok(Math.abs(cursorX-point.x)<0.1,`Cursor-to-data mapping: ${cursorX} vs ${point.x}`);
 await page.mouse.click(point.screenX,point.screenY);
 await page.locator('.spectrum-cursor-readout .lucide-lock-keyhole').waitFor();
 await page.mouse.move(point.screenX+60,point.screenY);
 assert.equal(Number(await page.locator('.plot-cursor').getAttribute('cx')),cursorX,'Locked cursor must remain on the same point');
 await page.getByRole('button',{name:'适配',exact:true}).click();
 const fullRange=await page.locator('.spectrum-pan > span').textContent();
 await page.getByTitle('横向放大',{exact:true}).click();
 assert.notEqual(await page.locator('.spectrum-pan > span').textContent(),fullRange);
 await page.getByRole('button',{name:'滚动',exact:true}).click();
 await plot.scrollIntoViewIfNeeded();
 const b=await plot.boundingBox();
 const beforePan=await page.locator('.spectrum-pan > span').textContent();
 await page.mouse.move(b.x+b.width*.5,b.y+b.height*.5);await page.mouse.down();await page.mouse.move(b.x+b.width*.6,b.y+b.height*.5,{steps:5});await page.mouse.up();
 assert.notEqual(await page.locator('.spectrum-pan > span').textContent(),beforePan);
 await page.getByRole('button',{name:'适配',exact:true}).click();
 await page.getByRole('button',{name:'框选',exact:true}).click();
 await plot.scrollIntoViewIfNeeded();
 const box=await plot.boundingBox();
 await page.mouse.move(box.x+box.width*.25,box.y+box.height*.25);await page.mouse.down();await page.mouse.move(box.x+box.width*.7,box.y+box.height*.7,{steps:5});await page.mouse.up();
 assert.notEqual(await page.locator('.spectrum-pan > span').textContent(),fullRange);
 await page.getByRole('button',{name:'适配',exact:true}).click();
 if(!process.env.QA_CDP) {
  const downloaded=page.waitForEvent('download');
  await page.getByRole('button',{name:'导出可见范围',exact:true}).click();
  const download=await downloaded;
  assert.ok(download.suggestedFilename().endsWith('.csv'));
  await download.saveAs(`${out}/visible-spectrum.csv`);
 }
 assert.deepEqual(errors,[]);
 await writeFile(`${out}/layout-results.json`,JSON.stringify(observations,null,2));
 console.log(`PASS S23: ${observations.length} layout states, method invalid-input zero writes, print panel, cursor mapping/lock, zoom/pan/box, ${process.env.QA_CDP?'desktop':'CSV download'}, no pageerror`);
} finally {await browser.close();}
