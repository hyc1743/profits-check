import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import * as echarts from 'echarts'
import type { EChartsOption } from 'echarts'
import { HttpResponse, http } from 'msw'
import { vi } from 'vitest'

import App from './App'
import { ChartSurface } from './components/chart-surface'
import { server } from './test/setup'

const summaryPayload = {
  totalValueUsd: '4025.00000000',
  assetCount: 2,
  accountCategoryTotals: [
    {
      provider: 'onchain',
      channelName: 'EVM Wallets',
      accountScope: 'token_total',
      valueUsd: '4025.00000000',
      assetCount: 2,
    },
  ],
  portfolioItems: [
    {
      key: 'channel:1|provider:onchain|scope:token_total|asset:ONCHAIN_TOTAL',
      channelId: 1,
      channelName: 'EVM Wallets',
      provider: 'onchain',
      accountScope: 'token_total',
      assetSymbol: 'ONCHAIN_TOTAL',
      label: 'EVM Wallets · token_total · ONCHAIN_TOTAL',
      quantity: '0E-8',
      valueUsd: '4025.00000000',
      includedInTotals: true,
    },
  ],
  channels: [{ provider: 'onchain', name: 'EVM Wallets', latestSnapshotTotalUsd: '4025.00000000' }],
}

const liveSummaryPayload = {
  totalValueUsd: '5250.00000000',
  assetCount: 3,
  accountCategoryTotals: [
    {
      provider: 'binance',
      channelName: '主账户',
      accountScope: 'spot',
      valueUsd: '3250.00000000',
      assetCount: 1,
    },
    {
      provider: 'binance',
      channelName: '主账户',
      accountScope: 'futures',
      valueUsd: '1200.00000000',
      assetCount: 1,
    },
    {
      provider: 'binance',
      channelName: '主账户',
      accountScope: 'earn',
      valueUsd: '800.00000000',
      assetCount: 1,
    },
  ],
  portfolioItems: [
    {
      key: 'channel:1|provider:binance|scope:spot|asset:BTC',
      channelId: 1,
      channelName: '主账户',
      provider: 'binance',
      accountScope: 'spot',
      assetSymbol: 'BTC',
      label: '主账户 · spot · BTC',
      quantity: '0.05000000',
      valueUsd: '3250.00000000',
      includedInTotals: true,
    },
    {
      key: 'channel:1|provider:binance|scope:futures|asset:USDT',
      channelId: 1,
      channelName: '主账户',
      provider: 'binance',
      accountScope: 'futures',
      assetSymbol: 'USDT',
      label: '主账户 · futures · USDT',
      quantity: '1200.00000000',
      valueUsd: '1200.00000000',
      includedInTotals: true,
    },
    {
      key: 'channel:1|provider:binance|scope:earn|asset:USDT',
      channelId: 1,
      channelName: '主账户',
      provider: 'binance',
      accountScope: 'earn',
      assetSymbol: 'USDT',
      label: '主账户 · earn · USDT',
      quantity: '800.00000000',
      valueUsd: '800.00000000',
      includedInTotals: true,
    },
  ],
  channels: [{ provider: 'onchain', name: 'EVM Wallets', latestSnapshotTotalUsd: '5250.00000000' }],
}

const channelsPayload = [
  {
    id: 1,
    name: 'EVM Wallets',
    provider: 'onchain',
    kind: 'chain',
    enabled: true,
    publicConfig: {
      walletAddresses: ['0x1111111111111111111111111111111111111111'],
      chainIndexes: ['1', '56'],
    },
    secretConfigured: false,
    secretConfigMask: {},
    lastTestStatus: 'ok',
  },
]

const onchainChainsPayload = [
  { chainIndex: '1', chainName: 'Ethereum', shortName: 'ETH', defaultSelected: true },
  { chainIndex: '56', chainName: 'BNB Smart Chain', shortName: 'BSC', defaultSelected: true },
  { chainIndex: '137', chainName: 'Polygon', shortName: 'POL', defaultSelected: false },
]

const snapshotsPayload = [
  { id: 4, status: 'success', totalValueUsd: '4025.00000000', createdAt: '2026-05-09T08:00:00+00:00', snapshotCount: 1 },
  { id: 5, status: 'success', totalValueUsd: '5250.00000000', createdAt: '2026-05-10T08:00:00+00:00', snapshotCount: 2 },
]

const schedulePayload = {
  snapshotScheduleTimes: '08:00',
  okxDexApiKey: '',
  okxDexSecretConfigured: false,
}

const schedulerPayload = {
  enabled: true,
  snapshot_schedule_times: '08:00',
  timezone: 'Asia/Shanghai',
  jobs: [{ id: 'scheduled-snapshot' }],
}

