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
  const snapshots = new Map<string, Readonly<SpectrumViewerSnapshot>>()
  const sessionRevisions = new Map<UserId, number>()
  let revision = 0
  let allRevision = 0

  return {
    saveSpectrumSnapshot(scopeKey: string, snapshot: SpectrumViewerSnapshot) {
      snapshots.set(scopeKey, Object.freeze({ ...snapshot, overlayIds: Object.freeze([...snapshot.overlayIds]) }))
    },
    peekSpectrumSnapshot(scopeKey: string) {
      return snapshots.get(scopeKey) ?? null
    },
    consumeSpectrumSnapshot(scopeKey: string) {
      const snapshot = snapshots.get(scopeKey) ?? null
      snapshots.delete(scopeKey)
      return snapshot
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
