import { api } from '../../api'

/** One finite legacy CCD check before opening a real capture workspace. */
export async function ensureCaptureConnection(token: string, profileId: number | null, transport: string | undefined,
  purpose: 'devices' | 'acquisition' | 'dispersion' | 'hardware-acquisition') {
  if (transport !== 'serial') return
  if (profileId == null) throw new Error('请选择设备参数中的真实串口档案')
  const result = await api.testDeviceConnection(token, profileId, purpose)
  if (!result.passed || !result.instrument_responded)
    throw new Error('未收到有效CCD响应，请在设备参数中完成连接测试后再进入摄谱')
}
