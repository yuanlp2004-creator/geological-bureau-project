// Run only against a fresh, isolated backend with QA_ISOLATED=1.
import assert from 'node:assert/strict';
import { pathToFileURL } from 'node:url';
import { mkdir, writeFile } from 'node:fs/promises';
assert.equal(process.env.QA_ISOLATED, '1');
const { chromium } = await import(pathToFileURL(process.env.PLAYWRIGHT_MODULE).href);
const browser = await chromium.launch({ channel: 'msedge', headless: true });
const output = process.env.QA_OUTPUT;
await mkdir(output, { recursive: true });
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 920 } });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('dialog', dialog => dialog.accept());
  await page.goto(process.env.QA_URL);
  const bootstrap = await page.request.post(`${process.env.QA_URL}/api/v1/auth/bootstrap`, { data: { username: 'discovery_qa', password: 'Discovery-QA-2026!' } });
  assert.ok(bootstrap.ok());
  await page.reload();
  await page.getByLabel('用户名', {exact: true}).fill('discovery_qa');
  await page.getByLabel('密码', {exact: true}).fill('Discovery-QA-2026!');
  await page.getByRole('button', {name: '登录', exact: true}).click();
  await page.locator('.workspace-page').waitFor();
  const results = [];
  for (const [label, endpoint, inputLabel, testid] of [
    ['旧方法与配置迁移', 'legacy-migration', '方法库 · DIRECT.MTD', 'legacy-migration-page'],
    ['旧谱数据迁移', 'spectrum-migration', '谱文件路径', 'spectrum-migration-page'],
    ['旧结果迁移', 'result-migration', '文件路径', 'result-migration-page'],
  ]) {
    await page.locator('[data-navigation-group="tools"]').click();
    await page.getByRole('menuitem').filter({has: page.locator('strong').filter({hasText: new RegExp(`^${label}$`)})}).click();
    await page.mouse.move(900, 75); await page.keyboard.press('Escape');
    const panel = page.getByTestId(testid);
    await panel.locator('.legacy-source-list button').first().waitFor();
    let choice;
    if (endpoint === 'legacy-migration') {
      choice = panel.locator('.legacy-source-list button').filter({hasText: 'Spec2.02'}).first();
    } else {
      const buttons = panel.locator('.legacy-source-list button');
      const index = await buttons.evaluateAll((items, spectrum) => items.findIndex(item => (spectrum ? /\.cdt/i : /\.dat/i).test(item.textContent)), endpoint === 'spectrum-migration');
      assert.ok(index >= 0);
      choice = buttons.nth(index);
    }
    await choice.click();
    const selected = await panel.getByLabel(inputLabel, {exact: true}).inputValue();
    assert.ok(selected.length > 5);
    if (endpoint === 'legacy-migration') {
      assert.ok((await panel.getByLabel('设备配置 · DIRECT.CFG').inputValue()).includes('Spec2.02'));
      assert.ok((await panel.getByLabel('软件选项 · DIRECT.OPT').inputValue()).includes('Spec2.02'));
    }
    await page.screenshot({path: `${output}/${endpoint}.png`});
    const [staged] = await Promise.all([
      page.waitForResponse(r => r.url().endsWith(`/${endpoint}/stage`) && r.request().method() === 'POST'),
      panel.getByRole('button', {name: endpoint === 'result-migration' ? '暂存解析' : '只读暂存并校验', exact: true}).click(),
    ]);
    assert.ok(staged.ok(), await staged.text());
    const [committed] = await Promise.all([
      page.waitForResponse(r => r.url().endsWith(`/${endpoint}/commit`) && r.request().method() === 'POST'),
      panel.getByRole('button', {name: '原子提交', exact: true}).click(),
    ]);
    assert.ok(committed.ok(), await committed.text());
    assert.equal((await committed.json()).status, 'committed');
    await panel.getByText('指定其他目录', {exact: true}).click();
    await panel.getByRole('textbox', {name: '旧版目录', exact: true}).fill('C:/missing-discovery-qa-directory');
    await panel.getByRole('button', {name: '检测目录', exact: true}).click();
    await panel.getByRole('alert').waitFor();
    assert.equal(await panel.getByLabel(inputLabel, {exact: true}).inputValue(), selected);
    await panel.getByRole('button', {name: '自动检测', exact: true}).click();
    await panel.locator('.legacy-source-list button').first().waitFor();
    for (const width of [1060, 1920]) {
      await page.setViewportSize({width, height: 920});
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
    }
    results.push({endpoint, selected, stage: 'passed', commit: 'passed', invalidDirectory: 'passed'});
  }
  assert.deepEqual(errors, []);
  await writeFile(`${output}/results.json`, JSON.stringify(results, null, 2));
  console.log(JSON.stringify(results));
} finally { await browser.close(); }
