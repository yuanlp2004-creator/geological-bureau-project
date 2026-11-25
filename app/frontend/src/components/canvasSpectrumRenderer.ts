export type PlotViewportRect = {
  left: number
  top: number
  width: number
  height: number
  viewWidth: number
  viewHeight: number
}

type Point = { x: number; y: number }
type XDatum = Pick<Point, 'x'>
type AspectRatio = 'none' | 'meet'
type CanvasTransformParams = {
  viewWidth: number
  viewHeight: number
  cssWidth: number
  cssHeight: number
  dpr: number
  preserveAspectRatio: AspectRatio
}
type InverseScreenMatrix = Pick<DOMMatrixReadOnly, 'a' | 'b' | 'c' | 'd' | 'e' | 'f'>

export function plotX(value: number, xStart: number, xEnd: number, rect: PlotViewportRect) {
  return rect.left + ((value - xStart) / (xEnd - xStart || 1)) * rect.width
}

export function plotY(value: number, yStart: number, yEnd: number, rect: PlotViewportRect) {
  return rect.top + rect.height - ((value - yStart) / (yEnd - yStart || 1)) * rect.height
}

export function dataX(viewX: number, xStart: number, xEnd: number, rect: PlotViewportRect) {
  return xStart + ((viewX - rect.left) / (rect.width || 1)) * (xEnd - xStart)
}

export function dataY(viewY: number, yStart: number, yEnd: number, rect: PlotViewportRect) {
  return yStart + ((rect.top + rect.height - viewY) / (rect.height || 1)) * (yEnd - yStart)
}

function fitViewBox(viewWidth: number, viewHeight: number, width: number, height: number, aspectRatio: AspectRatio) {
  const scaleX = width / (viewWidth || 1)
  const scaleY = height / (viewHeight || 1)
  if (aspectRatio === 'none') return { scaleX, scaleY, offsetX: 0, offsetY: 0 }

  const scale = Math.min(scaleX, scaleY)
  return {
    scaleX: scale,
    scaleY: scale,
    offsetX: (width - viewWidth * scale) / 2,
    offsetY: (height - viewHeight * scale) / 2
  }
}

export function computeCanvasTransform({ viewWidth, viewHeight, cssWidth, cssHeight, dpr, preserveAspectRatio }: CanvasTransformParams) {
  const backingWidth = Math.max(1, Math.round(cssWidth * dpr))
  const backingHeight = Math.max(1, Math.round(cssHeight * dpr))
  const cssFit = fitViewBox(viewWidth, viewHeight, cssWidth, cssHeight, preserveAspectRatio)
  // Fit in CSS pixels first so rounding the backing dimensions cannot move the SVG overlay.
  const backingScaleX = backingWidth / (cssWidth || 1)
  const backingScaleY = backingHeight / (cssHeight || 1)
  return {
    backingWidth,
    backingHeight,
    scaleX: cssFit.scaleX * backingScaleX,
    scaleY: cssFit.scaleY * backingScaleY,
    offsetX: cssFit.offsetX * backingScaleX,
    offsetY: cssFit.offsetY * backingScaleY
  }
}

export function clientToViewBoxPoint(
  clientX: number,
  clientY: number,
  rect: Pick<DOMRectReadOnly, 'left' | 'top' | 'width' | 'height'>,
  viewWidth: number,
  viewHeight: number,
  preserveAspectRatio: AspectRatio,
  ctmInverse?: InverseScreenMatrix | null
): Point {
  if (ctmInverse) {
    const { a, b, c, d, e, f } = ctmInverse
    return { x: a * clientX + c * clientY + e, y: b * clientX + d * clientY + f }
  }

  const { scaleX, scaleY, offsetX, offsetY } = fitViewBox(viewWidth, viewHeight, rect.width, rect.height, preserveAspectRatio)
  return {
    x: scaleX ? (clientX - rect.left - offsetX) / scaleX : 0,
    y: scaleY ? (clientY - rect.top - offsetY) / scaleY : 0
  }
}

