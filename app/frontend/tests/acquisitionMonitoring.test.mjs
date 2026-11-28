import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import ts from 'typescript'

const { test } = process.env.VITEST ? await import('vitest') : await import('node:test')
const source = readFileSync(new URL('../src/pages/acquisition/AcquisitionMonitoring.tsx', import.meta.url), 'utf8')
const { outputText } = ts.transpileModule(source, {
  compilerOptions: { jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
})
const exports = {}
new Function('require', 'exports', outputText)(createRequire(import.meta.url), exports)
const { AcquisitionMonitoring, interventionRequest } = exports

const waiting = {
  status: 'manual', attempt: 1, retry_count: 1, awaiting_intervention: true, can_accept: false,
  accept_blocked_reason: '当前尝试含损坏帧或缺少完整采集区间',
  last_anomalies: ['frame_fault'], last_summary: '监测异常：CCD 帧损坏。等待人工接管',
}

function render(state) {
  return renderToStaticMarkup(createElement(AcquisitionMonitoring, {
    monitoring: { state, monitored: true, retry_limit: 1, decisions: [] },
    enabled: true,
    intervene: async () => {},
  }))
}

test('状态、重采次数和禁用接受的原因可见', () => {
  const html = render(waiting)
  assert.match(html, /等待人工接管/)
  assert.match(html, /已重采 1 次/)
  assert.match(html, /CCD 帧损坏/)
  assert.match(html, /role="alert">当前尝试含损坏帧或缺少完整采集区间/)
  assert.match(html, /<button(?=[^>]*disabled)(?=[^>]*value="accept")[^>]*>接受当前帧/)
  assert.match(html, /继续重采/)
  assert.match(html, /安全停机/)
  assert.match(render({ ...waiting, status: 'unmonitored', awaiting_intervention: false }), /未监测/)
})

test('人工动作要求权限、接管状态、说明及可接受的完整帧', () => {
  assert.equal(interventionRequest(waiting, true, '复核', 'accept'), null)
  assert.equal(interventionRequest(waiting, false, '复核', 'retry'), null)
  assert.equal(interventionRequest(waiting, true, ' ', 'retry'), null)
  assert.equal(interventionRequest({ ...waiting, awaiting_intervention: false }, true, '复核', 'stop'), null)
  assert.deepEqual(interventionRequest(waiting, true, ' 停止检查 ', 'stop'), { action: 'stop', reason: '停止检查' })
  assert.deepEqual(interventionRequest(waiting, true, ' 重新装样 ', 'retry'), { action: 'retry', reason: '重新装样' })
  assert.deepEqual(interventionRequest({ ...waiting, can_accept: true }, true, ' 已复核 ', 'accept'),
    { action: 'accept', reason: '已复核' })
})
