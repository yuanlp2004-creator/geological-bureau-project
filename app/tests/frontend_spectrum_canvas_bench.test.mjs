import assert from 'node:assert/strict'
import test from 'node:test'
import {
  clientToViewBoxPoint, computeCanvasTransform, dataX, dataY, decimateMinMaxBuckets,
  findNearestDatumIndex, observeCanvasEnvironment, plotX, plotY, renderSpectrumCanvas, resolveCssColor
} from '../frontend/src/components/canvasSpectrumRenderer.ts'

const standardRect = { left: 54, top: 42, width: 872, height: 288, viewWidth: 960, viewHeight: 380 }

function closeTo(actual, expected) {
  assert.ok(Math.abs(actual - expected) < 1e-9, `${actual} should equal ${expected}`)
}

test('data and viewBox coordinates round-trip for the standard plot and a stretched plot', () => {
  for (const rect of [standardRect, { ...standardRect, top: 18, width: 1185.5, height: 244.25, viewWidth: 1273.5, viewHeight: 312.25 }]) {
    const x = 234.125
    const y = 1024.25
    closeTo(plotX(x, 200, 400, rect), rect.left + rect.width * 0.170625)
    closeTo(plotY(y, 0, 4097, rect), rect.top + rect.height * 0.75)
    closeTo(dataX(plotX(x, 200, 400, rect), 200, 400, rect), x)
    closeTo(dataY(plotY(y, 0, 4097, rect), 0, 4097, rect), y)
    assert.equal(plotX(5, 5, 5, rect), rect.left)
    assert.equal(plotY(5, 5, 5, rect), rect.top + rect.height)
    assert.equal(dataX(rect.left + rect.width, 5, 5, rect), 5)
    assert.equal(dataY(rect.top, 5, 5, rect), 5)
  }
})

test('alignment maps 1-based points to 0..512 in a 513×128 viewBox', () => {
  const rect = { left: 0, top: 1, width: 512, height: 126, viewWidth: 513, viewHeight: 128 }
  assert.equal(plotX(1, 1, 513, rect), 0)
  assert.equal(plotX(513, 1, 513, rect), 512)
  assert.equal(dataX(256, 1, 513, rect), 257)
  assert.equal(plotY(0, 0, 1000, rect), 127)
  assert.equal(plotY(1000, 0, 1000, rect), 1)
  const view = clientToViewBoxPoint(522, 113, { left: 10, top: 17, width: 1026, height: 192 }, 513, 128, 'none')
  assert.deepEqual(view, { x: 256, y: 64 })
  assert.equal(dataX(view.x, 1, 513, rect), 257)
  assert.equal(dataY(view.y, 0, 1000, rect), 500)
})

test('Canvas DPR transforms and client inverses align with none, meet and an SVG inverse CTM', () => {
  const view = { viewWidth: 960, viewHeight: 380 }
  const rect = { left: 30.5, top: 50.25, width: 1200, height: 760 }
  const params = { ...view, cssWidth: rect.width, cssHeight: rect.height, dpr: 2 }
  assert.deepEqual(computeCanvasTransform({ ...params, preserveAspectRatio: 'none' }), {
    backingWidth: 2400, backingHeight: 1520, scaleX: 2.5, scaleY: 4, offsetX: 0, offsetY: 0
  })
  assert.deepEqual(computeCanvasTransform({ ...params, preserveAspectRatio: 'meet' }), {
    backingWidth: 2400, backingHeight: 1520, scaleX: 2.5, scaleY: 2.5, offsetX: 0, offsetY: 285
  })
  const clientPoint = [rect.left + 300, rect.top + 190]
  assert.deepEqual(clientToViewBoxPoint(...clientPoint, rect, 960, 380, 'none'), { x: 240, y: 95 })
  assert.deepEqual(clientToViewBoxPoint(...clientPoint, rect, 960, 380, 'meet'), { x: 240, y: 38 })
  assert.deepEqual(clientToViewBoxPoint(100, 150, rect, 960, 380, 'meet', {
    a: 0, b: -0.5, c: 0.5, d: 0, e: -5, f: 110
  }), { x: 70, y: 60 })

  const fractional = { ...rect, width: 1200.25, height: 401.5 }
  const transform = computeCanvasTransform({ ...view, cssWidth: fractional.width, cssHeight: fractional.height, dpr: 1.25, preserveAspectRatio: 'meet' })
  assert.equal(transform.backingWidth, 1500)
  assert.equal(transform.backingHeight, 502)
  const fit = fractional.height / view.viewHeight
  const leftOffset = (fractional.width - view.viewWidth * fit) / 2
  const cssX = leftOffset + 800 * fit
  const cssY = 133 * fit
  closeTo((800 * transform.scaleX + transform.offsetX) / transform.backingWidth * fractional.width, cssX)
  closeTo((133 * transform.scaleY + transform.offsetY) / transform.backingHeight * fractional.height, cssY)
  const inverse = clientToViewBoxPoint(fractional.left + cssX, fractional.top + cssY, fractional, 960, 380, 'meet')
  closeTo(inverse.x, 800)
  closeTo(inverse.y, 133)
  const collapsed = computeCanvasTransform({ ...params, cssWidth: 0, cssHeight: 0, preserveAspectRatio: 'none' })
  assert.equal(collapsed.backingWidth, 1)
  assert.equal(collapsed.backingHeight, 1)
})