export function decimateMinMaxBuckets<T extends Point>({ data, xStart, xEnd, pixelWidth }: {
  data: readonly T[]
  xStart: number
  xEnd: number
  pixelWidth: number
}) {
  const bucketCount = Math.max(1, Math.floor(pixelWidth))
  const span = xEnd - xStart || 1
  let visibleCount = 0
  let firstVisible = data.length
  let lastVisible = -1
  let leftIndex = -1
  let rightIndex = -1
  let ordered = true
  let previousX = -Infinity

  for (let index = 0; index < data.length; index++) {
    const { x } = data[index]
    if (x < previousX) ordered = false
    previousX = x
    if (x < xStart) {
      leftIndex = index
    } else if (x > xEnd) {
      if (rightIndex === -1) rightIndex = index
    } else {
      if (visibleCount === 0) firstVisible = index
      lastVisible = index
      visibleCount++
    }
  }

  const indices: number[] = []
  if (leftIndex !== -1) indices.push(leftIndex)
  const decimated = visibleCount > Math.max(2, bucketCount) * 2
  if (decimated) {
    const buckets: Array<{ minIndex: number; maxIndex: number } | undefined> = new Array(bucketCount)
    for (let index = firstVisible; index <= lastVisible; index++) {
      const { x, y } = data[index]
      if (x < xStart || x > xEnd) continue
      const bucketIndex = Math.min(bucketCount - 1, Math.floor(((x - xStart) / span) * bucketCount))
      const bucket = buckets[bucketIndex]
      if (!bucket) {
        buckets[bucketIndex] = { minIndex: index, maxIndex: index }
      } else {
        if (y < data[bucket.minIndex].y) bucket.minIndex = index
        if (y > data[bucket.maxIndex].y) bucket.maxIndex = index
      }
    }

    // Keep both endpoints of each segment that crosses a viewport edge.
    if (leftIndex !== -1) indices.push(firstVisible)
    for (const bucket of buckets) {
      if (!bucket) continue
      const { minIndex, maxIndex } = bucket
      indices.push(Math.min(minIndex, maxIndex))
      if (minIndex !== maxIndex) indices.push(Math.max(minIndex, maxIndex))
    }
    if (rightIndex !== -1) indices.push(lastVisible)
  } else {
    for (let index = firstVisible; index <= lastVisible; index++) {
      const { x } = data[index]
      if (x >= xStart && x <= xEnd) indices.push(index)
    }
  }
  if (rightIndex !== -1) indices.push(rightIndex)

  if (!ordered) indices.sort((a, b) => a - b)
  const points: T[] = []
  for (let i = 0; i < indices.length; i++) {
    if (indices[i] !== indices[i - 1]) points.push(data[indices[i]])
  }
  return {
    points,
    decimated,
    singlePoint: data.length === 1,
    leftAnchor: data[leftIndex],
    rightAnchor: data[rightIndex]
  }
}

function isLocallyUnsorted(data: readonly XDatum[], index: number) {
  const { x } = data[index]
  return (index > 0 && data[index - 1].x > x) || (index + 1 < data.length && data[index + 1].x < x)
}

function scanNearest<T extends XDatum>(data: readonly T[], targetX: number) {
  let datumIndex = 0
  for (let index = 1; index < data.length; index++) {
    if (Math.abs(data[index].x - targetX) < Math.abs(data[datumIndex].x - targetX)) datumIndex = index
  }
  return { datumIndex, datum: data[datumIndex] }
}

/** Finds the first closest datum in a series ordered by nondecreasing x. */
export function findNearestDatumIndex<T extends XDatum>(data: readonly T[], targetX: number) {
  if (!data.length) return null
  if (data[0].x > data[data.length - 1].x) return scanNearest(data, targetX)

  let low = 0
  let high = data.length
  while (low < high) {
    const mid = low + Math.floor((high - low) / 2)
    if (isLocallyUnsorted(data, mid)) return scanNearest(data, targetX)
    if (data[mid].x < targetX) low = mid + 1
    else high = mid
  }

  const right = low
  if (right === 0) return { datumIndex: 0, datum: data[0] }
  const leftDistance = Math.abs(data[right - 1].x - targetX)
  if (right < data.length && Math.abs(data[right].x - targetX) < leftDistance) {
    return { datumIndex: right, datum: data[right] }
  }

  // The left candidate is the last of any equal-distance run. Find its first index.
  low = 0
  high = right - 1
  while (low < high) {
    const mid = low + Math.floor((high - low) / 2)
    if (isLocallyUnsorted(data, mid)) return scanNearest(data, targetX)
    if (Math.abs(data[mid].x - targetX) > leftDistance) low = mid + 1
    else high = mid
  }
  return { datumIndex: low, datum: data[low] }
}

