/** 样号、重复数、顺序和 SAM 文件接口；采集完成计数及关联由后端维护。 */
import { request, requestRaw } from './client'

export type SampleQueueItem = {
  id: number
  queue_id: number
  position: number
  source_name: string
  pre_name: string
  post_name: string | null
  repeats: number
  expanded_bands: number
  spectrum_hash: string | null
  created_at: string
  updated_at: string
}

export type SampleQueue = {
  id: number
  name: string
  name_length: 10 | 12 | 20
  status: 'draft' | 'ready' | 'completed'
  record_count: number
  expanded_bands: number
  items: SampleQueueItem[]
  created_at: string
  updated_at: string
}

export const sampleQueuesApi = {
  sampleQueues: /* 读取样品队列历史列表。 */ (token: string) =>
    request<SampleQueue[]>('/api/v1/sample-queues', { headers: { Authorization: `Bearer ${token}` } }),
  createSampleQueue: /* 创建样品队列，返回服务处理结果。 */ (
    token: string,
    payload: {
      name: string
      name_length?: 12 | 20
      items: Array<{ id?: number; pre_name: string; repeats: number }>
    }
  ) =>
    request<SampleQueue>('/api/v1/sample-queues', {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
      body: JSON.stringify(payload)
    }),
  updateSampleQueue: /* 更新样品队列，返回服务处理结果。 */ (
    token: string,
    queueId: number,
    items: Array<{ id?: number; pre_name: string; repeats: number }>,
    nameLength?: 12 | 20
  ) =>
    request<SampleQueue>(`/api/v1/sample-queues/${queueId}`, {
      method: 'PATCH',
      headers: { Authorization: `Bearer ${token}` },
      body: JSON.stringify({ items, name_length: nameLength })
    }),
  renameSampleItem: /* 保存队列条目的采集后名称。 */ (
    token: string,
    queueId: number,
    itemId: number,
    postName: string
  ) =>
    request<SampleQueue>(`/api/v1/sample-queues/${queueId}/items/${itemId}/rename`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
      body: JSON.stringify({ post_name: postName })
    }),
  deleteSampleItem: /* 删除尚可编辑的单个队列条目。 */ (token: string, queueId: number, itemId: number) =>
    request<SampleQueue>(`/api/v1/sample-queues/${queueId}/items/${itemId}`, {
      method: 'DELETE',
      headers: { Authorization: `Bearer ${token}` }
    }),
  clearSampleQueue: /* 清空指定队列中允许删除的条目。 */ (token: string, queueId: number) =>
    request<SampleQueue>(`/api/v1/sample-queues/${queueId}/clear`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` }
    }),
  importSampleQueue: /* 解码文本或原始字节并导入旧 SAM 队列。 */ (
    token: string,
    filename: string,
    content: string | Uint8Array,
    queueName?: string,
    lastModifiedMs?: number,
    encoding?: 'gb18030' | 'utf-8-sig'
  ) =>
    request<SampleQueue & { source_sha256: string }>('/api/v1/sample-queues/import', {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
      body: JSON.stringify({
        filename,
        ...(typeof content === 'string' ? {content} : {content_base64: btoa(Array.from(content, byte => String.fromCharCode(byte)).join(''))}),
        encoding,
        last_modified_ms: lastModifiedMs,
        queue_name: queueName
      })
    }),
  exportSampleQueue: /* 生成 SAM 文件并记录输出摘要。 */ async (token: string, queueId: number) => {
    const response = await requestRaw(`/api/v1/sample-queues/${queueId}/export`, {
      headers: { Authorization: `Bearer ${token}` }
    })
    return {
      blob: await response.blob(),
      filename: response.headers.get('Content-Disposition') ?? `queue-${queueId}.sam`
    }
  }
}
