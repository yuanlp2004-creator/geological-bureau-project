import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { call, navigate } from './contract_browser_support.mjs'

export async function prepareContinuousCaptureMethod(page) {
  const profiles = await call(page, '/api/v1/devices/profiles')
  await call(page, '/api/v1/devices/current', { profile_id: profiles.find(profile => profile.transport === 'simulator').id }, 'PUT')
  const method = await call(page, '/api/v1/methods', { name: '连续摄谱 QA', conditions: {
    selected_ccds: [0], exposure_mode: 'simple_mean', frame_count: 2, dark_frame_count: 0,
    angle_exposures: [{ angle_deg: 4, storage_mode: 'averaged', start_frame: 1, end_frame: 2 }],
  } })
  const line = JSON.parse(await readFile(new URL('./fixtures/station17-line.json', import.meta.url), 'utf8'))
  await call(page, `/api/v1/methods/${method.id}/lines`, line)
  const draft = await call(page, `/api/v1/methods/${method.id}`)
  const ids = draft.version.lines.map(item => item.id)
  assert.equal(ids.length, 2)
  await call(page, `/api/v1/methods/${method.id}`, { conditions: {
    angle_exposures: [4, 17].map((angle_deg, index) => ({ angle_deg, storage_mode: 'averaged', start_frame: 1, end_frame: 2,
      ccd_indices: [0], dispersion_calibration_id: draft.version.conditions.dispersion_calibration_id, line_ids: [ids[index]] })),
  } }, 'PATCH')
  await call(page, `/api/v1/methods/${method.id}/publish`, {})
  await call(page, '/api/v1/methods/current', { method_id: method.id })
}

export async function checkPreliminaryContinuousCapture(page, checks) {
  await prepareContinuousCaptureMethod(page)
  await page.reload()
  await page.setViewportSize({ width: 1060, height: 680 })
  for (const { mode, label, domain, create } of [
    { mode: 'dispersion', label: '色散摄谱', domain: 'dispersion', create: 'capture-sessions' },
    { mode: 'evaporation-acquisition', label: '蒸发摄谱', domain: 'acquisitions', create: 'evaporation-sessions' },
  ]) {
    for (const single of [false, true]) {
      const task = await call(page, `/api/v1/${domain}/${create}`, { name: `${label}-${single ? '本角' : '连续'}`, frame_count: 2, dark_frame_count: 0 })
      await page.reload()
      await navigate(page, 'analysis-tests', label, `[data-testid="${mode}-page"]`)
      const host = page.getByTestId(`${mode}-page`)
      await host.locator(`[data-task-id="${task.id}"] .task-open`).click()
      const controls = host.getByLabel('摄谱控制')
      const turnPages = host.getByRole('navigation', { name: '转角摄谱页面' })
      await turnPages.getByRole('button', { name: /17°/ }).waitFor()
      if (single) await turnPages.getByRole('button', { name: /17°/ }).click()
      const names = ['试样摄谱', '仅摄本转角', '预热摄谱', '停止摄谱', '结束']
      for (const name of names) assert.equal(await controls.getByRole('button', { name, exact: true }).isVisible(), true)
      const response = page.waitForResponse(reply => /\/tasks\/\d+\/start$/.test(new URL(reply.url()).pathname) && reply.request().method() === 'POST')
      await controls.getByRole('button', { name: single ? '仅摄本转角' : '试样摄谱', exact: true }).click()
      const received = await response
      assert.equal(received.status(), 200, await received.text())
      assert.equal(new URL(received.url()).searchParams.has('continuous'), !single)
      const last = task.capture_turns[1].id
      await turnPages.getByRole('button', { name: /17°.*完成/ }).waitFor({ timeout: 12000 })
      const [firstTurn, lastTurn] = await Promise.all([call(page, `/api/v1/${domain}/tasks/${task.id}`), call(page, `/api/v1/${domain}/tasks/${last}`)])
      assert.equal(firstTurn.status, single ? 'draft' : 'completed')
      assert.equal(lastTurn.status, 'completed')
      assert.equal(lastTurn.burn_frames_captured, 2)
      await controls.getByRole('button', { name: '结束', exact: true }).click()
    }
    checks.push(`${label}在 1060×680 显示五个操作，连续与仅摄本角分开执行`)
  }
  const queue = await call(page, '/api/v1/sample-queues', { name: '双转角验证', items: [{ pre_name: 'QA01', repeats: 1 }] })
  await call(page, '/api/v1/sample-queues/current', { queue_id: queue.id }, 'PUT')
  const task = await call(page, '/api/v1/acquisitions/sample-sessions', { name: '样品双角实时验证' })
  await page.reload()
  await navigate(page, 'analysis-tests', '样品摄谱', '[data-testid="sample-acquisition-page"]')
  const host = page.getByTestId('sample-acquisition-page')
  await host.locator(`[data-task-id="${task.id}"] .task-open`).click()
  const response = page.waitForResponse(reply => new URL(reply.url()).pathname === `/api/v1/acquisitions/tasks/${task.id}/start` && reply.request().method() === 'POST')
  await host.getByRole('button', { name: '试样摄谱', exact: true }).click()
  const received = await response
  assert.equal(received.status(), 200, await received.text())
  assert.equal(new URL(received.url()).searchParams.get('continuous'), 'true')
  await host.getByRole('navigation', { name: '转角摄谱页面' }).getByRole('button', { name: /17°.*已采/ }).waitFor({ timeout: 12000 })
  const complete = await call(page, `/api/v1/acquisitions/tasks/${task.id}`)
  assert.equal(complete.status, 'completed')
  assert.equal(complete.completed_repeats, 1)
  assert.deepEqual([...new Set(complete.samples[0].bands.map(band => band.turn_index))], [0, 1])
  await host.getByRole('button', { name: '结束', exact: true }).click()
  checks.push('样品摄谱一次启动双角，整次重复及逐角谱带均完成')
}
