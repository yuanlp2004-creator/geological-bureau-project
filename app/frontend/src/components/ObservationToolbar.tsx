import type { ReactNode } from 'react'
import { SpectroscopyToolButton } from './SpectroscopyToolButton'
import { ZOOM_IN, ZOOM_OUT, type SpectrumAxis } from './spectrumZoom'
import './observation-toolbar.css'

type Props = {
  navigation?: ReactNode
  children?: ReactNode
  disabled?: boolean
  tool: 'crosshair' | 'box' | 'pan'
  setTool: (tool: 'crosshair' | 'box' | 'pan') => void
  fit: () => void
  scales?: ReactNode
  zoom: (axis: SpectrumAxis, factor: number) => void
  resetY: () => void
  print?: () => void
  printDisabledReason?: string
  showPan?: boolean
}

// FmView.dfm: 谱带、CCD、查看/框选/滚动、比例、横向、纵向、打印。
export function ObservationToolbar({ navigation, children, disabled, tool, setTool, fit, scales, zoom, resetY, print, printDisabledReason, showPan = true }: Props) {
  return <div className="legacy-observation-toolbar" role="toolbar" aria-label="图像查看工具">
    {navigation && <div className="observation-tool-group">{navigation}</div>}
    <div className="observation-tool-group">
      {([['crosshair', 'crosshair', '十字线'], ['box', 'box-zoom', '区域放大'], ['pan', 'pan', '滚动工具']] as const).filter(([value]) => showPan || value !== 'pan').map(([value, icon, label]) =>
        <SpectroscopyToolButton key={value} icon={icon} label={label} disabled={disabled} aria-pressed={tool === value} onClick={() => setTool(value)} />)}
    </div>
    <div className="observation-tool-group">
      <SpectroscopyToolButton icon="fit" label="适合图像" disabled={disabled} onClick={fit} />{scales}
      <SpectroscopyToolButton icon="zoom-x-in" label="横向放大" disabled={disabled} onClick={() => zoom('x', ZOOM_IN)} />
      <SpectroscopyToolButton icon="zoom-x-out" label="横向缩小" disabled={disabled} onClick={() => zoom('x', ZOOM_OUT)} />
    </div>
    <div className="observation-tool-group">
      <SpectroscopyToolButton icon="zoom-y-in" label="纵向放大" disabled={disabled} onClick={() => zoom('y', ZOOM_IN)} />
      <SpectroscopyToolButton icon="zoom-y-out" label="纵向缩小" disabled={disabled} onClick={() => zoom('y', ZOOM_OUT)} />
      <SpectroscopyToolButton icon="reset-y" label="纵向还原" disabled={disabled} onClick={resetY} />
    </div>
    {print && <SpectroscopyToolButton icon="print" label="打印谱图" description={printDisabledReason} disabled={disabled||Boolean(printDisabledReason)} onClick={print} />}
    {children}
  </div>
}