const liquidationMonitorPayload = {
  config: {
    monitorEnabled: false,
    alertEnabled: false,
    thresholdPercent: '5.00000000',
    positionMonitorEnabled: false,
    positionThresholdPercent: '5.00000000',
    marginBalanceMonitorEnabled: false,
    marginBalanceThresholdPercent: '70.00000000',
    adlMonitorEnabled: false,
    adlThresholdPercent: '40.00000000',
    adlWindowSeconds: 60,
    adlSampleIntervalSeconds: 30,
    adlStartTime: '00:00',
    adlEndTime: '23:59',
    checkIntervalSeconds: 60,
    alertIntervalSeconds: 900,
    miaoCodeConfigured: false,
    barkPushUrlConfigured: false,
  },
  positions: [
    {
      id: 1,
      channelId: 1,
      provider: 'binance',
      channelName: '主账户',
      symbol: 'BTCUSDT',
      side: 'LONG',
      quantity: '0.50000000',
      entryPrice: '60000.00000000',
      markPrice: '58100.00000000',
      liquidationPrice: '58000.00000000',
      distancePercent: '0.17211704',
      thresholdPercent: '5.00000000',
      status: 'warning',
      unrealizedPnl: '-950.00000000',
      marginMode: 'isolated',
      leverage: '20',
      lastAlertStatus: 'sent',
      lastAlertError: null,
      lastAlertAt: '2026-05-12T07:00:00+00:00',
      updatedAt: '2026-05-12T07:00:00+00:00',
    },
  ],
  marginBalances: [
    {
      id: '1:margin-balance',
      channelId: 1,
      provider: 'binance',
      channelName: '主账户',
      walletBalance: '1000.00000000',
      marginBalance: '650.00000000',
      unrealizedPnl: '-350.00000000',
      riskPercent: '65.00000000',
      thresholdPercent: '70.00000000',
      status: 'warning',
      lastAlertStatus: null,
      lastAlertError: null,
      lastAlertAt: null,
    },
  ],
  adlEvents: [
    {
      id: 1,
      channelId: 1,
      provider: 'binance',
      channelName: '主账户',
      symbol: 'BTCUSDT',
      side: 'LONG',
      previousQuantity: '1.00000000',
      currentQuantity: '0.59000000',
      dropPercent: '41.00000000',
      thresholdPercent: '40.00000000',
      windowSeconds: 60,
      status: 'suspected',
      lastAlertStatus: 'sent',
      lastAlertError: null,
      lastAlertAt: '2026-05-12T08:00:30+00:00',
      detectedAt: '2026-05-12T08:00:30+00:00',
    },
  ],
}

const fundingFeesPayload = {
  date: '2026-06-09',
  startTime: '2026-06-09T00:00:00+08:00',
  endTime: '2026-06-10T00:00:00+08:00',
  received: '12.50000000',
  paid: '2.25000000',
  net: '10.25000000',
  recordsCount: 2,
  recentSevenDays: {
    startDate: '2026-06-03',
    endDate: '2026-06-09',
    received: '19.25000000',
    paid: '3.75000000',
    net: '15.50000000',
    recordsCount: 7,
  },
  channels: [
    {
      channelId: 1,
      channelName: '主账户',
      provider: 'binance',
      received: '12.50000000',
      paid: '2.25000000',
      net: '10.25000000',
      recordsCount: 2,
      status: 'success',
      error: null,
    },
  ],
}

test('shows recent seven day funding fee totals', async () => {
  installHandlers()

  render(<App />)

  expect(await screen.findByText('最近 7 天')).toBeInTheDocument()
  expect(await screen.findByText('2026-06-03 至 2026-06-09 · 7 条')).toBeInTheDocument()
  expect(screen.getByText('7 天资金费收取')).toBeInTheDocument()
  expect(screen.getByText('19.25 USD')).toBeInTheDocument()
  expect(screen.getByText('7 天资金费付出')).toBeInTheDocument()
  expect(screen.getByText('3.75 USD')).toBeInTheDocument()
  expect(screen.getByText('7 天净资金费')).toBeInTheDocument()
  expect(screen.getByText('15.50 USD')).toBeInTheDocument()
})

function installHandlers() {
  server.use(
    http.get('/api/auth/session', () => HttpResponse.json({ authenticated: true })),
    http.post('/api/auth/login', () => HttpResponse.json({ authenticated: true })),
    http.post('/api/auth/logout', () => HttpResponse.json({ authenticated: false })),
    http.get('/api/health', () => HttpResponse.json({ status: 'ok' })),
    http.get('/api/summary/latest', () => HttpResponse.json(summaryPayload)),
    http.get('/api/summary/live', () => HttpResponse.json(liveSummaryPayload)),
    http.get('/api/channels', () => HttpResponse.json(channelsPayload)),
    http.get('/api/onchain/chains', () => HttpResponse.json(onchainChainsPayload)),
    http.get('/api/snapshots/series', () => HttpResponse.json(snapshotsPayload)),
    http.get('/api/schedule', () => HttpResponse.json(schedulePayload)),
    http.get('/api/system/scheduler', () => HttpResponse.json(schedulerPayload)),
    http.get('/api/liquidation-monitor', () => HttpResponse.json(liquidationMonitorPayload)),
    http.get('/api/funding-fees', () => HttpResponse.json(fundingFeesPayload)),
    http.post('/api/liquidation-monitor/refresh', () => HttpResponse.json(liquidationMonitorPayload)),
    http.post('/api/liquidation-monitor/test-alert', () => HttpResponse.json({ status: 'sent' })),
    http.post('/api/liquidation-monitor/test-alert/miaotixing', () => HttpResponse.json({ status: 'sent' })),
    http.post('/api/liquidation-monitor/test-alert/bark', () => HttpResponse.json({ status: 'sent' })),
    http.post('/api/snapshots/run', () =>
      HttpResponse.json({
        id: 5,
        status: 'success',
        successCount: 1,
        failureCount: 0,
        totalValueUsd: '5000.00000000',
      }),
    ),
    http.post('/api/channels', async ({ request }) => {
      const body = (await request.json()) as Record<string, unknown>
      return HttpResponse.json({ id: 2, enabled: true, secretConfigured: false, secretConfigMask: {}, ...body }, { status: 201 })
    }),
    http.post('/api/channels/1/test', () => HttpResponse.json({ status: 'ok' })),
    http.put('/api/schedule', async ({ request }) => HttpResponse.json(await request.json())),
    http.put('/api/liquidation-monitor', async ({ request }) => {
      const body = (await request.json()) as Record<string, unknown>
      return HttpResponse.json({
        ...liquidationMonitorPayload,
        config: {
          ...liquidationMonitorPayload.config,
          ...body,
          miaoCodeConfigured: Boolean(body.miaoCode),
          barkPushUrlConfigured: Boolean(body.barkPushUrl),
        },
      })
    }),
    http.put('/api/portfolio-inclusion-rules', async ({ request }) => HttpResponse.json(await request.json())),
    http.put('/api/system/scheduler', async ({ request }) =>
      HttpResponse.json({ ...schedulerPayload, ...((await request.json()) as Record<string, unknown>) }),
    ),
    http.delete('/api/snapshots/runs/:runId', () => new HttpResponse(null, { status: 204 })),
  )
}

