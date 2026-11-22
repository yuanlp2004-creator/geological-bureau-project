import assert from 'node:assert/strict'

// Recalculation now stands alone; its completed batch must still be exportable.
export async function checkPostprocessing(page, checks) {
  await page.evaluate(async () => {
    const React=(await import('/node_modules/.vite/deps/react.js')).default
    const {createRoot}=(await import('/node_modules/.vite/deps/react-dom_client.js')).default
    const {PostProcessingPage}=await import('/src/pages/postprocessing/PostProcessingPage.tsx')
    const {api}=await import('/src/api/index.ts')
    const host=document.createElement('div');host.id='postprocessing-test'
    host.style.cssText='position:fixed;inset:0;z-index:99999;overflow:auto;background:white'
    document.body.append(host)
    const root=createRoot(host), originals={...api}
    window.__postprocessing={api,originals,host,root,forbiddenCalls:0}
    const batch={id:'fixed-batch',status:'completed',input_sha256:'batchhash',result:{sources:[]}}
    Object.assign(api,{
      postprocessingEdtRecords:async()=>{window.__postprocessing.forbiddenCalls++;return {records:[]}},
      postprocessingConversions:async()=>{window.__postprocessing.forbiddenCalls++;return {runs:[]}},
      postprocessingRecalculations:async()=>({runs:[]}),
      postprocessingRecalculationOptions:async()=>({
        methods:[{method_version_id:7,method_id:1,name:'test',version:1}],
        sources:[{id:'sample:77',kind:'sample',label:'SOURCE-77',source_sha256:'hash77'}],
        curve_snapshots:[{id:8,line_id:'L1',method_version_id:7,calculation_profile:'legacy_2_0_2',fit_mode:'linear',coordinate_type:'normal'}]
      }),
      recalculatePostprocessing:async(_token,payload)=>{
        window.__postprocessing.recalculation=payload
        api.postprocessingRecalculations=async()=>({runs:[batch]});return batch
      },
      exportPostprocessing:async(_token,payload)=>{window.__postprocessing.exportPayload=payload;return {status:'completed'}}
    })
    window.__postprocessing.renderView=view=>root.render(React.createElement(PostProcessingPage,{
      token:'test',view,canWrite:true,canExecute:true,canExport:true,onToast:()=>{}
    }))
    window.__postprocessing.renderView('recalculate')
  })
  const host=page.locator('#postprocessing-test')
  await host.locator('.postprocessing-choice-list.sources input').waitFor()
  assert.equal(await host.getByText('旧记录区间查看与 EDT 转换',{exact:true}).count(),0)
  assert.equal(await host.getByRole('button',{name:'打开蒸发摄谱文件',exact:true}).count(),0)
  await host.locator('.postprocessing-choice-list.sources input').check()
  await host.locator('.postprocessing-choice-list.curves input').check()
  await host.getByRole('button',{name:'执行精确重算',exact:true}).click()
  await page.waitForFunction(()=>!!window.__postprocessing.recalculation)
  assert.deepEqual(await page.evaluate(()=>window.__postprocessing.recalculation.source_record_ids),['sample:77'])
  await page.evaluate(()=>window.__postprocessing.renderView('intensity'))
  await host.getByLabel('矩阵输出来源').selectOption('recalc:fixed-batch')
  await host.getByLabel('输出目录',{exact:true}).fill('C:/Exports')
  await host.getByRole('button',{name:'导出数据',exact:true}).click()
  await page.waitForFunction(()=>!!window.__postprocessing.exportPayload)
  assert.deepEqual(await page.evaluate(()=>window.__postprocessing.exportPayload.record_ids),['recalc:fixed-batch'])
  assert.equal(await page.evaluate(()=>window.__postprocessing.forbiddenCalls),0)
  await page.evaluate(()=>{
    const state=window.__postprocessing;state.root.unmount();Object.assign(state.api,state.originals);state.host.remove();delete window.__postprocessing
  })
  checks.push('recalculation has no EDT UI or data loading; selected exact-version batch remains exportable')
}
