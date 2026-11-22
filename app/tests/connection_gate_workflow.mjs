import assert from 'node:assert/strict'
import path from 'node:path'
import { call, navigate } from './contract_browser_support.mjs'

export async function checkCaptureConnectionGate(page, serial, result, output) {
  const methods = await call(page, '/api/v1/methods')
  const method = methods.find(item => item.status === 'active' && item.current_version)
  assert.ok(method)
  await call(page, '/api/v1/methods/current', {method_id:method.id})
  await page.reload(); await page.getByTestId('workspace').waitFor()
  let probes = 0
  const testPattern = `**/api/v1/devices/profiles/${serial.id}/connection-test**`
  await page.route(testPattern, async route => {
    probes++
    await route.fulfill({status:409,contentType:'application/json',body:JSON.stringify({detail:{
      code:'device_connection_test_failed',message:'验收注入：端口已打开但仪器无有效CCD响应',details:{connected:false}}})})
  })
  // An unexpected bypass must fail the test rather than touching hardware.
  let unexpectedConnections = 0
  await page.route('**/api/v1/devices/connect', async route => {
    if (route.request().postDataJSON().profile_id === serial.id) {
      unexpectedConnections++
      await route.fulfill({status:409,contentType:'application/json',body:JSON.stringify({detail:'Unexpected real connect'})})
    } else await route.continue()
  })
  const writes=[]
  const observe=request=>{if(request.method()==='POST'&&/\/(acquisitions|dispersion|hardware-acquisitions)\/tasks$/.test(new URL(request.url()).pathname))writes.push(request.url())}
  page.on('request',observe)
  for (const [label,selector,dialogName,submit] of [
    ['样品摄谱','[data-testid="sample-acquisition-page"]','建立样品摄谱任务','创建任务'],
    ['蒸发摄谱','[data-testid="evaporation-acquisition-page"]','建立蒸发摄谱任务','创建任务'],
    ['色散摄谱','[data-testid="dispersion-page"][data-view="capture"]','建立色散摄谱任务','新建任务'],
    ['自动转角采集','[data-testid="hardware-acquisition-page"]','新建自动转角任务','建立任务']
  ]) {
    await navigate(page,'analysis-tests',label,selector)
    if (label !== '自动转角采集') {
      const mode = {'样品摄谱':'sample-acquisition','蒸发摄谱':'evaporation-acquisition','色散摄谱':'dispersion'}[label]
      if (await page.getByTestId('spectroscopy-workbench').getAttribute('data-mode') !== mode)
        await page.locator('.spectroscopy-modes').getByRole('button',{name:label,exact:true}).click()
      await page.waitForFunction(mode=>document.querySelector('[data-testid="spectroscopy-workbench"]')?.getAttribute('data-mode')===mode,mode)
    }
    const host=page.locator(selector)
    await page.getByRole('button',{name:'新建任务',exact:true}).click()
    const dialog=page.getByRole('dialog',{name:dialogName,exact:true})
    await dialog.getByLabel(/^设备档案/).selectOption(String(serial.id))
    const before=probes
    const response=page.waitForResponse(response=>response.url().includes(`/profiles/${serial.id}/connection-test`))
    await dialog.getByRole('button',{name:submit,exact:true}).click()
    assert.equal((await response).status(),409)
    await page.waitForFunction(()=>![...document.querySelectorAll('dialog[open] button')].some(button=>button.textContent.includes('建立中')))
    assert.equal(await dialog.isVisible(),true)
    assert.equal(await host.getAttribute('data-stage'),'tasks')
    assert.equal(await dialog.getByLabel(/^设备档案/).inputValue(),String(serial.id))
    assert.equal(probes,before+1)
    await page.screenshot({path:path.join(output,`blocked-${label}.png`)})
    await dialog.getByRole('button',{name:'取消',exact:true}).click()
    result.checks.push(`${label}选择真实仪器无CCD响应：不创建任务、不进入摄谱、保留所选档案`)
  }
  assert.deepEqual(writes,[])
  page.off('request',observe)
  assert.equal(unexpectedConnections,0)
  // A pre-existing real draft is subject to the same entry check.
  const draft=await call(page,'/api/v1/acquisitions/tasks',{
    task_kind:'evaporation',name:'QA真实草稿门禁',device_profile_id:serial.id,
    burn_frame_count:3,dark_frame_count:1,pre_excitation_seconds:1,sampling_period_seconds:1
  })
  await navigate(page,'analysis-tests','蒸发摄谱','[data-testid="evaporation-acquisition-page"]')
  await page.getByRole('button',{name:'刷新',exact:true}).click()
  const host=page.getByTestId('evaporation-acquisition-page')
  const response=page.waitForResponse(response=>response.url().includes(`/profiles/${serial.id}/connection-test`))
  await host.locator(`tr[data-task-id="${draft.id}"]`).getByRole('button').click()
  assert.equal((await response).status(),409)
  await page.getByText('验收注入：端口已打开但仪器无有效CCD响应',{exact:true}).first().waitFor()
  assert.equal(await host.getAttribute('data-stage'),'tasks')
  assert.equal((await call(page,`/api/v1/acquisitions/tasks/${draft.id}`)).status,'draft')
  result.checks.push('已有真实仪器草稿同样阻止进入；原任务及数据保持')
  await page.unroute(testPattern)
  await page.unroute('**/api/v1/devices/connect')
  assert.equal((await call(page,'/api/v1/devices/diagnostics')).adapter.connected,false)
}

export async function checkAlignmentRecovery(page, result) {
  await navigate(page,'tools','设备调试','.device-debug-page')
  await page.getByRole('tab',{name:'调试对中',exact:true}).click()
  const host=page.getByTestId('acquisition-page')
  await page.waitForFunction(()=>Boolean(document.querySelector('[data-testid="acquisition-page"] .alignment-connection-bar select')?.value))
  const profile=await host.locator('label').filter({hasText:'设备档案'}).locator('select').inputValue()
  assert.equal((await call(page,'/api/v1/devices/profiles')).find(item=>String(item.id)===profile).transport,'simulator')
  await host.getByRole('button',{name:'连接诊断',exact:true}).click()
  await page.route('**/api/v1/devices/debug/step',async route=>{
    await call(page,'/api/v1/devices/debug/stop',{})
    await call(page,'/api/v1/devices/disconnect',{})
    await route.fulfill({status:409,contentType:'application/json',body:JSON.stringify({detail:'验收注入：通信异常，后台端口已关闭'})})
  })
  await host.getByRole('button',{name:'开始',exact:true}).click()
  await page.getByText('验收注入：通信异常，后台端口已关闭',{exact:true}).waitFor()
  assert.equal(await host.getByRole('button',{name:'连接诊断',exact:true}).isEnabled(),true)
  assert.equal(await host.getByRole('button',{name:'开始',exact:true}).isDisabled(),true)
  assert.equal(await host.getByRole('button',{name:'停止',exact:true}).isDisabled(),true)
  assert.equal(await host.getByRole('button',{name:'断开',exact:true}).isDisabled(),true)
  assert.match(await host.locator('.alignment-status').textContent(),/状态：idle/)
  await page.unroute('**/api/v1/devices/debug/step')
  assert.equal((await call(page,'/api/v1/devices/diagnostics')).adapter.connected,false)
  result.checks.push('通信异常后重新读取实际状态：端口已关闭时恢复连接按钮，不残留debugging或无效开始／断开按钮')
}
