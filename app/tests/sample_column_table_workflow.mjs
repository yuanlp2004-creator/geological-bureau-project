import assert from 'node:assert/strict'
import path from 'node:path'
import { call, navigate } from './contract_browser_support.mjs'

export async function readSampleCells(page) {
  return page.getByRole('table', { name: '样号按列排列表格' }).locator('[data-sample-id]').evaluateAll(cells =>
    cells.map(cell => {
      const text = cell.querySelector('strong'), range = document.createRange()
      range.selectNodeContents(text)
      const bounds = range.getBoundingClientRect(), content = text.getBoundingClientRect()
      return { id: Number(cell.dataset.sampleId), position: Number(cell.dataset.samplePosition),
      name: cell.querySelector('strong').textContent, title: cell.title,
      x: cell.getBoundingClientRect().x + scrollX, y: cell.getBoundingClientRect().y + scrollY,
      width: cell.getBoundingClientRect().width, height: cell.getBoundingClientRect().height,
      textLines: range.getClientRects().length,
      fullTextVisible: text.scrollWidth <= text.clientWidth && bounds.left >= content.left - .5 && bounds.right <= content.right + .5
        && bounds.top >= cell.getBoundingClientRect().top && bounds.bottom <= cell.getBoundingClientRect().bottom,
    }}).sort((a, b) => a.position - b.position))
}

