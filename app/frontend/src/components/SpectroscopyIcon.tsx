const icons = {
  crosshair: new URL('../assets/spectroscopy/crosshair.png', import.meta.url).href,
  'box-zoom': new URL('../assets/spectroscopy/box-zoom.png', import.meta.url).href,
  pan: new URL('../assets/spectroscopy/pan.png', import.meta.url).href,
  fit: new URL('../assets/spectroscopy/fit.png', import.meta.url).href,
  'zoom-x-in': new URL('../assets/spectroscopy/zoom-x-in.png', import.meta.url).href,
  'zoom-x-out': new URL('../assets/spectroscopy/zoom-x-out.png', import.meta.url).href,
  'zoom-y-in': new URL('../assets/spectroscopy/zoom-y-in.png', import.meta.url).href,
  'zoom-y-out': new URL('../assets/spectroscopy/zoom-y-out.png', import.meta.url).href,
  lock: new URL('../assets/spectroscopy/lock.png', import.meta.url).href,
  capture: new URL('../assets/spectroscopy/capture.png', import.meta.url).href,
  preheat: new URL('../assets/spectroscopy/preheat.png', import.meta.url).href,
  stop: new URL('../assets/spectroscopy/stop.png', import.meta.url).href
}

export type SpectroscopyIconName = keyof typeof icons

export function SpectroscopyIcon({ name }: { name: SpectroscopyIconName }) {
  return <img className="spectroscopy-action-icon" data-spectroscopy-icon={name} src={icons[name]}
    width={20} height={20} alt="" aria-hidden="true" draggable={false} />
}