test('shows login screen when no session exists', async () => {
  server.use(http.get('/api/auth/session', () => HttpResponse.json({ authenticated: false })))

  render(<App />)

  expect(await screen.findByRole('heading', { name: 'Profits Check' })).toBeInTheDocument()
  expect(screen.getByLabelText('Password')).toBeInTheDocument()
  expect(screen.queryByText('总资产')).not.toBeInTheDocument()
})

test('logs in and loads the dashboard', async () => {
  installHandlers()
  let sessionAuthenticated = false
  const loginRequests: string[] = []
  server.use(
    http.get('/api/auth/session', () => HttpResponse.json({ authenticated: sessionAuthenticated })),
    http.post('/api/auth/login', async ({ request }) => {
      const body = (await request.json()) as { password: string }
      loginRequests.push(body.password)
      sessionAuthenticated = true
      return HttpResponse.json({ authenticated: true })
    }),
  )
  const user = userEvent.setup()

  render(<App />)

  await user.type(await screen.findByLabelText('Password'), 'correct horse battery staple')
  await user.click(screen.getByRole('button', { name: 'Sign in' }))

  expect(loginRequests).toEqual(['correct horse battery staple'])
  expect((await screen.findAllByText('4025.00 USD')).length).toBeGreaterThan(0)
})

test('returns to login when an authenticated request receives 401', async () => {
  installHandlers()
  server.use(http.get('/api/summary/latest', () => HttpResponse.json({ detail: 'Authentication required' }, { status: 401 })))

  render(<App />)

  expect(await screen.findByLabelText('Password')).toBeInTheDocument()
})

test('renders dashboard data and latest snapshot detail', async () => {
  installHandlers()

  render(<App />)

  expect((await screen.findAllByText('4025.00 USD')).length).toBeGreaterThan(0)
  expect(screen.getAllByText('总资产').length).toBeGreaterThan(0)
  expect(screen.queryByText('点击刷新')).not.toBeInTheDocument()
  expect(screen.getByText('按账户类别')).toBeInTheDocument()
  expect(screen.getByText('资产走势')).toBeInTheDocument()
  expect(screen.getByText('资产分布')).toBeInTheDocument()
  expect(screen.getByText('渠道占比与账户类别。')).toBeInTheDocument()
  expect(screen.getByRole('table', { name: '资产走势数据' })).toBeInTheDocument()
  expect(screen.getByRole('list', { name: '渠道占比数据' })).not.toBeVisible()
  expect(screen.getByText('EVM Wallets · 链上代币总估值')).not.toBeVisible()

  const totalAssetMetric = screen.getAllByText('总资产')[0].closest('.metric-card')
  const trendHeading = screen.getByRole('heading', { name: '资产走势' })
  const channelShareHeading = screen.getByRole('heading', { name: '渠道占比' })
  const accountHeading = screen.getByRole('heading', { name: '按账户类别' })

  expect(totalAssetMetric?.compareDocumentPosition(trendHeading)).toBe(Node.DOCUMENT_POSITION_FOLLOWING)
  expect(trendHeading.compareDocumentPosition(channelShareHeading)).toBe(Node.DOCUMENT_POSITION_FOLLOWING)
  expect(channelShareHeading.compareDocumentPosition(accountHeading)).toBe(Node.DOCUMENT_POSITION_FOLLOWING)
})

test('defaults to light theme and toggles theme from the top bar', async () => {
  installHandlers()
  const user = userEvent.setup()

  render(<App />)

  expect(await screen.findByRole('button', { name: 'Dark mode' })).toBeInTheDocument()
  expect(document.documentElement).toHaveAttribute('data-theme', 'light')

  await user.click(screen.getByRole('button', { name: 'Dark mode' }))

  expect(document.documentElement).toHaveAttribute('data-theme', 'dark')
  expect(screen.getByRole('button', { name: 'Light mode' })).toBeInTheDocument()
})

test('keeps asset distribution details collapsed until opened', async () => {
  installHandlers()
  const user = userEvent.setup()

  render(<App />)

  expect((await screen.findAllByText('4025.00 USD')).length).toBeGreaterThan(0)
  expect(screen.getByRole('list', { name: '渠道占比数据' })).not.toBeVisible()
  expect(screen.getByText('EVM Wallets · 链上代币总估值')).not.toBeVisible()

  await user.click(screen.getByText('渠道占比'))

  expect(screen.getByRole('list', { name: '渠道占比数据' })).toBeVisible()
  expect(screen.getByText('100%')).toBeInTheDocument()
  expect(screen.getByText('EVM Wallets · 链上代币总估值')).not.toBeVisible()

  await user.click(screen.getByText('按账户类别'))

  expect(screen.getByText('EVM Wallets · 链上代币总估值')).toBeVisible()
})

test('live refresh shows account categories', async () => {
  installHandlers()
  const user = userEvent.setup()

  render(<App />)

  await user.click(await screen.findByRole('button', { name: '刷新资产' }))

  expect(screen.getByText('主账户 · 现货')).toBeInTheDocument()
  expect(screen.getByText('主账户 · 合约')).toBeInTheDocument()
  expect(screen.getByText('主账户 · 理财')).toBeInTheDocument()
})

test('updates portfolio inclusion rules from settings', async () => {
  installHandlers()
  const updates: unknown[] = []
  server.use(
    http.put('/api/portfolio-inclusion-rules', async ({ request }) => {
      const body = await request.json()
      updates.push(body)
      return HttpResponse.json(body)
    }),
  )
  const user = userEvent.setup()

  render(<App />)

  await user.click(await screen.findByRole('button', { name: '设置' }))
  const checkbox = await screen.findByRole('checkbox', { name: /EVM Wallets.*ONCHAIN_TOTAL/ })
  expect(checkbox).toBeChecked()

  await user.click(checkbox)

  await waitFor(() => {
    expect(updates).toEqual([
      {
        items: [
          {
            key: 'channel:1|provider:onchain|scope:token_total|asset:ONCHAIN_TOTAL',
            includedInTotals: false,
          },
        ],
      },
    ])
  })
})

