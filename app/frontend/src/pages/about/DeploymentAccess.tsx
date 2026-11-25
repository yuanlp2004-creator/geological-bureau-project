import { useCallback, useEffect, useState } from 'react'
import { deploymentAccess, type ActivationStatus, type SupportStatus } from '../../api/deploymentAccess'

const activationLabels: Record<ActivationStatus['state'], string> = {
  unmanaged: '沿用现有授权策略',
  pending: '待激活',
  active: '已激活',
  expired: '已到期',
  invalid: '授权文件无效',
  configuration_error: '部署的验签配置不可用'
}
const formatTime = (iso: string) => new Date(iso).toLocaleString('zh-CN', {
  year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', timeZoneName: 'short'
})
const errorText = (error: unknown) => error instanceof Error ? error.message : '操作失败，请刷新重试'

export function ActivationPanel({ token }: { token: string }) {
  const [status, setStatus] = useState<ActivationStatus>()
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)
  const refresh = useCallback(async () => {
    try {
      setStatus(await deploymentAccess.activation(token))
    } catch (error) {
      setNotice(errorText(error))
    }
  }, [token])
  useEffect(() => { void refresh() }, [refresh])

  async function install(file: File) {
    setNotice('')
    if (file.size > 4096) {
      setNotice('授权文件过大')
      return
    }
    setBusy(true)
    try {
      setStatus(await deploymentAccess.install(token, await file.text()))
      setNotice('已导入有效授权')
    } catch (error) {
      setNotice(errorText(error))
    } finally {
      setBusy(false)
    }
  }

  return <section className="surface about-software-card deployment-access-card" aria-label="软件激活">
    <h2>软件激活</h2>
    <div className="deployment-actions">
      <strong>{status ? activationLabels[status.state] : '正在读取授权状态'}</strong>
      <button type="button" className="secondary-button" disabled={busy} onClick={() => { setNotice(''); void refresh() }}>刷新激活状态</button>
    </div>
    {status?.installation_id && <label className="field">
      <span>安装标识</span><input readOnly value={status.installation_id} />
    </label>}
    {status?.expires_at && <p>到期时间 {formatTime(status.expires_at)}</p>}
    {status?.installation_id && <label className="field">
      <span>导入激活或续期文件</span>
      <input type="file" accept=".json,application/json" disabled={busy} onChange={(event) => {
        const file = event.currentTarget.files?.[0]
        event.currentTarget.value = ''
        if (file) void install(file)
      }} />
    </label>}
    {notice && <p role="status">{notice}</p>}
  </section>
}

export function SupportPanel({ token }: { token: string }) {
  const [status, setStatus] = useState<SupportStatus>()
  const [supportToken, setSupportToken] = useState('')
  const [revealed, setRevealed] = useState(false)
  const [minutes, setMinutes] = useState(15)
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)

  const refresh = useCallback(async () => {
    try {
      const next = await deploymentAccess.support(token)
      setStatus(next)
      if (!next.active) {
        setSupportToken('')
        setRevealed(false)
      }
    } catch (error) {
      setNotice(errorText(error))
    }
  }, [token])
  useEffect(() => { void refresh() }, [refresh])
  useEffect(() => {
    if (!status?.active || !status.expires_at) return
    const timer = window.setTimeout(() => { void refresh() }, Math.max(1000, Date.parse(status.expires_at) - Date.now()))
    return () => window.clearTimeout(timer)
  }, [status, refresh])

  async function changeSharing(open: boolean) {
    setBusy(true)
    setNotice('')
    try {
      if (open) {
        const next = await deploymentAccess.openSupport(token, minutes)
        setSupportToken(next.access_token)
        setStatus({ active: next.active, port: next.port, expires_at: next.expires_at, checked_at: next.checked_at })
      } else {
        await deploymentAccess.closeSupport(token)
        setSupportToken('')
        setRevealed(false)
        await refresh()
      }
    } catch (error) {
      await refresh()
      setNotice(errorText(error))
    } finally {
      setBusy(false)
    }
  }

  async function refreshSnapshot() {
    setBusy(true)
    setNotice('')
    try {
      setStatus(await deploymentAccess.refreshSnapshot(token))
      setNotice('共享快照已更新')
    } catch (error) {
      await refresh()
      setNotice(errorText(error))
    } finally {
      setBusy(false)
    }
  }

  return <section className="surface about-software-card deployment-access-card" aria-label="模块远程诊断">
    <h2>模块远程诊断</h2>
    <p>开启后可通过已授权的安全隧道读取本次模块自检和脱敏日志。会话到期、退出登录或手动结束后，访问权限失效。</p>
    {!status ? <button type="button" className="secondary-button" onClick={() => { void refresh() }}>刷新诊断状态</button>
      : <div className="deployment-actions">
        <strong>{status.active ? '诊断已开启' : '诊断已关闭'}</strong>
        {status.active
          ? <>
            <button type="button" className="secondary-button" disabled={busy} onClick={() => { void refreshSnapshot() }}>刷新共享快照</button>
            <button type="button" className="secondary-button" disabled={busy} onClick={() => { void changeSharing(false) }}>结束诊断共享</button>
          </>
          : <>
            <label className="field"><span>有效时长</span>
              <select value={minutes} onChange={(event) => setMinutes(Number(event.target.value))}>
                {[5, 15, 30].map((value) => <option key={value} value={value}>{value} 分钟</option>)}
              </select>
            </label>
            <button type="button" className="primary-button" disabled={busy} onClick={() => { void changeSharing(true) }}>开启诊断共享</button>
          </>}
      </div>}
    {status?.active && <div className="deployment-access-details">
      <p>现场回环端口 {status.port} · 到期时间 {status.expires_at && formatTime(status.expires_at)}</p>
      {status.checked_at && <p>最近自检时间 {formatTime(status.checked_at)}</p>}
      {supportToken ? <div className="deployment-actions">
        <label className="field"><span>临时访问令牌</span><input type={revealed ? 'text' : 'password'} value={supportToken} readOnly autoComplete="off" /></label>
        <button type="button" className="secondary-button" onClick={() => setRevealed(!revealed)}>{revealed ? '隐藏令牌' : '显示令牌'}</button>
      </div> : <p>访问令牌只在开启时显示。需要重新提供令牌时，请结束后重新开启。</p>}
      <p>支持人员通过隧道读取 <code>/api/v1/support/snapshot</code>，并在 Authorization 请求头传入 Bearer 令牌。</p>
    </div>}
    {notice && <p role="status">{notice}</p>}
  </section>
}
