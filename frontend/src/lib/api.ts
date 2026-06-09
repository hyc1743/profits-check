export interface HealthResponse {
  status: string
}

export interface AuthSessionResponse {
  authenticated: boolean
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

export interface PortfolioItem {
  key: string
  channelId: number
  channelName: string
  provider: string
  accountScope: string
  assetSymbol: string
  label: string
  quantity: string | null
  valueUsd: string | null
  includedInTotals: boolean
}

export interface SummaryResponse {
  totalValueUsd: string | null
  assetCount: number
  accountCategoryTotals: SummaryAccountCategoryTotal[]
  portfolioItems?: PortfolioItem[]
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

export interface OnchainChainOption {
  chainIndex: string
  chainName: string
  shortName: string
  defaultSelected: boolean
}

export interface SchedulerResponse {
  enabled: boolean
  snapshot_schedule_times: string
  timezone: string
  jobs: Array<{ id: string; trigger?: string }>
}

export interface LiquidationMonitorConfig {
  monitorEnabled: boolean
  alertEnabled: boolean
  thresholdPercent: string
  positionMonitorEnabled: boolean
  positionThresholdPercent: string
  marginBalanceMonitorEnabled: boolean
  marginBalanceThresholdPercent: string
  adlMonitorEnabled: boolean
  adlThresholdPercent: string
  adlWindowSeconds: number
  adlSampleIntervalSeconds: number
  adlStartTime: string
  adlEndTime: string
  checkIntervalSeconds: number
  alertIntervalSeconds: number
  miaoCodeConfigured: boolean
  barkPushUrlConfigured: boolean
  miaoCode?: string
  barkPushUrl?: string
}

export interface LiquidationPositionResponse {
  id: number
  channelId: number
  provider: string
  channelName: string
  symbol: string
  side: string
  quantity: string
  entryPrice?: string | null
  markPrice: string
  liquidationPrice?: string | null
  distancePercent?: string | null
  thresholdPercent: string
  status: string
  unrealizedPnl?: string | null
  marginMode?: string | null
  leverage?: string | null
  lastAlertStatus?: string | null
  lastAlertError?: string | null
  lastAlertAt?: string | null
  updatedAt: string
}

export interface LiquidationMonitorResponse {
  config: LiquidationMonitorConfig
  positions: LiquidationPositionResponse[]
  marginBalances: LiquidationMarginBalanceResponse[]
  adlEvents: AdlEventResponse[]
  status?: string
  alertCount?: number
  failureCount?: number
}

export interface LiquidationMarginBalanceResponse {
  id: string
  channelId: number
  provider: string
  channelName: string
  walletBalance: string
  marginBalance: string
  unrealizedPnl?: string | null
  riskPercent?: string | null
  thresholdPercent: string
  status: string
  lastAlertStatus?: string | null
  lastAlertError?: string | null
  lastAlertAt?: string | null
}

export interface AdlEventResponse {
  id: number
  channelId: number
  provider: string
  channelName: string
  symbol: string
  side: string
  previousQuantity: string
  currentQuantity: string
  dropPercent: string
  thresholdPercent: string
  windowSeconds: number
  status: string
  lastAlertStatus?: string | null
  lastAlertError?: string | null
  lastAlertAt?: string | null
  detectedAt: string
}

export interface UpdateLiquidationMonitorPayload {
  monitorEnabled: boolean
  positionMonitorEnabled: boolean
  positionThresholdPercent: string
  marginBalanceMonitorEnabled: boolean
  marginBalanceThresholdPercent: string
  adlMonitorEnabled: boolean
  adlThresholdPercent: string
  adlWindowSeconds: number
  adlSampleIntervalSeconds: number
  adlStartTime: string
  adlEndTime: string
  checkIntervalSeconds: number
  alertIntervalSeconds: number
  miaoCode?: string
  barkPushUrl?: string
}

export interface ResetSystemResponse {
  status: string
  deletedChannels: number
  deletedSnapshots: number
  deletedAssets: number
}

export interface CreateChannelPayload {
  provider: string
  kind: string
  name: string
  publicConfig: Record<string, unknown>
  secretConfig: Record<string, string>
}

export interface UpdatePortfolioInclusionRulesPayload {
  items: Array<{
    key: string
    includedInTotals: boolean
  }>
}

export interface FundingFeeChannelSummary {
  channelId: number
  channelName: string
  provider: string
  received: string
  paid: string
  net: string
  recordsCount: number
  status: string
  error?: string | null
}

export interface FundingFeeDailySummary {
  date: string
  received: string
  paid: string
  net: string
  recordsCount: number
}

export interface FundingFeeSummaryResponse {
  date: string
  startTime: string
  endTime: string
  received: string
  paid: string
  net: string
  recordsCount: number
  recentDays: FundingFeeDailySummary[]
  channels: FundingFeeChannelSummary[]
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    credentials: 'include',
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
    const error = new Error(detail || `Request failed: ${response.status} ${response.statusText}`)
    if (response.status === 401) {
      window.dispatchEvent(new Event('profits-check:unauthorized'))
    }
    throw error
  }
  if (response.status === 204) {
    return undefined as T
  }
  return (await response.json()) as T
}

export const api = {
  getAuthSession: () => requestJson<AuthSessionResponse>('/api/auth/session'),
  login: (password: string) =>
    requestJson<AuthSessionResponse>('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({ password }),
    }),
  logout: () =>
    requestJson<AuthSessionResponse>('/api/auth/logout', {
      method: 'POST',
    }),
  getHealth: () => requestJson<HealthResponse>('/api/health'),
  getLatestSummary: () => requestJson<SummaryResponse>('/api/summary/latest'),
  getLiveSummary: () => requestJson<SummaryResponse>('/api/summary/live'),
  getFundingFees: (date: string) =>
    requestJson<FundingFeeSummaryResponse>(`/api/funding-fees?date=${encodeURIComponent(date)}`),
  updatePortfolioInclusionRules: (payload: UpdatePortfolioInclusionRulesPayload) =>
    requestJson<UpdatePortfolioInclusionRulesPayload>('/api/portfolio-inclusion-rules', {
      method: 'PUT',
      body: JSON.stringify(payload),
    }),
  getChannels: () => requestJson<ChannelResponse[]>('/api/channels'),
  getOnchainChains: () => requestJson<OnchainChainOption[]>('/api/onchain/chains'),
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
  clearSnapshots: () => requestJson<void>('/api/snapshots', { method: 'DELETE' }),
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
  getLiquidationMonitor: () =>
    requestJson<LiquidationMonitorResponse>('/api/liquidation-monitor'),
  refreshLiquidationMonitor: () =>
    requestJson<LiquidationMonitorResponse>('/api/liquidation-monitor/refresh', {
      method: 'POST',
    }),
  updateLiquidationMonitor: (payload: UpdateLiquidationMonitorPayload) =>
    requestJson<LiquidationMonitorResponse>('/api/liquidation-monitor', {
      method: 'PUT',
      body: JSON.stringify(payload),
    }),
  testLiquidationAlert: () =>
    requestJson<{ status: string; error?: string }>('/api/liquidation-monitor/test-alert', {
      method: 'POST',
    }),
  testMiaotixingAlert: () =>
    requestJson<{ status: string; error?: string }>('/api/liquidation-monitor/test-alert/miaotixing', {
      method: 'POST',
    }),
  testBarkAlert: () =>
    requestJson<{ status: string; error?: string }>('/api/liquidation-monitor/test-alert/bark', {
      method: 'POST',
    }),
  resetSystem: () =>
    requestJson<ResetSystemResponse>('/api/system/reset', {
      method: 'POST',
    }),
}
