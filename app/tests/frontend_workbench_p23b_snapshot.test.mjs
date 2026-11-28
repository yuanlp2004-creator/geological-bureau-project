import assert from 'node:assert/strict'
import test from 'node:test'
import { createWorkbenchStore, createWorkbenchVisit, permissionScopeKey } from '../frontend/src/stores/workbenchStoreCore.ts'
import {
  availableId, methodEditorSection, restoreMethodsSelection, restoreAnalysisSelection, restorePostProcessingSelection
} from '../frontend/src/stores/workbenchRestore.ts'
import {
  createNavigationGuard, methodFormIsDirty, lineFormIsDirty, recalculationIsDirty
} from '../frontend/src/layout/navigationGuard.ts'

const identity = { userId: 12, permissionsKey: permissionScopeKey(['read', 'write']), methodVersionId: 11 }
const method = { selectedMethodId: 2, editorSection: 'print', selectedLineId: 'Fe' }
const analysis = {
  selectedRunId: 5, manager: 'setup', railCollapsed: true,
  viewByRun: { 5: 'standards', 7: 'samples' }, lineByRun: { 5: 'Fe', 7: 'Mn' }
}
const processing = {
  methodVersionId: 13, profile: 'modern_v1', selectedSources: ['result:1', 'result:2'], sourceQuery: '样品一',
  selectedCurves: [17, 29], viewedCurveId: 17, allowOlderMethod: true, format: 'excel', filename: 'sample-data', setupOpen: true
}

function deferred() {
  let resolve
  const promise = new Promise(complete => { resolve = complete })
  return { promise, resolve }
}

test('all three intents consume once by account, permission set, view and method version', () => {
  const store = createWorkbenchStore()
  for (const [view, snapshot] of Object.entries({ methods: method, analysis, postprocessing: processing })) {
    const scope = { ...identity, view }
    const scopes = [
      scope, { ...scope, userId: 13 }, { ...scope, permissionsKey: permissionScopeKey(['read']) }, { ...scope, methodVersionId: null }
    ]
    for (const key of scopes) store.saveSnapshot(key, snapshot)
    for (const key of scopes) {
      assert.deepEqual(store.peekSnapshot(key), snapshot)
      assert.deepEqual(store.consumeSnapshot(key), snapshot)
      assert.equal(store.consumeSnapshot(key), null)
    }
    store.saveSnapshot(scope, snapshot)
  }
  assert.deepEqual(store.peekSnapshot({ ...identity, view: 'methods' }), method)
  assert.deepEqual(store.peekSnapshot({ ...identity, view: 'analysis' }), analysis)
  assert.deepEqual(store.peekSnapshot({ ...identity, view: 'postprocessing' }), processing)
  store.clearSession(identity.userId)
  assert.equal(store.peekSnapshot({ ...identity, view: 'analysis' }), null)

  const editable = structuredClone(processing)
  const scope = { ...identity, view: 'postprocessing' }
  store.saveSnapshot(scope, editable)
  editable.selectedSources.push('result:3')
  editable.selectedCurves.length = 0
  assert.deepEqual(store.peekSnapshot(scope), processing)
  assert.throws(() => store.peekSnapshot(scope).selectedCurves.push(31), TypeError)
})

test('A → B → A accepts the current load and leaves the new intent alone when old replies arrive', async () => {
  const store = createWorkbenchStore()
  const a = { ...identity, view: 'methods' }
  const b = { ...a, methodVersionId: 12 }
  let selection
  function start(scope) {
    const visit = createWorkbenchVisit(store, scope)
    visit.activate()
    const request = visit.beginLoad()
    const response = deferred()
    const load = response.promise.then(() => {
      if (request.valid()) selection = request.consume()?.selectedMethodId
    })
    return { visit, load, respond: response.resolve, request }
  }
  store.saveSnapshot(a, method)
  const first = start(a)
  first.visit.invalidate()
  const second = start(b)
  second.visit.invalidate()
  store.saveSnapshot(a, { ...method, selectedMethodId: 20 })
  const third = start(a)
  second.respond()
  first.respond()
  await Promise.all([first.load, second.load])
  assert.equal(selection, undefined)
  assert.equal(store.peekSnapshot(a).selectedMethodId, 20)

  third.respond()
  await third.load
  assert.equal(selection, 20)
  assert.equal(store.peekSnapshot(a), null)
  third.visit.save({ ...method, selectedMethodId: 21 })
  assert.equal(third.request.consume(), null)
  const previousRefresh = third.visit.beginLoad()
  const latestRefresh = third.visit.beginLoad()
  assert.equal(previousRefresh.valid(), false)
  assert.equal(latestRefresh.valid(), true)
  assert.equal(latestRefresh.consume(), null)
  assert.equal(store.peekSnapshot(a).selectedMethodId, 21)

  store.clearAll()
  store.saveSnapshot(a, method)
  assert.equal(latestRefresh.valid(), false)
  third.visit.save({ ...method, selectedMethodId: 22 })
  assert.deepEqual(store.peekSnapshot(a), method)
})

const methods = [
  { id: 1, status: 'active', version: { lines: [{ id: 'base' }, { id: 'Mn' }] } },
  { id: 2, status: 'active', version: { lines: [{ id: 'base' }, { id: 'Fe' }] } },
  { id: 3, status: 'deleted', version: { lines: [{ id: 'Fe' }] } }
]
const runs = [4, 5]
const run = { id: 5, curves: { lines: [{ line_id: 'base' }, { line_id: 'Fe' }] } }

