const analysis_spectrum = new URL('../../assets/help/analysis-spectrum.png', import.meta.url).href
const dispersion_points = new URL('../../assets/help/dispersion-points.png', import.meta.url).href
const method_parameters = new URL('../../assets/help/method-parameters.png', import.meta.url).href
const sample_numbers = new URL('../../assets/help/sample-numbers.png', import.meta.url).href
const spectral_lines = new URL('../../assets/help/spectral-lines.png', import.meta.url).href
const standard_curve = new URL('../../assets/help/standard-curve.png', import.meta.url).href

export const helpIllustrations: Record<string, { src: string; width: number; height: number }> = {
  'analysis-spectrum': { src: analysis_spectrum, width: 922, height: 371 },
  'dispersion-points': { src: dispersion_points, width: 840, height: 450 },
  'method-parameters': { src: method_parameters, width: 561, height: 370 },
  'sample-numbers': { src: sample_numbers, width: 1120, height: 456 },
  'spectral-lines': { src: spectral_lines, width: 816, height: 154 },
  'standard-curve': { src: standard_curve, width: 642, height: 463 },
}
