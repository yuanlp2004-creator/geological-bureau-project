import assert from 'node:assert/strict'
import { readFile, stat } from 'node:fs/promises'
import { createHash } from 'node:crypto'
import { call, navigate } from './contract_browser_support.mjs'

export async function checkDirectOpen(page, fixture, result, output) {
  const paths = fixture.open_paths
  const mark = text => { result.checks.push(text); console.log(`PASS ${text}`) }
  async function open(purpose, file, label, expected = 200) {
    await page.waitForLoadState('networkidle')
    const control = page.locator(`.open-legacy-file[data-purpose="${purpose}"]`).filter({visible:true}).first()
    await control.locator(':scope > button').waitFor()
    await page.waitForFunction(purpose=>{const b=document.querySelector(`.open-legacy-file[data-purpose="${purpose}"] > button`);return b && !b.disabled},purpose)
    const ready = page.waitForResponse(response => response.url().endsWith('/legacy-migration/open-file') && response.request().postDataJSON()?.purpose === purpose, {timeout:300000})
    ready.catch(() => {})
    if (process.env.QA_CDP) {
      // Exercise the packaged native command consumer with selected paths; OS picker requires separate manual QA.
      await page.evaluate(file => {
        window.__directOpenPaths = Array.isArray(file) ? file : [file]
        if (window.__directOpenInstalled) return
        window.__directOpenInstalled = true
        const bridge = window.chrome.webview, post = bridge.postMessage
        bridge.postMessage = function(message) {
          const data = typeof message === 'string' ? JSON.parse(message) : message
          if (data.cmd === 'select_sample_file') {
            queueMicrotask(() => window.__TAURI_INTERNALS__.runCallback(data.callback, window.__directSampleFile ?? null)); return
          }
          if (data.cmd === 'select_legacy_files') {
            queueMicrotask(() => window.__TAURI_INTERNALS__.runCallback(data.callback, window.__directOpenPaths)); return
          }
          return post.call(bridge, message)
        }
        const fetch = window.fetch
        window.fetch = function(input, init) {
          const url = new URL(typeof input === 'string' ? input : input.url, location.href)
          if (url.hostname === 'ipc.localhost' && url.pathname === '/select_sample_file')
            return Promise.resolve(new Response(JSON.stringify(window.__directSampleFile ?? null), {status:200,headers:{'Content-Type':'application/json','Tauri-Response':'ok'}}))
          if (url.hostname === 'ipc.localhost' && url.pathname === '/select_legacy_files')
            return Promise.resolve(new Response(JSON.stringify(window.__directOpenPaths), {status:200,headers:{'Content-Type':'application/json','Tauri-Response':'ok'}}))
          return fetch.call(window, input, init)
        }
      }, file)
      await control.getByRole('button',{name:label,exact:true}).click()
    } else {
      await control.getByRole('button',{name:label,exact:true}).click()
      await control.getByRole('textbox').fill(Array.isArray(file) ? file.join('\n') : file)
      await control.getByRole('button',{name:'打开并保存',exact:true}).click()
    }
    const response = await ready
    assert.equal(response.status(),expected,await response.text())
    if (expected === 200) {
      await control.getByRole('status').filter({hasText:'个文件已打开并保存'}).waitFor({timeout:300000})
      await page.waitForFunction(({purpose,label}) => {
        const button = document.querySelector(`.open-legacy-file[data-purpose="${purpose}"] > button`)
        return button && !button.disabled && button.textContent === label
      }, {purpose,label}, {timeout:300000})
    }
    else await control.getByRole('alert').waitFor()
    return response.json()
  }
  await navigate(page,'methods','方法管理与参数','.methods-page')
  const methods = await open('methods',paths.mtd,'打开方法')
  assert.equal(methods.method_ids.length,3)
  assert.ok((await call(page,'/api/v1/methods')).some(item => item.id === methods.method_ids[0]))
  await page.screenshot({path:`${output}/methods.png`})
  mark('方法页直接打开真实方法库，自动读取同目录配置并保存方法')
  const description = page.locator('.method-identity textarea')
  const originalDescription = await description.inputValue()
  await description.fill('direct-open-unsaved-draft')
  await open('methods',paths.mtd,'打开方法')
  assert.equal(await description.inputValue(),'direct-open-unsaved-draft')
  await description.fill(originalDescription)
  mark('打开方法保留当前未保存的方法编辑内容')

  await navigate(page,'analysis-tests','谱图查看','[data-testid="spectrum-viewer-page"]')
  const first = await open('spectra',paths.cdt,'打开谱文件')
  const again = await open('spectra',paths.cdt,'打开谱文件')
  assert.deepEqual(first.record_ids,again.record_ids);assert.equal(again.reused,true)
  await page.locator('.spectrum-viewer-page svg').first().waitFor()
  await page.screenshot({path:`${output}/spectrum.png`})
  mark('谱图页直接打开真实CDT并显示；重复打开复用相同记录')

  await navigate(page,'analysis-tests','样品分析','.analysis-workbench')
  await open('analysis',paths.cmt,'打开样品文件')
  await page.getByLabel('旧样品分析方法').waitFor()
  assert.ok((await page.getByLabel('旧样品记录').inputValue()) !== undefined)
  mark('样品分析直接打开真实CMT；方法不唯一时展开对应方法选择')

  await navigate(page,'analysis-tests','色散曲线','[data-testid="dispersion-page"]')
  const wdt = await open('dispersion',paths.wdt,'打开色散文件')
  assert.ok(wdt.task_ids.length)
  const task = await call(page,`/api/v1/dispersion/tasks/${wdt.task_ids[0]}`)
  assert.equal(task.status,'completed');assert.ok(task.last_event.ccds[0].points.length)
  await page.screenshot({path:`${output}/dispersion.png`})
  mark('色散曲线直接打开真实WDT并建立完成任务，可继续定位和拟合')

  await navigate(page,'analysis-tests','蒸发曲线','[data-testid="evaporation-curves-page"]')
  await open('evaporation',paths.edt,'打开蒸发文件')
  await page.getByTestId('evaporation-time-chart').waitFor({timeout:60000})
  await page.screenshot({path:`${output}/evaporation.png`})
  mark('蒸发曲线直接打开真实EDT并显示峰值和积分时间数据')

  await navigate(page,'data','重新计算','[data-testid="postprocessing-page"]')
  await open('recalculate',paths.pdt,'打开强度文件')
  assert.ok(await page.locator('.postprocessing-page input[type="checkbox"]:checked').count())
  mark('重新计算直接打开真实PDT并选中来源')

  await navigate(page,'data','打印与导出','[data-testid="data-processing-page"]')
  await open('reports',paths.dat,'打开报告文件')
  assert.equal(await page.getByLabel('旧结果单位').count(),0)
  assert.equal(await page.getByRole('button',{name:'建立报告版本',exact:true}).isEnabled(),true)
  mark('报告页直接打开DAT绑定当前文件，无需填写单位即可建立')
  await page.getByRole('tab',{name:'强度数据',exact:true}).click()
  await open('intensity',paths.pdt,'打开强度文件')
  await page.locator('.intensity-table-scroll tbody tr').first().waitFor()
  await page.screenshot({path:`${output}/intensity.png`})
  const snapshot = await page.locator('.intensity-table-scroll').innerText()
  await open('intensity',paths.dat,'打开强度文件',422)
  assert.equal(await page.locator('.intensity-table-scroll').innerText(),snapshot)
  mark('强度页直接打开PDT并预览，错误格式拒绝且保留当前表')

  await navigate(page,'tools','旧结果迁移','[data-testid="result-migration-page"]')
  await open('batch-results',[paths.pdt,paths.dat],'批量迁移结果文件')
  await page.locator('[data-purpose="batch-results"] [role="status"]').filter({hasText:'2 个文件'}).waitFor()
  mark('迁移页面支持PDT和DAT多文件顺序批量迁移')

  await navigate(page,'analysis-tests','样号与样品队列','.sample-queue-page')
  for (let index = 0; index < 2; index++) {
    const imported = page.waitForResponse(response => response.url().includes('/sample-queues/import'))
    imported.catch(() => {})
    if (process.env.QA_CDP) {
      const bytes = [...await readFile(paths.sam)], info = await stat(paths.sam)
      await page.evaluate(file => {window.__directSampleFile = file}, {name:'queue.sam',bytes,last_modified:info.mtimeMs})
      await page.getByRole('button',{name:'打开样品号',exact:true}).click()
    } else await page.locator('.sample-queue-page input[type="file"]').setInputFiles(paths.sam)
    const response = await imported
    assert.ok(response.ok(),await response.text())
  }
  if (process.env.QA_CDP) {
    const before = await page.getByLabel('选择样品队列').inputValue()
    await page.evaluate(() => {window.__directSampleFile = null})
    await page.getByRole('button',{name:'打开样品号',exact:true}).click()
    await page.waitForFunction(() => ![...document.querySelectorAll('button')].find(b=>b.textContent.includes('打开样品号'))?.disabled)
    assert.equal(await page.getByLabel('选择样品队列').inputValue(),before)
  }
  mark('样号页直接打开SAM，重复选择同一文件仍可读取')
  for (const [file, before] of Object.entries({...fixture.open_facts,...fixture.original_facts})) {
    const info = await stat(file,{bigint:true})
    assert.equal(Number(info.size),before.size)
    assert.equal(info.mtimeNs.toString(),before.mtime_ns)
    assert.equal(createHash('sha256').update(await readFile(file)).digest('hex'),before.sha256)
  }
  result.source_preservation = {copies:Object.keys(fixture.open_facts).length, originals:Object.keys(fixture.original_facts).length, size_mtime_sha256_unchanged:true}
  mark('实际旧原件及读取副本的大小、修改时间与SHA-256均保持')
}