test('shows liquidation risk positions without refreshing on initial dashboard load', async () => {
  installHandlers()
  let refreshCount = 0
  server.use(
    http.post('/api/liquidation-monitor/refresh', () => {
      refreshCount += 1
      return HttpResponse.json(liquidationMonitorPayload)
    }),
  )
  const user = userEvent.setup()

  render(<App />)

  expect(await screen.findByText('爆仓风险')).toBeInTheDocument()
  expect(refreshCount).toBe(0)
  expect(screen.getByText('主账户 · BTCUSDT')).toBeInTheDocument()
  expect(screen.getByText('0%')).toBeInTheDocument()
  expect(screen.queryByText('0.1721%')).not.toBeInTheDocument()
  expect(screen.getByText('58100.00 USD')).toBeInTheDocument()
  expect(screen.getByText('58000.00 USD')).toBeInTheDocument()
  expect(screen.getByText('已提醒')).toBeInTheDocument()

  await user.click(screen.getByRole('button', { name: '刷新爆仓风险' }))
  await waitFor(() => expect(refreshCount).toBe(1))
})

test('shows pending state only while manual liquidation refresh is pending', async () => {
  installHandlers()
  type JsonResponse = ReturnType<typeof HttpResponse.json>
  let resolveRefresh: (response: JsonResponse) => void = () => {}
  server.use(
    http.post('/api/liquidation-monitor/refresh', () =>
      new Promise<JsonResponse>((resolve) => {
        resolveRefresh = resolve
      }),
    ),
  )

  render(<App />)

  expect(await screen.findByText('爆仓风险')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: '刷新爆仓风险' })).toBeEnabled()

  await userEvent.click(screen.getByRole('button', { name: '刷新爆仓风险' }))
  expect(screen.getByRole('button', { name: '刷新中...' })).toBeDisabled()

  resolveRefresh(HttpResponse.json(liquidationMonitorPayload))
  expect(await screen.findByRole('button', { name: '刷新爆仓风险' })).toBeEnabled()
})

test('switches liquidation risk panel to margin balance risk by channel', async () => {
  installHandlers()
  const user = userEvent.setup()

  render(<App />)

  expect(await screen.findByRole('button', { name: '仓位风险' })).toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: '保证金余额' }))

  expect(screen.getByLabelText('爆仓风险保证金余额')).toBeInTheDocument()
  expect(screen.getByText('主账户 · Binance')).toBeInTheDocument()
  expect(screen.getByText('65%')).toBeInTheDocument()
  expect(screen.queryByText('65.0000%')).not.toBeInTheDocument()
  expect(screen.getByText('1000.00 USD')).toBeInTheDocument()
  expect(screen.getByText('650.00 USD')).toBeInTheDocument()
})

test('switches liquidation risk panel to suspected ADL events', async () => {
  installHandlers()
  const user = userEvent.setup()

  render(<App />)

  expect(await screen.findByRole('button', { name: 'ADL 检测' })).toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: 'ADL 检测' }))

  expect(screen.getByLabelText('ADL 检测事件')).toBeInTheDocument()
  expect(screen.getByText('主账户 · BTCUSDT')).toBeInTheDocument()
  expect(screen.getByText('LONG · 疑似 ADL')).toBeInTheDocument()
  expect(screen.getByText('41%')).toBeInTheDocument()
  expect(screen.getByText('1.00000000')).toBeInTheDocument()
  expect(screen.getByText('0.59000000')).toBeInTheDocument()
  expect(screen.getByText('2026-05-12 16:00:30')).toBeInTheDocument()
})

test('shows infinity and no-risk copy when liquidation price is unavailable', async () => {
  installHandlers()
  const unavailableLiquidationMonitorPayload = {
    ...liquidationMonitorPayload,
    positions: [
      {
        ...liquidationMonitorPayload.positions[0],
        id: 2,
        side: 'BOTH',
        liquidationPrice: null,
        distancePercent: null,
        status: 'unavailable',
        lastAlertStatus: null,
      },
    ],
  }
  server.use(
    http.get('/api/liquidation-monitor', () => HttpResponse.json(unavailableLiquidationMonitorPayload)),
    http.post('/api/liquidation-monitor/refresh', () => HttpResponse.json(unavailableLiquidationMonitorPayload)),
  )

  render(<App />)

  expect(await screen.findByText('主账户 · BTCUSDT')).toBeInTheDocument()
  expect(screen.getByText('BOTH · 无爆仓风险')).toBeInTheDocument()
  expect(screen.getAllByText('∞')).toHaveLength(2)
  expect(screen.queryByText('清算价不可用')).not.toBeInTheDocument()
  expect(screen.queryByText('未估值')).not.toBeInTheDocument()
})

