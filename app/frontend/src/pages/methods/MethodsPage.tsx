import { OpenLegacyFile } from '../../components/OpenLegacyFile'
import { confirmAction } from '../../platform/dialogs'
import { roundHalfEven } from '../../components/legacyObservation'
import {
  AlertTriangle,
  Check,
  Copy,
  PlayCircle,
  Plus,
  Printer,
  RefreshCw,
  Save,
  SlidersHorizontal,
  Trash2,
  X
} from 'lucide-react'
import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'
import {
  api,
  type AuthUser,
  type CurrentMethodState,
  type MethodConditions,
  type MethodOptions,
  type MethodRecord
} from '../../api'
import { CopyableCode } from '../../components/InformationDisplay'
import { reportInvalidNumericInput } from '../../components/NumericInput'
import { MethodExcitation } from './MethodExcitation'
import { MethodAngles } from './MethodAngles'
import { methodExposureMode } from './spectralLineDraft'
import { MethodGeometry } from './MethodGeometry'
import { MethodIdentity } from './MethodIdentity'
import { MethodPrintPanel } from './MethodPrintPanel'
import { MethodQuality } from './MethodQuality'
import { SpectralLinesPanel } from './SpectralLinesPanel'
import type { MethodShortcutRequest } from './methodShortcuts'
import { OpenMethodDialog } from './OpenMethodDialog'