type ReadCssVar = (token: string) => string | null | undefined

export function resolveCssColor(colorExpr: string, readVar: ReadCssVar | undefined, fallback: string): string {
  const active = new Set<string>()

  function resolve(expression: string): string | undefined {
    const color = expression.trim()
    if (!color.startsWith('var(')) return color || undefined
    const match = /^var\(\s*(--[^\s,()]+)\s*(?:,([\s\S]*))?\)$/.exec(color)
    if (!match) return undefined
    const [, token, nestedFallback] = match
    if (!active.has(token)) {
      const value = readVar?.(token)
      if (value) {
        active.add(token)
        const resolved = resolve(value)
        active.delete(token)
        if (resolved) return resolved
      }
    }
    return nestedFallback === undefined ? undefined : resolve(nestedFallback)
  }

  return resolve(colorExpr) ?? fallback
}

type CanvasContext = Pick<CanvasRenderingContext2D,
  'save' | 'restore' | 'setTransform' | 'clearRect' | 'fillRect' | 'beginPath' | 'rect' | 'clip' |
  'setLineDash' | 'strokeStyle' | 'fillStyle' | 'lineWidth' | 'globalAlpha' | 'moveTo' | 'lineTo' |
  'stroke' | 'arc' | 'fill' | 'filter'> & { canvas: { width: number; height: number } }

export type SpectrumCanvasOptions = Omit<CanvasTransformParams, 'viewWidth' | 'viewHeight'> & {
  rect: PlotViewportRect
  curveViewport?: { rect: PlotViewportRect; clampTop: boolean }
  xStart: number
  xEnd: number
  yStart: number
  yEnd: number
  curves: readonly { data: readonly Point[]; color: string; priority: boolean }[]
  xTicks?: readonly number[]
  yTicks?: readonly number[]
  gridInViewBox?: boolean
  backgroundColor?: string
  gridColor?: string
  gridLineDash?: readonly number[]
  gridLineWidth?: number
  lineWidth?: number
  lineOpacity?: number
  priorityColor?: string
  priorityLineWidth?: number
  curveBrightness?: number
  priorityBrightness?: number
  readVar?: ReadCssVar
}