test('saves liquidation monitor switches frequency threshold and test alert', async () => {
  installHandlers()
  const monitorUpdates: Array<Record<string, unknown>> = []
  let testAlertCalled = false
  server.use(
    http.put('/api/liquidation-monitor', async ({ request }) => {
      const body = (await request.json()) as Record<string, unknown>
      monitorUpdates.push(body)
      return HttpResponse.json({
        ...liquidationMonitorPayload,
        config: {
          ...liquidationMonitorPayload.config,
          ...body,
          miaoCodeConfigured: Boolean(body.miaoCode),
          barkPushUrlConfigured: Boolean(body.barkPushUrl),
        },
      })
    }),
    http.post('/api/liquidation-monitor/test-alert/miaotixing', () => {
      testAlertCalled = true
      return HttpResponse.json({ status: 'sent' })
    }),
    http.post('/api/liquidation-monitor/test-alert/bark', () => {
      testAlertCalled = true
      return HttpResponse.json({ status: 'sent' })
    }),
  )
  const user = userEvent.setup()

  render(<App />)

  await user.click(await screen.findByRole('button', { name: '设置' }))
  await user.click(screen.getByLabelText('开启仓位风险监控'))
  await user.click(screen.getByLabelText('开启保证金余额监控'))
  expect(screen.queryByLabelText('开启电话提醒')).not.toBeInTheDocument()
  expect(screen.getByLabelText('仓位风险阈值')).toHaveValue(5)
  expect(screen.getByLabelText('保证金余额阈值')).toHaveValue(70)
  await user.clear(screen.getByLabelText('仓位风险阈值'))
  await user.type(screen.getByLabelText('仓位风险阈值'), '2')
  await user.clear(screen.getByLabelText('保证金余额阈值'))
  await user.type(screen.getByLabelText('保证金余额阈值'), '75')
  await user.clear(screen.getByLabelText('监控频率'))
  await user.type(screen.getByLabelText('监控频率'), '45')
  await user.clear(screen.getByLabelText('提醒频率'))
  await user.type(screen.getByLabelText('提醒频率'), '120')
  await user.type(screen.getByLabelText('喵码'), 'miao-123')
  await user.type(screen.getByLabelText('Bark Push URL'), 'https://bark.example.com/device-key')
  await user.click(screen.getByRole('button', { name: '保存爆仓监控' }))

  await waitFor(() =>
    expect(monitorUpdates).toEqual([
      {
        monitorEnabled: true,
        positionMonitorEnabled: true,
        positionThresholdPercent: '2',
        marginBalanceMonitorEnabled: true,
        marginBalanceThresholdPercent: '75',
        adlMonitorEnabled: false,
        adlThresholdPercent: '40',
        adlWindowSeconds: 60,
        adlSampleIntervalSeconds: 30,
        adlStartTime: '00:00',
        adlEndTime: '23:59',
        checkIntervalSeconds: 45,
        alertIntervalSeconds: 120,
        miaoCode: 'miao-123',
        barkPushUrl: 'https://bark.example.com/device-key',
      },
    ]),
  )
  expect(screen.getByLabelText('喵码')).toHaveValue('miao-123')
  expect(screen.getByLabelText('Bark Push URL')).toHaveValue('https://bark.example.com/device-key')

  await user.click(screen.getByRole('button', { name: '测试喵提醒' }))
  await waitFor(() => expect(testAlertCalled).toBe(true))
  testAlertCalled = false
  await user.click(screen.getByRole('button', { name: '测试 Bark' }))
  await waitFor(() => expect(testAlertCalled).toBe(true))
})

test('saves liquidation monitor ADL controls', async () => {
  installHandlers()
  const monitorUpdates: Array<Record<string, unknown>> = []
  server.use(
    http.put('/api/liquidation-monitor', async ({ request }) => {
      const body = (await request.json()) as Record<string, unknown>
      monitorUpdates.push(body)
      return HttpResponse.json({
        ...liquidationMonitorPayload,
        config: {
          ...liquidationMonitorPayload.config,
          ...body,
        },
      })
    }),
  )
  const user = userEvent.setup()

  render(<App />)

  await user.click(await screen.findByRole('button', { name: '设置' }))
  await user.click(screen.getByLabelText('开启 ADL 检测'))
  await user.clear(screen.getByLabelText('ADL 减仓阈值'))
  await user.type(screen.getByLabelText('ADL 减仓阈值'), '40')
  await user.clear(screen.getByLabelText('ADL 检测窗口'))
  await user.type(screen.getByLabelText('ADL 检测窗口'), '60')
  await user.clear(screen.getByLabelText('ADL 采样间隔'))
  await user.type(screen.getByLabelText('ADL 采样间隔'), '30')
  await user.clear(screen.getByLabelText('ADL 开始时间'))
  await user.type(screen.getByLabelText('ADL 开始时间'), '21:00')
  await user.clear(screen.getByLabelText('ADL 结束时间'))
  await user.type(screen.getByLabelText('ADL 结束时间'), '02:00')
  await user.click(screen.getByRole('button', { name: '保存爆仓监控' }))

  await waitFor(() => expect(monitorUpdates).toHaveLength(1))
  expect(monitorUpdates[0]).toMatchObject({
    monitorEnabled: true,
    adlMonitorEnabled: true,
    adlThresholdPercent: '40',
    adlWindowSeconds: 60,
    adlSampleIntervalSeconds: 30,
    adlStartTime: '21:00',
    adlEndTime: '02:00',
  })
})

test('shows configured alert channel values and can clear them', async () => {
  installHandlers()
  const monitorUpdates: Array<Record<string, unknown>> = []
  server.use(
    http.get('/api/liquidation-monitor', () =>
      HttpResponse.json({
        ...liquidationMonitorPayload,
        config: {
          ...liquidationMonitorPayload.config,
          barkPushUrlConfigured: true,
          barkPushUrl: 'https://bark.example.com/device-key',
          miaoCodeConfigured: true,
          miaoCode: 'miao-123',
        },
      }),
    ),
    http.put('/api/liquidation-monitor', async ({ request }) => {
      const body = (await request.json()) as Record<string, unknown>
      monitorUpdates.push(body)
      return HttpResponse.json({
        ...liquidationMonitorPayload,
        config: {
          ...liquidationMonitorPayload.config,
          ...body,
          barkPushUrlConfigured: true,
        },
      })
    }),
  )
  const user = userEvent.setup()

  render(<App />)

  await user.click(await screen.findByRole('button', { name: '设置' }))
  expect(screen.getByLabelText('喵码')).toHaveValue('miao-123')
  expect(screen.getByLabelText('Bark Push URL')).toHaveValue('https://bark.example.com/device-key')
  await user.clear(screen.getByLabelText('喵码'))
  await user.clear(screen.getByLabelText('Bark Push URL'))
  await user.click(screen.getByRole('button', { name: '保存爆仓监控' }))

  await waitFor(() => expect(monitorUpdates).toHaveLength(1))
  expect(monitorUpdates[0]).toMatchObject({ miaoCode: '', barkPushUrl: '' })
})