export async function checkSampleColumnTable(page, result, output) {
  const checked = message => { result.checks.push(message); console.log(`PASS: ${message}`) }
  const capture = async name => {
    await page.evaluate(() => { scrollTo(0, 0); return new Promise(requestAnimationFrame) })
    await page.screenshot({ path: path.join(output, name), fullPage: true })
  }
  await navigate(page, 'analysis-tests', '样号与样品队列', '.sample-queue-page')
  const host = page.locator('.sample-queue-page')
  const table = host.getByRole('table', { name: '样号按列排列表格' })
  const input = host.getByLabel('样品名', { exact: true })
  const detail = host.getByRole('region', { name: '选中样品详情' })
  const nameOf = (length, index) => String(index).padStart(length, '0')
  const capacity = async () => Number(await host.locator('.sample-number-sheet').getAttribute('data-page-size'))
  async function append(queue, index) {
    const waiting = page.waitForResponse(r => r.url().endsWith(`/sample-queues/${queue.id}`) && r.request().method() === 'PATCH')
    await input.fill(nameOf(queue.name_length, index))
    await host.getByRole('button', { name: '插入样品', exact: true }).click()
    const response = await waiting
    assert.equal(response.status(), 200)
    const next = await response.json()
    await page.waitForFunction(count => document.querySelector('.sample-number-toolbar nav span')?.textContent.includes(`共 ${count} 项`), next.items.length)
    return next
  }
  function unchanged(before, after) {
    for (const previous of before) {
      const current = after.find(cell => cell.id === previous.id)
      assert.ok(current)
      for (const coordinate of ['x', 'y', 'width']) assert.ok(Math.abs(current[coordinate] - previous[coordinate]) < .6, `${previous.position}: ${coordinate} shifted`)
    }
  }
  async function gridMetrics() {
    return host.locator('.sample-number-sheet').evaluate(sheet => {
      const scroll = sheet.querySelector('.sample-number-scroll'), editor = sheet.closest('.sample-editor')
      const style = getComputedStyle(editor)
      const contentWidth = editor.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight)
      return { rows: Number(sheet.dataset.rows), columns: Number(sheet.dataset.columns), capacity: Number(sheet.dataset.pageSize),
        gridWidth: scroll.getBoundingClientRect().width, contentWidth,
        overflow: scroll.scrollWidth - scroll.clientWidth,
        slots: sheet.querySelectorAll('tbody td').length }
    })
  }
  result.grid_metrics = []
  let lastQueue
  for (const length of [12, 20]) {
    let queue = await call(page, '/api/v1/sample-queues', { name: `${length}位满幅小格样号`, name_length: length,
      items: Array.from({ length: 3 }, (_, index) => ({ pre_name: index === 0 ? '样'.repeat(length) : index === 1 ? 'W'.repeat(length) : nameOf(length, index + 1), repeats: index === 0 ? 3 : 1 })) })
    queue = await call(page, `/api/v1/sample-queues/${queue.id}/items/${queue.items[2].id}/rename`, { post_name: 'POST3' })
    await host.getByRole('button', { name: '刷新', exact: true }).click()
    await host.getByLabel(/^选择样品队列/).selectOption(String(queue.id))
    await table.locator('[data-sample-position="3"]').waitFor()
    const methodRepeat = host.getByRole('checkbox', { name: '按当前方法默认次数' })
    if (await methodRepeat.isVisible()) await methodRepeat.uncheck()
    await host.getByLabel('重复次数', { exact: true }).fill('1')
    let cells = await readSampleCells(page)
    if (length === 12) {
      const original = cells, originalColumns = (await gridMetrics()).columns
      for (const mode of [20, 12]) {
        const waiting = page.waitForResponse(r => r.url().endsWith(`/sample-queues/${queue.id}`) && r.request().method() === 'PATCH')
        await host.getByLabel(/^样号长度/).selectOption(String(mode))
        assert.equal((await waiting).status(), 200)
        await page.waitForFunction(mode => Number(document.querySelector('.sample-number-sheet')?.dataset.nameLength) === mode, mode)
        await page.waitForFunction(({ columns, wide }) => {
          const current = Number(document.querySelector('.sample-number-sheet')?.dataset.columns)
          return wide ? current < columns : current === columns
        }, { columns: originalColumns, wide: mode === 20 })
        const changed = await readSampleCells(page)
        assert.ok(changed.every(cell => cell.fullTextVisible))
        assert.deepEqual(changed.map(cell => [cell.id, cell.name]), original.map(cell => [cell.id, cell.name]))
        if (mode === 20) assert.ok(changed[0].width > original[0].width)
        else unchanged(original, changed)
      }
      cells = await readSampleCells(page)
    }
    const metrics = await gridMetrics()
    assert.equal(metrics.rows, 20)
    assert.ok(metrics.columns >= 3)
    assert.equal(metrics.slots, metrics.capacity)
    assert.ok(Math.abs(metrics.gridWidth - metrics.contentWidth) <= 2)
    assert.ok(metrics.overflow <= 1)
    assert.ok(cells.every(cell => cell.width >= length * 7.2 + 10 && cell.width < length * 10 && cell.height <= 29 && cell.fullTextVisible))
    assert.equal(cells[1].textLines, 1)
    assert.equal(cells[2].textLines, 1)
    result.grid_metrics.push({ name_length: length, ...metrics, cellWidth: cells[0].width, cellHeight: cells[0].height })
    assert.ok(cells.every((cell, i) => cell.x === cells[0].x && (i === 0 || cell.y > cells[i - 1].y)))
    const third = table.locator('[data-sample-position="3"]')
    const originalItems = queue.items
    const tableHeight = await table.evaluate(element => element.getBoundingClientRect().height)
    await third.dblclick()
    assert.ok(Math.abs(await table.evaluate(element => element.getBoundingClientRect().height) - tableHeight) < .6)
    const editor = table.getByRole('textbox', { name: '修改样号 3', exact: true })
    const editedName = `E${'1'.repeat(length - 1)}`
    await editor.fill(editedName)
    assert.equal(await host.getByLabel(/^选择样品队列/).isDisabled(), true)
    assert.equal(await host.getByLabel(/^样号长度/).isDisabled(), true)
    assert.equal(await host.getByRole('button', { name: '插入样品', exact: true }).isDisabled(), true)
    let releaseSave, requests = 0
    const saveGate = new Promise(resolve => { releaseSave = resolve })
    const routeUrl = `**/api/v1/sample-queues/${queue.id}`
    await page.route(routeUrl, async route => {
      if (route.request().method() === 'PATCH') { requests++; await saveGate }
      await route.continue()
    })
    try {
      const waiting = page.waitForResponse(r => r.url().endsWith(`/sample-queues/${queue.id}`) && r.request().method() === 'PATCH')
      await editor.press('Enter')
      await page.waitForFunction(() => document.querySelector('.sample-number-edit')?.disabled)
      assert.equal(await detail.getByRole('button', { name: '正在保存…', exact: true }).isDisabled(), true)
      assert.equal(await detail.getByRole('button', { name: '取消修改', exact: true }).isDisabled(), true)
      await editor.dispatchEvent('keydown', { key: 'Enter' })
      releaseSave()
      const response = await waiting
      assert.equal(response.status(), 200)
      queue = await response.json()
      await page.waitForFunction(() => !document.querySelector('.sample-number-edit'))
      assert.equal(requests, 1)
    } finally { releaseSave(); await page.unroute(routeUrl) }
    const preserved = item => [item.id, item.position, item.repeats, item.expanded_bands, item.post_name, item.spectrum_hash, item.source_name]
    assert.deepEqual(queue.items.map(preserved), originalItems.map(preserved))
    assert.equal(queue.items[2].pre_name, editedName)
    unchanged(cells, await readSampleCells(page))
    await third.focus()
    await third.press('F2')
    const invalid = 'X'.repeat(length + 1)
    await editor.fill(invalid)
    const rejected = page.waitForResponse(r => r.url().endsWith(`/sample-queues/${queue.id}`) && r.request().method() === 'PATCH')
    await editor.press('Enter')
    assert.equal((await rejected).status(), 422)
    await host.getByRole('alert').filter({ hasText: `超过 ${length} 位` }).waitFor()
    assert.equal(await editor.inputValue(), invalid)
    assert.equal((await call(page, `/api/v1/sample-queues/${queue.id}`)).items[2].pre_name, editedName)
    await editor.press('Escape')
    await detail.getByRole('button', { name: '修改样号', exact: true }).click()
    await editor.fill('CANCELLED')
    await detail.getByRole('button', { name: '取消修改', exact: true }).click()
    assert.equal((await call(page, `/api/v1/sample-queues/${queue.id}`)).items[2].pre_name, editedName)
    assert.equal(await host.getByRole('button', { name: '插入样品', exact: true }).isDisabled(), false)
    await third.dblclick()
    await capture(`sample-edit-${length}.png`)
    await editor.press('Escape')
    checked(`${length}位双击/F2/按钮均能编辑，回车真实保存；请求中禁止重复提交和切换，超长422保留输入，Esc和取消不改后台，ID/顺序/重复/采后信息保持`)
    queue = await append(queue, 4)
    unchanged(cells, await readSampleCells(page))
    await capture(`sample-grid-${length}-four.png`)
    for (let i = 5; i <= 20; i++) queue = await append(queue, i)
    cells = await readSampleCells(page)
    queue = await append(queue, 21)
    let next = await readSampleCells(page)
    unchanged(cells, next)
    assert.ok(next[20].x > next[0].x && next[20].y === next[0].y)
    assert.deepEqual(next.map(cell => cell.name), queue.items.map(item => item.pre_name))
    assert.equal(next[0].title, `第 1 项：${queue.items[0].pre_name}`)
    await table.locator('[data-sample-position="1"]').click()
    assert.equal(await detail.locator('dd').first().innerText(), queue.items[0].pre_name)
    assert.ok(next.every(cell => cell.fullTextVisible))
    checked(`${length}位按数字字母宽度收窄，满位数字字母完整单行、中文格内换行，满幅空格保留；新增3→4、20→21已有坐标不变`)

    const limit = await capacity()
    queue = await call(page, `/api/v1/sample-queues/${queue.id}`, { items: [
      ...queue.items.map(item => ({ id: item.id, pre_name: item.pre_name, repeats: item.repeats })),
      ...Array.from({ length: limit - 21 }, (_, i) => ({ pre_name: nameOf(length, i + 22), repeats: 1 }))] }, 'PATCH')
    await host.getByRole('button', { name: '刷新', exact: true }).click()
    await table.locator(`[data-sample-position="${limit}"]`).waitFor()
    cells = await readSampleCells(page)
    queue = await append(queue, limit + 1)
    unchanged(cells, await readSampleCells(page))
    assert.equal((await readSampleCells(page)).length, limit)
    await host.getByRole('button', { name: '下一页样号' }).click()
    await table.locator(`[data-sample-position="${limit + 1}"]`).waitFor()
    const second = await readSampleCells(page)
    assert.equal(second.length, 1)
    assert.equal(second[0].id, queue.items[limit].id)
    await host.getByRole('button', { name: '上一页样号' }).click()
    unchanged(cells, await readSampleCells(page))
    const stored = await call(page, `/api/v1/sample-queues/${queue.id}`)
    assert.deepEqual(stored.items.map(item => [item.id, item.pre_name, item.repeats]), queue.items.map(item => [item.id, item.pre_name, item.repeats]))
    checked(`${length}位超出当前网格容量后翻页，当前页位置及后台队列顺序保持`)
    await capture(`sample-table-${length}-light.png`)
    lastQueue = queue
  }

  await table.locator('[data-sample-position="1"]').click()
  assert.equal(await detail.locator('dd').nth(1).innerText(), '3')
  await call(page, `/api/v1/sample-queues/${lastQueue.id}/items/${lastQueue.items[1].id}/rename`, { post_name: '完成样品名称' })
  await host.getByRole('button', { name: '刷新', exact: true }).click()
  await table.locator('[data-sample-position="2"]').click()
  await detail.getByText('完成样品名称', { exact: true }).waitFor()
  const deleting = page.waitForResponse(r => r.url().endsWith(`/items/${lastQueue.items[1].id}`) && r.request().method() === 'DELETE')
  await detail.getByRole('button', { name: '删除样品 2', exact: true }).click()
  assert.equal((await deleting).status(), 200)
  await page.waitForFunction(count => document.querySelector('.sample-number-toolbar nav span')?.textContent.includes(`共 ${count} 项`), lastQueue.items.length - 1)
  const deleted = await call(page, `/api/v1/sample-queues/${lastQueue.id}`)
  assert.deepEqual(deleted.items.map(item => item.id), lastQueue.items.filter(item => item.id !== lastQueue.items[1].id).map(item => item.id))
  checked('选中样品可查看重复、谱带和采集后名称，删除仍按原队列规则执行')

  const [shortening] = await Promise.all([
    page.waitForResponse(r => r.url().endsWith(`/sample-queues/${lastQueue.id}`) && r.request().method() === 'PATCH'),
    host.getByLabel(/^样号长度/).selectOption('12'),
  ])
  assert.equal(shortening.status(), 422)
  assert.equal(await host.getByLabel(/^样号长度/).inputValue(), '20')
  assert.equal((await call(page, `/api/v1/sample-queues/${lastQueue.id}`)).name_length, 20)
  await page.reload()
  await page.getByTestId('workspace').waitFor()
  await navigate(page, 'analysis-tests', '样号与样品队列', '.sample-queue-page')
  await host.getByLabel(/^选择样品队列/).selectOption(String(lastQueue.id))
  await table.locator('[data-sample-position="21"]').waitFor()
  checked('20位缩短到12位时拒绝截断，失败后保持20位，刷新后队列和排列保持')

  result.layouts = []
  for (const [width, theme] of [[1440, 'light'], [1060, 'dark']]) {
    if (process.env.QA_CDP) await page.evaluate(width => window.__TAURI__.core.invoke('plugin:window|set_size', { value: { Logical: { width, height: 1000 } } }), width)
    else await page.setViewportSize({ width, height: 1000 })
    await call(page, '/api/v1/settings', { display: { theme, density: theme === 'dark' ? 'compact' : 'comfortable' } }, 'PATCH')
    await page.getByRole('button', { name: '刷新服务状态', exact: true }).click()
    await page.waitForFunction(theme => document.querySelector('.app-shell')?.dataset.theme === theme, theme)
    const metrics = await gridMetrics()
    const cells = await readSampleCells(page)
    assert.equal(cells.length, Math.min(deleted.items.length, metrics.capacity))
    assert.ok(Math.abs(metrics.gridWidth - metrics.contentWidth) <= 2 && metrics.overflow <= 1)
    assert.ok(cells.every(cell => cell.width >= 20 * 7.2 + 10 && cell.width < 20 * 10 && cell.height <= 29 && cell.fullTextVisible))
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1))
    assert.ok(cells[20].x > cells[0].x && cells[20].y === cells[0].y)
    await capture(`sample-table-${width}-${theme}.png`)
    result.layouts.push({ width, theme, ...metrics })
  }
  checked('12/20位切换同步调整格宽且保存原名称；明色1440与暗色紧凑1060完整显示满位样号，铺满宽度，无多余水平滚动条或窗口溢出')

  const protectedQueue = await call(page, '/api/v1/sample-queues', { name: '采集关联保护', name_length: 20,
    items: [{ pre_name: 'LOCKED001', repeats: 1 }] })
  await host.getByRole('button', { name: '刷新', exact: true }).click()
  await host.getByLabel(/^选择样品队列/).selectOption(String(protectedQueue.id))
  await table.locator('[data-sample-position="1"]').dblclick()
  const protectedEditor = table.getByRole('textbox', { name: '修改样号 1', exact: true })
  await protectedEditor.fill('UNSAVED002')
  let task = await call(page, '/api/v1/acquisitions/tasks', { task_kind: 'sample', name: '样号编辑关联保护',
    queue_id: protectedQueue.id, queue_item_id: protectedQueue.items[0].id,
    burn_frame_count: 1, dark_frame_count: 0, pre_excitation_seconds: 0 })
  const blocked = page.waitForResponse(r => r.url().endsWith(`/sample-queues/${protectedQueue.id}`) && r.request().method() === 'PATCH')
  await protectedEditor.press('Enter')
  assert.equal((await blocked).status(), 409)
  await host.getByRole('alert').filter({ hasText: '已关联采集' }).waitFor()
  assert.equal(await protectedEditor.inputValue(), 'UNSAVED002')
  assert.equal((await call(page, `/api/v1/sample-queues/${protectedQueue.id}`)).items[0].pre_name, 'LOCKED001')
  await protectedEditor.press('Escape')
  task = await call(page, `/api/v1/acquisitions/tasks/${task.id}/start`, {})
  for (let i = 0; i < 20 && !['completed', 'failed'].includes(task.status); i++) task = await call(page, `/api/v1/acquisitions/tasks/${task.id}/step`, {})
  assert.equal(task.status, 'completed')
  await host.getByRole('button', { name: '刷新', exact: true }).click()
  await page.waitForFunction(() => document.querySelector('.sample-number-detail-actions .secondary-button')?.disabled)
  assert.equal(await detail.getByRole('button', { name: '修改样号', exact: true }).isDisabled(), true)
  await table.locator('[data-sample-position="1"]').dblclick()
  assert.equal(await table.locator('input').count(), 0)
  assert.ok((await call(page, `/api/v1/sample-queues/${protectedQueue.id}`)).items[0].spectrum_hash)
  await capture('sample-linked-protection.png')
  checked('编辑期间新增采集关联时真实409拒绝且保留草稿；模拟采集完成后禁止改采前样号，原名称和谱图关联保持')
}