export function MethodsPage({
  token,
  currentUser,
  currentMethod,
  initialSection,
  shortcut,
  onShortcutHandled,
  onViewChange,
  onCurrentMethodChange,
  onToast
}: {
  token: string
  currentUser: AuthUser
  currentMethod: CurrentMethodState | null
  initialSection: string | null
  shortcut?: MethodShortcutRequest | null
  onShortcutHandled?: () => void
  onViewChange: (view: string) => void
  onCurrentMethodChange: (method: CurrentMethodState) => void
  onToast: (message: string) => void
}) {
  const [methods, setMethods] = useState<MethodRecord[]>([])
  const [options, setOptions] = useState<MethodOptions | null>(null)
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [draftName, setDraftName] = useState('')
  const [draftDescription, setDraftDescription] = useState('')
  const [draftWorkType, setDraftWorkType] = useState('routine')
  const [conditions, setConditions] = useState<MethodConditions | null>(null)
  const [draftMethodId, setDraftMethodId] = useState<number | null>(null)
  const [composer, setComposer] = useState<'create' | 'copy' | null>(null)
  const [composerName, setComposerName] = useState('')
  const [editorSection, setEditorSection] = useState<'conditions' | 'lines' | 'print'>('conditions')
  const [busy, setBusy] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [saveError, setSaveError] = useState<string | null>(null)
  const actionPending = useRef(false)
  const canWrite = currentUser.permissions.includes('methods.write')
  const methodPicker = useRef<HTMLSelectElement>(null)
  const handledShortcut = useRef<number | null>(null)
  const [openingMethod, setOpeningMethod] = useState(false)
  const [openError, setOpenError] = useState<string | null>(null)

  useEffect(() => {
    if (initialSection === 'lines') setEditorSection('lines')
    else if (initialSection === 'print-settings' || initialSection === 'print-preview') setEditorSection('print')
    else setEditorSection('conditions')
  }, [initialSection])

  const load = useCallback(async () => {
    try {
      const [nextMethods, nextOptions, nextCurrent] = await Promise.all([
        api.methods(token),
        api.methodOptions(token),
        api.currentMethod(token)
      ])
      setMethods(nextMethods)
      setOptions(nextOptions)
      setSelectedId((previous) =>
        nextMethods.some((item) => item.id === previous)
          ? previous
          : (nextCurrent.method_id ?? nextMethods[0]?.id ?? null)
      )
      onCurrentMethodChange(nextCurrent)
      setLoadError(null)
      return true
    } catch (error) {
      setLoadError(error instanceof Error ? error.message : '无法读取方法数据')
      return false
    }
  }, [onCurrentMethodChange, token])

  useEffect(() => {
    void load()
  }, [load])
  const selected = methods.find((item) => item.id === selectedId) ?? null
  const selectedVersion = selected?.version ?? null
  const issues = selectedVersion?.validation_errors ?? []
  const unsaved = selectedVersion?.state === 'draft' || Boolean(selected && selectedVersion && (
    draftName !== selected.name || draftDescription !== selected.description || draftWorkType !== selected.work_type ||
    JSON.stringify(conditions) !== JSON.stringify({ ...selectedVersion.conditions,
      exposure_mode: methodExposureMode(selectedVersion.conditions, selectedVersion.lines) })
  ))

  useEffect(() => {
    if (!shortcut || handledShortcut.current === shortcut.id || (!options && !loadError)) return
    if (selected?.version && draftMethodId !== selected.id) return
    handledShortcut.current = shortcut.id
    onShortcutHandled?.()
    if (busy) return onToast('方法操作进行中，请稍后再试')
    if (shortcut.action === 'open') {
      if (!canWrite) return
      if (composer) return onToast('请先完成或取消当前方法表单')
      if (unsaved) return onToast('请先保存当前修改，再打开方法')
      setOpenError(null)
      setOpeningMethod(true)
      return
    }
    if (!canWrite) return
    const nextComposer = shortcut.action === 'copy' ? 'copy' : 'create'
    if (composer) {
      if (composer !== nextComposer) onToast('请先完成或取消当前方法表单')
      return
    }
    if (shortcut.action === 'copy') {
      if (!selected) return onToast('请先选择要另存的方法')
      if (unsaved) return onToast('请先保存当前修改，再另存为')
      setComposer('copy')
      setComposerName(`${selected.name}-副本`)
    } else {
      setComposer('create')
      setComposerName('')
    }
  }, [shortcut, options, loadError, busy, canWrite, selected, draftMethodId, composer, unsaved, onShortcutHandled, onToast])

  useEffect(() => setSaveError(null), [selectedId, draftName, draftDescription, draftWorkType, conditions])

  useEffect(() => {
    if (!selected?.version) return
    setDraftName(selected.name)
    setDraftDescription(selected.description)
    setDraftWorkType(selected.work_type)
    setConditions({ ...structuredClone(selected.version.conditions),
      exposure_mode: methodExposureMode(selected.version.conditions, selected.version.lines) })
    setDraftMethodId(selected.id)
  }, [selected])

  const setCondition = <K extends keyof MethodConditions>(key: K, value: MethodConditions[K]) => {
    setConditions((previous) => (previous ? { ...previous, [key]: value,
      ...(key === 'sampling_period_seconds' && value !== previous.sampling_period_seconds
        ? { dark_frame_count: roundHalfEven((options?.dark_round_time_seconds ?? 8) / Number(value)) } : {}),
      ...(key === 'frame_count' ? { angle_exposures: previous.angle_exposures.map((angle) =>
        ({ ...angle, start_frame: 1, end_frame: value as number })) } : {}),
      ...(key === 'reference_wavelength_nm' ? { actual_reference_wavelength_nm: value as number } : {}) } : previous))
  }
  const openSelectedMethod = async (id: number) => {
    if (!canWrite || actionPending.current || busy) return
    actionPending.current = true
    setBusy(true)
    setOpenError(null)
    try {
      await api.openMethod(token, id, true)
      const refreshed = await load()
      setSelectedId(id)
      setOpeningMethod(false)
      onToast(refreshed ? '当前方法已打开' : '方法已打开，状态刷新失败，请刷新页面')
    } catch (error) {
      setOpenError(error instanceof Error ? error.message : '打开方法失败，请重试')
    } finally {
      actionPending.current = false
      setBusy(false)
    }
  }
  const hasIssue = (field: string) =>
    issues.some(
      (issue) => issue.field === field || issue.field.startsWith(`${field}.`) || issue.field.startsWith(`${field}[`)
    )
  const notifyError = (error: unknown, fallback: string) => onToast(error instanceof Error ? error.message : fallback)

  const runAction = async (action: () => Promise<unknown>, success: string) => {
    if (actionPending.current) return
    actionPending.current = true
    setBusy(true)
    try {
      await action()
      await load()
      onToast(success)
    } catch (error) {
      notifyError(error, '方法操作失败')
    } finally {
      actionPending.current = false
      setBusy(false)
    }
  }

  const saveMethod = () => {
    if (!selected || !conditions || actionPending.current) return
    if (!reportInvalidNumericInput(document.querySelector('.methods-page'))) return onToast('请先修正方法中的无效数值')
    // 本界面只维护存储方式；兼容字段在新草稿中统一为全帧，已有发布快照不变。
    void runAction(
      () =>
        api.saveMethod(token, selected.id, {
          expected_latest_version: selected.latest_version ?? undefined,
          name: draftName,
          description: draftDescription,
          work_type: draftWorkType,
          conditions: { ...conditions, angle_exposures: conditions.angle_exposures.map((angle) =>
            ({ ...angle, start_frame: 1, end_frame: conditions.frame_count })) }
        }).catch((error) => {
          setSaveError(error instanceof Error ? error.message : '方法保存失败')
          throw error
        }),
      selected.is_current && selected.status === 'active' ? '方法已保存，当前方法已更新' : '方法已保存，可打开使用'
    )
  }

  const submitComposer = (event: FormEvent) => {
    event.preventDefault()
    if (!composerName.trim()) return
    const action =
      composer === 'copy' && selected
        ? api.copyMethod(token, selected.id, composerName)
        : api.createMethod(token, { name: composerName })
    setBusy(true)
    void action
      .then(async (created) => {
        setComposer(null)
        setComposerName('')
        await load()
        setSelectedId(created.id)
        onToast(composer === 'copy' ? '方法副本已创建，请核对后保存' : '新方法已创建，请配置后保存')
      })
      .catch((error) => notifyError(error, '创建方法失败'))
      .finally(() => setBusy(false))
  }

  const currentLayout = options?.ccd_layouts.find(
    (item) => item.id === Number(conditions?.ccd_layout_id) || item.name === String(conditions?.ccd_layout_id)
  )
  const currentCalibration = options?.dispersion_calibrations.find(
    (item) =>
      item.id === Number(conditions?.dispersion_calibration_id) ||
      item.name === String(conditions?.dispersion_calibration_id)
  )

  const changeCalibration = (calibrationId: number) => {
    const calibration = options?.dispersion_calibrations.find((item) => item.id === calibrationId && item.enabled)
    const layout = options?.ccd_layouts.find((item) => item.id === calibration?.ccd_layout_id)
    if (!calibration || !layout) return
    // 只在用户选择色散曲线时带入 CCD；读取和保存其他参数保留既有配置。
    setConditions((previous) =>
      previous
        ? {
          ...previous,
          ccd_layout_id: layout.id,
          selected_ccds: [...layout.ccd_indices],
          dispersion_calibration_id: calibration.id
        }
        : previous
    )
  }

  return (
    <div
      className="page-content methods-page refined-page"
      data-testid="methods-page"
      data-navigation-view={initialSection ?? 'lifecycle'}
    >
      {openingMethod && <OpenMethodDialog token={token} methods={methods} selectedId={selectedId} busy={busy} error={openError}
        onOpen={id => void openSelectedMethod(id)} onCancel={() => setOpeningMethod(false)} onBusyChange={setBusy}
        onImported={async () => { await load(); onToast('方法已加入列表，请选择要打开的已保存方法') }} />}
      <section className="surface method-action-bar method-context-bar">
        <div className="method-context-main">
          <div className="method-picker">
            
            <select
              ref={methodPicker}
              aria-label="选择编辑方法"
              title={selected?.name}
              value={selectedId ?? ''}
              onChange={(event) => setSelectedId(Number(event.target.value))}
              disabled={busy || methods.length === 0}
            >
              {methods.length === 0 && <option value="">暂无方法</option>}
              {methods.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                  {item.is_current ? ' · 当前运行' : ''}
                  {item.status === 'paused' ? ' · 已停用' : ''}
                </option>
              ))}
            </select>
          </div>
          {selected && (
            <div className="method-context-status">
              <span className={`version-chip ${selectedVersion?.state}`}>
                {unsaved ? '待保存' : '已保存'}
              </span>
              {selected.is_current && <span className="current-chip">当前运行</span>}
              {selected.status !== 'active' && (
                  <span className="issue-chip">{selected.status === 'paused' ? '已停用' : '已删除'}</span>
              )}
              {issues.length > 0 && (
                <span className="issue-chip">
                  <AlertTriangle size={13} />
                  {issues.length} 项待修正
                </span>
              )}
              <details className="method-version-details">
                <summary>版本信息</summary>
                <div>
                  <span>工作类型：{selected.work_type}</span>
                  <span>已保存版本：{selected.current_version ? `v${selected.current_version}` : '—'}</span>
                  <span>编辑版本：{selectedVersion ? `v${selectedVersion.version}` : '—'}</span>
                  <span>
                    最新内容摘要：
                    <CopyableCode value={selectedVersion?.content_sha256} visibleLength={10} />
                  </span>
                  <small>保存时自动保留历史版本，已有任务和结果继续引用原版本。</small>
                </div>
              </details>
            </div>
          )}
        </div>
        <div className="method-context-actions">
          <div className="method-actions">


            {canWrite && selected && (
              <>
                <button
                  className="secondary-button"
                  onClick={() => {
                    setComposer('copy')
                    setComposerName(`${selected.name}-副本`)
                  }}
                  disabled={busy || unsaved}
                  title={unsaved ? '请先保存当前修改，再另存为' : undefined}
                >
                  <Copy size={15} />
                  另存为
                </button>
                <button
                  className="primary-button"
                  onClick={saveMethod}
                  disabled={busy || selected.status === 'deleted'}
                >
                  <Save size={15} />
                  保存
                </button>
                {selected.published_version && (!selected.is_current || selected.status === 'paused') && selected.status !== 'deleted' && (
                  <button
                    className="primary-button"
                    onClick={() => void runAction(() => api.openMethod(token, selected.id, true), '当前方法已打开')}
                    disabled={busy || unsaved}
                    title={unsaved ? '请先保存修改，再打开方法' : undefined}
                  >
                    <PlayCircle size={15} />
                    使用方法
                  </button>
                )}
                <button
                  className="icon-button danger"
                  title="删除方法"
                  onClick={async () => {
                    if (await confirmAction(`确认删除方法“${selected.name}”？历史版本仍会保留。`))
                      void runAction(() => api.deleteMethod(token, selected.id), '方法已删除，历史版本已保留')
                  }}
                  disabled={busy}
                >
                  <Trash2 size={15} />
                </button>
              </>
            )}
          </div>
          <div className="method-library-actions file-actions">
            <OpenLegacyFile onBusyChange={setBusy} token={token} purpose="methods" label="打开方法" disabled={busy} onOpened={async result => {
              if (unsaved) {
                const next = await api.methods(token)
                setMethods(current => [...current, ...next.filter(item => !current.some(existing => existing.id === item.id))])
                onToast('方法已加入列表，当前未保存的编辑内容已保留')
              } else {
                await load(); setSelectedId(result.method_ids[0] ?? null)
                onToast('方法库已打开，请从列表选择要使用的方法')
              }
            }}/>
            <button className="secondary-button" onClick={() => void load()} disabled={busy}>
              <RefreshCw size={16} />
              刷新
            </button>
            {canWrite && (
              <button
                className="primary-button"
                disabled={busy}
                onClick={() => {
                  setComposer('create')
                  setComposerName('')
                }}
              >
                <Plus size={16} />
                新建方法
              </button>
            )}
          </div>
        </div>
      </section>
      {loadError && (
        <div className="auth-error">
          <AlertTriangle size={15} />
          {loadError}
        </div>
      )}
      {composer && (
        <form className="surface method-composer" onSubmit={submitComposer}>
          <div>
            <span className="section-kicker">{composer === 'copy' ? '另存为' : '新建方法'}</span>
            <strong>{composer === 'copy' ? `将“${selected?.name ?? ''}”另存为` : '创建新方法'}</strong>
          </div>
          <label className="field">
            <span>新方法名称</span>
            <input
              autoFocus
              maxLength={20}
              value={composerName}
              onChange={(event) => setComposerName(event.target.value)}
              placeholder="GB18030 不超过 20 字节"
              required
            />
          </label>
          <button className="primary-button" disabled={busy}>
            <Check size={15} />
            确认
          </button>
          <button type="button" className="icon-button" title="取消" onClick={() => setComposer(null)}>
            <X size={15} />
          </button>
        </form>
      )}
      <div className="method-workbench">
        <main className="method-editor">
          {!selected || !conditions ? (
            <section className="surface method-empty">
              <SlidersHorizontal size={30} />
              <h2>选择或新建方法</h2>
              <p>方法条件、版本状态和运行操作会显示在这里。</p>
            </section>
          ) : (
            <>
              <div className="method-editor-tabs" role="tablist">
                <button
                  className={editorSection === 'conditions' ? 'active' : ''}
                  onClick={() => {
                    setEditorSection('conditions')
                    onViewChange('conditions')
                  }}
                >
                  方法管理与参数
                </button>
                <button
                  className={editorSection === 'lines' ? 'active' : ''}
                  onClick={() => {
                    setEditorSection('lines')
                    onViewChange('lines')
                  }}
                >
                  分析谱线 <span>{selectedVersion?.lines?.length ?? 1}</span>
                </button>
                <button
                  className={editorSection === 'print' ? 'active' : ''}
                  onClick={() => {
                    setEditorSection('print')
                    onViewChange('print-preview')
                  }}
                >
                  <Printer size={13} />
                  预览与打印
                </button>
              </div>
              {editorSection === 'conditions' && (
                <>
                  {selectedVersion?.legacy_imported && <section className="surface method-legacy-upgrade">
                    <p>从原 MTD 补全旧方法的曝光段与标准强度。补全后请核对并保存，原有版本保留。</p>
                    <button className="secondary-button" disabled={!canWrite || busy}
                      onClick={() => void runAction(() => api.upgradeLegacyMethod(token, selected.id), '旧方法功能数据已补全，请核对并保存')}>补全旧方法功能数据</button>
                  </section>}
                  {(issues.length > 0 || saveError) && (
                    <section className="surface method-issues">
                      <div>
                        <AlertTriangle size={17} />
                        <strong>{saveError ?? '方法存在待修正项'}</strong>
                        <span>修正后点击保存；原有效版本保持不变。</span>
                      </div>
                      <ul>
                        {issues.map((issue, index) => (
                          <li key={`${issue.field}-${index}`}>
                            <code>{issue.field}</code>
                            <span>{issue.message}</span>
                          </li>
                        ))}
                      </ul>
                    </section>
                  )}
                  <MethodIdentity
                    draftName={draftName}
                    setDraftName={setDraftName}
                    canWrite={canWrite && !busy}
                    draftDescription={draftDescription}
                    setDraftDescription={setDraftDescription}
                  />
                  <div className="method-parameters-grid">
                    <MethodGeometry
                      token={token}
                      hasIssue={hasIssue}
                      currentLayout={currentLayout}
                      changeCalibration={changeCalibration}
                      canWrite={canWrite && !busy}
                      options={options}
                      currentCalibration={currentCalibration}
                      setCondition={setCondition}
                      conditions={conditions}
                    />
                    <MethodExcitation
                      hasIssue={hasIssue}
                      conditions={conditions}
                      canWrite={canWrite && !busy}
                      setCondition={setCondition}
                    />
                  </div>
                  <MethodAngles
                    conditions={conditions}
                    canWrite={canWrite && !busy}
                    hasIssue={hasIssue}
                    options={options}
                    onChange={(angles) => setCondition('angle_exposures', angles)}
                  />
                  <MethodQuality
                    hasIssue={hasIssue}
                    conditions={conditions}
                    canWrite={canWrite && !busy}
                    setCondition={setCondition}
                  />
                </>
              )}
              {editorSection === 'lines' && (
                <SpectralLinesPanel
                  methodId={selected.id}
                  token={token}
                  canWrite={canWrite && !busy}
                  onChanged={async () => { await load() }}
                  onToast={onToast}
                />
              )}
              {editorSection === 'print' && (
                <MethodPrintPanel
                  methodId={selected.id}
                  methodName={selected.name}
                  version={selectedVersion?.version ?? null}
                  token={token}
                  canWrite={canWrite && !busy}
                  onToast={onToast}
                />
              )}
            </>
          )}
        </main>
      </div>
    </div>
  )
}
