import { useLayoutEffect, useMemo } from 'react'
import { createWorkbenchStore, createWorkbenchVisit, type WorkbenchIdentity, type WorkbenchView } from './workbenchStoreCore.ts'

export {
  buildWorkbenchScopeKey, permissionScopeKey, type SpectrumViewerSnapshot, type EvaporationCurvesSnapshot,
  type MethodsPageSnapshot, type AnalysisPageSnapshot, type PostProcessingPageSnapshot,
  type WorkbenchIdentity, type WorkbenchView
} from './workbenchStoreCore.ts'

export const workbenchStore = createWorkbenchStore()

export function useWorkbenchVisit<View extends WorkbenchView>(
  view: View, { userId, permissionsKey, methodVersionId }: WorkbenchIdentity, token: string
) {
  const visit = useMemo(() => createWorkbenchVisit(workbenchStore, { view, userId, permissionsKey, methodVersionId }),
    [view, userId, permissionsKey, methodVersionId, token])
  useLayoutEffect(() => {
    visit.activate()
    return visit.invalidate
  }, [visit])
  return visit
}
