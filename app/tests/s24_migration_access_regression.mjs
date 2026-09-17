// Isolated database only. Seed with seed_bf02_browser.py; never use user data.
import assert from 'node:assert/strict';
import { pathToFileURL } from 'node:url';
import { mkdir, writeFile } from 'node:fs/promises';
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

  page.on('dialog',async dialog=>{assert.ok(/^确认把本次/.test(dialog.message()));await dialog.accept()});
  const source=process.env.QA_SOURCE_DIR;
  assert.ok(source);
  for(const [key,endpoint,file] of [['migration','legacy-migration','runtime-DIRECT.MTD'],['spectrum-migration','spectrum-migration','sample.cdt'],['result-migration','result-migration','result.dat']]){
    await navigate(key);
    if(key!=='result-migration')await page.locator('.reader-state.ready').waitFor();
    const input=key==='migration'?page.getByLabel('方法库 · DIRECT.MTD',{exact:true}):page.locator('.migration-source-surface input').first();
    if(key==='migration'){
      await page.getByLabel('设备配置 · DIRECT.CFG',{exact:true}).fill(`${source}/runtime-DIRECT.CFG`);
      await page.getByLabel('软件选项 · DIRECT.OPT',{exact:true}).fill(`${source}/runtime-DIRECT.OPT`);
    }
    await input.fill(`${source}/missing.${file.split('.').pop()}`);
    const submit=page.getByRole('button',{name:key==='result-migration'?'暂存解析':'只读暂存并校验',exact:true});
    const [failed]=await Promise.all([page.waitForResponse(r=>r.url().endsWith(`/${endpoint}/stage`)&&r.request().method()==='POST'),submit.click()]);
    assert.ok(!failed.ok());
    assert.ok((await input.inputValue()).includes('missing.'));
    await capture(`${key}-missing-source`);
    await input.fill(`${source}/${file}`);
    const [staged]=await Promise.all([page.waitForResponse(r=>r.url().endsWith(`/${endpoint}/stage`)&&r.request().method()==='POST'),submit.click()]);
    assert.ok(staged.ok(),await staged.text());
    if((await staged.json()).already_committed){await capture(`${key}-already-committed`);continue;}
    await page.getByRole('button',{name:'原子提交',exact:true}).waitFor();
    await capture(`${key}-staged`);
    const [committed]=await Promise.all([page.waitForResponse(r=>r.url().endsWith(`/${endpoint}/commit`)&&r.request().method()==='POST'),page.getByRole('button',{name:'原子提交',exact:true}).click()]);
    assert.ok(committed.ok(),await committed.text());
    await capture(`${key}-committed`);
  }
  console.log('PASS: all three migration pages reject missing source, retain fields, stage and commit copies');
  await navigate('settings');
  const directory=page.getByLabel('数据目录',{exact:true});const original=await directory.inputValue();
  await directory.fill('C:/长中文目录/设置失败后必须保留');
  await page.route('**/api/v1/settings',r=>r.request().method()==='PATCH'?r.fulfill({status:422,contentType:'application/json',body:JSON.stringify({code:'qa_settings_error',message:'隔离测试：设置保存失败'})}):r.continue());
  await page.getByRole('button',{name:'保存设置',exact:true}).click();await page.locator('.toast.error').waitFor();
  assert.equal(await directory.inputValue(),'C:/长中文目录/设置失败后必须保留');
  await page.unroute('**/api/v1/settings');await directory.fill(original);
  await capture('settings-failed-preserved');
  await navigate('maintenance');
  await page.getByLabel('备份目录',{exact:true}).fill(source+'/result.dat');
  const [failedBackup]=await Promise.all([page.waitForResponse(r=>r.url().endsWith('/backups')&&r.request().method()==='POST'),page.getByRole('button',{name:'创建备份',exact:true}).click()]);
  assert.ok(!failedBackup.ok());await capture('maintenance-invalid-directory');
  await navigate('help');await page.getByLabel('搜索帮助主题').fill('QA不存在主题');await page.getByText('没有匹配的帮助主题',{exact:true}).waitFor();await capture('help-empty');
  await page.getByRole('button',{name:'清空搜索',exact:true}).click();await page.locator('.help-topic-row').first().waitFor();
  await navigate('about');await page.getByRole('button',{name:'查看完整模块能力',exact:true}).click();await page.locator('.capability-row').first().waitFor();await capture('about-capabilities');
  const cmt=await call('/spectrum-migration/stage',{path:`${source}/sample.cmt`});
  if(!cmt.already_committed)await call('/spectrum-migration/commit',{run_id:cmt.id});
  await navigate('postprocessing','interval');
  await page.locator('.postprocessing-table tbody tr').filter({hasText:'CMT'}).first().locator('input').check();
  await page.getByLabel('起始帧',{exact:true}).fill('1');await page.getByLabel('结束帧',{exact:true}).fill('2');
  await page.getByRole('button',{name:'查看区间',exact:true}).click();await page.locator('.postprocessing-interval-result').waitFor();await capture('postprocessing-cmt-interval');
  await page.getByLabel('结束帧',{exact:true}).fill('999999');
  const [invalidInterval]=await Promise.all([page.waitForResponse(r=>r.url().includes('/interval?')),page.getByRole('button',{name:'查看区间',exact:true}).click()]);assert.ok(!invalidInterval.ok());await capture('postprocessing-invalid-interval');
  const roles=await call('/roles' ,undefined,'GET');
  const auditor=roles.find(x=>x.name==='read_only_auditor');
  const role=await call('/roles',{name:`ui_read_${Date.now()}`,description:'隔离 UI 权限回归',permission_keys:[...auditor.permission_keys,'users.read']});
  const username=`ui_read_${Date.now()}`;
  await call('/users',{username,password:'QaTest-2026!',role_ids:[role.id]});
  const authResponse=await page.request.post(new URL('/api/v1/auth/login',page.url()).href,{data:{username,password:'QaTest-2026!'}});
  const readAuth=await authResponse.json();
  await page.evaluate(token=>sessionStorage.setItem('geospectrum.token',token),readAuth.access_token);
  await page.reload();await page.locator('.workspace-page').waitFor();
  await navigate('users');
  assert.equal(await page.getByRole('button',{name:'创建用户',exact:true}).count(),0);
  assert.equal(await page.getByRole('button',{name:'创建角色',exact:true}).count(),0);
  await capture('users-read-only');
  const forbidden=await page.request.post(new URL('/api/v1/users',page.url()).href,{headers:{Authorization:`Bearer ${readAuth.access_token}`},data:{username:'forbidden',password:'QaTest-2026!',role_ids:[]}});
  assert.equal(forbidden.status(),403);
  await navigate('maintenance');assert.ok(await page.getByRole('button',{name:'创建备份',exact:true}).isDisabled());await capture('maintenance-read-only');
  await page.route('**/health',route=>route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({message:'隔离离线状态'})}));
  await page.reload();await page.locator('.error-page').waitFor();await capture('service-offline');await page.unroute('**/health');
  await page.evaluate(()=>sessionStorage.removeItem('geospectrum.token'));await page.reload();await page.locator('.auth-form').waitFor();await capture('login');
  await page.getByLabel('用户名',{exact:true}).fill('qa_admin');await page.getByLabel('密码',{exact:true}).fill('Incorrect-test!');await page.getByRole('button',{name:'登录',exact:true}).click();await page.getByText('用户名或密码错误',{exact:true}).waitFor();await capture('login-error');
  await page.route('**/api/v1/auth/status',route=>route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({bootstrapped:false})}));
  await page.reload();await page.getByRole('heading',{name:'初始化本地管理员',exact:true}).waitFor();
  await page.getByLabel('用户名',{exact:true}).fill('initialization_test');await page.getByLabel('密码',{exact:true}).fill('QaTest-2026!');await page.getByLabel('确认密码',{exact:true}).fill('Different-2026!');
  let bootstrapWrites=0;page.on('request',r=>{if(r.method()==='POST'&&r.url().endsWith('/auth/bootstrap'))bootstrapWrites++});
  await page.getByRole('button',{name:'创建管理员',exact:true}).click();await page.locator('.auth-error').waitFor();assert.equal(bootstrapWrites,0);await capture('bootstrap-mismatch-mocked-status');
  assert.deepEqual(errors,[]);
  await writeFile(`${out}/results.json`,JSON.stringify({observations,errors},null,2));
  console.log('PASS: settings failure preservation, maintenance failure, help empty and about disclosure');
} catch(error) {
  if(page)await page.screenshot({path:`${out}/failure.png`}).catch(()=>{});
  await writeFile(`${out}/partial-results.json`,JSON.stringify(observations,null,2));
  throw error;
} finally { await browser.close(); }
