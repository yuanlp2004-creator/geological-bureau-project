const powers = new Map<string, number>([['ug/g', 0], ['mg/g', 3], ['%', 4]])
export const analysisUnits = Array.from(powers.keys())
export const unitScale = (unit: string) => 10 ** (powers.get(unit) ?? 0)
export const decimalLimit = (unit: string) => 6 + (powers.get(unit) ?? 0)

export function convertUnitValue(value: number, source: string, target: string) {
  // 保留输入的有效数字，避免 0.1 等十进制数的二进制尾数进入编辑器。
  return Number((value * unitScale(source) / unitScale(target)).toPrecision(15))
}

export function convertLineUnit<T extends {
  unit: string; decimal_places: number; valid_range_min: number; valid_range_max: number
  standard_points: { value: number }[]
}>(line: T, unit: string): T {
  if (!powers.has(line.unit) || !powers.has(unit) || line.unit === unit) return { ...line, unit }
  const convert = (value: number) => convertUnitValue(value, line.unit, unit)
  return { ...line, unit,
    decimal_places: Math.max(0, Math.min(decimalLimit(unit), line.decimal_places + powers.get(unit)! - powers.get(line.unit)!)),
    valid_range_min: convert(line.valid_range_min), valid_range_max: convert(line.valid_range_max),
    standard_points: line.standard_points.map((point) => ({ ...point, value: convert(point.value) })) }
}

export function formatAnalysisValue(value: number, digits = 6) {
  const places = Math.max(0, Math.min(10, digits))
  const text = value.toLocaleString('en-US', { minimumFractionDigits: places, maximumFractionDigits: places, useGrouping: false })
  return value !== 0 && Number(text) === 0 ? value.toExponential(5) : text
}
