type UserId = number | string

export type WorkbenchScope = {
  userId: UserId
  permissionsHash: string
  page: string
  methodVersionId?: number | null
}

export type SpectrumViewerSnapshot = {
  fileGroup: string
  sourceKind: string
  search: string
  angleFilter: string
  selectedId: string | null
  overlayIds: readonly string[]
  priorityId: string | null
  multiMode: 'auto' | 'single' | 'multi'
  showRecords: boolean
  recordLocked: boolean
  ccd: number
  line: number
  mode: 'mean' | 'peak' | 'back' | 'value'
  exposureStart: number
  exposureEnd: number
  manualZoomX: number
  zoomY: number
  panX: number
  panY: number
  tool: 'crosshair' | 'pan' | 'box'
  pixelMode: 1 | 4 | 10 | null
  pointCoordinates: boolean
  fixedView: boolean
  followPoint: boolean
  viewLine: string
  locateValue: string
}

export type EvaporationCurvesSnapshot = SpectrumViewerSnapshot

export type MethodsPageSnapshot = {
  selectedMethodId: number | null
  editorSection: 'conditions' | 'lines' | 'print'
  selectedLineId: string | null
}

export type AnalysisPageSnapshot = {
  selectedRunId: number | null
  manager: 'setup' | 'review' | null
  railCollapsed: boolean
  viewByRun: Record<number, 'raw' | 'quality' | 'curve' | 'standards' | 'samples'>
  lineByRun: Record<number, string>
}

export type PostProcessingPageSnapshot = {
  methodVersionId?: number
  profile: 'legacy_2_0_2' | 'modern_v1'
  selectedSources: string[]
  sourceQuery: string
  selectedCurves: number[]
  viewedCurveId?: number
  allowOlderMethod: boolean
  format: 'txt' | 'csv' | 'excel'
  filename: string
  setupOpen: boolean
}

type Snapshots = {
  spectra: SpectrumViewerSnapshot
  evaporation: EvaporationCurvesSnapshot
  methods: MethodsPageSnapshot
  analysis: AnalysisPageSnapshot
  postprocessing: PostProcessingPageSnapshot
}

export type WorkbenchView = keyof Snapshots
export type WorkbenchIdentity = { userId: UserId; permissionsKey: string; methodVersionId: number | null }
type SnapshotScope<View extends WorkbenchView> = WorkbenchIdentity & { view: View }

const sessionPrefix = (userId: UserId) => `${JSON.stringify(userId)}:`

export function buildWorkbenchScopeKey({ userId, permissionsHash, page, methodVersionId }: WorkbenchScope): string {
  return sessionPrefix(userId) + JSON.stringify([permissionsHash, page, methodVersionId ?? null])
}

export function hashPermissions(permissions: readonly string[]): string {
  const canonical = JSON.stringify([...new Set(permissions)].sort())
  let hash = 0x811c9dc5
  for (let index = 0; index < canonical.length; index++) {
    hash = Math.imul(hash ^ canonical.charCodeAt(index), 0x01000193)
  }
  return (hash >>> 0).toString(16).padStart(8, '0')
}

export function createWorkbenchStore() {
  const snapshots = new Map<string, Readonly<Snapshots[WorkbenchView]>>()
  const sessionRevisions = new Map<UserId, number>()
  let revision = 0
  let allRevision = 0

  const keyFor = ({ userId, permissionsKey, view, methodVersionId }: SnapshotScope<WorkbenchView>) =>
    buildWorkbenchScopeKey({ userId, permissionsHash: permissionsKey, page: view, methodVersionId })
  const getSnapshot = (key: string, consume = false) => {
    const snapshot = snapshots.get(key) ?? null
    if (consume) snapshots.delete(key)
    return snapshot
  }

  return {
    saveSpectrumSnapshot(scopeKey: string, snapshot: SpectrumViewerSnapshot) {
      snapshots.set(scopeKey, Object.freeze({ ...snapshot, overlayIds: Object.freeze([...snapshot.overlayIds]) }))
    },
    peekSpectrumSnapshot(scopeKey: string) {
      return getSnapshot(scopeKey) as Readonly<SpectrumViewerSnapshot> | null
    },
    consumeSpectrumSnapshot(scopeKey: string) {
      return getSnapshot(scopeKey, true) as Readonly<SpectrumViewerSnapshot> | null
    },
    saveSnapshot<View extends WorkbenchView>(scope: SnapshotScope<View>, snapshot: Snapshots[NoInfer<View>]) {
      const copy = Object.fromEntries(Object.entries(snapshot).map(([key, value]) => [
        key, value && typeof value === 'object' ? Object.freeze(Array.isArray(value) ? [...value] : { ...value }) : value
      ])) as Snapshots[View]
      snapshots.set(keyFor(scope), Object.freeze(copy))
    },
    peekSnapshot<View extends WorkbenchView>(scope: SnapshotScope<View>) {
      return getSnapshot(keyFor(scope)) as Readonly<Snapshots[View]> | null
    },
    consumeSnapshot<View extends WorkbenchView>(scope: SnapshotScope<View>) {
      return getSnapshot(keyFor(scope), true) as Readonly<Snapshots[View]> | null
    },
    getSessionRevision(userId: UserId) {
      return sessionRevisions.get(userId) ?? allRevision
    },
    clearSession(userId: UserId) {
      const prefix = sessionPrefix(userId)
      for (const key of snapshots.keys()) {
        if (key.startsWith(prefix)) snapshots.delete(key)
      }
      sessionRevisions.set(userId, ++revision)
    },
    clearAll() {
      snapshots.clear()
      sessionRevisions.clear()
      allRevision = ++revision
    }
  }
}

/** A visit accepts only its latest load, and only while the session is current. */
export function createWorkbenchVisit<View extends WorkbenchView>(
  store: ReturnType<typeof createWorkbenchStore>, scope: SnapshotScope<View>
) {
  let sessionRevision: number | null = null
  let request = 0
  let restored = false
  const isActive = () => sessionRevision === store.getSessionRevision(scope.userId)

  return {
    activate() {
      sessionRevision = store.getSessionRevision(scope.userId)
    },
    invalidate() {
      sessionRevision = null
      request++
    },
    beginLoad() {
      const id = ++request
      const valid = () => isActive() && id === request
      return {
        valid,
        peek: () => valid() && !restored ? store.peekSnapshot(scope) : null,
        consume() {
          if (!valid() || restored) return null
          restored = true
          return store.consumeSnapshot(scope)
        }
      }
    },
    save(snapshot: Snapshots[View]) {
      if (isActive() && restored) store.saveSnapshot(scope, snapshot)
    }
  }
}