/** The host sets the CSS size. This renderer sizes and clears the backing canvas. */
export function renderSpectrumCanvas(ctx: CanvasContext, options: SpectrumCanvasOptions): void {
  const {
    rect, curveViewport, xStart, xEnd, yStart, yEnd, curves, readVar, cssWidth, dpr,
    xTicks = [], yTicks = [], gridInViewBox = false, backgroundColor, gridColor = '#e6ebf2', gridLineDash = [], gridLineWidth = 1,
    lineWidth = 1.15, lineOpacity = 0.72, priorityLineWidth = 2.1, priorityColor = 'var(--plot-priority-color)',
    curveBrightness = 1, priorityBrightness = curveBrightness
  } = options
  const { backingWidth, backingHeight, scaleX, scaleY, offsetX, offsetY } = computeCanvasTransform({
    ...options, viewWidth: rect.viewWidth, viewHeight: rect.viewHeight
  })
  if (ctx.canvas.width !== backingWidth) ctx.canvas.width = backingWidth
  if (ctx.canvas.height !== backingHeight) ctx.canvas.height = backingHeight

  ctx.save()
  try {
    ctx.setTransform(1, 0, 0, 1, 0, 0)
    ctx.clearRect(0, 0, backingWidth, backingHeight)
    if (scaleX <= 0 || scaleY <= 0 || rect.width <= 0 || rect.height <= 0) return

    // Map positions to the backing canvas while keeping strokes and circles isotropic.
    const left = rect.left * scaleX + offsetX
    const top = rect.top * scaleY + offsetY
    const width = rect.width * scaleX
    const height = rect.height * scaleY
    ctx.beginPath()
    ctx.rect(left, top, width, height)
    ctx.clip()
    ctx.globalAlpha = 1
    ctx.filter = 'none'
    if (backgroundColor) {
      ctx.fillStyle = resolveCssColor(backgroundColor, readVar, '#fbfcfe')
      ctx.fillRect(left, top, width, height)
    }

    const viewX = (value: number) => value * scaleX + offsetX
    const viewY = (value: number) => value * scaleY + offsetY
    if (xTicks.length || yTicks.length) {
      ctx.beginPath()
      ctx.strokeStyle = resolveCssColor(gridColor, readVar, '#e6ebf2')
      ctx.lineWidth = gridLineWidth * dpr
      ctx.setLineDash(gridLineDash.map(length => length * dpr))
      for (const tick of xTicks) {
        const x = viewX(gridInViewBox ? tick : plotX(tick, xStart, xEnd, rect))
        ctx.moveTo(x, top)
        ctx.lineTo(x, top + height)
      }
      for (const tick of yTicks) {
        const y = viewY(gridInViewBox ? tick : plotY(tick, yStart, yEnd, rect))
        ctx.moveTo(left, y)
        ctx.lineTo(left + width, y)
      }
      ctx.stroke()
    }

    ctx.setLineDash([])
    // Use the on-screen plot width so higher DPR only increases raster resolution.
    const pixelWidth = width * (cssWidth / backingWidth)
    const curveRect = curveViewport?.rect ?? rect
    const toX = (value: number) => viewX(plotX(value, xStart, xEnd, curveRect))
    const toY = (value: number) => {
      const y = plotY(value, yStart, yEnd, curveRect)
      return viewY(curveViewport?.clampTop ? Math.max(curveRect.top, y) : y)
    }
    // An inset curve viewport can still have visible segments outside its data bounds.
    const visibleStart = curveViewport ? dataX(rect.left, xStart, xEnd, curveRect) : xStart
    const visibleEnd = curveViewport ? dataX(rect.left + rect.width, xStart, xEnd, curveRect) : xEnd
    for (const curve of [...curves].sort((a, b) => Number(a.priority) - Number(b.priority))) {
      const { data, priority } = curve
      if (!data.length) continue
      const color = resolveCssColor(curve.color, readVar, '#1570a6')
      const stroke = priority ? resolveCssColor(priorityColor, readVar, color) : color
      if (data.length === 1) {
        ctx.beginPath()
        ctx.globalAlpha = 1
        ctx.filter = 'none'
        ctx.fillStyle = stroke
        ctx.arc(toX(data[0].x), toY(data[0].y), 4 * dpr, 0, 2 * Math.PI)
        ctx.fill()
        continue
      }

      const { points } = decimateMinMaxBuckets({ data, xStart: visibleStart, xEnd: visibleEnd, pixelWidth })
      if (points.length < 2) continue
      ctx.beginPath()
      ctx.globalAlpha = priority ? 1 : lineOpacity
      const brightness = priority ? priorityBrightness : curveBrightness
      ctx.filter = brightness === 1 ? 'none' : `brightness(${brightness})`
      ctx.strokeStyle = stroke
      ctx.lineWidth = (priority ? priorityLineWidth : lineWidth) * dpr
      ctx.moveTo(toX(points[0].x), toY(points[0].y))
      for (let i = 1; i < points.length; i++) ctx.lineTo(toX(points[i].x), toY(points[i].y))
      ctx.stroke()
    }
  } finally {
    ctx.restore()
  }
}

export function observeCanvasEnvironment(onChange: () => void, hostElement?: Element): () => void {
  if (typeof window === 'undefined' || typeof document === 'undefined') return () => {}

  let disposed = false
  const observer = typeof window.MutationObserver === 'function'
    ? new window.MutationObserver(() => { if (!disposed) onChange() })
    : undefined
  const attributes = { attributeFilter: ['data-theme', 'class', 'style'] }
  observer?.observe(document.documentElement, attributes)
  for (let element = hostElement; element && element !== document.documentElement; element = element.parentElement ?? undefined) {
    observer?.observe(element, attributes)
  }

  let media: MediaQueryList | undefined
  function watchDpr() {
    media?.removeEventListener('change', onDprChange)
    media = window.matchMedia(`(resolution: ${window.devicePixelRatio || 1}dppx)`)
    media.addEventListener('change', onDprChange)
  }
  function onDprChange() {
    if (disposed) return
    watchDpr()
    onChange()
  }
  if (typeof window.matchMedia === 'function') watchDpr()

  return () => {
    if (disposed) return
    disposed = true
    observer?.disconnect()
    media?.removeEventListener('change', onDprChange)
  }
}
