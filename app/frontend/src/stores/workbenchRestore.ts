import type { AnalysisPageSnapshot, MethodsPageSnapshot, PostProcessingPageSnapshot } from './workbenchStoreCore'

export function availableId<Id>(ids: readonly Id[], preferred: Id | null | undefined, fallback?: Id | null) {
  if (preferred != null && ids.includes(preferred)) return preferred
  if (fallback != null && ids.includes(fallback)) return fallback
  return ids[0]
}

export function methodEditorSection(view: string | null): MethodsPageSnapshot['editorSection'] {
  if (view === 'lines') return 'lines'
  if (view === 'print-preview' || view === 'print-settings') return 'print'
  return 'conditions'
}

export function restoreMethodsSelection(
  methods: readonly { id: number; status: string; version: { lines: readonly { id: string }[] } | null }[],
  currentId: number | null,
  snapshot: Readonly<MethodsPageSnapshot> | null,
  explicitSection?: MethodsPageSnapshot['editorSection']
): MethodsPageSnapshot {
  const selectedMethodId = availableId(methods.filter(method => method.status !== 'deleted').map(method => method.id),
    snapshot?.selectedMethodId, currentId) ?? null
  const lines = methods.find(method => method.id === selectedMethodId)?.version?.lines ?? []
  return {
    selectedMethodId,
    editorSection: explicitSection ?? snapshot?.editorSection ?? 'conditions',
    selectedLineId: availableId(lines.map(line => line.id),
      selectedMethodId === snapshot?.selectedMethodId ? snapshot.selectedLineId : null) ?? null
  }
}

export function restoreAnalysisSelection(
  snapshot: Readonly<AnalysisPageSnapshot> | null,
  runIds: readonly number[],
  selected: { id: number; curves: { lines: readonly { line_id: string }[] } } | null,
  explicitView?: AnalysisPageSnapshot['viewByRun'][number]
): AnalysisPageSnapshot {
  const viewByRun = Object.fromEntries(runIds.flatMap(id => snapshot?.viewByRun[id] ? [[id, snapshot.viewByRun[id]]] : []))
  const lineByRun = Object.fromEntries(runIds.flatMap(id => snapshot?.lineByRun[id] ? [[id, snapshot.lineByRun[id]]] : []))
  if (selected) {
    if (explicitView) viewByRun[selected.id] = explicitView
    const lineId = availableId(selected.curves.lines.map(line => line.line_id), lineByRun[selected.id])
    if (lineId === undefined) delete lineByRun[selected.id]
    else lineByRun[selected.id] = lineId
  }
  return {
    selectedRunId: selected?.id ?? null,
    manager: explicitView ? 'review' : snapshot?.manager ?? null,
    railCollapsed: snapshot?.railCollapsed ?? false,
    viewByRun,
    lineByRun
  }
}

export function restorePostProcessingSelection(
  snapshot: Readonly<PostProcessingPageSnapshot>,
  options: {
    methods: readonly { method_version_id: number }[]
    sources: readonly { id: string }[]
    curve_snapshots: readonly {
      id: number; method_version_id: number; calculation_profile: PostProcessingPageSnapshot['profile']
    }[]
  }
): PostProcessingPageSnapshot {
  const methodVersionId = availableId(options.methods.map(method => method.method_version_id), snapshot.methodVersionId)
  const sourceIds = new Set(options.sources.map(source => source.id))
  const curveIds = options.curve_snapshots.filter(curve =>
    curve.method_version_id === methodVersionId && curve.calculation_profile === snapshot.profile
  ).map(curve => curve.id)
  const selectedCurves = snapshot.selectedCurves.filter(id => curveIds.includes(id))
  return {
    ...snapshot,
    methodVersionId,
    selectedSources: snapshot.selectedSources.filter(id => sourceIds.has(id)),
    selectedCurves,
    viewedCurveId: availableId(curveIds, snapshot.viewedCurveId, curveIds.find(id => selectedCurves.includes(id)))
  }
}