test('800 pixel buckets preserve both one-datum extrema in a 20,000-point trace in source order', () => {
  const data = Array.from({ length: 20_000 }, (_, index) => ({ x: index, y: Math.sin(index), index }))
  // Put the maximum before the minimum in the same bucket to check both extrema and ordering.
  data[12_345].y = 50_000
  data[12_349].y = -12_000
  const result = decimateMinMaxBuckets({ data, xStart: 0, xEnd: 19_999, pixelWidth: 800.9 })
  assert.equal(result.decimated, true)
  assert.equal(result.singlePoint, false)
  assert.ok(result.points.length <= 1600)
  assert.ok(result.points.includes(data[12_345]))
  assert.ok(result.points.includes(data[12_349]))
  assert.ok(result.points.every((point, index) => !index || point.index > result.points[index - 1].index))
})

test('a zoomed trace keeps the original segments crossing both edges of the clip', () => {
  const data = Array.from({ length: 100 }, (_, x) => ({ x, y: 0 }))
  data[15].y = -10
  data[16].y = 10
  const result = decimateMinMaxBuckets({ data, xStart: 10.25, xEnd: 20.75, pixelWidth: 1 })
  assert.equal(result.decimated, true)
  assert.equal(result.leftAnchor, data[10])
  assert.equal(result.rightAnchor, data[21])
  assert.deepEqual(result.points, [data[10], data[11], data[15], data[16], data[20], data[21]])

  const small = decimateMinMaxBuckets({ data, xStart: 11, xEnd: 14, pixelWidth: 0 })
  assert.equal(small.decimated, false)
  assert.deepEqual(small.points, data.slice(10, 16))
  const gap = decimateMinMaxBuckets({ data, xStart: 20.25, xEnd: 20.75, pixelWidth: 1 })
  assert.deepEqual(gap.points, data.slice(20, 22))
})

test('empty, single-point and two-point curves preserve their original datum objects', () => {
  const xRange = { xStart: 0, xEnd: 1, pixelWidth: 0 }
  const first = { x: 0, y: 10 }
  const last = { x: 1, y: 20 }
  for (const data of [[], [first], [first, last]]) {
    const result = decimateMinMaxBuckets({ data, ...xRange })
    assert.equal(result.decimated, false)
    assert.equal(result.singlePoint, data.length === 1)
    assert.deepEqual(result.points, data)
    assert.ok(result.points.every((point, index) => point === data[index]))
  }
})

test('binary lookup chooses the earliest index for equidistant and duplicate values', () => {
  const data = [1, 1, 3, 3, 7, 7].map((x, index) => ({ x, y: index }))
  for (const [target, index] of [[-10, 0], [1, 0], [2, 0], [3, 2], [5, 2], [7, 4], [10, 4], [1e20, 0]]) {
    const found = findNearestDatumIndex(data, target)
    assert.equal(found.datumIndex, index)
    assert.equal(found.datum, data[index])
  }
  assert.equal(findNearestDatumIndex([], 0), null)
  const outOfOrder = [1, 6, 3, 8].map(x => ({ x }))
  assert.deepEqual(findNearestDatumIndex(outOfOrder, 5), { datumIndex: 1, datum: outOfOrder[1] })
})

test('binary lookup matches a full scan of seeded random sorted series and out-of-range targets', () => {
  let state = 42
  function random() {
    state = (Math.imul(1_664_525, state) + 1_013_904_223) >>> 0
    return state / 2 ** 32
  }
  for (const size of [1, 3, 32, 513, 4096]) {
    for (let trial = 0; trial < 8; trial++) {
      let x = -100
      const data = Array.from({ length: size }, (_, index) => ({ x: x += Math.floor(random() * 5), index }))
      const end = data[data.length - 1].x
      const targets = [data[0].x - 1, end + 1, 1e20, -1e20]
      for (let i = 0; i < 64; i++) targets.push(Math.round((data[0].x + random() * (end - data[0].x)) * 2) / 2)
      for (const target of targets) {
        const datum = data.reduce((best, point) => Math.abs(point.x - target) < Math.abs(best.x - target) ? point : best)
        const found = findNearestDatumIndex(data, target)
        assert.equal(found.datumIndex, datum.index)
        assert.equal(found.datum, datum)
      }
    }
  }
})

