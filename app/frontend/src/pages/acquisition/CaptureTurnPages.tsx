import type { CaptureTurn, CaptureTurnPage } from '../../api/acquisition'

export function CaptureTurnPages({ pages, current, disabled, choose }: {
  pages: { turn_index: number; angle_deg: number; state: string }[]
  current: number; disabled: boolean; choose: (index: number) => void
}) {
  if (!pages.length) return null
  return <nav className="capture-turn-pages" aria-label="转角摄谱页面">
    {pages.map(page => <button type="button" key={page.turn_index} aria-pressed={page.turn_index === current}
      disabled={disabled && page.turn_index !== current} title={`${page.angle_deg}° · ${page.state}`}
      onClick={() => { if (page.turn_index !== current) choose(page.turn_index) }}>
      {page.angle_deg}° <span>{page.state}</span>
    </button>)}
  </nav>
}

type TurnTask = { id: number; name: string; status: string; active_capture_id?: number; capture_turn?: CaptureTurn; capture_turns?: CaptureTurnPage[] }

export function groupedCaptureTasks<T extends TurnTask>(tasks: T[]): T[] {
  const representatives = new Map<string, T>()
  for (const task of tasks) {
    const key = task.capture_turn?.group ?? `task:${task.id}`
    const prior = representatives.get(key)
    if (!prior || (task.capture_turn?.turn_index ?? 0) < (prior.capture_turn?.turn_index ?? 0)) representatives.set(key, task)
  }
  return [...representatives.values()]
}

export function captureAngleName(task: TurnTask) {
  return task.capture_turn ? `${task.name} · ${task.capture_turn.angle_deg}°` : task.name
}

export function updateCaptureTask<T extends TurnTask>(tasks: T[], fresh: T): T[] {
  const updated = tasks.map(task => {
    if (task.id === fresh.id) return fresh
    if (!fresh.capture_turn?.group || task.capture_turn?.group !== fresh.capture_turn.group) return task
    const status = fresh.capture_turns?.find(turn => turn.id === task.id)?.status ?? task.status
    return { ...task, status, active_capture_id: fresh.active_capture_id, capture_turns: fresh.capture_turns }
  })
  return updated.some(task => task.id === fresh.id) ? updated : [fresh, ...updated]
}
