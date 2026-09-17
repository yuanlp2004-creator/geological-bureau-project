// Run only against an isolated seed_bf02_browser.py fixture.
import assert from 'node:assert/strict';
import {pathToFileURL} from 'node:url';
import {mkdir, writeFile} from 'node:fs/promises';
assert.equal(process.env.QA_ISOLATED,'1');
const {chromium}=await import(pathToFileURL(process.env.PLAYWRIGHT_MODULE).href);
const browser=process.env.QA_CDP ? await chromium.connectOverCDP(process.env.QA_CDP) : await chromium.launch({channel:'msedge',headless:true});
const out=process.env.QA_OUTPUT;
await mkdir(out,{recursive:true});
const observations=[];
try {
 const page=process.env.QA_CDP ? browser.contexts()[0].pages().find(p=>p.url().includes('tauri.localhost')) : await browser.newPage({viewport:{width:1920,height:1080}});
 const errors=[]; page.on('pageerror',e=>errors.push(e.message));
 if(!process.env.QA_CDP) await page.goto('http://127.0.0.1:5174');
 await page.getByLabel('用户名',{exact:true}).fill('qa_admin');
 await page.getByLabel('密码',{exact:true}).fill('QaTest-2026!');
 await page.getByRole('button',{name:'登录',exact:true}).click();
 await page.locator('.workspace-page').waitFor();
 await page.locator('.quick-action').filter({hasText:'方法管理'}).click();
 await page.getByLabel('选择编辑方法').waitFor();
 await page.waitForFunction(()=>Array.from(document.querySelector('select[aria-label="选择编辑方法"]')?.options??[]).some(o=>o.textContent.includes('S16 测试方法')));
 const original=await page.getByLabel('选择编辑方法').locator('option').filter({hasText:'S16 测试方法'}).getAttribute('value');
 await page.getByLabel('选择编辑方法').selectOption(original);
 await page.locator('.method-editor-tabs button').filter({hasText:'分析谱线'}).click();
 await page.locator('.spectral-line-card').first().waitFor();
 for(const width of (process.env.QA_CDP ? [null] : [1920,1280,1060])) {
  if(width) await page.setViewportSize({width,height:width===1920?1080:720});
  for(const dark of [false,true]) {
   await page.evaluate(dark=>{document.documentElement.dataset.theme=dark?'dark':'light';document.documentElement.dataset.density=dark?'compact':'comfortable'},dark);
   const list=await page.locator('.spectral-list-surface').boundingBox();
   const editor=await page.locator('.spectral-editor-surface').boundingBox();
   const context=await page.locator('.method-context-bar').boundingBox();
   assert.ok(Math.abs(list.y-editor.y)<2,'List and editor must start at the same height');
   assert.ok(editor.width>list.width*1.7,'Editor must dominate width');
   assert.ok(context.height<170,'Toolbar must stay compact');
   assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'No viewport overflow');
   observations.push({width:width||'desktop',dark,list,editor,context});
   await page.screenshot({path:`${out}/methods-${width||'desktop'}-${dark?'dark':'light'}.png`});
  }
 }
 await page.getByRole('button',{name:'收起清单',exact:true}).click();
 assert.equal(await page.locator('.spectral-list-surface').isVisible(),false);
 await page.getByRole('button',{name:'展开谱线清单',exact:true}).click();
 assert.equal(await page.locator('.spectral-list-surface').isVisible(),true);
 await page.getByRole('button',{name:'新建方法',exact:true}).click();
 const name=`UI布局${Date.now().toString().slice(-6)}`;
 await page.getByLabel('新方法名称').fill(name);
 await page.getByRole('button',{name:'确认',exact:true}).click();
 await page.waitForFunction(name=>document.querySelector('select[aria-label="选择编辑方法"]')?.selectedOptions[0]?.textContent.includes(name),name);
 const created=await page.getByLabel('选择编辑方法').inputValue();
 assert.notEqual(created,original);
 await page.locator('.method-editor-tabs button').filter({hasText:'方法条件'}).click();
 await page.getByLabel('说明',{exact:true}).fill('布局回归草稿');
 await Promise.all([page.waitForResponse(r=>r.request().method()==='PATCH'&&r.url().endsWith(`/methods/${created}`)&&r.ok()),page.getByRole('button',{name:'保存草稿',exact:true}).click()]);
 await page.getByLabel('选择编辑方法').selectOption(original);
 await page.getByLabel('选择编辑方法').selectOption(created);
 await page.waitForFunction(()=>document.querySelector('.method-field-grid textarea')?.value==='布局回归草稿');
 const frame=page.locator('.field').filter({hasText:/^采集帧数/}).locator('input');
 await frame.fill('');
 let writes=0;
 const listener=r=>{if(r.method()==='PATCH'&&r.url().includes('/methods/'))writes++};
 page.on('request',listener);
 await page.getByRole('button',{name:'保存草稿',exact:true}).click();
 assert.equal(await frame.inputValue(),'');
 assert.equal(await frame.evaluate(el=>el.checkValidity()),false);
 assert.equal(await frame.evaluate(el=>document.activeElement===el),true);
 assert.equal(writes,0);
 page.off('request',listener);
 await page.getByLabel('选择编辑方法').selectOption(original);
 await page.locator('.method-editor-tabs button').filter({hasText:'分析谱线'}).click();
 if(!process.env.QA_CDP) await page.setViewportSize({width:1920,height:1080});
 await page.evaluate(()=>{document.documentElement.dataset.theme='light';document.documentElement.dataset.density='comfortable'});
 await page.locator('.spectral-line-card').first().waitFor();
 await page.screenshot({path:`${out}/method-layout-final.png`});
 assert.deepEqual(errors,[]);
 await writeFile(`${out}/result.json`,JSON.stringify({status:'passed',observations,checks:['single local sidebar','fold/unfold','create and select','save persistence','invalid numeric zero writes','no page errors']},null,2));
 console.log(JSON.stringify({status:'passed',observations}));
} finally {await browser.close()}
