type Props = {
  xMin: number
  xMax: number
  yMin: number
  yMax: number
  xLabel: string
  yLabel: string
  fractionalY?: boolean
  fractionalX?: boolean
  logarithmicX?: boolean
  logarithmicY?: boolean
}

const NICE_FACTORS = [1, 2, 2.5, 5, 10]

function niceIntegerStep(span: number, targetIntervals = 5): number {
  const rough = Math.max(1, Math.abs(span) / targetIntervals)
  const magnitude = 10 ** Math.floor(Math.log10(rough))
  const normalized = rough / magnitude
  const factor = NICE_FACTORS.reduce((best, candidate) =>
    Math.abs(candidate - normalized) < Math.abs(best - normalized) ? candidate : best
  )
  return Math.max(1, Math.round(factor * magnitude))
}

export function integerAxisTicks(minimum: number, maximum: number, targetIntervals = 5): number[] {
  if (!Number.isFinite(minimum) || !Number.isFinite(maximum)) return [0, 1]
  const low = Math.min(minimum, maximum)
  const high = Math.max(minimum, maximum)
  if (low === high) return Number.isInteger(low) ? [low] : []
  const step = niceIntegerStep(high - low, targetIntervals)
  const first = Math.ceil(low / step) * step
  const last = Math.floor(high / step) * step
  const ticks: number[] = []
  for (let value = first; value <= last && ticks.length < 12; value += step) ticks.push(Math.round(value))
  if (ticks.length >= 2) return ticks
  const fallback = Array.from(new Set([Math.ceil(low), Math.floor(high)])).filter(
    (value) => value >= low && value <= high
  )
  return fallback
}

export function formatIntegerTick(value: number): string {
  return Math.round(value).toLocaleString('zh-CN')
}

function fractionalTicks(low: number, high: number): number[] {
  const span = high - low
  if (!Number.isFinite(span) || span <= 0) return [low]
  const magnitude = 10 ** Math.floor(Math.log10(span / 5))
  const step = (NICE_FACTORS.find((factor) => factor * magnitude >= span / 5) ?? 10) * magnitude
  const ticks: number[] = []
  for (let index = Math.ceil(low / step); index * step <= high + step * 1e-9 && ticks.length < 12; index++) {
    ticks.push(Number((index * step).toPrecision(12)))
  }
  return ticks
}

function formatFractionalTick(value: number): string {
  if (value !== 0 && Math.abs(value) < 1e-6) return value.toExponential(2)
  return value.toLocaleString('zh-CN', { maximumFractionDigits: 10 })
}

function formatLogTick(value: number): string {
  const raw=Math.exp(value)
  if(raw<1e-3 || raw>=1e5)return raw.toExponential(2)
  return raw.toLocaleString('zh-CN',{maximumSignificantDigits:4})
}

export function SimpleChartAxes({ xMin, xMax, yMin, yMax, xLabel, yLabel, fractionalY = false,
  fractionalX = false, logarithmicX = false, logarithmicY = false }: Props) {
  const xSpan = xMax - xMin || 1
  const ySpan = yMax - yMin || 1
  const xTicks = fractionalX || logarithmicX ? fractionalTicks(xMin, xMax) : integerAxisTicks(xMin, xMax)
  const yTicks = fractionalY || logarithmicY ? fractionalTicks(yMin, yMax) : integerAxisTicks(yMin, yMax)

  return (
    <div className="simple-chart-axes" aria-label={`横轴 ${xLabel}，纵轴 ${yLabel}`}>
      <div className="simple-axis-border" />
      <span className="simple-axis-title simple-axis-y-title">{yLabel}</span>
      <span className="simple-axis-title simple-axis-x-title">{xLabel}</span>
      <div className="simple-axis-x-scale">
        {xTicks.map((value) => {
          const position = (value - xMin) / xSpan
          return (
            <span
              className="simple-axis-tick simple-axis-x-tick"
              key={`x-${value}`}
              style={{ left: `${position * 100}%` }}
            >
              <i />
              {logarithmicX ? formatLogTick(value) : fractionalX ? formatFractionalTick(value) : formatIntegerTick(value)}
            </span>
          )
        })}
      </div>
      <div className="simple-axis-y-scale">
        {yTicks.map((value) => {
          const position = (value - yMin) / ySpan
          return (
            <span
              className="simple-axis-tick simple-axis-y-tick"
              key={`y-${value}`}
              style={{ bottom: `${position * 100}%` }}
            >
              <i />
              {logarithmicY ? formatLogTick(value) : fractionalY ? formatFractionalTick(value) : formatIntegerTick(value)}
            </span>
          )
        })}
      </div>
    </div>
  )
}
