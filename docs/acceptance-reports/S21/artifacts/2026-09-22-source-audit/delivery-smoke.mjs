import assert from 'node:assert/strict';
import { writeFile } from 'node:fs/promises';
import { pathToFileURL } from 'node:url';
const { chromium } = await import(pathToFileURL(process.env.PLAYWRIGHT_MODULE).href);
const browser = await chromium.connectOverCDP(process.env.QA_CDP);
const result={status:'failed',checks:[]};
try {
 const page=browser.contexts()[0].pages().find(p=>p.url().includes('tauri.localhost'));
 assert.ok(page,'packaged Tauri page');
 page.setDefaultTimeout(20000);
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.getByRole('heading',{name:'初始化本地管理员'}).waitFor();
 await page.getByLabel('用户名',{exact:true}).fill('delivery-admin');
 await page.getByLabel('密码',{exact:true}).fill('Delivery-check-2026!');
 await page.getByLabel('确认密码',{exact:true}).fill('Delivery-check-2026!');
 await page.getByRole('button',{name:'创建管理员'}).click();
 await page.getByRole('heading',{name:'登录工作台'}).waitFor();
 await page.getByLabel('密码',{exact:true}).fill('Delivery-check-2026!');
 await page.getByRole('button',{name:'登录',exact:true}).click();
 await page.waitForFunction(()=>!!sessionStorage.getItem('geospectrum.token')&&!document.querySelector('.auth-form'));
 result.checks.push('packaged root EXE bootstrap and login');
 const verified=await page.evaluate(async()=>{
  const config=await window.__TAURI__.core.invoke('runtime_config');
  const headers={'X-GeoSpectrum-Process-Key':config.process_key,Authorization:`Bearer ${sessionStorage.getItem('geospectrum.token')}`};
  const health=await (await fetch(`${config.api_base}/health`,{headers})).json();
  const schema=await (await fetch(`${config.api_base}/openapi.json`,{headers})).json();
  const denied=await fetch(`${config.api_base}/api/v1/analyses/options`);
  return {health,legacyImportAvailable:!!schema.paths['/api/v1/analyses/legacy-sources'],deniedStatus:denied.status,scripts:[...document.scripts].map(s=>s.src).filter(Boolean)};
 });
 assert.equal(verified.health.status,'ok');assert.equal(verified.health.schema_version,21);
 assert.ok(verified.legacyImportAvailable);assert.ok([401,403].includes(verified.deniedStatus));
 result.checks.push('real Tauri runtime handshake, schema v21, new legacy-import API, unauthorized denial');
 assert.ok(verified.scripts.some(src=>src.endsWith('index-DOtmQrQz.js')), 'packaged frontend must match the validated build');
 result.runtime=verified;
 const group=page.locator('[data-navigation-group="methods"]');
 if(await group.count()) { if(await group.getAttribute('aria-expanded')!=='true')await group.click(); }
 const methodItem=page.getByRole('menuitem').filter({has:page.locator('strong').getByText('方法管理',{exact:true})});
 if(await methodItem.count())await methodItem.click();
 assert.deepEqual(errors,[]);result.checks.push('no page errors');
 await page.screenshot({path:process.env.QA_SMOKE_SCREENSHOT});
 result.status='passed';
} catch(error){result.error=error.stack;throw error;}
finally {await writeFile(process.env.QA_SMOKE_OUTPUT,JSON.stringify(result,null,2));await browser.close();}
