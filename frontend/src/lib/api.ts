export interface HealthResponse {
  status: string
}

export interface ChannelResponse {
  id: number
  name: string
  provider: string
  kind: string
  enabled: boolean
  publicConfig: Record<string, unknown>
  secretConfigured: boolean
  secretConfigMask: Record<string, string>
  lastTestStatus?: string | null
}

export interface SummaryChannel {
  provider: string
  name: string
  latestSnapshotTotalUsd?: string | null
}

export interface SummaryAccountCategoryTotal {
  provider: string
  channelName: string
  accountScope: string
  valueUsd: string | null
  assetCount: number
}

export interface SummaryResponse {
  totalValueUsd: string | null
  assetCount: number
  accountCategoryTotals: SummaryAccountCategoryTotal[]
  channels: SummaryChannel[]
}

export interface SnapshotItem {
  id: number
  status: string
  totalValueUsd: string
  createdAt: string
  snapshotCount: number
}

export interface SnapshotDetailResponse {
  id: number
  channel_id: number
  channelName?: string | null
  provider?: string | null
  status: string
  totalValueUsd: string
  total_value_usd: string
}

export interface RunSnapshotResponse {
  id: number
  status: string
  successCount: number
  failureCount: number
  totalValueUsd: string
}

export interface ScheduleResponse {
  snapshotScheduleTimes: string
  okxDexApiKey?: string
  okxDexSecretConfigured?: boolean
}

export interface SchedulerResponse {
  enabled: boolean
  snapshot_schedule_times: string
  timezone: string
  jobs: Array<{ id: string; trigger?: string }>
}

export interface CreateChannelPayload {
  provider: string
  kind: string
  name: string
  publicConfig: Record<string, unknown>
  secretConfig: Record<string, string>
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
    ...init,
  })
  if (!response.ok) {
    let detail = ''
    try {
      const body = await response.json()
      detail = (body as { detail?: string }).detail ?? ''
    } catch {
      // response body is not JSON
    }
    throw new Error(detail || `Request failed: ${response.status} ${response.statusText}`)
  }
  if (response.status === 204) {
    return undefined as T
  }
  return (await response.json()) as T
}

export const api = {
  getHealth: () => requestJson<HealthResponse>('/api/health'),
  getLatestSummary: () => requestJson<SummaryResponse>('/api/summary/latest'),
  getLiveSummary: () => requestJson<SummaryResponse>('/api/summary/live'),
  getChannels: () => requestJson<ChannelResponse[]>('/api/channels'),
  createChannel: (payload: CreateChannelPayload) =>
    requestJson<ChannelResponse>('/api/channels', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  updateChannel: (channelId: number, payload: CreateChannelPayload) =>
    requestJson<ChannelResponse>(`/api/channels/${channelId}`, {
      method: 'PUT',
      body: JSON.stringify(payload),
    }),
  deleteChannel: (channelId: number) =>
    requestJson<void>(`/api/channels/${channelId}`, { method: 'DELETE' }),
  testChannel: (channelId: number) =>
    requestJson<{ status: string }>(`/api/channels/${channelId}/test`, {
      method: 'POST',
    }),
  getSnapshots: () => requestJson<SnapshotItem[]>('/api/snapshots/series'),
  getSnapshotDetail: (snapshotId: number) =>
    requestJson<SnapshotDetailResponse>(`/api/snapshots/${snapshotId}`),
  deleteSnapshotRun: (runId: number) =>
    requestJson<void>(`/api/snapshots/runs/${runId}`, { method: 'DELETE' }),
  runSnapshot: () =>
    requestJson<RunSnapshotResponse>('/api/snapshots/run', {
      method: 'POST',
    }),
  getSchedule: () => requestJson<ScheduleResponse>('/api/schedule'),
  updateSchedule: (payload: ScheduleResponse) =>
    requestJson<ScheduleResponse>('/api/schedule', {
      method: 'PUT',
      body: JSON.stringify(payload),
    }),
  getScheduler: () => requestJson<SchedulerResponse>('/api/system/scheduler'),
  updateScheduler: (enabled: boolean) =>
    requestJson<SchedulerResponse>('/api/system/scheduler', {
      method: 'PUT',
      body: JSON.stringify({ enabled }),
    }),
}
