type DirtyEdit = { reason: string; discard?: () => void }
export type DirtyGuard = () => DirtyEdit | null
export type RegisterDirtyGuard = (guard: DirtyGuard) => () => void
export type GuardNavigation = (guard: DirtyGuard, commit: () => void) => Promise<boolean>

export function createNavigationGuard(confirm: (reason: string) => Promise<boolean>) {
  let pending = false
  return async (guard: DirtyGuard, commit: () => void, valid = () => true) => {
    if (pending) return false
    const dirty = guard()
    if (dirty) {
      pending = true
      try {
        if (!await confirm(dirty.reason) || !valid()) return false
        dirty.discard?.()
        commit()
        return true
      } finally {
        pending = false
      }
    }
    commit()
    return true
  }
}

type MethodForm = { name: string; description: string; work_type: string; conditions: unknown }

export function methodFormIsDirty(
  draft: MethodForm | null, baseline: MethodForm | null, composer: string | null, composerName: string
) {
  return Boolean((composer && composerName.trim()) || (draft && baseline && (
    draft.name !== baseline.name || draft.description !== baseline.description || draft.work_type !== baseline.work_type ||
    JSON.stringify(draft.conditions) !== JSON.stringify(baseline.conditions)
  )))
}

export function lineFormIsDirty(draft: unknown, baseline: unknown) {
  return baseline != null && JSON.stringify(draft) !== JSON.stringify(baseline)
}

export function recalculationIsDirty(drafts: Record<number, unknown>, completed: boolean) {
  return !completed && Object.keys(drafts).length > 0
}
