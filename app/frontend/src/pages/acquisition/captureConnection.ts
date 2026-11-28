import { api } from '../../api'
import { ApiError } from '../../api/client'
import { hardwareLockStore } from '../../stores/hardwareLockStore'
import type { CaptureActivity, OperationToken } from '../../stores/hardwareLockStoreCore'

type CaptureTask = {
  id: number
  active_capture_id?: number
  device_profile_id: number
  profile: { transport: string }
  status: string
}
const idleTaskStates = new Set(['draft', 'ready', 'between_repeats', 'completed', 'failed', 'stopped'])

export function captureActivity(task?: CaptureTask | null): CaptureActivity | null {
  if (!task || task.active_capture_id === undefined && idleTaskStates.has(task.status)) return null
  return { taskId: task.active_capture_id ?? task.id, profileId: task.device_profile_id,
    transport: task.profile.transport, state: task.status }
}

export function activeCaptureTask<T extends CaptureTask>(tasks: T[]) {
  return tasks.find(task => task.active_capture_id === task.id) ?? tasks.find(task => captureActivity(task) !== null)
}

export function checkCaptureShutdown(task: CaptureTask & { failure_code: string | null; failure_message: string | null; stop_confirmed?: boolean }) {
  if (task.status === 'failed' && task.stop_confirmed !== true) {
    throw new ApiError(task.failure_message || '摄谱停机结果尚未确认', 409, task.failure_code ?? undefined)
  }
}

/** One finite legacy CCD check before opening a real capture workspace. */
export async function ensureCaptureConnection(token: string, profileId: number | null, transport: string | undefined,
  purpose: 'devices' | 'acquisition' | 'dispersion', operation?: OperationToken) {
  if (transport !== 'serial') return
  if (profileId == null) throw new Error('请选择设备参数中的真实串口档案')
  const result = await api.testDeviceConnection(token, profileId, purpose)
  if (operation && !result.connected) hardwareLockStore.recordPortReleased(operation, profileId)
  if (!result.passed || !result.instrument_responded || result.connected)
    throw new Error('未收到有效CCD响应，请在设备参数中完成连接测试后再进入摄谱')
}
