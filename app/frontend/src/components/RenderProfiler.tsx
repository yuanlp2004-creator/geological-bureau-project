import { Profiler, type ReactNode } from 'react'

type ProfileId = 'WorkspaceApp' | 'SpectrumPlot' | 'MessagePanel'
type ProfileWindow = Window & {
  __GS_E2E_PROFILE__?: boolean
  __GS_RENDER_COUNTS__?: Partial<Record<ProfileId, number>>
}

export function isRenderProfilerEnabled() {
  return import.meta.env.DEV || Boolean((window as ProfileWindow).__GS_E2E_PROFILE__)
}

function countRender(id: string) {
  const counts = ((window as ProfileWindow).__GS_RENDER_COUNTS__ ??= {})
  const key = id as ProfileId
  counts[key] = (counts[key] ?? 0) + 1
}

export function RenderProfiler({ id, children }: { id: ProfileId; children: ReactNode }) {
  return isRenderProfilerEnabled()
    ? <Profiler id={id} onRender={countRender}>{children}</Profiler>
    : children
}

function ProfilerLeaf() {
  return null
}

export function RenderProfilerProbe({ id }: { id: ProfileId }) {
  // The leaf commits with its owner without observing the owner's other children.
  return isRenderProfilerEnabled()
    ? <Profiler id={id} onRender={countRender}><ProfilerLeaf /></Profiler>
    : null
}