test('switches channel form fields for onchain and runs manual snapshot', async () => {
  installHandlers()
  const user = userEvent.setup()

  render(<App />)

  await user.click(await screen.findByRole('button', { name: '设置' }))
  const providerSelect = await screen.findByLabelText('渠道')
  await user.selectOptions(providerSelect, 'onchain')

  expect(screen.getByLabelText('钱包地址')).toBeInTheDocument()

  await user.click(screen.getByRole('button', { name: '关闭' }))

  await user.click(screen.getByRole('button', { name: '保存快照' }))

  await waitFor(() => {
    expect(screen.getByText(/快照执行完成/)).toBeInTheDocument()
  })
})

test('saves onchain channel with selected EVM chains and no BSC provider option', async () => {
  installHandlers()
  const createdPayloads: Array<Record<string, unknown>> = []
  server.use(
    http.post('/api/channels', async ({ request }) => {
      const body = (await request.json()) as Record<string, unknown>
      createdPayloads.push(body)
      return HttpResponse.json({ id: 2, enabled: true, secretConfigured: false, secretConfigMask: {}, ...body }, { status: 201 })
    }),
  )
  const user = userEvent.setup()

  render(<App />)

  await user.click(await screen.findByRole('button', { name: '设置' }))
  const providerSelect = await screen.findByLabelText('渠道')
  expect(within(providerSelect).queryByRole('option', { name: 'BSC' })).not.toBeInTheDocument()

  await user.type(screen.getByLabelText('名称'), 'EVM Wallets')
  await user.selectOptions(providerSelect, 'onchain')
  await user.type(screen.getByLabelText('钱包地址'), '0x1111111111111111111111111111111111111111')
  expect(await screen.findByRole('checkbox', { name: /Ethereum/ })).toBeChecked()
  expect(screen.getByRole('checkbox', { name: /BNB Smart Chain/ })).toBeChecked()
  await user.click(screen.getByRole('checkbox', { name: /Polygon/ }))
  await user.click(screen.getByRole('button', { name: '保存渠道' }))

  await waitFor(() => expect(createdPayloads).toHaveLength(1))
  expect(createdPayloads[0]).toMatchObject({
    provider: 'onchain',
    kind: 'chain',
    name: 'EVM Wallets',
    publicConfig: {
      walletAddresses: ['0x1111111111111111111111111111111111111111'],
      chainIndexes: ['1', '56', '137'],
    },
    secretConfig: {},
  })
})

test('allows Aster channels to save wallet and API wallet credentials', async () => {
  installHandlers()
  const createdPayloads: Array<Record<string, unknown>> = []
  server.use(
    http.post('/api/channels', async ({ request }) => {
      const body = (await request.json()) as Record<string, unknown>
      createdPayloads.push(body)
      return HttpResponse.json({ id: 2, enabled: true, secretConfigured: true, secretConfigMask: {}, ...body }, { status: 201 })
    }),
  )
  const user = userEvent.setup()

  render(<App />)

  await user.click(await screen.findByRole('button', { name: '设置' }))
  await user.type(await screen.findByLabelText('名称'), 'AsterMain')
  await user.selectOptions(screen.getByLabelText('渠道'), 'aster')
  await user.type(screen.getByLabelText('钱包地址'), '0x1111111111111111111111111111111111111111')
  await user.type(screen.getByLabelText('User Wallet'), '0x2222222222222222222222222222222222222222')
  await user.type(screen.getByLabelText('Signer Wallet'), '0x3333333333333333333333333333333333333333')
  await user.type(screen.getByLabelText('Private Key'), 'aster-private-key')
  await user.click(screen.getByRole('button', { name: '保存渠道' }))

  await waitFor(() => expect(createdPayloads).toHaveLength(1))
  expect(createdPayloads[0]).toMatchObject({
    provider: 'aster',
    kind: 'cex',
    name: 'AsterMain',
    publicConfig: { walletAddresses: ['0x1111111111111111111111111111111111111111'] },
    secretConfig: {
      user: '0x2222222222222222222222222222222222222222',
      signer: '0x3333333333333333333333333333333333333333',
      privateKey: 'aster-private-key',
    },
  })
})

test('loads live balances only after refresh is clicked', async () => {
  installHandlers()
  const user = userEvent.setup()

  render(<App />)

  expect(screen.queryByText('5250.00 USD')).not.toBeInTheDocument()

  await user.click(await screen.findByRole('button', { name: '刷新资产' }))

  expect((await screen.findAllByText('5250.00 USD')).length).toBeGreaterThan(0)
  expect(screen.getByText('主账户 · 现货')).toBeInTheDocument()
})

test('toggles backend scheduled snapshots without a frontend timer', async () => {
  installHandlers()
  const schedulerRequests: boolean[] = []
  server.use(
    http.put('/api/system/scheduler', async ({ request }) => {
      const body = (await request.json()) as { enabled: boolean }
      schedulerRequests.push(body.enabled)
      return HttpResponse.json({ ...schedulerPayload, enabled: body.enabled, jobs: body.enabled ? schedulerPayload.jobs : [] })
    }),
  )
  const user = userEvent.setup()

  render(<App />)

  expect((await screen.findAllByText('4025.00 USD')).length).toBeGreaterThan(0)

  await user.click(await screen.findByRole('button', { name: '关闭自动快照' }))
  await waitFor(() => expect(schedulerRequests).toEqual([false]))
  expect(screen.getByRole('button', { name: '开启自动快照' })).toBeInTheDocument()

  await user.click(screen.getByRole('button', { name: '开启自动快照' }))
  await waitFor(() => expect(schedulerRequests).toEqual([false, true]))
})

