import assert from 'node:assert/strict'

// 验证真实页面的筛选选择、区间查看、转换参数和跨视图共享选择。
export async function checkPostprocessing(page, checks) {
  await page.evaluate(async () => {
    const React = (await import('/node_modules/.vite/deps/react.js')).default
    const { createRoot } = (await import('/node_modules/.vite/deps/react-dom_client.js')).default
    const { PostProcessingPage } = await import('/src/pages/postprocessing/PostProcessingPage.tsx')
    const { api } = await import('/src/api/index.ts')
    const originals = { ...api },
      calls = [],
      toasts = []
    const records = [
      { id: 'raw:1', format: 'edt', sample_name: 'Alpha' },
      { id: 'raw:2', format: 'cmt', sample_name: 'Beta' }
    ].map((record) => ({
      kind: 'raw',
      frame_count: 4,
      ccd_count: 1,
      ccd_indices: [0],
      points_per_ccd: 4,
      source_sha256: 'abc123',
      record_index: 0,
      band_name: '',
      measure_time: '2026-09-21T00:00:00Z',
      ignition: {},
      ...record
    }))
    const host = document.createElement('div')
    host.id = 'postprocessing-test'
    host.style.cssText = 'position:fixed;inset:0;z-index:99999;overflow:auto;background:white'
    document.body.append(host)
    const root = createRoot(host)
    window.__postprocessing = { api, originals, root, host, calls, toasts, fail: false }
    Object.assign(api, {
      postprocessingEdtRecords: async () => ({ records: [...records] }),
      postprocessingConversions: async () => ({ runs: [] }),
      postprocessingRecalculations: async () => ({ runs: [] }),
      postprocessingRecalculationOptions: async () => ({
        methods: [{ method_version_id: 7, method_id: 1, name: 'test', version: 1 }],
        sources: [],
        curve_snapshots: []
      }),
      postprocessingInterval: async (_token, id, params) => {
        calls.push({ action: 'interval', id, params })
        if (window.__postprocessing.fail) throw new Error('test interval failure')
        return {
          id,
          source_sha256: 'abc123',
          measure_time: null,
          ccd: params.ccd,
          start_frame: params.startFrame,
          end_frame: params.endFrame,
          points_per_ccd: 4,
          mean: { values: [1, 2, 3, 4] }
        }
      },
      convertPostprocessingEdt: async (_token, payload) => {
        calls.push({ action: 'convert', payload })
        return {}
      }
    })
    window.__postprocessing.renderView = (view) => root.render(
      React.createElement(PostProcessingPage, {
        token: 'test', view, canReadAnalysis: false,
        canWrite: true, canExecute: true, canExport: true,
        onToast: (message) => toasts.push(message)
      })
    )
    window.__postprocessing.renderView('recalculate')
  })
  const host = page.locator('#postprocessing-test')
  const source = host.locator('.postprocessing-source-surface')
  const search = source.getByRole('textbox', { name: '搜索源记录' })
  await host.locator('.postprocessing-legacy-tools > summary').click()
  await source.getByLabel('选择记录 raw:1').waitFor()
  await source.locator('summary').click()
  await search.fill('Alpha')
  await source.getByRole('button', { name: '全选', exact: true }).click()
  await search.fill('Beta')
  await source.getByRole('button', { name: '反选', exact: true }).click()
  await search.fill('')
  assert.equal(await source.locator('input[type=checkbox]:checked').count(), 2)
  await source.getByLabel('选择记录 raw:1').uncheck()
  assert.equal(await source.getByRole('button', { name: /转换所选 EDT/ }).isDisabled(), true)
  await source.getByLabel('起始帧', { exact: true }).fill('2')
  await source.getByRole('textbox', { name: /^结束帧/ }).fill('3')
  await source.getByRole('button', { name: '查看区间' }).click()
  await source.locator('.postprocessing-interval-result').waitFor()
  assert.match(await source.locator('.postprocessing-interval-result').innerText(), /2–3 帧/)
  await search.fill('Beta')
  await page.evaluate(() => window.__postprocessing.renderView('intensity'))
  assert.equal(await host.getByRole('button', { name: /全时/ }).count(), 0)
  await page.evaluate(() => window.__postprocessing.renderView('recalculate'))
  assert.equal(await search.inputValue(), 'Beta')
  assert.equal(await source.getByRole('textbox', { name: /^结束帧/ }).inputValue(), '3')
  await source.getByRole('textbox', { name: /^结束帧/ }).fill('')
  await source.getByRole('button', { name: '查看区间' }).click()
  assert.equal(await source.getByRole('textbox', { name: /^结束帧/ }).inputValue(), '')
  assert.equal(await page.evaluate(() => window.__postprocessing.calls.length), 1)
  await source.getByRole('textbox', { name: /^结束帧/ }).fill('0')
  await source.getByRole('button', { name: '查看区间' }).click()
  assert.equal(await page.evaluate(() => window.__postprocessing.calls.length), 1)
  await source.getByRole('textbox', { name: /^结束帧/ }).fill('3')
  await page.evaluate(() => {
    window.__postprocessing.fail = true
  })
  await source.getByRole('button', { name: '查看区间' }).click()
  await page.waitForFunction(() => window.__postprocessing.toasts.includes('test interval failure'))
  await search.fill('')
  await source.getByLabel('选择记录 raw:1').check()
  await source.getByRole('button', { name: /转换所选 EDT/ }).click()
  await page.waitForFunction(() => window.__postprocessing.calls.some((call) => call.action === 'convert'))
  const calls = await page.evaluate(() => window.__postprocessing.calls)
  assert.deepEqual(calls[0], { action: 'interval', id: 'raw:2', params: { ccd: 0, startFrame: 2, endFrame: 3 } })
  assert.deepEqual(calls.find((call) => call.action === 'convert').payload, {
    record_ids: ['raw:1'],
    start_frame: 2,
    end_frame: 3,
    target_ccd_layout_id: 1,
    storage_mode: 'full_interval',
    method_version_id: 7
  })
  await page.evaluate(() => {
    const r = window.__postprocessing
    const batch = {
      id: 'fixed-batch',
      status: 'completed',
      input_sha256: 'batchhash',
      result: { sources: [{ lines: [{ calculated_value: 9.47 }] }] }
    }
    r.api.postprocessingRecalculationOptions = async () => ({
      methods: [{ method_version_id: 7, method_id: 1, name: 'test', version: 1 }],
      sources: [{ id: 'sample:77', kind: 'sample', label: 'SOURCE-77', source_sha256: 'hash77' }],
      curve_snapshots: [
        {
          id: 8,
          line_id: 'L1',
          method_version_id: 7,
          calculation_profile: 'legacy_2_0_2',
          fit_mode: 'linear',
          coordinate_type: 'normal'
        }
      ]
    })
    r.api.recalculatePostprocessing = async () => {
      r.api.postprocessingRecalculations = async () => ({ runs: [batch] })
      return batch
    }
    r.api.exportPostprocessing = async (_token, payload) => {
      r.exportPayload = payload
      return { status: 'completed' }
    }
  })
  await host.getByRole('button', { name: '刷新数据', exact: true }).click()
  await page.evaluate(() => window.__postprocessing.renderView('recalculate'))
  await host.locator('.postprocessing-choice-list.sources input').check()
  await host.locator('.postprocessing-choice-list.curves input').check()
  await host.getByRole('button', { name: '执行精确重算', exact: true }).click()
  await page.waitForFunction(
    () =>
      document.querySelector('#postprocessing-test select') && window.__postprocessing.api.postprocessingRecalculations
  )
  await page.evaluate(() => window.__postprocessing.renderView('intensity'))
  await host.getByLabel('矩阵输出来源').selectOption('recalc:fixed-batch')
  await host.getByLabel('输出目录', { exact: true }).fill('C:/Exports')
  await host.getByRole('button', { name: '导出数据', exact: true }).click()
  await page.waitForFunction(() => !!window.__postprocessing.exportPayload)
  assert.deepEqual(await page.evaluate(() => window.__postprocessing.exportPayload.record_ids), ['recalc:fixed-batch'])
  checks.push('FIX-02: completed recalculation selects its batch and exports recalc:id from actual page controls')
  await page.evaluate(() => {
    const r = window.__postprocessing
    r.root.unmount()
    Object.assign(r.api, r.originals)
    r.host.remove()
    delete window.__postprocessing
  })
  checks.push(
    'postprocessing: filtered selection, CMT interval, tab state, invalid input, failure feedback and EDT-only conversion payload'
  )
}
