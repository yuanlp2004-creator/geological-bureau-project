import { AdvancedSettings } from '../../components/AdvancedSettings'
import { SectionHeading } from '../../components/SectionHeading'
import { PageFileActions } from '../../components/PageFileActions'
import { useEffect, useRef, useState } from 'react'
import { CheckCircle2, Clock3, FolderOpen, RefreshCw, Save, SlidersHorizontal } from 'lucide-react'
import { type Settings } from '../../api'
import { reportInvalidNumericInput, NumericInput as EmptyableNumberInput } from '../../components/NumericInput'

export function SettingsPage({
  settings,
  onSave,
  onReset,
  onToast,
  actionsTarget
}: {
  settings: Settings
  onSave: (settings: Settings) => void
  onReset: () => void
  onToast: (message: string) => void
  actionsTarget?: HTMLElement | null
}) {
  const [draft, setDraft] = useState(settings)
  const [pickerTarget, setPickerTarget] = useState<string | null>(null)
  const pickerRef = useRef<HTMLInputElement>(null)
  const pageRef = useRef<HTMLDivElement>(null)
  const save = () => {
    if (!reportInvalidNumericInput(pageRef.current)) {
      onToast('请先修正设置中的无效数值')
      return
    }
    onSave(draft)
  }
  useEffect(() => setDraft(settings), [settings])
  const changeDirectory = (key: string, value: string) =>
    setDraft({ ...draft, directories: { ...draft.directories, [key]: value } })
  const chooseDirectory = (key: string) => {
    setPickerTarget(key)
    pickerRef.current?.click()
  }
  const onPickedDirectory = (files: FileList | null) => {
    const relativePath = files?.[0]?.webkitRelativePath
    if (pickerTarget && relativePath) changeDirectory(pickerTarget, relativePath.split('/')[0])
    setPickerTarget(null)
  }
  return (
    <div ref={pageRef} className="page-content settings-page refined-page remaining-page" data-testid="settings">
      <PageFileActions target={actionsTarget}>
          <span className="settings-live-badge">
            <CheckCircle2 size={14} />
            保存后生效
          </span>
          <button className="secondary-button" onClick={onReset}>
            <RefreshCw size={16} />
            恢复默认
          </button>
          <button className="primary-button" data-testid="settings-save" onClick={save}>
            <Save size={16} />
            保存设置
          </button>
      </PageFileActions>
      <input
        ref={pickerRef}
        className="hidden-picker"
        type="file"
        multiple
        onChange={(event) => onPickedDirectory(event.target.files)}
        {...({ webkitdirectory: '' } as Record<string, string>)}
      />
      <div className="settings-layout">
        <section className="surface settings-section">
          <div className="surface-heading">
            <SectionHeading title="备份目录" />
          </div>
          <p className="settings-effect-note">用于在线备份；文件保存和导出仍在相应操作中选择位置。</p>
          <div className="field-grid">
            {Object.entries(draft.directories).filter(([key]) => key === 'backups').map(([key, value]) => (
              <label className="field" key={key}>
                <span>
                  {(
                    {
                      data: '数据目录',
                      methods: '方法目录',
                      samples: '样品目录',
                      exports: '导出目录',
                      backups: '备份目录'
                    } as Record<string, string>
                  )[key] ?? key}
                </span>
                <div className="field-with-action">
                  <input value={value} onChange={(event) => changeDirectory(key, event.target.value)} />
                  <button className="icon-button compact" title="选择目录" onClick={() => chooseDirectory(key)}>
                    <FolderOpen size={15} />
                  </button>
                </div>
              </label>
            ))}
          </div>
        </section>
        <section className="surface settings-section">
          <div className="surface-heading">
            <SectionHeading title="显示设置" />
          </div>
          <p className="settings-effect-note">
            主题、信息密度和侧栏状态区在保存后生效。
          </p>
          <div className="field-grid settings-display-fields">
            <label className="field">
              <span>界面主题</span>
              <select
                value={draft.display.theme}
                onChange={(event) => setDraft({ ...draft, display: { ...draft.display, theme: event.target.value } })}
              >
                <option value="light">浅色工作区</option>
                <option value="dark">深色工作区</option>
              </select>
            </label>
            <label className="field">
              <span>信息密度</span>
              <select
                value={draft.display.density}
                onChange={(event) => setDraft({ ...draft, display: { ...draft.display, density: event.target.value } })}
              >
                <option value="comfortable">舒适</option>
                <option value="compact">紧凑</option>
              </select>
            </label>
          <label className="toggle-row">
            <input
              type="checkbox"
              checked={draft.display.show_status_bar}
              onChange={(event) =>
                setDraft({ ...draft, display: { ...draft.display, show_status_bar: event.target.checked } })
              }
            />
            <span>
              <strong>显示侧栏运行状态</strong>
              <small>显示本地服务连接状态和版本</small>
            </span>
          </label>
          </div>
        </section>
        <section className="surface settings-section">
          <AdvancedSettings title="高级维护设置">
            <div className="advanced-field-grid">
            <label className="field">
              <span>日志级别</span>
              <select
                value={draft.logging.level}
                onChange={(event) => setDraft({ ...draft, logging: { ...draft.logging, level: event.target.value } })}
              >
                <option value="debug">调试</option>
                <option value="info">信息</option>
                <option value="warning">警告</option>
              </select>
            </label>
            <label className="field">
              <span>日志保留天数</span>
              <EmptyableNumberInput
                min="1"
                max="365"
                value={draft.logging.retention_days}
                onValueChange={(value) => setDraft({ ...draft, logging: { ...draft.logging, retention_days: value } })}
              />
            </label>
            <label className="field">
              <span>日志上限（字节）</span>
              <EmptyableNumberInput
                min="1024"
                max="1073741824"
                value={draft.logging.max_bytes}
                onValueChange={(value) => setDraft({ ...draft, logging: { ...draft.logging, max_bytes: value } })}
              />
            </label>
            <label className="field">
              <span>时区</span>
              <select
                value={draft.time.timezone}
                onChange={(event) => setDraft({ ...draft, time: { ...draft.time, timezone: event.target.value } })}
              >
                <option>Asia/Shanghai</option>
                <option>UTC</option>
              </select>
            </label>
            </div>
          </AdvancedSettings>
        </section>
      </div>
    </div>
  )
}