test('clears all channels and snapshots from settings after confirmation', async () => {
  installHandlers()
  let resetCalled = false
  server.use(
    http.post('/api/system/reset', () => {
      resetCalled = true
      return HttpResponse.json({
        status: 'ok',
        deletedChannels: 1,
        deletedSnapshots: 2,
        deletedAssets: 3,
      })
    }),
    http.get('/api/channels', () => HttpResponse.json(resetCalled ? [] : channelsPayload)),
    http.get('/api/snapshots/series', () => HttpResponse.json(resetCalled ? [] : snapshotsPayload)),
    http.get('/api/summary/latest', () =>
      HttpResponse.json(
        resetCalled
          ? { totalValueUsd: null, assetCount: 0, accountCategoryTotals: [], channels: [] }
          : summaryPayload,
      ),
    ),
    http.get('/api/summary/live', () =>
      HttpResponse.json(
        resetCalled
          ? { totalValueUsd: null, assetCount: 0, accountCategoryTotals: [], channels: [] }
          : liveSummaryPayload,
      ),
    ),
  )
  const user = userEvent.setup()

  render(<App />)

  expect((await screen.findAllByText('4025.00 USD')).length).toBeGreaterThan(0)
  await user.click(await screen.findByRole('button', { name: '设置' }))
  await user.click(screen.getByRole('button', { name: '清空所有配置' }))
  expect(screen.getByText('将删除所有渠道和快照数据。此操作无法撤销。')).toBeInTheDocument()

  await user.click(screen.getByRole('button', { name: '确认清空所有配置' }))

  await waitFor(() => expect(resetCalled).toBe(true))
  expect(await screen.findByText('所有配置已清空。')).toBeInTheDocument()
  expect(await screen.findByText('还没有渠道')).toBeInTheDocument()
  expect(await screen.findByText('还没有快照')).toBeInTheDocument()
})

test('clears only saved snapshots from settings after confirmation', async () => {
  installHandlers()
  let clearSnapshotsCalled = false
  server.use(
    http.delete('/api/snapshots', () => {
      clearSnapshotsCalled = true
      return new HttpResponse(null, { status: 204 })
    }),
    http.get('/api/snapshots/series', () =>
      HttpResponse.json(clearSnapshotsCalled ? [] : snapshotsPayload),
    ),
    http.get('/api/summary/latest', () =>
      HttpResponse.json(
        clearSnapshotsCalled
          ? { totalValueUsd: null, assetCount: 0, accountCategoryTotals: [], channels: [] }
          : summaryPayload,
      ),
    ),
  )
  const user = userEvent.setup()

  render(<App />)

  expect((await screen.findAllByText('4025.00 USD')).length).toBeGreaterThan(0)
  await user.click(await screen.findByRole('button', { name: '设置' }))
  await user.click(screen.getByRole('button', { name: '清除资产快照' }))
  expect(screen.getByText('只删除已保存的资产快照，渠道配置会保留。此操作无法撤销。')).toBeInTheDocument()

  await user.click(screen.getByRole('button', { name: '确认清除资产快照' }))

  await waitFor(() => expect(clearSnapshotsCalled).toBe(true))
  expect(await screen.findByText('资产快照已清除。')).toBeInTheDocument()
  expect(screen.getByText('EVM Wallets')).toBeInTheDocument()
  expect(await screen.findByText('还没有快照')).toBeInTheDocument()
})

test('uses real snapshot series data and can delete a saved snapshot run', async () => {
  let seriesRequestCount = 0
  const deletedRunIds: string[] = []
  installHandlers()
  server.use(
    http.get('/api/snapshots/series', () => {
      seriesRequestCount += 1
      return HttpResponse.json(snapshotsPayload)
    }),
    http.delete('/api/snapshots/runs/:runId', ({ params }) => {
      deletedRunIds.push(String(params.runId))
      return new HttpResponse(null, { status: 204 })
    }),
  )
  const user = userEvent.setup()

  render(<App />)

  expect((await screen.findAllByText('4025.00 USD')).length).toBeGreaterThan(0)
  await waitFor(() => expect(seriesRequestCount).toBeGreaterThan(0))

  await user.click(screen.getByRole('button', { name: '编辑快照' }))
  expect(screen.getByText('2 个渠道快照')).toBeInTheDocument()

  await user.click(screen.getByRole('button', { name: '删除 5250.00 USD 快照' }))
  expect(screen.getByText('将删除该时间点的所有渠道快照。此操作无法撤销。')).toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: '确认删除 5250.00 USD 快照' }))
  await waitFor(() => expect(deletedRunIds).toEqual(['5']))
})

test('shows a clear empty state when no snapshots exist', async () => {
  installHandlers()
  server.use(http.get('/api/snapshots/series', () => HttpResponse.json([])))

  render(<App />)

  expect(await screen.findByText('还没有快照')).toBeInTheDocument()
  expect(screen.getAllByText('保存一次快照后，这里会显示总资产变化。').length).toBeGreaterThan(0)
})

