import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import * as echarts from 'echarts'
import { HttpResponse, http } from 'msw'
import { vi } from 'vitest'

import App from './App'
import { server } from './test/setup'

const summaryPayload = {
  totalValueUsd: '4025.00000000',
  assetCount: 2,
  accountCategoryTotals: [
    {
      provider: 'bsc',
      channelName: 'BSC Wallets',
      accountScope: 'wallet:0x1111',
      valueUsd: '4025.00000000',
      assetCount: 2,
    },
  ],
  channels: [{ provider: 'bsc', name: 'BSC Wallets', latestSnapshotTotalUsd: '4025.00000000' }],
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
  channels: [{ provider: 'bsc', name: 'BSC Wallets', latestSnapshotTotalUsd: '5250.00000000' }],
}

const channelsPayload = [
  {
    id: 1,
    name: 'BSC Wallets',
    provider: 'onchain',
    kind: 'chain',
    enabled: true,
    publicConfig: {
      walletAddresses: ['0x1111111111111111111111111111111111111111'],
    },
    secretConfigured: false,
    secretConfigMask: {},
    lastTestStatus: 'ok',
  },
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
    checkIntervalSeconds: 60,
    miaoCodeConfigured: false,
    supportedFrequencies: [30, 60, 180, 300, 900, 1800, 3600],
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
}

function installHandlers() {
  server.use(
    http.get('/api/auth/session', () => HttpResponse.json({ authenticated: true })),
    http.post('/api/auth/login', () => HttpResponse.json({ authenticated: true })),
    http.post('/api/auth/logout', () => HttpResponse.json({ authenticated: false })),
    http.get('/api/health', () => HttpResponse.json({ status: 'ok' })),
    http.get('/api/summary/latest', () => HttpResponse.json(summaryPayload)),
    http.get('/api/summary/live', () => HttpResponse.json(liveSummaryPayload)),
    http.get('/api/channels', () => HttpResponse.json(channelsPayload)),
    http.get('/api/snapshots/series', () => HttpResponse.json(snapshotsPayload)),
    http.get('/api/schedule', () => HttpResponse.json(schedulePayload)),
    http.get('/api/system/scheduler', () => HttpResponse.json(schedulerPayload)),
    http.get('/api/liquidation-monitor', () => HttpResponse.json(liquidationMonitorPayload)),
    http.post('/api/liquidation-monitor/refresh', () => HttpResponse.json(liquidationMonitorPayload)),
    http.post('/api/liquidation-monitor/test-alert', () => HttpResponse.json({ status: 'sent' })),
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
        },
      })
    }),
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
  expect(screen.getByText('BSC Wallets · wallet:0x1111')).toBeInTheDocument()
  expect(screen.getByText('渠道占比与账户类别。')).toBeInTheDocument()
  expect(screen.getByRole('table', { name: '资产走势数据' })).toBeInTheDocument()
  expect(screen.getByRole('list', { name: '渠道占比数据' })).toBeInTheDocument()
  expect(screen.getByText('100%')).toBeInTheDocument()

  const totalAssetMetric = screen.getAllByText('总资产')[0].closest('.metric-card')
  const trendHeading = screen.getByRole('heading', { name: '资产走势' })
  const channelShareHeading = screen.getByRole('heading', { name: '渠道占比' })
  const accountHeading = screen.getByRole('heading', { name: '按账户类别' })

  expect(totalAssetMetric?.compareDocumentPosition(trendHeading)).toBe(Node.DOCUMENT_POSITION_FOLLOWING)
  expect(trendHeading.compareDocumentPosition(channelShareHeading)).toBe(Node.DOCUMENT_POSITION_FOLLOWING)
  expect(channelShareHeading.compareDocumentPosition(accountHeading)).toBe(Node.DOCUMENT_POSITION_FOLLOWING)
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

test('shows liquidation risk positions and can refresh them', async () => {
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
  expect(screen.getByText('主账户 · BTCUSDT')).toBeInTheDocument()
  expect(screen.getByText('0.1721%')).toBeInTheDocument()
  expect(screen.getByText('58100.00 USD')).toBeInTheDocument()
  expect(screen.getByText('58000.00 USD')).toBeInTheDocument()
  expect(screen.getByText('已提醒')).toBeInTheDocument()

  await user.click(screen.getByRole('button', { name: '刷新爆仓风险' }))
  await waitFor(() => expect(refreshCount).toBe(1))
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
        },
      })
    }),
    http.post('/api/liquidation-monitor/test-alert', () => {
      testAlertCalled = true
      return HttpResponse.json({ status: 'sent' })
    }),
  )
  const user = userEvent.setup()

  render(<App />)

  await user.click(await screen.findByRole('button', { name: '设置' }))
  await user.click(screen.getByLabelText('开启监控'))
  await user.click(screen.getByLabelText('开启电话提醒'))
  await user.clear(screen.getByLabelText('提醒阈值'))
  await user.type(screen.getByLabelText('提醒阈值'), '1.5')
  await user.selectOptions(screen.getByLabelText('监控频率'), '300')
  await user.type(screen.getByLabelText('喵码'), 'miao-123')
  await user.click(screen.getByRole('button', { name: '保存爆仓监控' }))

  await waitFor(() =>
    expect(monitorUpdates).toEqual([
      {
        monitorEnabled: true,
        alertEnabled: true,
        thresholdPercent: '1.5',
        checkIntervalSeconds: 300,
        miaoCode: 'miao-123',
      },
    ]),
  )

  await user.click(screen.getByRole('button', { name: '测试电话提醒' }))
  await waitFor(() => expect(testAlertCalled).toBe(true))
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
