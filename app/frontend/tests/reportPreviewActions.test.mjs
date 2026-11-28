import assert from 'node:assert/strict'
import test from 'node:test'
import { reportSourceLabel, reportStatusLabel, runReportOutput } from '../src/pages/reports/reportPreviewActions.ts'
import { selectablePermissions } from '../src/pages/auth/permissionChoices.ts'

test('report summaries and details explain the source and status in Chinese', () => {
  assert.equal(reportSourceLabel({ source_run_ids: [7, 8] }), '2 个分析批次')
  assert.equal(reportSourceLabel({ source_run_ids: [] }), '旧 DAT')
  assert.equal(reportSourceLabel({ source_run_ids: [], model: { legacy_sources: [{ id: 4 }], runs: [] } }), '旧 DAT')
  assert.equal(reportStatusLabel('draft'), '草稿')
  assert.equal(reportStatusLabel('confirmed'), '已确认')
})

test('draft output requires write and export, existing confirmations need export alone', async () => {
  const calls = []
  const action = {
    status: 'draft', canWrite: true, canExport: true, isCurrent: () => true,
    confirm: async () => { calls.push('confirm') }, output: async () => calls.push('output'),
  }
  await runReportOutput({ ...action, canWrite: false })
  await runReportOutput({ ...action, canExport: false })
  assert.deepEqual(calls, [])
  await runReportOutput(action)
  assert.deepEqual(calls.splice(0), ['confirm', 'output'])
  await runReportOutput({ ...action, status: 'confirmed', canWrite: false })
  assert.deepEqual(calls, ['output'])
})

test('closing or switching during confirmation drops the output and a late download is discarded', async () => {
  let current = true
  let releaseConfirm
  const result = runReportOutput({
    status: 'draft', canWrite: true, canExport: true, isCurrent: () => current,
    confirm: () => new Promise(resolve => { releaseConfirm = resolve }),
    output: async () => assert.fail('stale preview attempted to output'),
  })
  current = false
  releaseConfirm()
  assert.equal(await result, undefined)
  current = true
  const lateDownload = await runReportOutput({
    status: 'confirmed', canWrite: false, canExport: true, isCurrent: () => current,
    confirm: async () => assert.fail('ready to output'), output: async () => { current = false; return 'PDF' },
  })
  assert.equal(lateDownload, undefined)
})

test('new permission choices omit retired grants while an existing template can preserve the exact keys', () => {
  const active = ['hardware-acquisition.read', 'hardware-acquisition.execute', 'mercury-calibration.read']
  const retired = ['hardware-acquisition.write', 'mercury-calibration.execute', 'results.read', 'results.export']
  assert.deepEqual(selectablePermissions([...active, ...retired]), active)
  assert.deepEqual(selectablePermissions([...active, ...retired], retired), [...active, ...retired])
  assert.ok(!selectablePermissions([], retired).includes('reports.export'))
})
