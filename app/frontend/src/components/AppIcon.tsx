const iconUrl = new URL('../assets/brand/geospectrum.png', import.meta.url).href

export function AppIcon({ className = '', size = 32 }: { className?: string; size?: number }) {
  return <img className={`app-icon ${className}`} src={iconUrl} width={size} height={size} alt="" aria-hidden="true" draggable={false} />
}
