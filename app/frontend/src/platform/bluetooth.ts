/** Fixed native action: Windows owns Bluetooth pairing and authentication. */
export async function openBluetoothSettings(): Promise<void> {
  const invoke = window.__TAURI__?.core?.invoke
  if (!invoke) throw new Error('请打开 Windows 设置 → 蓝牙和设备完成配对，再回到软件刷新端口。')
  await invoke('open_bluetooth_settings')
}