test('shows integer asset values directly inside calendar days', async () => {
  installHandlers()
  server.use(
    http.get('/api/snapshots/series', () =>
      HttpResponse.json([
        { id: 2, status: 'success', totalValueUsd: '1234567.00000000', createdAt: '2026-03-20T08:00:00+00:00', snapshotCount: 1 },
        { id: 3, status: 'success', totalValueUsd: '3900.00000000', createdAt: '2026-04-15T08:00:00+00:00', snapshotCount: 1 },
        ...snapshotsPayload,
      ]),
    ),
  )
  const user = userEvent.setup()

  render(<App />)

  expect((await screen.findAllByText('4025.00 USD')).length).toBeGreaterThan(0)

  await user.click(screen.getByRole('button', { name: '日历查看' }))

  const calendar = screen.getByLabelText('资产日历')
  expect(within(calendar).getByRole('heading', { name: '2026-05' })).toBeInTheDocument()
  expect(within(calendar).getByRole('grid', { name: '2026-05' })).toBeInTheDocument()
  expect(screen.queryByLabelText('选择日期')).not.toBeInTheDocument()
  expect(within(calendar).getByRole('gridcell', { name: '2026-05-09 资产 4025' })).toBeInTheDocument()
  expect(within(calendar).getByRole('gridcell', { name: '2026-05-10 资产 5250' })).toBeInTheDocument()
  expect(within(calendar).getByText('4025')).toBeInTheDocument()
  expect(within(calendar).getByText('5250')).toBeInTheDocument()
  expect(within(calendar).queryByText('5250.00 USD')).not.toBeInTheDocument()
  expect(within(calendar).getByRole('gridcell', { name: '2026-05-11 无快照' })).toBeInTheDocument()
  expect(calendar.querySelectorAll('.calendar-value')).toHaveLength(2)

  await user.selectOptions(screen.getByLabelText('查看月份'), '2026-04')

  expect(within(calendar).getByLabelText('2026-04-15 资产 3900')).toBeInTheDocument()
  expect(within(calendar).getByText('3900')).toBeInTheDocument()
  expect(within(calendar).queryByText('5250')).not.toBeInTheDocument()

  await user.selectOptions(screen.getByLabelText('查看月份'), '2026-03')

  expect(within(calendar).getByRole('grid', { name: '2026-03' })).toBeInTheDocument()
  expect(within(calendar).getByRole('gridcell', { name: '2026-03-20 资产 1234567' })).toBeInTheDocument()
  expect(within(calendar).getByText('1.2M')).toBeInTheDocument()
  expect(within(calendar).queryByText('1234567')).not.toBeInTheDocument()
})

test('shows previous-day profit calendar with monthly and yearly totals', async () => {
  installHandlers()
  server.use(
    http.get('/api/snapshots/series', () =>
      HttpResponse.json([
        { id: 1, status: 'success', totalValueUsd: '4000.00000000', createdAt: '2026-05-08T08:00:00+00:00', snapshotCount: 1 },
        { id: 2, status: 'success', totalValueUsd: '4025.00000000', createdAt: '2026-05-09T08:00:00+00:00', snapshotCount: 1 },
        { id: 3, status: 'success', totalValueUsd: '5250.00000000', createdAt: '2026-05-10T08:00:00+00:00', snapshotCount: 1 },
        { id: 4, status: 'success', totalValueUsd: '6000.00000000', createdAt: '2026-06-01T08:00:00+00:00', snapshotCount: 1 },
      ]),
    ),
  )
  const user = userEvent.setup()

  render(<App />)

  expect((await screen.findAllByText('4025.00 USD')).length).toBeGreaterThan(0)

  await user.click(screen.getByRole('button', { name: '利润查看' }))

  const profitCalendar = screen.getByLabelText('利润日历')
  expect(within(profitCalendar).getByRole('heading', { name: '2026-05' })).toBeInTheDocument()
  expect(within(profitCalendar).getByRole('grid', { name: '2026-05 利润' })).toBeInTheDocument()
  const may8Profit = within(profitCalendar).getByRole('gridcell', { name: '2026-05-08 利润 25' })
  const may9Profit = within(profitCalendar).getByRole('gridcell', { name: '2026-05-09 利润 1225' })
  expect(may8Profit).toBeInTheDocument()
  expect(may9Profit).toBeInTheDocument()
  expect(within(profitCalendar).getByRole('gridcell', { name: '2026-05-10 无利润数据' })).toBeInTheDocument()
  expect(within(may8Profit).getByText('25')).toBeInTheDocument()
  expect(within(may9Profit).getByText('1225')).toBeInTheDocument()
  expect(within(profitCalendar).getByText('月度利润')).toBeInTheDocument()
  expect(within(profitCalendar).getAllByText('1250')).toHaveLength(2)
  expect(within(profitCalendar).getByText('年度利润')).toBeInTheDocument()
  expect(within(profitCalendar).getByText('2026')).toBeInTheDocument()
})

test('uses every snapshot date as an asset trend x-axis label', async () => {
  installHandlers()
  server.use(
    http.get('/api/snapshots/series', () =>
      HttpResponse.json([
        { id: 10, status: 'success', totalValueUsd: '46241.24000000', createdAt: '2026-05-10T14:11:00+00:00', snapshotCount: 6 },
        { id: 11, status: 'success', totalValueUsd: '46625.63000000', createdAt: '2026-05-10T23:00:01+00:00', snapshotCount: 6 },
      ]),
    ),
  )

  render(<App />)

  expect(await screen.findByText('46241.24 USD')).toBeInTheDocument()

  const setOption = vi.mocked(echarts.init).mock.results.at(-1)?.value.setOption
  expect(setOption).toHaveBeenCalled()

  type AssetTrendOption = {
    xAxis?: { type?: string; data?: string[] }
  }

  const assetTrendOption = vi.mocked(setOption!).mock.calls
    .map(([option]: [unknown]) => option as AssetTrendOption)
    .find((option: AssetTrendOption) => option.xAxis?.data?.includes('05-11'))

  expect(assetTrendOption?.xAxis?.type).toBe('category')
  expect(assetTrendOption?.xAxis?.data).toEqual(['05-10', '05-11'])
})

test('reuses the chart instance when chart options update', async () => {
  const firstOption: EChartsOption = { series: [{ type: 'line', data: [1] }] }
  const secondOption: EChartsOption = { series: [{ type: 'line', data: [1, 2] }] }

  const { rerender, unmount } = render(<ChartSurface ariaLabel="资产走势" option={firstOption} />)

  await waitFor(() => expect(echarts.init).toHaveBeenCalledTimes(1))
  const chart = vi.mocked(echarts.init).mock.results[0]?.value

  rerender(<ChartSurface ariaLabel="资产走势" option={secondOption} />)

  await waitFor(() => expect(chart.setOption).toHaveBeenLastCalledWith(secondOption))
  expect(echarts.init).toHaveBeenCalledTimes(1)
  expect(chart.dispose).not.toHaveBeenCalled()

  unmount()

  expect(chart.dispose).toHaveBeenCalledTimes(1)
})
