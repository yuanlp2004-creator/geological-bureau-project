import { Flame, TestTube2 } from 'lucide-react'
import { type FormEvent } from 'react'
import type { SampleQueue, SampleQueueItem } from '../../api/sampleQueues'
import { NumericInput } from '../../components/NumericInput'
import { AcquisitionSetupFields, AcquisitionTimingFields, type AcquisitionConditionsProps } from './AcquisitionConditionFields'

// 父页面统一持有草稿、选中项和请求状态。
export type SampleAcquisitionFormProps = AcquisitionConditionsProps & {
  saveConditions: () => Promise<void>
  useMethodConditions: boolean
  setUseMethodConditions: React.Dispatch<React.SetStateAction<boolean>>
  useMethodIntervals: boolean
  setUseMethodIntervals: React.Dispatch<React.SetStateAction<boolean>>
  managementSample: boolean
  setManagementSample: React.Dispatch<React.SetStateAction<boolean>>
  create: (event: FormEvent) => Promise<void>
  methodKey: string
  setMethodKey: React.Dispatch<React.SetStateAction<string>>
  queueId: string
  setQueueId: React.Dispatch<React.SetStateAction<string>>
  setQueueItemId: React.Dispatch<React.SetStateAction<string>>
  queue: SampleQueue | undefined
  queueItemId: string
  sampleName: string
  nameLength: 12 | 20
  setNameLength: React.Dispatch<React.SetStateAction<12 | 20>>
  setSampleName: React.Dispatch<React.SetStateAction<string>>
  sampleKind: 'standard' | 'normal' | 'test' | 'blank' | 'preheat'
  setSampleKind: React.Dispatch<React.SetStateAction<'standard' | 'normal' | 'test' | 'blank' | 'preheat'>>
  storageMode: 'averaged' | 'full_interval'
  setStorageMode: React.Dispatch<React.SetStateAction<'averaged' | 'full_interval'>>
  queueItem: SampleQueueItem | undefined
  displayedRepeatCount: number
  setRepeatCount: React.Dispatch<React.SetStateAction<number>>
}
export function SampleAcquisitionForm(props: SampleAcquisitionFormProps) {
  const {
    useMethodConditions,
    setUseMethodConditions,
    create,
    canWrite,
    busy,
    options,
    methodKey,
    setMethodKey,
    queueId,
    setQueueId,
    setQueueItemId,
    queue,
    queueItemId,
    sampleName,
    setSampleName,
    nameLength,
    setNameLength,
    sampleKind,
    setSampleKind,
    storageMode,
    setStorageMode,
    queueItem,
    displayedRepeatCount,
    setRepeatCount,
    useMethodIntervals,
    setUseMethodIntervals,
    managementSample,
    setManagementSample
  } = props
  const methodConditions = options?.methods.find((item) => `${item.method_id}:${item.method_version}` === methodKey)?.conditions
  const methodMode = sampleKind === 'preheat' ? null : methodConditions?.exposure_mode
    ?? (methodConditions?.legacy_exposure_mode ? 'line_interval' : null)
  const methodStorage = sampleKind === 'preheat' ? null : methodMode === 'line_interval' ? 'full_interval'
    : useMethodIntervals && methodConditions
      ? (methodConditions.angle_exposures.some((angle) => angle.storage_mode === 'full_interval') ? 'full_interval' : 'averaged')
      : methodMode ? 'averaged' : null
  return (
    <section className="surface acquisition-create">
      <div className="surface-heading">
        <div>
          <h2>建立样品摄谱任务</h2>
        </div>
        <Flame size={17} />
      </div>
      <form className="acquisition-form" onSubmit={create}>
        <>
            <label className="field">
              <span>已发布方法版本</span>
              <select
                value={methodKey}
                onChange={(e) => setMethodKey(e.target.value)}
                disabled={!canWrite || busy || !options?.methods.length}
                required
              >
                <option value="">{options?.methods.length ? '请选择方法版本' : '暂无已发布方法版本'}</option>
                {options?.methods.map((item) => (
                  <option
                    value={`${item.method_id}:${item.method_version}`}
                    key={`${item.method_id}:${item.method_version}`}
                  >
                    {item.name} · v{item.method_version}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              <span>样品队列</span>
              <select
                value={queueId}
                onChange={(e) => {
                  setQueueId(e.target.value)
                  setQueueItemId('')
                }}
                disabled={!canWrite || busy}
              >
                <option value="">临时样号</option>
                {options?.queues.map((item) => (
                  <option value={item.id} key={item.id}>
                    {item.name}
                  </option>
                ))}
              </select>
            </label>
            {queue && (
              <label className="field">
                <span>预录样品</span>
                <select
                  value={queueItemId}
                  onChange={(e) => setQueueItemId(e.target.value)}
                  disabled={!canWrite || busy}
                >
                  <option value="">请选择队列项</option>
                  {queue.items
                    .filter((item) => !item.spectrum_hash)
                    .map((item) => (
                      <option value={item.id} key={item.id}>
                        {item.pre_name || '空样'} · {item.repeats || 1} 次
                      </option>
                    ))}
                </select>
              </label>
            )}
            {!queueId && (
              <>
                <label className="field">
                  <span>临时样号</span>
                  <input
                    value={sampleName}
                    onChange={(e) => setSampleName(e.target.value)}
                    placeholder="采集后也可命名"
                    disabled={!canWrite || busy}
                  />
                </label>
                <label className="field">
                  <span>样品类型</span>
                  <select
                    value={sampleKind}
                    onChange={(e) => setSampleKind(e.target.value as typeof sampleKind)}
                    disabled={!canWrite || busy}
                  >
                    <option value="test">试样</option>
                    <option value="normal">普通样</option>
                    <option value="standard">标准样</option>
                    <option value="blank">空样</option>
                    <option value="preheat">预热</option>
                  </select>
                </label>
              </>
            )}
        </>
        <label className="field">
          <span>重复次数{queueItem ? '（来自队列）' : ''}</span>
          <NumericInput
            min={1}
            max={10}
            value={displayedRepeatCount}
            onValueChange={setRepeatCount}
            disabled={!canWrite || busy || Boolean(queueItem)}
          />
        </label>
        <button
          className="primary-button acquisition-create-button"
          type="submit"
          disabled={
            !canWrite || busy || !methodKey || (Boolean(queueId) && !queueItemId)
          }
        >
          <TestTube2 size={15} />
          创建任务
        </button>
        {sampleKind !== 'preheat' && (
          <>
            <label className="field">
              <span>存储设置来源</span>
              <select
                value={useMethodIntervals ? 'method' : 'custom'}
                disabled={!canWrite || busy}
                onChange={(event) => setUseMethodIntervals(event.target.value === 'method')}
              >
                <option value="custom">任务保存设置</option>
                <option value="method">方法逐转角设置</option>
              </select>
            </label>
            <div className="field">
              <span>管理样</span>
              <label className="checkbox-row">
                <input
                  type="checkbox"
                  style={{ width: 16, height: 16, minHeight: 0, flex: '0 0 auto' }}
                  aria-label="管理样"
                  aria-describedby="acquisition-management-help"
                  checked={managementSample}
                  disabled={!canWrite || busy || Boolean(queue)}
                  onChange={(event) => {
                    setManagementSample(event.target.checked)
                    if (event.target.checked) setSampleKind('test')
                  }}
                />
                <span>用于曲线适配</span>
              </label>
            </div>
          </>
        )}
        <label className="field">
          <span>样号长度</span>
          <select
            value={nameLength}
            onChange={(e) => setNameLength(Number(e.target.value) as 12 | 20)}
            disabled={!canWrite || busy || Boolean(queue)}
          >
            <option value={12}>12 位</option>
            <option value={20}>20 位</option>
          </select>
        </label>
        <AcquisitionSetupFields {...props} />
        <label className="field">
            <span>保存模式</span>
            <select
              value={methodStorage ?? storageMode}
              onChange={(e) => setStorageMode(e.target.value as typeof storageMode)}
              disabled={!canWrite || busy || Boolean(methodStorage)}
            >
              <option value="averaged">平均值 float32</option>
              <option value="full_interval">全时原始区间</option>
            </select>
            {methodStorage && <small>{useMethodIntervals && methodMode !== 'line_interval'
              ? '由已发布方法的高级分角度存储设置决定' : '由已发布方法的“区间曝光”开关决定'}</small>}
        </label>
        <AcquisitionTimingFields {...props} conditionsLocked={sampleKind !== 'preheat' && useMethodConditions}
          advancedFields={sampleKind !== 'preheat' ? (
            <label className="field">
              <span>激发参数与默认次数</span>
              <select value={useMethodConditions ? 'method' : 'custom'} disabled={!canWrite || busy}
                onChange={(event) => setUseMethodConditions(event.target.value === 'method')}>
                <option value="method">按已发布方法条件</option>
                <option value="custom">手动设置（队列次数优先）</option>
              </select>
            </label>
          ) : null} />



        <p id="acquisition-management-help" className="acquisition-management-note">
            管理样：采集、分析并完成质控后，可在标准点页输入给定含量适配曲线。
        </p>
      </form>
    </section>
  )
}
