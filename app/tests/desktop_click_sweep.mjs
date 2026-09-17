// Use only with the isolated seed_bf02_browser fixture, after BF02 regression.
import assert from 'node:assert/strict';
import { readFile, writeFile } from 'node:fs/promises';
import { pathToFileURL } from 'node:url';
const { chromium } = await import(pathToFileURL(process.env.PLAYWRIGHT_MODULE).href);
assert.ok(process.env.QA_CDP && process.env.QA_SWEEP_OUTPUT);
const browser = await chromium.connectOverCDP(process.env.QA_CDP);
const results = [], errors = [];
try {
  const page = browser.contexts()[0].pages().find(p => p.url().includes('tauri.localhost'));
  assert.ok(page);
  page.setDefaultTimeout(7000);
  page.on('pageerror', e => errors.push(e.message));
  page.on('response', r => { if (r.status() >= 500) errors.push(`${r.status()} ${new URL(r.url()).pathname}`); });
  const manifest = JSON.parse(await readFile(new URL('../manifest.generated.json', import.meta.url), 'utf8'));
  const entries = manifest.modules.flatMap(m => m.navigation_entries || []);
  const go = async entry => {
    const group = page.locator(`[data-navigation-group="${entry.group}"]`);
    if (entry.group === 'workspace') await group.click();
    else {
      if (await group.getAttribute('aria-expanded') !== 'true') await group.click();
      const item = page.getByRole('menuitem').filter({has:page.locator('strong').getByText(entry.label,{exact:true})});
      if (await item.getAttribute('aria-disabled') === 'true') return {blocked:await item.getAttribute('title')};
      await item.click();
    }
    await page.locator('.breadcrumbs strong').getByText(entry.label,{exact:true}).waitFor();
    await page.locator(entry.page === 'analysis' ? '.analysis-page' : '.page-content').first().waitFor();
    if (entry.page === 'analysis' && entry.view) {
      assert.equal(await page.locator('.analysis-page').getAttribute('data-navigation-view'), entry.view);
    }
    await page.locator('.breadcrumbs').click();
    return {};
  };
  const check = async (name, fn) => {
    try { await fn(); results.push({name,status:'passed'}); }
    catch(e) { results.push({name,status:'failed',error:e.message}); }
    console.log(JSON.stringify(results.at(-1)));
  };
  for (const entry of entries) {
    try {
      const state = await go(entry);
      results.push({name:entry.label,status:state.blocked?'blocked_context':'opened',...state});
    } catch(e) { results.push({name:entry.label,status:'failed',error:e.message}); }
    console.log(JSON.stringify(results.at(-1)));
  }
  await check('离线帮助逐主题、搜索和清空', async()=>{
    await go(entries.find(e=>e.page==='help'));
    await page.locator('.help-topic-row').first().waitFor();
    const count=await page.locator('.help-topic-row').count();
    assert.ok(count>0);
    for(let i=0;i<count;i++) {
      const row=page.locator('.help-topic-row').nth(i);
      const title=await row.locator('strong').innerText();
      await row.click();
      assert.equal(await page.locator('.help-article h2').innerText(),title);
    }
    await page.getByLabel('搜索帮助主题').fill('汞灯');
    await page.locator('.help-topic-row').filter({hasText:'汞灯'}).first().waitFor();
    await page.getByRole('button',{name:'清空搜索',exact:true}).click();
    assert.equal(await page.getByLabel('搜索帮助主题').inputValue(),'');
  });
  await check('备份创建、校验与隔离恢复',async()=>{
    await go(entries.find(e=>e.page==='maintenance'));
    await page.getByLabel('备份目录',{exact:true}).fill('click-sweep-backups');
    for(const [button,toast] of [['创建备份','在线备份已完成'],['校验','备份校验通过'],['恢复演练','恢复演练通过']]) {
      await page.getByRole('button',{name:button,exact:true}).first().click();
      await page.getByText(toast,{exact:true}).waitFor();
    }
  });
  await check('模拟调试连接、开始、缩放、停止与断开',async()=>{
    await go(entries.find(e=>e.page==='acquisition'));
    await page.getByRole('button',{name:'连接诊断',exact:true}).click();
    await page.getByRole('button',{name:'开始',exact:true}).click();
    await page.getByRole('button',{name:'停止',exact:true}).waitFor();
    for(const title of ['横向放大','横向缩小','十字线','还原视图']) await page.getByTitle(title,{exact:true}).click();
    for(const name of ['400%','100%','适配']) await page.getByRole('button',{name,exact:true}).click();
    await page.getByRole('button',{name:'停止',exact:true}).click();
    await page.getByRole('button',{name:'断开',exact:true}).click();
  });
  results.push({name:'JavaScript异常及HTTP 5xx',status:errors.length?'failed':'passed',errors});
} finally {
  await writeFile(process.env.QA_SWEEP_OUTPUT,JSON.stringify(results,null,2));
  await browser.close();
}
if(results.some(r=>r.status==='failed')) process.exitCode=1;