test('CSS colors resolve direct values, nested fallbacks and cyclic references without a DOM', () => {
  const tokens = new Map([
    ['--curve', ' rgb(12, 23, 34) '], ['--a', 'var(--b)'], ['--b', 'var(--a)'],
    ['--high', 'var(--curve)'], ['--blank', '   ']
  ])
  const color = expression => resolveCssColor(expression, token => tokens.get(token), '#000')
  assert.equal(color(' #abc '), '#abc')
  assert.equal(color('rgb(1, 2, 3)'), 'rgb(1, 2, 3)')
  assert.equal(color('var(--curve)'), 'rgb(12, 23, 34)')
  assert.equal(color('var(--high, #fff)'), 'rgb(12, 23, 34)')
  assert.equal(color('var(--missing, var(--curve, #1570a6))'), 'rgb(12, 23, 34)')
  assert.equal(color('var(--a, var(--b, #1570a6))'), '#1570a6')
  assert.equal(color('var(--a)'), '#000')
  assert.equal(color('var(--blank, rgb(90, 80, 70))'), 'rgb(90, 80, 70)')
  assert.equal(resolveCssColor('var(--absent)', undefined, '#000'), '#000')
})

function mockCanvas(captureGeometry = false) {
  const operations = []
  const draws = []
  let segments = 0
  let moves = 0
  let circle
  let path
  return {
    canvas: { width: 0, height: 0 }, operations, draws,
    save() { operations.push(['save']) },
    restore() { operations.push(['restore']) },
    setTransform(...matrix) { operations.push(['transform', ...matrix]) },
    clearRect(...bounds) { operations.push(['clear', ...bounds]) },
    fillRect(...bounds) { operations.push(['background', this.fillStyle, ...bounds]) },
    rect(...bounds) { operations.push(['rect', ...bounds]) },
    clip() { operations.push(['clip']) },
    setLineDash(dash) { this.dash = dash },
    beginPath() { segments = 0; moves = 0; circle = undefined; path = captureGeometry ? [] : undefined },
    moveTo(x, y) { moves++; path?.push(['move', x, y]) },
    lineTo(x, y) { segments++; path?.push(['line', x, y]) },
    stroke() {
      draws.push({ color: this.strokeStyle, width: this.lineWidth, opacity: this.globalAlpha, dash: this.dash,
        segments, moves, filter: this.filter, ...(path ? { path } : {}) })
    },
    arc(...geometry) { circle = geometry },
    fill() { draws.push({ color: this.fillStyle, opacity: this.globalAlpha, circle }) }
  }
}

test('Canvas clears in physical pixels, clips the background and grid, and draws priority last', () => {
  const ctx = mockCanvas()
  const [left, top, width, height] = [108, 84, 1744, 576]
  const pair = [{ x: 0, y: 0 }, { x: 1, y: 1 }]
  const curves = Object.freeze([
    { data: pair, priority: true, color: '#1570a6' },
    { data: pair, priority: false, color: '#111' },
    { data: [{ x: 0.5, y: 0.5 }], priority: false, color: '#222' },
    { data: [], priority: false, color: '#333' }
  ])
  renderSpectrumCanvas(ctx, {
    rect: standardRect, cssWidth: 960, cssHeight: 380, dpr: 2, preserveAspectRatio: 'none',
    xStart: 0, xEnd: 1, yStart: 0, yEnd: 1, curves,
    xTicks: [0.25, 0.75], yTicks: [0.5], backgroundColor: '#fff', gridColor: '#ccc',
    gridLineDash: [2, 3], gridLineWidth: 0.5, lineWidth: 1.25, lineOpacity: 0.45, priorityLineWidth: 3,
    readVar: token => token === '--plot-priority-color' ? '#f43' : undefined
  })
  assert.deepEqual(ctx.canvas, { width: 1920, height: 760 })
  assert.deepEqual(ctx.operations, [
    ['save'], ['transform', 1, 0, 0, 1, 0, 0], ['clear', 0, 0, 1920, 760],
    ['rect', left, top, width, height], ['clip'],
    ['background', '#fff', left, top, width, height], ['restore']
  ])
  assert.deepEqual(ctx.draws, [
    { color: '#ccc', width: 1, opacity: 1, dash: [4, 6], segments: 3, moves: 3, filter: 'none' },
    { color: '#111', width: 2.5, opacity: 0.45, dash: [], segments: 1, moves: 1, filter: 'none' },
    { color: '#222', opacity: 1, circle: [980, 372, 8, 0, 2 * Math.PI] },
    { color: '#f43', width: 6, opacity: 1, dash: [], segments: 1, moves: 1, filter: 'none' }
  ])
})

