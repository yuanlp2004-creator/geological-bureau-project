import { useState } from 'react'
import { Wrench } from 'lucide-react'
import { api, type Capability } from '../../api'
import { CopyableCode } from '../../components/InformationDisplay'

export function ExtensionPage({ token, extension, onToast }: { token: string; extension: Capability; onToast: (message: string) => void }) {
  const [result, setResult] = useState<Record<string, unknown> | null>(null)
  const execute = async () => { try { const next = await api.executeExtension(token, extension.key); setResult(next); onToast('测试模块事件已记录') } catch (error) { onToast(error instanceof Error ? error.message : '测试模块执行失败') } }
  return <div className="page-content disabled-page" data-testid="test-extension-page"><div className="disabled-illustration"><Wrench size={34} /></div><span className="section-kicker">TEST BUILD MODULE</span><h1>{extension.title}</h1><p>此页面由构建期模块清单接入，仅用于验证迁移、API、导航、权限、审计、版本化事件和可选 Tauri 能力。正式包不会包含该模块。</p><button className="primary-button" onClick={() => void execute()}>执行版本化事件</button>{result && <CopyableCode value={JSON.stringify(result)} visibleLength={36} />}</div>
}
