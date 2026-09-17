/** sampleQueues requests and models; moved without changing payloads or responses. */
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
  status: 'draft' | 'ready' | 'completed'
  record_count: number
  expanded_bands: number
  items: SampleQueueItem[]
  created_at: string
  updated_at: string
}

export const sampleQueuesApi = {
  sampleQueues: (token: string) => request<SampleQueue[]>('/api/v1/sample-queues', { headers: { Authorization: `Bearer ${token}` } }),
  createSampleQueue: (token: string, payload: { name: string; items: Array<{ pre_name: string; repeats: number }> }) => request<SampleQueue>('/api/v1/sample-queues', { method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify(payload) }),
  updateSampleQueue: (token: string, queueId: number, items: Array<{ pre_name: string; repeats: number }>) => request<SampleQueue>(`/api/v1/sample-queues/${queueId}`, { method: 'PATCH', headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify({ items }) }),
  renameSampleItem: (token: string, queueId: number, itemId: number, postName: string) => request<SampleQueue>(`/api/v1/sample-queues/${queueId}/items/${itemId}/rename`, { method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify({ post_name: postName }) }),
  deleteSampleItem: (token: string, queueId: number, itemId: number) => request<SampleQueue>(`/api/v1/sample-queues/${queueId}/items/${itemId}`, { method: 'DELETE', headers: { Authorization: `Bearer ${token}` } }),
  clearSampleQueue: (token: string, queueId: number) => request<SampleQueue>(`/api/v1/sample-queues/${queueId}/clear`, { method: 'POST', headers: { Authorization: `Bearer ${token}` } }),
  importSampleQueue: (token: string, filename: string, content: string, queueName?: string) => request<SampleQueue & { source_sha256: string }>('/api/v1/sample-queues/import', { method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: JSON.stringify({ filename, content, queue_name: queueName }) }),
  exportSampleQueue: async (token: string, queueId: number) => {
    const response = await requestRaw(`/api/v1/sample-queues/${queueId}/export`, { headers: { Authorization: `Bearer ${token}` } })
    return { blob: await response.blob(), filename: response.headers.get('Content-Disposition') ?? `queue-${queueId}.sam` }
  },
}
