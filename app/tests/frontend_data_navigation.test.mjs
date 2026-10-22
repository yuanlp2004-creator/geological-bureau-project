import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { navigationEntries } from '../frontend/src/navigation.ts'

const capabilities = JSON.parse(readFileSync(new URL('../manifest.generated.json', import.meta.url), 'utf8')).modules
const dataEntries = permissions => navigationEntries(capabilities, permissions).filter(item => item.group === 'data')

test('data processing exposes two tasks and keeps partial read roles reachable', () => {
  assert.deepEqual(dataEntries(['postprocessing.read']).map(item => item.label), ['重新计算'])
  assert.deepEqual(dataEntries(['reports.read']).map(item => item.label), ['打印与导出'])
  assert.deepEqual(dataEntries(['analysis.read']).map(item => item.label), ['打印与导出'])
  assert.deepEqual(dataEntries([]), [])
})
