import {
  SlidersHorizontal
} from 'lucide-react'
import { SpectroscopyIcon } from '../../components/SpectroscopyIcon'
import {
  type DispersionCalibrationVersion,
  type DispersionTask,
  type MethodRecord
} from '../../api'

// 父页面统一持有草稿、选中项和请求状态。
type PanelProps = {
  calibrationName: string
  setCalibrationName: React.Dispatch<React.SetStateAction<string>>
  fit: () => Promise<DispersionTask | undefined> | undefined
  canWrite: boolean
  active: DispersionTask
  latestCalibration: DispersionCalibrationVersion | null
  publish: (calibration: DispersionCalibrationVersion) => Promise<DispersionTask | undefined> | undefined
  bindMethodId: number | null
  setBindMethodId: React.Dispatch<React.SetStateAction<number | null>>
  methods: MethodRecord[]
  bind: () => Promise<DispersionTask | undefined> | undefined
}

export function DispersionCalibration({
  calibrationName,
  setCalibrationName,
  fit,
  canWrite,
  active,
  latestCalibration,
  publish,
  bindMethodId,
  setBindMethodId,
  methods,
  bind,
}: PanelProps) {
  return (
    <section className="surface dispersion-fit-panel">
      <div className="surface-heading">
        <div>
          <h2>拟合、发布与方法绑定</h2>
        </div>
        <SlidersHorizontal size={17} />
      </div>
      <div className="dispersion-fit-form">
        <label className="field">
          <span>曲线名称</span>
          <input value={calibrationName} onChange={(event) => setCalibrationName(event.target.value)} />
        </label>
        <button
          className="primary-button"
          onClick={() => void fit()}
          disabled={
            !canWrite ||
            active.lines.filter((line) => line.saved_position !== null || line.located_position !== null)
              .length < 3
          }
        >
          <SpectroscopyIcon name="fit-curve" />二次拟合
        </button>
        {latestCalibration?.state === 'draft' && (
          <button
            className="secondary-button"
            onClick={() => void publish(latestCalibration)}
            disabled={!canWrite || !latestCalibration.publishable}
          >
            发布版本
          </button>
        )}
      </div>
      {latestCalibration ? (
        <div className="calibration-result">
          <div>
            <span>版本</span>
            <strong title={`${latestCalibration.name} · v${latestCalibration.version}`}>
              {latestCalibration.name} · v{latestCalibration.version}
            </strong>
            <small>{latestCalibration.state}</small>
          </div>
          <div>
            <span>有效波段</span>
            <strong>
              {latestCalibration.wavelength_min.toFixed(4)}–{latestCalibration.wavelength_max.toFixed(4)} nm
            </strong>
            <small>{latestCalibration.point_count} 个定位点</small>
          </div>
          <div>
            <span>残差</span>
            <strong>RMS {latestCalibration.residual_rms.toFixed(4)}</strong>
            <small>
              最大 {latestCalibration.residual_max.toFixed(4)} / 允许值 {latestCalibration.residual_limit_points.toFixed(4)} 点
            </small>
          </div>
          <div>
            <span>系数</span>
            <code title={latestCalibration.coefficients.map((value) => value.toExponential(4)).join(' · ')}>
              {latestCalibration.coefficients.map((value) => value.toExponential(4)).join(' · ')}
            </code>
          </div>
        </div>
      ) : (
        <div className="dispersion-empty compact">
          <p>至少三个实测定位点即可拟合；“保存位置”仅供恢复。</p>
        </div>
      )}
      {latestCalibration?.state === 'draft' && !latestCalibration.publishable && (
        <p role="status" className="dispersion-fit-warning">
          {latestCalibration.inputs_current === false ? '实测位置或布局已改变，请重新拟合。'
            : '拟合误差达到或超过允许值，请检查定位点后重新拟合；当前不能发布。'}
        </p>
      )}
      {latestCalibration?.state === 'published' && (
        <div className="dispersion-bind">
          <label className="field">
            <span>绑定已发布方法版本</span>
            <select
              value={bindMethodId ?? ''}
              onChange={(event) => setBindMethodId(Number(event.target.value))}
            >
              {methods.map((method) => (
                <option value={method.id} key={method.id}>
                  {method.name} · v{method.current_version}
                </option>
              ))}
            </select>
          </label>
          <button
            className="primary-button"
            onClick={() => void bind()}
            disabled={!canWrite || bindMethodId === null}
          >
            绑定修订
          </button>
          <small>绑定记录独立保存，不原地修改方法版本。</small>
        </div>
      )}
    </section>
  )
}
