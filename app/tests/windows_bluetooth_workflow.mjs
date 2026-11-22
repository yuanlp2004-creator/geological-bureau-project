import assert from 'node:assert/strict'
import { call, navigate } from './contract_browser_support.mjs'

/** System mapping is injected; profile persistence and simulator use the real API. */
export async function checkWindowsBluetoothConnection(page, result) {
  const check = value => result.checks.push(value)
  const original = await call(page, '/api/v1/devices/profiles')
  const simulator = original.find(item => item.transport === 'simulator')
  result.systemBluetooth = await call(page, '/api/v1/devices/bluetooth')
  const address = '112233445566', keyboard = 'AABBCCDDEEFF'
  let devices = [
    {address,name:'测试串口设备',connected:false,paired:true,ports:[
      {device:'COM7',port:7,description:'测试蓝牙串口',is_bluetooth:true,bluetooth_address:address,direction:'outgoing'},
      {device:'COM9',port:9,description:'另一串口服务',is_bluetooth:true,bluetooth_address:address,direction:'outgoing'}]},
    {address:keyboard,name:'测试键盘',connected:true,paired:true,ports:[]}
  ]
  await page.route('**/api/v1/devices/bluetooth', route => route.fulfill({json:{devices}}))
  await page.route('**/api/v1/devices/ports', route => route.fulfill({json:devices.flatMap(device=>device.ports)}))
  // Windows-API validation is separately tested at the backend boundary. Remove
  // only the injected hardware identity before forwarding to real persistence.
  let bindingPayload
  await page.route('**/api/v1/devices/port', async route => {
    bindingPayload = route.request().postDataJSON()
    const {bluetooth_address:_address,...payload}=bindingPayload
    const response=await route.fetch({postData:JSON.stringify(payload)})
    await route.fulfill({response})
  })
  await navigate(page,'tools','设备连接','[data-testid="device-connection"]')
  const panel=page.getByTestId('device-connection'),button=name=>panel.getByRole('button',{name,exact:true})
  const left=panel.getByLabel('Windows蓝牙设备',{exact:true}),right=panel.getByLabel('绑定COM口',{exact:true})
  assert.equal(await panel.getByLabel('连接设备档案').count(),0)
  assert.equal(await panel.getByRole('button',{name:/新建.*档案/}).count(),0)
  await left.selectOption(keyboard)
  assert.equal(await right.isDisabled(),true)
  await panel.getByText(/不提供串口服务/).waitFor()
  assert.equal(await button('保存绑定').isDisabled(),true)
  assert.equal(await button('连接设备').isDisabled(),true)
  check('左侧显示Windows设备及真实状态，无串口服务的设备不可绑定或连接')
  await left.selectOption(address)
  assert.deepEqual(await right.locator('option').evaluateAll(nodes=>nodes.map(node=>node.value)),['','COM7','COM9'])
  await right.selectOption('COM9')
  assert.equal(await button('连接设备').isDisabled(),true)
  await button('保存绑定').click()
  await page.waitForFunction(()=>!document.querySelector('[data-testid="device-connection"] button.primary-button')?.disabled)
  assert.equal(bindingPayload.bluetooth_address,address)
  const saved=await call(page,'/api/v1/devices/current')
  assert.equal(saved.port,9);assert.equal(saved.transport,'serial')
  assert.deepEqual((await call(page,'/api/v1/devices/profiles')).slice(0,original.length),original)
  check('右侧仅列所选设备的COM口，保存包含设备身份并保留旧档案和参数')
  let connects=0
  await page.route('**/api/v1/devices/connect',route=>{
    connects++;return route.fulfill({status:409,json:{detail:{code:'serial_open_failed',message:'测试：端口被占用，连接失败'}}})
  })
  await button('连接设备').click()
  await panel.getByRole('alert').filter({hasText:'端口被占用'}).waitFor()
  assert.equal((await call(page,'/api/v1/devices/diagnostics')).adapter.connected,false)
  assert.equal((await call(page,'/api/v1/devices/current')).id,saved.id)
  check('连接失败显示错误并保留已选设备及端口，不报告假成功')
  devices[0].ports=[]
  await button('刷新设备与端口').click()
  await left.selectOption(address)
  assert.equal(await right.isDisabled(),true)
  assert.equal(await button('连接设备').isDisabled(),true)
  assert.equal(connects,1)
  check('Windows端口映射消失后禁用连接，要求系统添加端口后刷新')
  devices[0].ports=[{device:'COM7',port:7,description:'测试蓝牙串口',is_bluetooth:true,bluetooth_address:address,direction:'outgoing'}]
  await page.getByRole('tab',{name:'设备参数',exact:true}).click()
  const parameters=page.locator('#device-panel-device')
  const simulate=parameters.getByLabel('模拟设备（用于测试）',{exact:true})
  const com=parameters.getByLabel('通讯口',{exact:true})
  assert.equal(await parameters.getByLabel('设备档案',{exact:true}).count(),0)
  const comBounds=await com.boundingBox(),simulationBounds=await simulate.boundingBox()
  assert.ok(Math.abs((comBounds.y+comBounds.height/2)-(simulationBounds.y+simulationBounds.height/2))<4,'模拟勾选项须在通讯口旁边')
  await com.selectOption('COM7')
  await page.waitForFunction(()=>!document.querySelector('#device-panel-device fieldset')?.disabled)
  const activeProfile=await call(page,'/api/v1/devices/current')
  const {id:_id,created_at:_created,updated_at:_updated,screen_conversion:_screen,...copy}=activeProfile
  const duplicate=await call(page,'/api/v1/devices/profiles',{...copy,name:'同端口独立参数测试 '+Date.now(),baud_rate:921600,ccd_indices:[0,2,5]})
  await call(page,'/api/v1/devices/current',{profile_id:duplicate.id},'PUT')
  await page.reload();await page.locator('[data-navigation-group="tools"]').waitFor()
  await navigate(page,'tools','设备调试','[data-testid="device-debug-page"]')
  await page.getByRole('tab',{name:'设备参数',exact:true}).click()
  await page.waitForFunction(()=>document.querySelector('#device-panel-device [aria-label="通讯口"]')?.value==='COM7')
  const realBefore=await call(page,'/api/v1/devices/current')
  assert.equal(realBefore.id,duplicate.id)
  await simulate.click()
  await page.waitForFunction(()=>document.querySelector('#device-panel-device .legacy-communication-row input[type="checkbox"]')?.checked===true && !document.querySelector('#device-panel-device fieldset')?.disabled)
  assert.equal(await simulate.isChecked(),true)
  assert.equal((await call(page,'/api/v1/devices/current')).transport,'simulator')
  await page.getByRole('button',{name:'连接测试',exact:true}).click()
  await parameters.getByText('模拟设备连接测试通过',{exact:true}).first().waitFor()
  await simulate.click()
  await page.waitForFunction(()=>document.querySelector('#device-panel-device .legacy-communication-row input[type="checkbox"]')?.checked===false && !document.querySelector('#device-panel-device [aria-label="通讯口"]')?.disabled)
  assert.equal(await simulate.isChecked(),false)
  assert.deepEqual(await call(page,'/api/v1/devices/current'),realBefore)
  assert.equal(await com.inputValue(),'COM7')
  check('通讯口旁独立模拟勾选可测试，取消后恢复原COM和真实参数')
  await page.reload();await page.locator('[data-navigation-group="tools"]').waitFor()
  await navigate(page,'tools','设备连接','[data-testid="device-connection"]')
  await page.waitForFunction(expected=>document.querySelector('[aria-label="Windows蓝牙设备"]')?.value===expected,address)
  assert.equal(await page.getByLabel('Windows蓝牙设备',{exact:true}).inputValue(),address)
  assert.equal(await page.getByLabel('绑定COM口',{exact:true}).inputValue(),'COM7')
  check('重新打开页面后从Windows映射恢复当前设备和COM选择')
  for(const pattern of ['**/api/v1/devices/bluetooth','**/api/v1/devices/ports','**/api/v1/devices/port','**/api/v1/devices/connect'])await page.unroute(pattern)
  // Return to an actually enumerated device for screenshots; never connect it.
  const actual=result.systemBluetooth.devices.find(item=>item.ports.length)
  if(actual)await call(page,'/api/v1/devices/port',{transport:'serial',port:actual.ports[0].port,bluetooth_address:actual.address},'PUT')
  else await call(page,'/api/v1/devices/current',{profile_id:simulator.id},'PUT')
  await page.reload();await page.locator('[data-navigation-group="tools"]').waitFor()
  await navigate(page,'tools','设备连接','[data-testid="device-connection"]')
  await page.waitForFunction(()=>document.querySelector('[data-testid="device-connection"] .connection-state')?.textContent==='未连接')
  assert.equal((await call(page,'/api/v1/devices/diagnostics')).adapter.connected,false)
  check('最终审阅恢复系统真实设备映射，未连接实体串口')
}
