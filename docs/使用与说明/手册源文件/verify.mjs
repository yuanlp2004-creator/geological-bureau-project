import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {pathToFileURL,fileURLToPath} from 'node:url';

// 用法：node verify.mjs <playwright 模块入口路径>
if(!process.argv[2])throw new Error('请指定 playwright 模块入口路径');
const {chromium}=await import(pathToFileURL(path.resolve(process.argv[2])).href);
const source=path.dirname(fileURLToPath(import.meta.url));
const url=pathToFileURL(path.join(source,'../GeoSpectrum_使用手册.html')).href;
const output=fs.mkdtempSync(path.join(os.tmpdir(),'geospectrum-manual-qa-'));
const browser=await chromium.launch({channel:'msedge',headless:true});
const errors=[],externalRequests=[];
try{
 const page=await browser.newPage({viewport:{width:1440,height:1000}});
 page.on('pageerror',e=>errors.push(e.message));
 page.on('request',request=>{if(/^https?:/.test(request.url()))externalRequests.push(request.url())});
 await page.goto(url);
 await page.locator('#topic-title').waitFor();
 assert.equal(await page.locator('#topic-title').innerText(),'手册首页');
 assert.equal(await page.locator('.tree-group').count(),10);
 const routes=await page.locator('.tree-link').evaluateAll(links=>links.map(a=>({id:a.dataset.topic,title:a.textContent})));
 assert.equal(routes.length,54);
 // 逐页验证路由、目录定位、正文、所有相关主题与页内锚点。
 const ids=new Set(routes.map(r=>r.id));
 for(const r of routes){
  await page.evaluate(id=>{location.hash=id},r.id);
  await page.waitForFunction(title=>document.getElementById('topic-title').textContent===title,r.title);
  assert.ok((await page.locator('.article-body').innerText()).length>75,r.id);
  assert.equal((await page.locator('.article-body').innerText()).includes('**'),false,r.id);
  assert.equal(await page.locator('.tree-link[aria-current="page"]').getAttribute('data-topic'),r.id);
  const badLinks=await page.locator('a[href^="#"]').evaluateAll((links,valid)=>links.flatMap(a=>{
   const [id,anchor]=a.getAttribute('href').slice(1).split('~');
   if(!valid.includes(id))return[a.getAttribute('href')];
   if(anchor&&!document.getElementById(anchor))return[a.getAttribute('href')];return[];
  }),[...ids]);
  assert.deepEqual(badLinks,[],r.id);
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,r.id);
 }
 // 正文跳转、页内跳转与阅读历史。
 await page.goto(url);
 await page.locator('.article-body a[href="#first-run"]').first().click();
 await page.waitForFunction(()=>document.getElementById('topic-title').textContent==='首次使用路线');
 await page.locator('#outline a').last().click();
 assert.ok((await page.url()).includes('~section-'));
 assert.ok(await page.locator('#main').evaluate(el=>el.scrollTop>0));
 await page.locator('#back').click();
 await page.waitForFunction(()=>location.hash==='#first-run');
 await page.locator('#back').click();
 await page.waitForFunction(()=>document.getElementById('topic-title').textContent==='手册首页');
 await page.locator('#forward').click();
 await page.waitForFunction(()=>document.getElementById('topic-title').textContent==='首次使用路线');
 await page.locator('#page-nav a').last().click();
 await page.waitForFunction(()=>document.getElementById('topic-title').textContent==='日常分析流程');
 // 全文搜索、空结果和用户输入转义。
 await page.locator('#search').fill('标准样 名称');
 assert.ok(await page.locator('.search-result').count()>0);
 await page.screenshot({path:path.join(output,'search-1440.png')});
 await page.locator('.search-result').first().click();
 assert.equal(await page.locator('#not-found').isVisible(),false);
 await page.locator('#search').fill('<img src=x onerror=alert(1)>');
 assert.equal(await page.locator('.search-result').count(),0);
 assert.equal(await page.locator('#result-list img').count(),0);
 await page.locator('#clear-search').click();
 assert.equal(await page.locator('#toc').isVisible(),true);
 await page.locator('#expand-all').click();
 assert.equal(await page.locator('#toc details:not([open])').count(),0);
 await page.locator('#expand-all').click();
 assert.equal(await page.locator('#toc details[open]').count(),0);
 await page.locator('#home').click();
 await page.locator('#font-larger').click();
 assert.equal(await page.locator('.article-body').evaluate(e=>getComputedStyle(e).fontSize),'17px');
 await page.locator('#font-smaller').click();
 await page.screenshot({path:path.join(output,'home-1440.png')});
 await page.setViewportSize({width:1920,height:1080});
 await page.screenshot({path:path.join(output,'home-1920.png')});
 // 刷新深链接和无效主题兜底。
 await page.goto(url+'#backup');await page.reload();
 assert.equal(await page.locator('#topic-title').innerText(),'在线备份与恢复演练');
 await page.screenshot({path:path.join(output,'backup-1920.png')});
 await page.goto(url+'#missing-topic');
 assert.equal(await page.locator('#not-found').isVisible(),true);
 await page.locator('#home').click();
 await page.emulateMedia({media:'print'});
 assert.equal(await page.locator('#sidebar').isVisible(),false);
 assert.equal(await page.locator('#article').isVisible(),true);
 await page.emulateMedia({media:'screen'});
 // 小屏目录开合与键盘搜索。
 await page.setViewportSize({width:390,height:844});
 await page.locator('#menu-toggle').click();
 assert.equal(await page.locator('#sidebar').isVisible(),true);
 await page.locator('#search').fill('备份');
 await page.locator('.search-result').first().click();
 assert.equal(await page.locator('#sidebar').isVisible(),false);
 assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
 await page.screenshot({path:path.join(output,'mobile-390.png')});
 await page.locator('#main').focus();await page.keyboard.press('/');
 assert.equal(await page.locator('#search').evaluate(el=>document.activeElement===el),true);
 await page.keyboard.press('Escape');
 assert.equal(await page.locator('#sidebar').isVisible(),false);
 assert.deepEqual(errors,[]);assert.deepEqual(externalRequests,[]);
 console.log(JSON.stringify({status:'passed',topics:routes.length,checks:['54 routes and body links','tree nesting and selected topic','body and section jumps','back and forward','next page','full text search and empty result','input escaping','deep link reload','invalid route fallback','font size','print media','mobile navigation','keyboard search','zero external requests','zero page errors'],screenshots:output},null,2));
}finally{await browser.close()}
