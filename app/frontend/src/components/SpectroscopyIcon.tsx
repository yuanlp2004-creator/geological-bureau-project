import type { CSSProperties } from 'react'

const icons = {
  'previous-band': new URL('../assets/spectroscopy/previous-band.png', import.meta.url).href,
  'next-band': new URL('../assets/spectroscopy/next-band.png', import.meta.url).href,
  'previous-ccd': new URL('../assets/spectroscopy/previous-ccd.png', import.meta.url).href,
  'next-ccd': new URL('../assets/spectroscopy/next-ccd.png', import.meta.url).href,
  'select-ccd': new URL('../assets/spectroscopy/select-ccd.png', import.meta.url).href,
  'crosshair': new URL('../assets/spectroscopy/crosshair.png', import.meta.url).href,
  'box-zoom': new URL('../assets/spectroscopy/box-zoom.png', import.meta.url).href,
  'pan': new URL('../assets/spectroscopy/pan.png', import.meta.url).href,
  'fit': new URL('../assets/spectroscopy/fit.png', import.meta.url).href,
  'scale-1': new URL('../assets/spectroscopy/scale-1.png', import.meta.url).href,
  'scale-4': new URL('../assets/spectroscopy/scale-4.png', import.meta.url).href,
  'scale-10': new URL('../assets/spectroscopy/scale-10.png', import.meta.url).href,
  'zoom-x-in': new URL('../assets/spectroscopy/zoom-x-in.png', import.meta.url).href,
  'zoom-x-out': new URL('../assets/spectroscopy/zoom-x-out.png', import.meta.url).href,
  'zoom-y-in': new URL('../assets/spectroscopy/zoom-y-in.png', import.meta.url).href,
  'zoom-y-out': new URL('../assets/spectroscopy/zoom-y-out.png', import.meta.url).href,
  'reset-y': new URL('../assets/spectroscopy/reset-y.png', import.meta.url).href,
  'print': new URL('../assets/spectroscopy/print.png', import.meta.url).href,
  'add-line': new URL('../assets/spectroscopy/add-line.png', import.meta.url).href,
  'delete-line': new URL('../assets/spectroscopy/delete-line.png', import.meta.url).href,
  'sample-input': new URL('../assets/spectroscopy/sample-input.png', import.meta.url).href,
  'reference-correction': new URL('../assets/spectroscopy/reference-correction.png', import.meta.url).href,
  'line-correction': new URL('../assets/spectroscopy/line-correction.png', import.meta.url).href,
  'fit-curve': new URL('../assets/spectroscopy/fit-curve.png', import.meta.url).href,
  'measure': new URL('../assets/spectroscopy/measure.png', import.meta.url).href,
  'pause': new URL('../assets/spectroscopy/pause.png', import.meta.url).href,
  'close': new URL('../assets/spectroscopy/close.png', import.meta.url).href,
  'capture': new URL('../assets/spectroscopy/capture.png', import.meta.url).href,
  'preheat': new URL('../assets/spectroscopy/preheat.png', import.meta.url).href,
  'stop': new URL('../assets/spectroscopy/stop.png', import.meta.url).href,
  'finish': new URL('../assets/spectroscopy/finish.png', import.meta.url).href,
  'input-samples': new URL('../assets/spectroscopy/input-samples.png', import.meta.url).href,
  'insert-sample': new URL('../assets/spectroscopy/insert-sample.png', import.meta.url).href,
  'clear-samples': new URL('../assets/spectroscopy/clear-samples.png', import.meta.url).href,
  'sample-list-input': new URL('../assets/spectroscopy/sample-list-input.png', import.meta.url).href,
  'sample-list-clear': new URL('../assets/spectroscopy/sample-list-clear.png', import.meta.url).href,
  'multi-view': new URL('../assets/spectroscopy/multi-view.png', import.meta.url).href,
  'record-lock': new URL('../assets/spectroscopy/record-lock.png', import.meta.url).href,
  'record-unlock': new URL('../assets/spectroscopy/record-unlock.png', import.meta.url).href,
  'lock': new URL('../assets/spectroscopy/lock.png', import.meta.url).href,
}

export type SpectroscopyIconName = keyof typeof icons

export function SpectroscopyIcon({ name, style }: { name: SpectroscopyIconName; style?: CSSProperties }) {
  return <img className="spectroscopy-action-icon" data-spectroscopy-icon={name} src={icons[name]} style={style}
    width={20} height={20} alt="" aria-hidden="true" draggable={false} />
}