test('nonuniform stretch maps grid and traces in physical pixels without stretching stroke widths or circles', () => {
  const ctx = mockCanvas(true)
  const curves = [
    { data: [{ x: 0, y: 0.25 }, { x: 1, y: 0.25 }, { x: 1, y: 1 }], priority: false, color: '#111' },
    { data: [{ x: 0.5, y: 0.5 }], priority: false, color: '#222' },
    { data: [{ x: 0, y: 0 }, { x: 1, y: 1 }], priority: true, color: '#333' }
  ]
  renderSpectrumCanvas(ctx, {
    rect: standardRect, cssWidth: 1280, cssHeight: 760, dpr: 1.5, preserveAspectRatio: 'none',
    xStart: 0, xEnd: 1, yStart: 0, yEnd: 1, curves, xTicks: [0.5], yTicks: [0.5],
    backgroundColor: '#fff', gridLineDash: [4, 3], lineWidth: 2, priorityLineWidth: 3,
    priorityColor: '#f43', curveBrightness: 1.65, priorityBrightness: 1
  })
  assert.deepEqual(ctx.canvas, { width: 1920, height: 1140 })
  assert.deepEqual(ctx.operations, [
    ['save'], ['transform', 1, 0, 0, 1, 0, 0], ['clear', 0, 0, 1920, 1140],
    ['rect', 108, 126, 1744, 864], ['clip'], ['background', '#fff', 108, 126, 1744, 864], ['restore']
  ])
  assert.deepEqual(ctx.draws, [
    { color: '#e6ebf2', width: 1.5, opacity: 1, dash: [6, 4.5], segments: 2, moves: 2, filter: 'none',
      path: [['move', 980, 126], ['line', 980, 990], ['move', 108, 558], ['line', 1852, 558]] },
    { color: '#111', width: 3, opacity: 0.72, dash: [], segments: 2, moves: 1, filter: 'brightness(1.65)',
      path: [['move', 108, 774], ['line', 1852, 774], ['line', 1852, 126]] },
    { color: '#222', opacity: 1, circle: [980, 558, 6, 0, 2 * Math.PI] },
    { color: '#f43', width: 4.5, opacity: 1, dash: [], segments: 1, moves: 1, filter: 'none',
      path: [['move', 108, 990], ['line', 1852, 126]] }
  ])
})

test('alignment preserves the 1-based trace, clamped narrow peaks and fixed grid, then clears an empty frame', () => {
  const ctx = mockCanvas(true)
  const rect = { left: 0, top: 0, width: 513, height: 128, viewWidth: 513, viewHeight: 128 }
  const options = {
    rect, curveViewport: { rect: { ...rect, top: 1, width: 512, height: 126 }, clampTop: true },
    cssWidth: 256.5, cssHeight: 192, dpr: 2, preserveAspectRatio: 'none',
    xStart: 1, xEnd: 2049, yStart: 0, yEnd: 1000,
    xTicks: Array.from({ length: 9 }, (_, i) => i * 64), yTicks: [0, 63.5, 127], gridInViewBox: true,
    backgroundColor: '#fff', gridLineDash: [2, 3], gridLineWidth: 0.75
  }
  const points = Array.from({ length: 2054 }, (_, i) => ({ x: i + 1, y: i === 1024 || i === 2050 ? 1500 : 0 }))
  renderSpectrumCanvas(ctx, { ...options, curves: [{ data: points, priority: false, color: '#c32d35' }] })

  const [grid, trace] = ctx.draws
  assert.deepEqual(ctx.canvas, { width: 513, height: 384 })
  assert.deepEqual(grid.dash, [4, 6])
  assert.equal(grid.width, 1.5)
  assert.deepEqual(grid.path, [
    ...options.xTicks.flatMap(x => [['move', x, 0], ['line', x, 384]]),
    ...options.yTicks.flatMap(y => [['move', 0, y * 3], ['line', 513, y * 3]])
  ])
  assert.ok(trace.segments < points.length / 2)
  assert.deepEqual(trace.path[0], ['move', 0, 381])
  assert.ok(trace.path.some(([kind, x, y]) => kind === 'line' && x === 256 && y === 3))
  assert.ok(trace.path.some(([kind, x, y]) => kind === 'line' && x === 512.5 && y === 3))

  const firstDrawOperations = ctx.operations.slice()
  renderSpectrumCanvas(ctx, { ...options, xStart: 1, xEnd: 2, curves: [] })
  assert.deepEqual(ctx.operations.slice(firstDrawOperations.length), firstDrawOperations)
  assert.deepEqual(ctx.draws.slice(2), [grid])
})

