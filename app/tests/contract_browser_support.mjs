import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import path from 'node:path'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'

const app = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')

// 在已登录的隔离页面中调用真实 API，桌面密钥只留在页面与进程内存。
export async function call(page, url, body, method = body === undefined ? 'GET' : 'POST') {
  const result = await page.evaluate(
    /* 验证隔离桌面操作或处理测试响应。 */ async ({ url, body, method }) => {
      const config = window.__TAURI__?.core
        ? await window.__TAURI__.core.invoke('runtime_config')
        : null
      const response = await fetch(config ? `${config.api_base}${url}` : url, {
        method, headers: { 'Content-Type': 'application/json',
          Authorization: `Bearer ${sessionStorage.getItem('geospectrum.token')}`,
          ...(config ? { 'X-GeoSpectrum-Process-Key': config.process_key } : {}) },
        ...(body === undefined ? {} : { body: JSON.stringify(body) }),
      })
      const text = await response.text()
      return { status: response.status, value: text ? JSON.parse(text) : null }
    },
    { url, body, method }
  )
  assert.ok(result.status >= 200 && result.status < 300, `${method} ${url}: ${JSON.stringify(result.value)}`)
  return result.value
}

// 使用既有键盘导航，避免悬停计时影响测试菜单的展开状态。
export async function navigate(page, group, label, selector) {
  const trigger = page.locator(`[data-navigation-group="${group}"]`)
  await trigger.focus()
  await trigger.press('ArrowRight')
  await page.getByRole('menuitem', { name: label }).click()
  await page.keyboard.press('Escape')
  await page.locator(selector).waitFor()
}

// 在同一真实库贯通方法、队列、模拟采集、分析、报告与在线备份。