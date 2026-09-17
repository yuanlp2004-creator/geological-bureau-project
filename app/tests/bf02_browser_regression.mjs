// Run only against an isolated backend seeded with test_s16_analysis._seed and a test admin.
import assert from 'node:assert/strict';
import { pathToFileURL } from 'node:url';
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE ? pathToFileURL(process.env.PLAYWRIGHT_MODULE).href : 'playwright');
const browser = process.env.QA_CDP
  ? await chromium.connectOverCDP(process.env.QA_CDP)
  : await chromium.launch({ channel: 'msedge', headless: true });
try {
  const page = process.env.QA_CDP
    ? browser.contexts()[0].pages().find(p => p.url().includes('tauri.localhost'))
    : await browser.newPage({ viewport: { width: 1600, height: 1000 } });
  assert.ok(page, 'The test desktop WebView was not found');
  const errors = [];
  page.on('pageerror', e => { errors.push(e.message); console.error(e.stack); });
  if (!process.env.QA_CDP) await page.goto(process.env.QA_URL || 'http://127.0.0.1:5173');
  await page.getByLabel('用户名', {exact:true}).fill(process.env.QA_USER || 'qa_admin');
  await page.getByLabel('密码', {exact:true}).fill(process.env.QA_PASSWORD || 'QaTest-2026!');
  await page.getByRole('button', {name:'登录',exact:true}).click();
  await page.locator('.quick-action').filter({hasText:'方法管理'}).click();
  await page.locator('.breadcrumbs strong').filter({hasText:'方法库与当前方法'}).waitFor();
  console.log('PASS F04: no-current-method shortcut reaches lifecycle');
  const token = await page.evaluate(()=>sessionStorage.getItem('geospectrum.token'));
  const runtime = process.env.QA_CDP ? await page.evaluate(()=>window.__TAURI__.core.invoke('runtime_config')) : null;
  const headers = {Authorization:`Bearer ${token}`, ...(runtime ? {'X-GeoSpectrum-Process-Key':runtime.process_key} : {})};
  const call = async (path, data, method='POST') => {
    const response = await page.request.fetch(new URL(`/api/v1${path}`, runtime?.api_base || page.url()).href, {method,headers,data});
    assert.equal(response.ok(),true,await response.text());
    return response.json();
  };
  await call('/methods/1/open');
  await page.reload();
  await page.getByRole('button', {name:'分析测试',exact:true}).click();
  await page.getByRole('menuitem').filter({hasText:'定量分析与慢进'}).click();
  const submit=page.getByRole('button',{name:'建立并锁定输入',exact:true});
  await submit.click();
  await page.locator('.analysis-create [role="alert"]').filter({hasText:'请至少选择'}).waitFor();
  const timeout=page.getByLabel('慢进超时（秒）');
  await timeout.fill(''); await submit.click();
  await page.locator('.analysis-create [role="alert"]').filter({hasText:'无效数值'}).waitFor();
  await timeout.fill('300');
  await page.locator('.analysis-sample-groups input').first().check();
  await page.route('**/api/v1/analyses/runs', route => route.request().method()==='POST'
    ? route.fulfill({status:422,contentType:'application/json',body:JSON.stringify({detail:{code:'analysis_lines_missing',message:'方法版本没有已启用的分析线'}})})
    : route.continue());
  await submit.click();
  await page.locator('.analysis-create [role="alert"]').filter({hasText:'方法版本没有已启用的分析线'}).waitFor();
  await page.unroute('**/api/v1/analyses/runs');
  await page.locator('.analysis-switch input').uncheck();
  await submit.click();
  await page.locator('.analysis-detail').waitFor();
  const [started] = await Promise.all([page.waitForResponse(r=>r.url().endsWith('/start')&&r.request().method()==='POST'),page.getByRole('button',{name:'开始',exact:true}).click()]);
  let run = await started.json();
  for(let i=0;i<30 && run.status==='running';i++) {
    const [stepped] = await Promise.all([page.waitForResponse(r=>r.url().endsWith('/step')&&r.request().method()==='POST'),page.getByRole('button',{name:'推进一条谱线',exact:true}).click()]);
    run = await stepped.json();
  }
  assert.equal(run.status,'completed');
  await page.locator('.analysis-status.completed').waitFor();
  console.log('PASS F03: blank selection, invalid timeout, backend error feedback, real analysis completion');
  const created = await call('/methods',{name:`BF02-${Date.now()}`});
  await call(`/methods/${created.id}/publish`);
  await call(`/methods/${created.id}/open`);
  await page.reload();
  await page.locator('.quick-action').filter({hasText:'方法管理'}).click();
  await page.locator('.breadcrumbs strong').filter({hasText:'方法库与当前方法'}).waitFor();
  await page.getByLabel('选择编辑方法').selectOption(String(created.id));
  await page.locator('.method-editor-tabs button').filter({hasText:'分析谱线'}).click();
  await page.locator('.spectral-heading button').click();
  const wave=page.getByLabel('理论波长 (nm)',{exact:true});
  let writes=0;
  page.on('request',r=>{if(r.method()==='POST'&&r.url().endsWith(`/methods/${created.id}/lines`)) writes++;});
  await wave.fill('9999');
  await page.locator('.spectral-savebar button').click();
  assert.equal(await wave.inputValue(),'9999');
  assert.equal(writes,0);
  await wave.fill('254');
  await page.locator('.spectral-savebar button').click();
  await page.getByText('谱线已添加到新草稿版本',{exact:true}).waitFor();
  assert.equal(writes,1);
  console.log('PASS F02/F04: rejected stale numeric submission, valid save, current-method shortcut');
  await call('/settings',{directories:{backups:'bf02-configured-backups'}},'PATCH');
  await page.getByRole('button',{name:'系统管理',exact:true}).click();
  await page.getByRole('menuitem').filter({hasText:'备份与维护'}).click();
  await page.getByLabel('备份目录',{exact:true}).waitFor();
  await page.waitForFunction(()=>document.querySelector('.maintenance-primary input')?.value==='bf02-configured-backups');
  console.log('PASS F05: maintenance reads configured backup directory');
  assert.deepEqual(errors,[]);
} finally { await browser.close(); }