test('missing methods, spectral lines and analysis runs fall back to available rows', () => {
  assert.deepEqual(restoreMethodsSelection(methods, 1, { ...method, selectedMethodId: 3 }), {
    selectedMethodId: 1, editorSection: 'print', selectedLineId: 'base'
  })
  assert.equal(restoreMethodsSelection(methods, 1, { ...method, selectedLineId: 'deleted' }).selectedLineId, 'base')
  assert.equal(restoreMethodsSelection([], 1, method).selectedMethodId, null)
  assert.equal(availableId([4, 6], analysis.selectedRunId), 4)
  const restored = restoreAnalysisSelection(analysis, [4, 6], { id: 4, curves: { lines: [{ line_id: 'base' }] } })
  assert.deepEqual(restored, {
    selectedRunId: 4, manager: 'setup', railCollapsed: true, viewByRun: {}, lineByRun: { 4: 'base' }
  })
  assert.deepEqual(restoreAnalysisSelection(analysis, runs, { ...run, curves: { lines: [] } }).lineByRun, {})
  assert.equal(restoreAnalysisSelection(analysis, [], null).selectedRunId, null)
})

test('explicit methods and analysis entrances take precedence over the stored view', () => {
  assert.deepEqual(restoreMethodsSelection(methods, 1, method), method)
  for (const [entry, section] of [['lines', 'lines'], ['print-preview', 'print'], ['conditions', 'conditions']]) {
    assert.deepEqual(restoreMethodsSelection(methods, 1, method, methodEditorSection(entry)), { ...method, editorSection: section })
  }
  const ordinary = restoreAnalysisSelection(analysis, runs, run)
  assert.equal(ordinary.viewByRun[5], 'standards')
  assert.equal(ordinary.manager, 'setup')
  assert.equal(ordinary.lineByRun[5], 'Fe')
  for (const view of ['quality', 'curve', 'standards', 'samples']) {
    const explicit = restoreAnalysisSelection(analysis, runs, run, view)
    assert.equal(explicit.viewByRun[5], view)
    assert.equal(explicit.manager, 'review')
    assert.equal(explicit.railCollapsed, true)
  }
})

test('recalculation restores only live sources and compatible curves, with a valid viewed curve', () => {
  const curve = { method_version_id: 13, calculation_profile: 'modern_v1' }
  const options = {
    methods: [{ method_version_id: 13 }, { method_version_id: 14 }],
    sources: [{ id: 'result:2' }],
    curve_snapshots: [{ ...curve, id: 19 }, { ...curve, id: 29 }, { ...curve, id: 17, calculation_profile: 'legacy_2_0_2' }]
  }
  assert.deepEqual(restorePostProcessingSelection(processing, options), {
    ...processing, selectedSources: ['result:2'], selectedCurves: [29], viewedCurveId: 29
  })
  const fallback = restorePostProcessingSelection({ ...processing, methodVersionId: 999, selectedCurves: [17] }, options)
  assert.equal(fallback.methodVersionId, 13)
  assert.deepEqual(fallback.selectedCurves, [])
  assert.equal(fallback.viewedCurveId, 19)
  assert.equal(restorePostProcessingSelection(processing, { ...options, methods: [] }).viewedCurveId, undefined)
})

test('dirty detection reflects local form edits, untouched drafts and submitted recalculations', () => {
  const saved = { state: 'draft', name: '方法', description: '说明', work_type: 'routine', conditions: { frame_count: 20 } }
  assert.equal(methodFormIsDirty(structuredClone(saved), saved, null, ''), false)
  for (const patch of [{ name: '新名称' }, { description: '' }, { work_type: 'other' }, { conditions: { frame_count: 21 } }]) {
    assert.equal(methodFormIsDirty({ ...saved, ...patch }, saved, null, ''), true)
  }
  assert.equal(methodFormIsDirty(null, null, 'create', '   '), false)
  assert.equal(methodFormIsDirty(null, null, 'copy', '新副本'), true)

  const line = { wavelength_nm: 250, standard_points: [{ concentration: 1 }] }
  assert.equal(lineFormIsDirty(structuredClone(line), line), false)
  assert.equal(lineFormIsDirty({ ...line, wavelength_nm: 251 }, line), true)
  assert.equal(lineFormIsDirty(line, null), false)
  assert.equal(recalculationIsDirty({ 17: { workspace: {} } }, false), true)
  assert.equal(recalculationIsDirty({ 17: { fittedRequest: {} } }, false), true)
  assert.equal(recalculationIsDirty({ 17: { fittedRequest: {} } }, true), false)
  assert.equal(recalculationIsDirty({}, false), false)
})

test('the navigation guard keeps the draft and target on cancellation and dismisses duplicate clicks', async () => {
  let answer = deferred()
  const prompts = []
  const navigate = createNavigationGuard(reason => { prompts.push(reason); return answer.promise })
  let draft = '未保存'
  let target = 'methods'
  const guard = () => ({ reason: '放弃修改？', discard: () => { draft = '' } })

  const first = navigate(guard, () => { target = 'analysis' })
  assert.equal(await navigate(guard, () => { target = 'postprocessing' }), false)
  assert.equal(target, 'methods')
  assert.deepEqual(prompts, ['放弃修改？'])
  answer.resolve(false)
  assert.equal(await first, false)
  assert.equal(draft, '未保存')
  assert.equal(target, 'methods')

  answer = deferred()
  const second = navigate(guard, () => { target = 'analysis' })
  answer.resolve(true)
  assert.equal(await second, true)
  assert.equal(draft, '')
  assert.equal(target, 'analysis')
})
