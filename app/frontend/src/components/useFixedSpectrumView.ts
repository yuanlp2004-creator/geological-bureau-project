import { useRef, useState } from 'react'

export function useFixedSpectrumView() {
  const [enabled, setEnabled] = useState(true)
  const [showDetails, setShowDetails] = useState(false)
  const lastRange = useRef<{ scope: string; xMin: number; xMax: number } | null>(null)
  return { enabled, lastRange, toggle: () => setEnabled(value => !value), showDetails, setShowDetails }
}

export type FixedSpectrumView = ReturnType<typeof useFixedSpectrumView>
