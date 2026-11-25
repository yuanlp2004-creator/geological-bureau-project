import assert from 'node:assert/strict'

export function spectrumCanvas(scope) {
  return scope.locator('xpath=.//canvas[contains(concat(" ", normalize-space(@class), " "), " spectrum-canvas ")] | self::*[@data-testid="spectrum-plot"]/../canvas').first()
}

export async function spectrumCanvasSnapshot(scope) {
  return spectrumCanvas(scope).evaluate(canvas => {
    const svg = canvas.nextElementSibling
    const { x, y, width, height } = svg.getBoundingClientRect()
    return {
      image: canvas.toDataURL(), box: { x, y, width, height }, viewBox: svg.getAttribute('viewBox'),
      xStart: Number(canvas.dataset.xStart), xEnd: Number(canvas.dataset.xEnd),
      yStart: Number(canvas.dataset.yStart), yEnd: Number(canvas.dataset.yEnd),
    }
  })
}

const readSpectrumPixels = (canvas, expected) => {
  const { renderSeq, lineCount, singlePointCount, curveIds } = canvas.dataset
  const lines = Number(lineCount), points = Number(singlePointCount), seq = Number(renderSeq)
  if (!(seq > (expected.after ?? 0)) || (expected.lines == null && expected.points == null && lines < 1)
    || (expected.lines != null && lines !== expected.lines) || (expected.points != null && points < expected.points)
    || (expected.xSpanBelow != null && Number(canvas.dataset.xEnd) - Number(canvas.dataset.xStart) >= expected.xSpanBelow)
    || (expected.id && !curveIds.split(' ').includes(expected.id))) return { ready: false, seq, lines, points, curveIds }

  const hit = canvas.nextElementSibling.querySelector('.plot-background')
  const overlay = getComputedStyle(hit).fill
  const frame = hit.getBoundingClientRect(), bounds = canvas.getBoundingClientRect()
  const scaleX = canvas.width / bounds.width, scaleY = canvas.height / bounds.height
  const left = Math.ceil((frame.left - bounds.left) * scaleX)
  const top = Math.ceil((frame.top - bounds.top) * scaleY)
  const width = Math.floor((frame.right - bounds.left) * scaleX) - left
  const height = Math.floor((frame.bottom - bounds.top) * scaleY) - top
  if (width < 1 || height < 1) return { ready: false, width, height }
  const styles = getComputedStyle(canvas.parentElement)
  const readVar = name => styles.getPropertyValue(name).trim()
  const swatch = document.createElement('canvas')
  swatch.width = swatch.height = 1
  const color = swatch.getContext('2d')
  const rgba = value => {
    color.clearRect(0, 0, 1, 1)
    color.fillStyle = value
    color.fillRect(0, 0, 1, 1)
    return [...color.getImageData(0, 0, 1, 1).data]
  }
  const background = rgba(readVar('--plot-background-color') || '#fbfcfe')
  const grid = rgba(readVar('--plot-grid-color') || readVar('--line') || '#e6ebf2')
  const difference = grid.slice(0, 3).map((value, index) => value - background[index])
  const axis = difference.reduce((best, value, index) => Math.abs(value) > Math.abs(difference[best]) ? index : best, 0)
  const { data } = canvas.getContext('2d').getImageData(left, top, width, height)
  let corner = null
  let ink = false
  for (let offset = 0; offset < data.length; offset += 4) {
    if (data[offset + 3] !== 255) return { ready: false, opaque: false, seq }
    const same = background.every((value, channel) => data[offset + channel] === value)
    if (same) {
      if (!corner && offset / 4 % width < 24 && offset / 4 < width * 24) corner = [...data.subarray(offset, offset + 4)]
      continue
    }
    // A grid pixel can be an antialiased blend of the grid and background colors.
    const coverage = difference[axis] ? Math.max(0, Math.min(1, (data[offset + axis] - background[axis]) / difference[axis])) : 0
    if (difference.some((delta, channel) => Math.abs(data[offset + channel] - background[channel] - coverage * delta) > 3)) ink = true
    if (ink && corner && expected.ink !== false) break
  }
  return { ready: overlay === 'rgba(0, 0, 0, 0)' && Boolean(corner) && ink === (expected.ink ?? true),
    seq, lines, points, curveIds, corner, ink, overlay }
}

export async function waitForSpectrumInk(scope, expected = {}) {
  const canvas = spectrumCanvas(scope)
  await canvas.waitFor()
  const deadline = Date.now() + 8000
  let painted
  do {
    painted = await canvas.evaluate(readSpectrumPixels, expected)
    if (painted.ready) return painted
    await new Promise(resolve => setTimeout(resolve, 40))
  } while (Date.now() < deadline)
  assert.fail(`Canvas paint ${JSON.stringify(expected)}: ${JSON.stringify(painted)}`)
}

export async function assertSpectrumCleared(scope, emptyState = scope.locator('.inspector-empty')) {
  const canvas = spectrumCanvas(scope)
  if (await canvas.count()) {
    const paint = await waitForSpectrumInk(scope, { lines: 0, ink: false })
    assert.equal(paint.points, 0)
    assert.equal(paint.curveIds, '')
  } else {
    // Some workbenches replace the entire chart with their explicit empty state.
    await emptyState.waitFor()
    assert.equal(await canvas.count(), 0)
  }
}

export async function leaveLegacyCapture(page) {
  const close = page.getByRole('button', { name: '关闭色散处理窗口', exact: true })
  if (await close.isVisible().catch(() => false)) await close.click()
  const end = page.locator('.legacy-capture-desk:visible').getByRole('button', { name: '结束', exact: true })
  if (await end.isVisible().catch(() => false)) await end.click()
}
export async function openSpectrumReadout(scope) {
  const page = scope.page(), dialog = scope.locator('.spectrum-observer-dialog')
  if (await dialog.isVisible()) return
  await page.locator('.legacy-window-caption:visible').click({ button: 'right' })
  await page.getByRole('menuitem', { name: '谱图点位与视野', exact: true }).click()
  await dialog.waitFor()
}
export async function closeSpectrumReadout(scope) {
  const close = scope.getByRole('button', { name: '关闭谱图读数', exact: true })
  if (await close.isVisible()) await close.click()
}

export async function openViewerFiles(scope, dispersion = false) {
  const title = dispersion ? '选择色散文件' : '选择谱文件'
  await scope.locator('.legacy-view-rail > header').first().click({ button: 'right' })
  await scope.page().getByRole('menuitem', { name: title, exact: true }).click()
  const dialog = scope.getByRole('dialog', { name: title, exact: true })
  await dialog.waitFor()
  return dialog
}

export async function selectViewerFile(scope, group, dispersion = false) {
  const dialog = await openViewerFiles(scope, dispersion)
  const select = dialog.getByLabel(dispersion ? '色散数据文件' : '当前谱文件')
  await select.locator(`option[value=${JSON.stringify(group)}]`).waitFor({ state: 'attached' })
  if (await select.inputValue() === group) await dialog.getByRole('button', {
    name: dispersion ? '关闭选择色散文件' : '关闭选择谱文件', exact: true
  }).click()
  else await select.selectOption(group)
  await dialog.waitFor({ state: 'hidden' })
}

export async function openViewerPlotAction(scope, name) {
  const chart = scope.locator('svg.spectrum-plot .plot-background').first()
  await chart.click({ button: 'right', position: { x: 40, y: 35 }, force: true })
  await scope.page().getByRole('menu', { name: '谱图菜单', exact: true })
    .getByRole('menuitem', { name, exact: true }).click()
}