test('30 × 4,096 Canvas benchmark bounds path segments by the displayed plot width at DPR 2', t => {
  const ctx = mockCanvas()
  const count = 4096
  const curves = Array.from({ length: 30 }, (_, curve) => ({
    priority: curve === 0, color: curve === 0 ? '#f43' : '#1570a6',
    data: Array.from({ length: count }, (_, x) => ({ x, y: 1000 + 900 * Math.sin(x / 53 + curve) }))
  }))
  const start = performance.now()
  renderSpectrumCanvas(ctx, {
    rect: standardRect, cssWidth: 1200, cssHeight: 400, dpr: 2, preserveAspectRatio: 'meet',
    xStart: 0, xEnd: count - 1, yStart: 0, yEnd: 2000, curves
  })
  const elapsed = performance.now() - start
  const buckets = Math.floor(872 * (400 / 380))
  const segments = ctx.draws.reduce((total, draw) => total + draw.segments, 0)
  assert.deepEqual(ctx.canvas, { width: 2400, height: 800 })
  assert.equal(ctx.draws.length, 30)
  assert.ok(ctx.draws.every(draw => draw.moves === 1 && draw.segments > 0 && draw.segments <= 2 * buckets - 1))
  assert.ok(segments <= curves.length * (2 * buckets - 1))
  assert.ok(segments < curves.length * count / 2)
  assert.equal(ctx.draws[ctx.draws.length - 1].color, '#f43')
  t.diagnostic(`Mock Canvas: ${curves.length * count} input points, ${segments} line segments, ${elapsed.toFixed(2)} ms`)
})

test('theme observation rewires the DPI query before redraw and disposes every listener', t => {
  assert.doesNotThrow(() => observeCanvasEnvironment(() => assert.fail('Node must not subscribe'))())
  const root = {}
  const parent = { parentElement: root }
  const host = { parentElement: parent }
  const observed = []
  const queries = new Map()
  const activeQueries = () => [...queries.keys()].filter(query => queries.get(query).size > 0)
  const redraws = []
  let disconnects = 0
  let notifyMutation
  const win = {
    devicePixelRatio: 1,
    MutationObserver: class {
      constructor(callback) { notifyMutation = callback }
      observe(target, { attributeFilter }) { observed.push([target, attributeFilter]) }
      disconnect() { disconnects++ }
    },
    matchMedia(query) {
      assert.deepEqual(activeQueries(), [])
      const listeners = new Set()
      queries.set(query, listeners)
      return {
        addEventListener(type, callback) { assert.equal(type, 'change'); listeners.add(callback) },
        removeEventListener(type, callback) { assert.equal(type, 'change'); listeners.delete(callback) }
      }
    }
  }
  Object.defineProperty(globalThis, 'window', { value: win, configurable: true })
  Object.defineProperty(globalThis, 'document', { value: { documentElement: root }, configurable: true })
  t.after(() => { delete globalThis.window; delete globalThis.document })

  const dispose = observeCanvasEnvironment(() => redraws.push(activeQueries()), host)
  const attributes = ['data-theme', 'class', 'style']
  const at1 = '(resolution: 1dppx)'
  const at2 = '(resolution: 2dppx)'
  const at125 = '(resolution: 1.25dppx)'
  assert.deepEqual(observed, [[root, attributes], [host, attributes], [parent, attributes]])
  assert.deepEqual(activeQueries(), [at1])
  notifyMutation()
  win.devicePixelRatio = 2
  const [moveTo2] = queries.get(at1)
  moveTo2()
  win.devicePixelRatio = 1.25
  const [moveTo125] = queries.get(at2)
  moveTo125()
  assert.deepEqual(redraws, [[at1], [at2], [at125]])
  const [lastListener] = queries.get(at125)
  dispose()
  dispose()
  assert.equal(disconnects, 1)
  assert.deepEqual(activeQueries(), [])
  notifyMutation()
  lastListener()
  assert.equal(redraws.length, 3)
})
