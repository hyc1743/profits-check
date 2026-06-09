import { type CSSProperties, type ReactNode, useEffect, useId, useRef, useState } from 'react'
import { QueryClient, QueryClientProvider, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { zodResolver } from '@hookform/resolvers/zod'
import { useForm, useWatch } from 'react-hook-form'
import { z } from 'zod'
import type { EChartsOption } from 'echarts'

import './App.css'
import { ChartSurface } from './components/chart-surface'
import {
  api,
  type ChannelResponse,
  type CreateChannelPayload,
  type FundingFeeSummaryResponse,
  type LiquidationMonitorResponse,
  type OnchainChainOption,
  type PortfolioItem,
  type SnapshotItem,
  type ScheduleResponse,
  type UpdateLiquidationMonitorPayload,
} from './lib/api'
import { formatUsd, humanizeAccountScope, humanizeProvider, humanizeStatus } from './lib/format'

const channelProviders = ['binance', 'gate', 'okx', 'bitget', 'bybit', 'aster', 'onchain'] as const
const channelKinds = ['cex', 'dex', 'chain'] as const

const channelSchema = z.object({
  name: z.string().min(2),
  provider: z.enum(channelProviders),
  kind: z.enum(channelKinds),
  apiKey: z.string().optional(),
  apiSecret: z.string().optional(),
  passphrase: z.string().optional(),
  asterUser: z.string().optional(),
  asterSigner: z.string().optional(),
  asterPrivateKey: z.string().optional(),
  walletAddresses: z.string().optional(),
  chainIndexes: z.array(z.string()).optional(),
})

type ChannelFormValues = z.infer<typeof channelSchema>

const scheduleSchema = z.object({
  snapshotScheduleTimes: z
    .string()
    .min(1, '请输入至少一个时间。')
    .refine(
      (val) =>
        val
          .split(',')
          .map((t) => t.trim())
          .every((t) => /^\d{2}:\d{2}$/.test(t)),
      '格式不正确，请使用 HH:MM，多个时间用逗号分隔。',
    ),
  okxDexApiKey: z.string().optional(),
  okxDexApiSecret: z.string().optional(),
  okxDexPassphrase: z.string().optional(),
})

type ScheduleFormInput = z.input<typeof scheduleSchema>
type ScheduleFormValues = z.output<typeof scheduleSchema>

const liquidationMonitorSchema = z.object({
  positionMonitorEnabled: z.boolean(),
  positionThresholdPercent: z.string().regex(/^[1-9]\d*$/, '仓位风险阈值必须是正整数。'),
  marginBalanceMonitorEnabled: z.boolean(),
  marginBalanceThresholdPercent: z.string().regex(/^[1-9]\d*$/, '保证金余额阈值必须是正整数。'),
  adlMonitorEnabled: z.boolean(),
  adlThresholdPercent: z.string().regex(/^[1-9]\d*$/, 'ADL 减仓阈值必须是正整数。'),
  adlWindowSeconds: z.coerce.number().int().positive('ADL 检测窗口必须是正整数秒。'),
  adlSampleIntervalSeconds: z.coerce.number().int().positive('ADL 采样间隔必须是正整数秒。'),
  adlStartTime: z.string().regex(/^\d{2}:\d{2}$/, 'ADL 开始时间格式必须是 HH:MM。'),
  adlEndTime: z.string().regex(/^\d{2}:\d{2}$/, 'ADL 结束时间格式必须是 HH:MM。'),
  checkIntervalSeconds: z.coerce.number().int().positive('监控频率必须是正整数秒。'),
  alertIntervalSeconds: z.coerce.number().int().positive('提醒频率必须是正整数秒。'),
  miaoCode: z.string().optional(),
  barkPushUrl: z.string().optional(),
})

type LiquidationMonitorFormInput = z.input<typeof liquidationMonitorSchema>
type LiquidationMonitorFormValues = z.output<typeof liquidationMonitorSchema>

const calendarWeekdays = ['日', '一', '二', '三', '四', '五', '六']
const fallbackChartPalette = {
  accent: '#2ebd85',
  accentSoft: 'rgba(46,189,133,0.25)',
  accentFaint: 'rgba(46,189,133,0.02)',
  ink: '#182126',
}

type ThemeMode = 'light' | 'dark'

function hexToRgb(value: string) {
  const normalized = value.replace('#', '')

  if (!/^[0-9a-f]{6}$/i.test(normalized)) {
    return null
  }

  return {
    r: Number.parseInt(normalized.slice(0, 2), 16),
    g: Number.parseInt(normalized.slice(2, 4), 16),
    b: Number.parseInt(normalized.slice(4, 6), 16),
  }
}

function withAlpha(color: string, alpha: number) {
  const rgb = hexToRgb(color)
  return rgb ? `rgba(${rgb.r},${rgb.g},${rgb.b},${alpha})` : color
}

function toDateKey(value: string) {
  const d = new Date(value)
  const utc8 = new Date(d.getTime() + 8 * 60 * 60 * 1000)
  return utc8.toISOString().slice(0, 10)
}

function toMonthKey(value: string) {
  return toDateKey(value).slice(0, 7)
}

function getSnapshotMonths(snapshots: Array<{ createdAt: string }>) {
  return Array.from(new Set(snapshots.map((snapshot) => toMonthKey(snapshot.createdAt)))).sort()
}

function getCurrentDateKey() {
  return toDateKey(new Date().toISOString())
}

function formatTrendAxisLabel(value: number) {
  const d = new Date(value + 8 * 60 * 60 * 1000)
  return d.toISOString().slice(5, 10)
}

function formatSnapshotTime(value: string) {
  const d = new Date(new Date(value).getTime() + 8 * 60 * 60 * 1000)
  return d.toISOString().replace('T', ' ').slice(0, 19)
}

function formatPercent(value: string | number | null | undefined) {
  if (value === null || value === undefined) {
    return '不可用'
  }
  const numeric = typeof value === 'number' ? value : Number(value)
  if (Number.isNaN(numeric)) {
    return '不可用'
  }
  return `${Math.round(numeric)}%`
}

function formatLiquidationRiskPercent(value: string | number | null | undefined) {
  return value === null || value === undefined ? '∞' : formatPercent(value)
}

function formatLiquidationPrice(value: string | number | null | undefined) {
  return value === null || value === undefined ? '∞' : formatUsd(value)
}

function humanizeRiskStatus(value: string | null | undefined) {
  if (value === 'warning') return '接近爆仓'
  if (value === 'unavailable') return '无爆仓风险'
  if (value === 'ok') return '正常'
  return value || '未检测'
}

function humanizeRiskProvider(value: string) {
  const names: Record<string, string> = {
    binance: 'Binance',
    gate: 'Gate',
    okx: 'OKX',
    bitget: 'Bitget',
    bybit: 'Bybit',
    aster: 'Aster',
  }
  return names[value.toLowerCase()] ?? humanizeProvider(value)
}

function humanizeAlertStatus(value: string | null | undefined) {
  if (value === 'sent') return '已提醒'
  if (value === 'warning') return '提醒未确认电话'
  if (value === 'failed') return '提醒失败'
  return '未提醒'
}

function humanizeAdlStatus(value: string | null | undefined) {
  if (value === 'suspected') return '疑似 ADL'
  return value || '未检测'
}

function formatFrequency(seconds: number) {
  if (seconds < 60) return `${seconds} 秒`
  return `${Math.round(seconds / 60)} 分钟`
}

function formatIntegerInputValue(value: string | number | null | undefined, fallback: string) {
  if (value === null || value === undefined || value === '') {
    return fallback
  }
  const numeric = typeof value === 'number' ? value : Number(value)
  return Number.isNaN(numeric) ? fallback : String(Math.round(numeric))
}

function getEntryMonths(entries: Array<{ dateKey: string }>) {
  return Array.from(new Set(entries.map((entry) => entry.dateKey.slice(0, 7)))).sort()
}

function getCalendarMonthDays(dateKey: string) {
  if (!dateKey) {
    return []
  }

  const [year, month] = dateKey.split('-').map(Number)
  const firstDay = new Date(Date.UTC(year, month - 1, 1))
  const daysInMonth = new Date(Date.UTC(year, month, 0)).getUTCDate()
  const leadingBlankCount = firstDay.getUTCDay()

  return [
    ...Array.from({ length: leadingBlankCount }, () => null),
    ...Array.from({ length: daysInMonth }, (_, index) => {
      const day = index + 1
      return {
        day,
        dateKey: `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`,
      }
    }),
  ]
}

function formatCalendarAssetValue(value: string | number) {
  return String(Math.round(Number(value)))
}

function formatCompactCalendarAssetValue(value: string | number) {
  const roundedValue = Math.round(Number(value))
  const absValue = Math.abs(roundedValue)

  if (absValue >= 1_000_000) {
    return `${(roundedValue / 1_000_000).toFixed(1).replace(/\.0$/, '')}M`
  }

  if (absValue >= 100_000) {
    return `${Math.round(roundedValue / 1_000)}k`
  }

  return String(roundedValue)
}

function getNextDateKey(dateKey: string) {
  const [year, month, day] = dateKey.split('-').map(Number)
  const date = new Date(Date.UTC(year, month - 1, day))
  date.setUTCDate(date.getUTCDate() + 1)
  return date.toISOString().slice(0, 10)
}

function buildDailyProfitEntries(snapshots: SnapshotItem[]) {
  const sortedSnapshots = [...snapshots].sort((a, b) => a.createdAt.localeCompare(b.createdAt))

  return sortedSnapshots.slice(1).flatMap((snapshot, index) => {
    const previousSnapshot = sortedSnapshots[index]
    const previousDateKey = toDateKey(previousSnapshot.createdAt)
    const currentDateKey = toDateKey(snapshot.createdAt)

    if (getNextDateKey(previousDateKey) !== currentDateKey) {
      return []
    }

    return [{
      dateKey: previousDateKey,
      value: Number(snapshot.totalValueUsd) - Number(previousSnapshot.totalValueUsd),
    }]
  })
}

function readChartPalette() {
  if (typeof document === 'undefined') {
    return fallbackChartPalette
  }

  const styles = getComputedStyle(document.documentElement)
  const accent = styles.getPropertyValue('--accent').trim() || fallbackChartPalette.accent
  const ink = styles.getPropertyValue('--ink').trim() || fallbackChartPalette.ink

  return {
    accent,
    ink,
    accentSoft: withAlpha(accent, 0.25),
    accentFaint: withAlpha(accent, 0.02),
  }
}

function App() {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: { retry: false, refetchOnWindowFocus: false },
        },
      }),
  )

  return (
    <QueryClientProvider client={queryClient}>
      <AuthGate />
    </QueryClientProvider>
  )
}

function AuthGate() {
  const queryClient = useQueryClient()
  const sessionQuery = useQuery({ queryKey: ['auth', 'session'], queryFn: api.getAuthSession })

  useEffect(() => {
    const handleUnauthorized = () => {
      queryClient.setQueryData(['auth', 'session'], { authenticated: false })
      queryClient.removeQueries({ predicate: (query) => query.queryKey[0] !== 'auth' })
    }

    window.addEventListener('profits-check:unauthorized', handleUnauthorized)
    return () => window.removeEventListener('profits-check:unauthorized', handleUnauthorized)
  }, [queryClient])

  if (sessionQuery.isLoading) {
    return (
      <main className="shell auth-shell">
        <div className="grain" aria-hidden="true" />
        <p className="auth-loading">Checking session...</p>
      </main>
    )
  }

  if (sessionQuery.isError || !sessionQuery.data?.authenticated) {
    return (
      <LoginView
        onAuthenticated={async () => {
          queryClient.setQueryData(['auth', 'session'], { authenticated: true })
          await queryClient.invalidateQueries({ queryKey: ['auth', 'session'] })
        }}
      />
    )
  }

  return (
    <ProfitConsole
      onLogout={async () => {
        await api.logout()
        queryClient.clear()
        queryClient.setQueryData(['auth', 'session'], { authenticated: false })
      }}
    />
  )
}

function LoginView({ onAuthenticated }: { onAuthenticated: () => Promise<void> }) {
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const loginMutation = useMutation({
    mutationFn: api.login,
    onSuccess: async () => {
      setError(null)
      await onAuthenticated()
    },
    onError: (loginError) => setError(loginError.message),
  })

  return (
    <main className="shell auth-shell">
      <div className="grain" aria-hidden="true" />
      <section className="auth-panel" aria-labelledby="login-title">
        <p className="panel-kicker">Private console</p>
        <h1 id="login-title">Profits Check</h1>
        <form
          className="auth-form"
          onSubmit={(event) => {
            event.preventDefault()
            loginMutation.mutate(password)
          }}
        >
          <label className="field">
            <span>Password</span>
            <input
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              autoComplete="current-password"
            />
          </label>
          {error ? <p className="form-error">{error}</p> : null}
          <button type="submit" className="button button-primary" disabled={loginMutation.isPending || !password}>
            {loginMutation.isPending ? 'Signing in...' : 'Sign in'}
          </button>
        </form>
      </section>
    </main>
  )
}

function ProfitConsole({ onLogout }: { onLogout: () => Promise<void> }) {
  const queryClient = useQueryClient()
  const [themeMode, setThemeMode] = useState<ThemeMode>('light')
  const [chartPalette, setChartPalette] = useState(readChartPalette)
  const [notice, setNotice] = useState<string | null>(null)
  const [showSettings, setShowSettings] = useState(false)
  const [showSnapshotEditor, setShowSnapshotEditor] = useState(false)
  const [showAssetCalendar, setShowAssetCalendar] = useState(false)
  const [showProfitCalendar, setShowProfitCalendar] = useState(false)
  const [selectedCalendarMonth, setSelectedCalendarMonth] = useState('')
  const [selectedProfitMonth, setSelectedProfitMonth] = useState('')
  const [selectedFundingDate, setSelectedFundingDate] = useState(getCurrentDateKey)
  const [pendingSnapshotDeleteId, setPendingSnapshotDeleteId] = useState<number | null>(null)
  const [editingChannel, setEditingChannel] = useState<ChannelResponse | null>(null)
  const [isManualLiquidationRefreshPending, setIsManualLiquidationRefreshPending] = useState(false)
  const [portfolioInclusionOverrides, setPortfolioInclusionOverrides] = useState<Record<string, boolean>>({})

  useEffect(() => {
    document.documentElement.dataset.theme = themeMode
  }, [themeMode])

  const summaryQuery = useQuery({ queryKey: ['summary'], queryFn: api.getLatestSummary })
  const liveSummaryQuery = useQuery({
    queryKey: ['summary', 'live'],
    queryFn: api.getLiveSummary,
    enabled: false,
  })
  const channelsQuery = useQuery({ queryKey: ['channels'], queryFn: api.getChannels })
  const snapshotsQuery = useQuery({ queryKey: ['snapshots'], queryFn: api.getSnapshots })
  const scheduleQuery = useQuery({ queryKey: ['schedule'], queryFn: api.getSchedule })
  const schedulerQuery = useQuery({ queryKey: ['scheduler'], queryFn: api.getScheduler })
  const liquidationMonitorQuery = useQuery({
    queryKey: ['liquidation-monitor'],
    queryFn: api.getLiquidationMonitor,
  })
  const fundingFeesQuery = useQuery({
    queryKey: ['funding-fees', selectedFundingDate],
    queryFn: () => api.getFundingFees(selectedFundingDate),
  })

  const runSnapshotMutation = useMutation({
    mutationFn: api.runSnapshot,
    onSuccess: async (result) => {
      setNotice(`快照执行完成，成功渠道 ${result.successCount} 个。`)
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['summary'] }),
        queryClient.invalidateQueries({ queryKey: ['summary', 'live'] }),
        queryClient.invalidateQueries({ queryKey: ['snapshots'] }),
      ])
    },
    onError: (error) => setNotice(error.message),
  })

  const schedulerMutation = useMutation({
    mutationFn: api.updateScheduler,
    onSuccess: (result) => {
      queryClient.setQueryData(['scheduler'], result)
      setNotice(result.enabled ? '定时快照已开启。' : '定时快照已停止。')
    },
    onError: (error) => setNotice(error.message),
  })

  const createChannelMutation = useMutation({
    mutationFn: api.createChannel,
    onSuccess: async () => {
      setNotice('渠道配置已保存。')
      await queryClient.invalidateQueries({ queryKey: ['channels'] })
    },
    onError: (error) => setNotice(error.message),
  })

  const scheduleMutation = useMutation({
    mutationFn: api.updateSchedule,
    onSuccess: async () => {
      setNotice('调度配置已更新。')
      await queryClient.invalidateQueries({ queryKey: ['schedule'] })
    },
    onError: (error) => setNotice(error.message),
  })

  const refreshLiquidationMonitorMutation = useMutation({
    mutationFn: (variables?: { silent?: boolean }) => {
      void variables
      return api.refreshLiquidationMonitor()
    },
    onMutate: (variables) => {
      if (!variables?.silent) {
        setIsManualLiquidationRefreshPending(true)
      }
    },
    onSuccess: (result, variables) => {
      queryClient.setQueryData(['liquidation-monitor'], result)
      if (!variables?.silent) {
        setNotice(`爆仓风险已刷新，触发提醒 ${result.alertCount ?? 0} 条。`)
      }
    },
    onError: (error) => setNotice(error.message),
    onSettled: (_result, _error, variables) => {
      if (!variables?.silent) {
        setIsManualLiquidationRefreshPending(false)
      }
    },
  })

  const liquidationMonitorMutation = useMutation({
    mutationFn: api.updateLiquidationMonitor,
    onSuccess: async () => {
      setNotice('爆仓监控配置已更新。')
      await queryClient.invalidateQueries({ queryKey: ['liquidation-monitor'] })
    },
    onError: (error) => setNotice(error.message),
  })

  const testMiaotixingAlertMutation = useMutation({
    mutationFn: api.testMiaotixingAlert,
    onSuccess: (result) => {
      setNotice(result.status === 'sent' ? '测试喵提醒已发送。' : '测试喵提醒已提交。')
    },
    onError: (error) => setNotice(error.message),
  })
  const testBarkAlertMutation = useMutation({
    mutationFn: api.testBarkAlert,
    onSuccess: (result) => {
      setNotice(result.status === 'sent' ? '测试 Bark 已发送。' : '测试 Bark 已提交。')
    },
    onError: (error) => setNotice(error.message),
  })

  const testChannelMutation = useMutation({
    mutationFn: api.testChannel,
    onSuccess: async () => {
      setNotice('渠道连通性测试成功。')
      await queryClient.invalidateQueries({ queryKey: ['channels'] })
    },
    onError: (error) => setNotice(error.message),
  })

  const deleteChannelMutation = useMutation({
    mutationFn: api.deleteChannel,
    onSuccess: async () => {
      setNotice('渠道已删除。')
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['channels'] }),
        queryClient.invalidateQueries({ queryKey: ['snapshots'] }),
        queryClient.invalidateQueries({ queryKey: ['summary'] }),
      ])
    },
    onError: (error) => setNotice(error.message),
  })

  const deleteSnapshotMutation = useMutation({
    mutationFn: api.deleteSnapshotRun,
    onSuccess: async () => {
      setPendingSnapshotDeleteId(null)
      setNotice('快照数据已删除。')
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['snapshots'] }),
        queryClient.invalidateQueries({ queryKey: ['summary'] }),
        queryClient.invalidateQueries({ queryKey: ['summary', 'live'] }),
      ])
    },
    onError: (error) => setNotice(error.message),
  })

  const clearSnapshotsMutation = useMutation({
    mutationFn: api.clearSnapshots,
    onSuccess: async () => {
      setPendingSnapshotDeleteId(null)
      setNotice('资产快照已清除。')
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['snapshots'] }),
        queryClient.invalidateQueries({ queryKey: ['summary'] }),
        queryClient.invalidateQueries({ queryKey: ['summary', 'live'] }),
      ])
    },
    onError: (error) => setNotice(error.message),
  })

  const resetSystemMutation = useMutation({
    mutationFn: api.resetSystem,
    onSuccess: async () => {
      setEditingChannel(null)
      setPendingSnapshotDeleteId(null)
      setNotice('所有配置已清空。')
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['channels'] }),
        queryClient.invalidateQueries({ queryKey: ['snapshots'] }),
        queryClient.invalidateQueries({ queryKey: ['summary'] }),
        queryClient.invalidateQueries({ queryKey: ['summary', 'live'] }),
      ])
    },
    onError: (error) => setNotice(error.message),
  })

  const updateChannelMutation = useMutation({
    mutationFn: ({ id, ...payload }: CreateChannelPayload & { id: number }) =>
      api.updateChannel(id, payload),
    onSuccess: async () => {
      setNotice('渠道已更新。')
      setEditingChannel(null)
      await queryClient.invalidateQueries({ queryKey: ['channels'] })
    },
    onError: (error) => setNotice(error.message),
  })

  const updatePortfolioInclusionMutation = useMutation({
    mutationFn: api.updatePortfolioInclusionRules,
    onSuccess: async (_data, variables) => {
      setPortfolioInclusionOverrides((current) => {
        const next = { ...current }
        variables.items.forEach((item) => {
          delete next[item.key]
        })
        return next
      })
      setNotice('统计范围已更新。')
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['summary'] }),
        queryClient.invalidateQueries({ queryKey: ['summary', 'live'] }),
      ])
    },
    onError: async (error, variables) => {
      setPortfolioInclusionOverrides((current) => {
        const next = { ...current }
        variables.items.forEach((item) => {
          delete next[item.key]
        })
        return next
      })
      setNotice(error.message)
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['summary'] }),
        queryClient.invalidateQueries({ queryKey: ['summary', 'live'] }),
      ])
    },
  })

  const displayData = liveSummaryQuery.data ?? summaryQuery.data
  const portfolioItems = (displayData?.portfolioItems ?? []).map((item) =>
    Object.prototype.hasOwnProperty.call(portfolioInclusionOverrides, item.key)
      ? { ...item, includedInTotals: portfolioInclusionOverrides[item.key] }
      : item,
  )
  const snapshotRuns = snapshotsQuery.data ?? []
  const hasSnapshots = snapshotRuns.length > 0
  const firstSnapshot = snapshotRuns[0]
  const latestSnapshot = snapshotRuns.at(-1)
  const snapshotMonths = getSnapshotMonths(snapshotRuns)
  const latestSnapshotMonth = latestSnapshot ? toMonthKey(latestSnapshot.createdAt) : ''
  const calendarMonthKey = snapshotMonths.includes(selectedCalendarMonth)
    ? selectedCalendarMonth
    : latestSnapshotMonth
  const calendarTitleId = `asset-calendar-${calendarMonthKey || 'empty'}`
  const calendarDays = getCalendarMonthDays(calendarMonthKey)
  const latestSnapshotByDate = new Map(
    snapshotRuns.map((snapshot) => [toDateKey(snapshot.createdAt), snapshot]),
  )
  const profitEntries = buildDailyProfitEntries(snapshotRuns)
  const profitMonths = getEntryMonths(profitEntries)
  const latestProfitMonth = profitMonths.at(-1) ?? ''
  const profitMonthKey = profitMonths.includes(selectedProfitMonth)
    ? selectedProfitMonth
    : latestProfitMonth
  const profitYearKey = profitMonthKey.slice(0, 4)
  const profitCalendarTitleId = `profit-calendar-${profitMonthKey || 'empty'}`
  const profitCalendarDays = getCalendarMonthDays(profitMonthKey)
  const profitByDate = new Map(profitEntries.map((entry) => [entry.dateKey, entry]))
  const monthlyProfitTotal = profitEntries
    .filter((entry) => entry.dateKey.startsWith(profitMonthKey))
    .reduce((total, entry) => total + entry.value, 0)
  const yearlyProfitTotal = profitEntries
    .filter((entry) => entry.dateKey.startsWith(profitYearKey))
    .reduce((total, entry) => total + entry.value, 0)
  const schedulerEnabled = schedulerQuery.data?.enabled ?? false
  const fundingSummary = fundingFeesQuery.data
  const schedulerTimes = schedulerQuery.data?.snapshot_schedule_times ?? '08:00'
  const totalValue = displayData?.totalValueUsd ?? null
  const configuredChannelCount = channelsQuery.data?.length ?? 0
  const liveAccountCount = displayData?.accountCategoryTotals.length ?? 0
  const riskWarningCount = [
    ...(liquidationMonitorQuery.data?.positions ?? []),
    ...(liquidationMonitorQuery.data?.marginBalances ?? []),
  ].filter((item) => item.status === 'warning').length
  const latestSnapshotTime = latestSnapshot ? formatSnapshotTime(latestSnapshot.createdAt) : '无快照'
  const channelShareTotal = (displayData?.channels ?? []).reduce(
    (total, channel) => total + Number(channel.latestSnapshotTotalUsd ?? 0),
    0,
  )
  const channelShareItems = (displayData?.channels ?? [])
    .map((channel) => {
      const value = Number(channel.latestSnapshotTotalUsd ?? 0)
      return {
        name: channel.name,
        value,
        percent: channelShareTotal > 0 ? Math.round((value / channelShareTotal) * 100) : 0,
      }
    })
    .filter((channel) => channel.value > 0)
  const trendSummary = hasSnapshots && firstSnapshot && latestSnapshot
    ? `最近 ${snapshotRuns.length} 次快照：${formatUsd(firstSnapshot.totalValueUsd)} 到 ${formatUsd(latestSnapshot.totalValueUsd)}`
    : '保存一次快照后，这里会显示总资产变化。'
  const assetTrendOption: EChartsOption = {
    animation: true,
    tooltip: {
      trigger: 'axis',
      confine: true,
      formatter: (params: unknown) => {
        const items = Array.isArray(params) ? params : [params]
        const point = items[0] as { data: { value: number; createdAt: string }; marker: string }
        return `${formatSnapshotTime(point.data.createdAt)}<br/>${point.marker} $${point.data.value.toLocaleString()}`
      },
    },
    xAxis: {
      type: 'category',
      data: snapshotRuns.map((snapshot) => formatTrendAxisLabel(new Date(snapshot.createdAt).getTime())),
      axisLabel: {
        color: chartPalette.ink,
        fontSize: 11,
        rotate: 30,
        margin: 8,
      },
    },
    yAxis: {
      type: 'value',
      axisLabel: {
        color: chartPalette.ink,
        formatter: (v: number) => `$${(v / 1000).toFixed(1)}k`,
      },
    },
    series: [
      {
        type: 'line',
        smooth: true,
        symbol: 'circle',
        symbolSize: 6,
        data:
          snapshotRuns.map((s) => ({
            value: Number(s.totalValueUsd),
            createdAt: s.createdAt,
          })) ?? [],
        lineStyle: { color: chartPalette.accent, width: 2 },
        itemStyle: { color: chartPalette.accent },
        areaStyle: {
          color: {
            type: 'linear',
            x: 0, y: 0, x2: 0, y2: 1,
            colorStops: [
              { offset: 0, color: chartPalette.accentSoft },
              { offset: 1, color: chartPalette.accentFaint },
            ],
          },
        },
      },
    ],
    grid: { left: 50, right: 20, top: 20, bottom: 50 },
  }

  return (
    <main className="shell console-shell">
      <div className="grain" aria-hidden="true" />
      <div className="console-layout">
        <aside className="side-rail" aria-label="控制台状态">
          <div className="brand-mark">
            <span>PC</span>
          </div>
          <nav className="rail-nav" aria-label="页面区域">
            <a href="#overview">总览</a>
            <a href="#risk">风险</a>
            <a href="#distribution">分布</a>
          </nav>
          <div className="rail-status" aria-label="系统状态">
            <span>Snapshots</span>
            <strong>{schedulerEnabled ? 'Auto' : 'Manual'}</strong>
          </div>
        </aside>

        <div className="workspace">
          <div className="top-bar">
            <div className="top-copy">
              <p className="panel-kicker">Profits Check</p>
              <h1>Portfolio Risk Console</h1>
              <span>{`Latest snapshot · ${latestSnapshotTime}`}</span>
            </div>
            <div className="top-actions">
              <button
                type="button"
                className="settings-button"
                onClick={() => {
                  const nextTheme = themeMode === 'light' ? 'dark' : 'light'
                  document.documentElement.dataset.theme = nextTheme
                  setThemeMode(nextTheme)
                  setChartPalette(readChartPalette())
                }}
              >
                {themeMode === 'light' ? 'Dark mode' : 'Light mode'}
              </button>
              <button type="button" className="settings-button" onClick={() => setShowSettings(true)}>
                设置
              </button>
              <button type="button" className="settings-button" onClick={() => void onLogout()}>
                Sign out
              </button>
            </div>
          </div>

          <div className="system-strip" aria-label="资产监控摘要">
            <Metric label="总资产" value={formatUsd(totalValue)} />
            <Metric label="渠道" value={`${configuredChannelCount} 个配置`} />
            <Metric label="账户分类" value={`${liveAccountCount} 组`} />
            <Metric label="风险提醒" value={`${riskWarningCount} 条`} />
          </div>

      {notice ? (
        <p className="notice" role="status">
          {notice}
        </p>
      ) : null}

      <section className="grid">
        <article className="panel overview-panel" id="overview">
          <div className="panel-head">
            <div className="overview-title">
              <p className="panel-kicker">资产总览</p>
              <h2>看清总资产和分布</h2>
            </div>
            <div className="action-group">
              <button
                type="button"
                className="button button-secondary"
                onClick={async () => {
                  const result = await liveSummaryQuery.refetch()
                  if (result.error) {
                    setNotice(result.error.message)
                  } else {
                    setNotice('实时资产已刷新。')
                  }
                }}
                disabled={liveSummaryQuery.isFetching}
              >
                {liveSummaryQuery.isFetching ? '刷新中...' : '刷新资产'}
              </button>
              <button
                type="button"
                className="button button-primary"
                onClick={() => {
                  const todayKey = toDateKey(new Date().toISOString())
                  const hasSnapshotToday = snapshotRuns.some((s) => toDateKey(s.createdAt) === todayKey)
                  if (hasSnapshotToday && !window.confirm('今日已存在快照。继续保存会覆盖今天的快照。')) {
                    return
                  }
                  runSnapshotMutation.mutate()
                }}
                disabled={runSnapshotMutation.isPending}
              >
                {runSnapshotMutation.isPending ? '保存中...' : '保存快照'}
              </button>
              <button
                type="button"
                className="button button-ghost"
                onClick={() => schedulerMutation.mutate(!schedulerEnabled)}
                disabled={schedulerQuery.isLoading || schedulerMutation.isPending}
              >
                {schedulerMutation.isPending
                  ? '更新中...'
                  : schedulerEnabled
                    ? '关闭自动快照'
                    : '开启自动快照'}
              </button>
            </div>
          </div>

          <div className="mini-metrics">
            <Metric
              label="总资产"
              value={formatUsd(totalValue)}
            />
            <Metric label="自动快照" value={`${schedulerEnabled ? '开启' : '关闭'} · ${schedulerTimes}`} />
          </div>

          <div className="asset-trend-block">
            <div className="asset-totals-head">
              <h3>资产走势</h3>
              <span>{trendSummary}</span>
            </div>
            <div className="chart-block">
              {hasSnapshots ? (
                <ChartSurface ariaLabel={`资产走势。${trendSummary}`} option={assetTrendOption}>
                  <table aria-label="资产走势数据">
                    <thead>
                      <tr>
                        <th>日期</th>
                        <th>总资产</th>
                      </tr>
                    </thead>
                    <tbody>
                      {snapshotRuns.map((snapshot) => (
                        <tr key={snapshot.id}>
                          <td>{toDateKey(snapshot.createdAt)}</td>
                          <td>{formatUsd(snapshot.totalValueUsd)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </ChartSurface>
              ) : (
                <div className="empty-state">
                  <strong>还没有快照</strong>
                  <span>保存一次快照后，这里会显示总资产变化。</span>
                </div>
              )}
            </div>
            <button
              type="button"
              className="button button-ghost"
              onClick={() => setShowAssetCalendar((current) => !current)}
            >
              日历查看
            </button>
            <button
              type="button"
              className="button button-ghost"
              onClick={() => setShowSnapshotEditor((current) => !current)}
            >
              编辑快照
            </button>
            <button
              type="button"
              className="button button-ghost"
              onClick={() => setShowProfitCalendar((current) => !current)}
            >
              利润查看
            </button>
            {showAssetCalendar ? (
              <div className="calendar-panel" aria-label="资产日历">
                {calendarDays.length > 0 ? (
                  <>
                    <div className="calendar-toolbar">
                      <div className="calendar-copy">
                        <h4 id={calendarTitleId}>{calendarMonthKey}</h4>
                        <span>每日资产</span>
                      </div>
                      <label className="field calendar-month-field">
                        <span>查看月份</span>
                        <select
                          value={calendarMonthKey}
                          onChange={(event) => setSelectedCalendarMonth(event.target.value)}
                        >
                          {snapshotMonths.map((month) => (
                            <option key={month} value={month}>
                              {month}
                            </option>
                          ))}
                        </select>
                      </label>
                    </div>
                    <div className="calendar-grid" role="grid" aria-labelledby={calendarTitleId}>
                      {calendarWeekdays.map((weekday) => (
                        <span key={weekday} className="calendar-weekday" role="columnheader">
                          {weekday}
                        </span>
                      ))}
                      {calendarDays.map((day, index) => {
                        if (!day) {
                          return <span key={`blank-${index}`} className="calendar-day calendar-day-empty" />
                        }

                        const snapshot = latestSnapshotByDate.get(day.dateKey)
                        const assetValue = snapshot ? formatCalendarAssetValue(snapshot.totalValueUsd) : null
                        const displayAssetValue = snapshot ? formatCompactCalendarAssetValue(snapshot.totalValueUsd) : null
                        return (
                          <div
                            key={day.dateKey}
                            className={assetValue ? 'calendar-day calendar-day-has-value' : 'calendar-day'}
                            role="gridcell"
                            aria-label={assetValue ? `${day.dateKey} 资产 ${assetValue}` : `${day.dateKey} 无快照`}
                          >
                            <span className="calendar-date">{day.day}</span>
                            {displayAssetValue ? (
                              <strong
                                className="calendar-value"
                                style={{ '--asset-digits': displayAssetValue.length } as CSSProperties}
                              >
                                {displayAssetValue}
                              </strong>
                            ) : null}
                          </div>
                        )
                      })}
                    </div>
                  </>
                ) : (
                  <p className="empty-copy">这一天没有保存的快照。</p>
                )}
              </div>
            ) : null}
            {showProfitCalendar ? (
              <div className="calendar-panel profit-calendar-panel" aria-label="利润日历">
                {profitCalendarDays.length > 0 ? (
                  <>
                    <div className="calendar-toolbar">
                      <div className="calendar-copy">
                        <h4 id={profitCalendarTitleId}>{profitMonthKey}</h4>
                        <span>前日利润</span>
                      </div>
                      <label className="field calendar-month-field">
                        <span>查看月份</span>
                        <select
                          value={profitMonthKey}
                          onChange={(event) => setSelectedProfitMonth(event.target.value)}
                        >
                          {profitMonths.map((month) => (
                            <option key={month} value={month}>
                              {month}
                            </option>
                          ))}
                        </select>
                      </label>
                    </div>
                    <div className="profit-summary-grid">
                      <Metric label="月度利润" value={formatCompactCalendarAssetValue(monthlyProfitTotal)} />
                      <Metric label="年度利润" value={formatCompactCalendarAssetValue(yearlyProfitTotal)} />
                      <Metric label="统计年份" value={profitYearKey} />
                    </div>
                    <div className="calendar-grid" role="grid" aria-label={`${profitMonthKey} 利润`}>
                      {calendarWeekdays.map((weekday) => (
                        <span key={weekday} className="calendar-weekday" role="columnheader">
                          {weekday}
                        </span>
                      ))}
                      {profitCalendarDays.map((day, index) => {
                        if (!day) {
                          return <span key={`profit-blank-${index}`} className="calendar-day calendar-day-empty" />
                        }

                        const profit = profitByDate.get(day.dateKey)
                        const roundedProfit = profit ? formatCalendarAssetValue(profit.value) : null
                        const displayProfit = profit ? formatCompactCalendarAssetValue(profit.value) : null
                        return (
                          <div
                            key={day.dateKey}
                            className={profit ? 'calendar-day calendar-day-has-value profit-day' : 'calendar-day'}
                            role="gridcell"
                            aria-label={roundedProfit ? `${day.dateKey} 利润 ${roundedProfit}` : `${day.dateKey} 无利润数据`}
                          >
                            <span className="calendar-date">{day.day}</span>
                            {displayProfit ? (
                              <strong
                                className="calendar-value"
                                style={{ '--asset-digits': displayProfit.length } as CSSProperties}
                              >
                                {displayProfit}
                              </strong>
                            ) : null}
                          </div>
                        )
                      })}
                    </div>
                  </>
                ) : (
                  <p className="empty-copy">至少需要连续两天快照后，才能计算利润。</p>
                )}
              </div>
            ) : null}
            <FundingFeePanel
              summary={fundingSummary}
              selectedDate={selectedFundingDate}
              isLoading={fundingFeesQuery.isFetching}
              error={fundingFeesQuery.error?.message}
              onDateChange={setSelectedFundingDate}
            />
            {showSnapshotEditor ? (
              <div className="snapshot-list" aria-label="保存的快照">
                {snapshotRuns.length === 0 ? (
                  <p className="empty-copy">没有可编辑的快照。</p>
                ) : null}
                {snapshotRuns.map((snapshot) => {
                  const isPendingDelete = pendingSnapshotDeleteId === snapshot.id
                  return (
                    <div key={snapshot.id} className="snapshot-item">
                      <div className="snapshot-copy">
                        <strong>{formatUsd(snapshot.totalValueUsd)}</strong>
                        <span>{new Date(snapshot.createdAt).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' })}</span>
                        <span>{`${snapshot.snapshotCount} 个渠道快照`}</span>
                      </div>
                      {isPendingDelete ? (
                        <div className="confirm-delete">
                          <span>将删除该时间点的所有渠道快照。此操作无法撤销。</span>
                          <button
                            type="button"
                            className="button button-danger"
                            onClick={() => deleteSnapshotMutation.mutate(snapshot.id)}
                            disabled={deleteSnapshotMutation.isPending}
                          >
                            {`确认删除 ${formatUsd(snapshot.totalValueUsd)} 快照`}
                          </button>
                          <button
                            type="button"
                            className="button button-ghost"
                            onClick={() => setPendingSnapshotDeleteId(null)}
                            disabled={deleteSnapshotMutation.isPending}
                          >
                            取消
                          </button>
                        </div>
                      ) : (
                        <button
                          type="button"
                          className="button button-danger-ghost"
                          onClick={() => setPendingSnapshotDeleteId(snapshot.id)}
                        >
                          {`删除 ${formatUsd(snapshot.totalValueUsd)} 快照`}
                        </button>
                      )}
                    </div>
                  )
                })}
              </div>
            ) : null}
          </div>

          {liquidationMonitorQuery.data ? (
            <LiquidationRiskPanel
              monitor={liquidationMonitorQuery.data}
              isRefreshing={isManualLiquidationRefreshPending}
              onRefresh={() => refreshLiquidationMonitorMutation.mutate(undefined)}
            />
          ) : null}

          <div className="distribution-block" id="distribution">
            <div className="asset-totals-head">
              <h3>资产分布</h3>
              <span>渠道占比与账户类别。</span>
            </div>
            <div className="distribution-grid">
              <details className="distribution-chart">
                <summary>
                  <h4>渠道占比</h4>
                </summary>
                {channelShareItems.length > 0 ? (
                  <>
                    <ChartSurface
                      ariaLabel="渠道资产占比"
                      option={{
                        animation: false,
                        series: [
                          {
                            type: 'pie',
                            radius: ['55%', '78%'],
                            label: {
                              color: chartPalette.ink,
                              formatter: (params: { name?: string; percent?: number }) =>
                                `${params.name ?? ''} ${Math.round(Number(params.percent ?? 0))}%`,
                            },
                            data:
                              channelShareItems.map((channel) => ({
                                name: channel.name,
                                value: channel.value,
                              })),
                          },
                        ],
                      }}
                    />
                    <div className="channel-share-list" role="list" aria-label="渠道占比数据">
                      {channelShareItems.map((channel) => (
                        <div key={channel.name} className="channel-share-row" role="listitem">
                          <strong>{channel.name}</strong>
                          <span>{formatUsd(channel.value)}</span>
                          <em>{`${channel.percent}%`}</em>
                        </div>
                      ))}
                    </div>
                  </>
                ) : (
                  <p className="empty-copy">暂无渠道占比数据。</p>
                )}
              </details>
              <details className="account-list">
                <summary>
                  <h4>按账户类别</h4>
                </summary>
                {(displayData?.accountCategoryTotals ?? []).map((item) => (
                  <div key={`${item.channelName}-${item.accountScope}`} className="account-row">
                    <div>
                      <strong>{`${item.channelName} · ${humanizeAccountScope(item.accountScope)}`}</strong>
                      <span>{`${humanizeProvider(item.provider)} · ${item.assetCount} 条记录`}</span>
                    </div>
                    <em>{formatUsd(item.valueUsd)}</em>
                  </div>
                ))}
                {(displayData?.accountCategoryTotals ?? []).length === 0 ? (
                  <p className="empty-copy">暂无账户分类数据。</p>
                ) : null}
              </details>
            </div>
          </div>
        </article>
      </section>

      {showSettings ? (
        <SettingsDialog
          channels={channelsQuery.data ?? []}
          schedule={scheduleQuery.data}
          editingChannel={editingChannel}
          onCreateChannel={(payload) => {
            if (editingChannel) {
              updateChannelMutation.mutate({ id: editingChannel.id, ...payload })
            } else {
              createChannelMutation.mutate(payload)
            }
          }}
          onEditChannel={setEditingChannel}
          onTestChannel={(id) => testChannelMutation.mutate(id)}
          onDeleteChannel={(id) => deleteChannelMutation.mutate(id)}
          onSaveSchedule={(payload) => scheduleMutation.mutate(payload)}
          portfolioItems={portfolioItems}
          onUpdatePortfolioInclusion={(key, includedInTotals) => {
            setPortfolioInclusionOverrides((current) => ({ ...current, [key]: includedInTotals }))
            updatePortfolioInclusionMutation.mutate({ items: [{ key, includedInTotals }] })
          }}
          liquidationMonitor={liquidationMonitorQuery.data}
          onSaveLiquidationMonitor={(payload) => liquidationMonitorMutation.mutate(payload)}
          onTestMiaotixingAlert={() => testMiaotixingAlertMutation.mutate()}
          onTestBarkAlert={() => testBarkAlertMutation.mutate()}
          onClearSnapshots={() => clearSnapshotsMutation.mutate()}
          onResetSystem={() => resetSystemMutation.mutate()}
          isSavingChannel={createChannelMutation.isPending || updateChannelMutation.isPending}
          isSavingSchedule={scheduleMutation.isPending}
          isSavingPortfolioInclusion={updatePortfolioInclusionMutation.isPending}
          isSavingLiquidationMonitor={liquidationMonitorMutation.isPending}
          isTestingMiaotixingAlert={testMiaotixingAlertMutation.isPending}
          isTestingBarkAlert={testBarkAlertMutation.isPending}
          isClearingSnapshots={clearSnapshotsMutation.isPending}
          isResetting={resetSystemMutation.isPending}
          onClose={() => { setShowSettings(false); setEditingChannel(null) }}
        />
      ) : null}
        </div>
      </div>
    </main>
  )
}

function SettingsDialog({
  channels,
  schedule,
  editingChannel,
  onCreateChannel,
  onEditChannel,
  onTestChannel,
  onDeleteChannel,
  onSaveSchedule,
  portfolioItems,
  onUpdatePortfolioInclusion,
  liquidationMonitor,
  onSaveLiquidationMonitor,
  onTestMiaotixingAlert,
  onTestBarkAlert,
  onClearSnapshots,
  onResetSystem,
  isSavingChannel,
  isSavingSchedule,
  isSavingPortfolioInclusion,
  isSavingLiquidationMonitor,
  isTestingMiaotixingAlert,
  isTestingBarkAlert,
  isClearingSnapshots,
  isResetting,
  onClose,
}: {
  channels: ChannelResponse[]
  schedule?: ScheduleResponse
  editingChannel: ChannelResponse | null
  onCreateChannel: (payload: CreateChannelPayload) => void
  onEditChannel: (channel: ChannelResponse | null) => void
  onTestChannel: (id: number) => void
  onDeleteChannel: (id: number) => void
  onSaveSchedule: (payload: ScheduleResponse) => void
  portfolioItems: PortfolioItem[]
  onUpdatePortfolioInclusion: (key: string, includedInTotals: boolean) => void
  liquidationMonitor?: LiquidationMonitorResponse
  onSaveLiquidationMonitor: (payload: UpdateLiquidationMonitorPayload) => void
  onTestMiaotixingAlert: () => void
  onTestBarkAlert: () => void
  onClearSnapshots: () => void
  onResetSystem: () => void
  isSavingChannel: boolean
  isSavingSchedule: boolean
  isSavingPortfolioInclusion: boolean
  isSavingLiquidationMonitor: boolean
  isTestingMiaotixingAlert: boolean
  isTestingBarkAlert: boolean
  isClearingSnapshots: boolean
  isResetting: boolean
  onClose: () => void
}) {
  const headingId = useId()
  const dialogRef = useRef<HTMLDivElement>(null)
  const previousFocusRef = useRef<HTMLElement | null>(null)
  const [isConfirmingReset, setIsConfirmingReset] = useState(false)
  const [isConfirmingClearSnapshots, setIsConfirmingClearSnapshots] = useState(false)

  useEffect(() => {
    previousFocusRef.current = document.activeElement as HTMLElement
    const firstInput = dialogRef.current?.querySelector<HTMLElement>(
      'input, select, textarea, button, [tabindex]:not([tabindex="-1"])',
    )
    firstInput?.focus()

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose()
        return
      }
      if (e.key !== 'Tab') return
      const focusable = dialogRef.current?.querySelectorAll<HTMLElement>(
        'input:not([disabled]), select:not([disabled]), textarea:not([disabled]), button:not([disabled]), [tabindex]:not([tabindex="-1"])',
      )
      if (!focusable || focusable.length === 0) return
      const first = focusable[0]
      const last = focusable[focusable.length - 1]
      if (e.shiftKey) {
        if (document.activeElement === first) {
          e.preventDefault()
          last.focus()
        }
      } else {
        if (document.activeElement === last) {
          e.preventDefault()
          first.focus()
        }
      }
    }

    document.addEventListener('keydown', handleKeyDown)
    return () => {
      document.removeEventListener('keydown', handleKeyDown)
      previousFocusRef.current?.focus()
    }
  }, [onClose])

  return (
    <div
      className="settings-overlay"
      role="presentation"
      onClick={onClose}
    >
      <div
        ref={dialogRef}
        className="settings-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby={headingId}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="settings-header">
          <h2 id={headingId}>设置</h2>
          <button type="button" className="button button-secondary" onClick={onClose}>
            关闭
          </button>
        </div>

        <div className="settings-body">
          <article className="panel">
            <div className="panel-head">
              <div>
                <p className="panel-kicker">渠道</p>
                <h3>连接配置</h3>
              </div>
            </div>
            <div className="channel-layout">
              <ChannelList
                channels={channels}
                onTest={onTestChannel}
                onDelete={onDeleteChannel}
                onEdit={onEditChannel}
              />
              <ChannelForm
                onSubmit={onCreateChannel}
                isSaving={isSavingChannel}
                editingChannel={editingChannel}
                onCancelEdit={() => onEditChannel(null)}
              />
            </div>
          </article>

          <article className="panel">
            <div className="panel-head">
              <div>
                <p className="panel-kicker">全局</p>
                <h3>调度 & API</h3>
              </div>
            </div>
            <ScheduleForm
              defaultValues={schedule}
              onSubmit={onSaveSchedule}
              isSaving={isSavingSchedule}
            />
          </article>

          <article className="panel">
            <div className="panel-head">
              <div>
                <p className="panel-kicker">统计</p>
                <h3>计入范围</h3>
              </div>
            </div>
            <PortfolioInclusionPanel
              items={portfolioItems}
              isSaving={isSavingPortfolioInclusion}
              onToggle={onUpdatePortfolioInclusion}
            />
          </article>

          <article className="panel">
            <div className="panel-head">
              <div>
                <p className="panel-kicker">风险</p>
                <h3>爆仓监控</h3>
              </div>
            </div>
            <LiquidationMonitorForm
              monitor={liquidationMonitor}
              onSubmit={onSaveLiquidationMonitor}
              onTestMiaotixingAlert={onTestMiaotixingAlert}
              onTestBarkAlert={onTestBarkAlert}
              isSaving={isSavingLiquidationMonitor}
              isTestingMiaotixingAlert={isTestingMiaotixingAlert}
              isTestingBarkAlert={isTestingBarkAlert}
            />
          </article>

          <article className="panel danger-zone">
            <div className="panel-head">
              <div>
                <p className="panel-kicker">重置</p>
                <h3>危险操作</h3>
              </div>
            </div>
            <p>只删除已保存的资产快照，渠道配置会保留。此操作无法撤销。</p>
            {isConfirmingClearSnapshots ? (
              <div className="danger-actions">
                <button
                  type="button"
                  className="button button-danger"
                  aria-label="确认清除资产快照"
                  disabled={isClearingSnapshots}
                  onClick={() => {
                    onClearSnapshots()
                    setIsConfirmingClearSnapshots(false)
                  }}
                >
                  {isClearingSnapshots ? '清除中...' : '确认清除资产快照'}
                </button>
                <button
                  type="button"
                  className="button button-secondary"
                  disabled={isClearingSnapshots}
                  onClick={() => setIsConfirmingClearSnapshots(false)}
                >
                  取消
                </button>
              </div>
            ) : (
              <button
                type="button"
                className="button button-danger-ghost"
                disabled={isClearingSnapshots}
                onClick={() => setIsConfirmingClearSnapshots(true)}
              >
                清除资产快照
              </button>
            )}
            <p>将删除所有渠道和快照数据。此操作无法撤销。</p>
            {isConfirmingReset ? (
              <div className="danger-actions">
                <button
                  type="button"
                  className="button button-danger"
                  aria-label="确认清空所有配置"
                  disabled={isResetting}
                  onClick={() => {
                    onResetSystem()
                    setIsConfirmingReset(false)
                  }}
                >
                  {isResetting ? '清空中...' : '确认清空'}
                </button>
                <button
                  type="button"
                  className="button button-secondary"
                  disabled={isResetting}
                  onClick={() => setIsConfirmingReset(false)}
                >
                  取消
                </button>
              </div>
            ) : (
              <button
                type="button"
                className="button button-danger-ghost"
                disabled={isResetting}
                onClick={() => setIsConfirmingReset(true)}
              >
                清空所有配置
              </button>
            )}
          </article>
        </div>
      </div>
    </div>
  )
}

function PortfolioInclusionPanel({
  items,
  isSaving,
  onToggle,
}: {
  items: PortfolioItem[]
  isSaving: boolean
  onToggle: (key: string, includedInTotals: boolean) => void
}) {
  if (items.length === 0) {
    return <p className="empty-copy">刷新资产后，这里会显示可配置的仓位和币种。</p>
  }

  const grouped = items.reduce<Record<string, PortfolioItem[]>>((acc, item) => {
    const key = item.channelName
    acc[key] = acc[key] ? [...acc[key], item] : [item]
    return acc
  }, {})

  return (
    <div className="portfolio-inclusion-list" aria-label="资产统计计入范围">
      {Object.entries(grouped).map(([channelName, channelItems]) => (
        <div key={channelName} className="portfolio-inclusion-group">
          <div className="portfolio-inclusion-group-head">
            <strong>{channelName}</strong>
            <span>{`${channelItems.length} 项`}</span>
          </div>
          {channelItems.map((item) => {
            const displayName = `${item.channelName} · ${humanizeAccountScope(item.accountScope)} · ${item.assetSymbol}`
            return (
              <label key={item.key} className="portfolio-inclusion-row">
                <input
                  type="checkbox"
                  checked={item.includedInTotals}
                  disabled={isSaving}
                  aria-label={`计入统计 ${displayName}`}
                  onChange={(event) => onToggle(item.key, event.target.checked)}
                />
                <span>
                  <strong>{`${humanizeAccountScope(item.accountScope)} · ${item.assetSymbol}`}</strong>
                  <em>{`${humanizeProvider(item.provider)} · ${formatUsd(item.valueUsd)}`}</em>
                </span>
                <b>{item.includedInTotals ? '计入统计' : '仅展示'}</b>
              </label>
            )
          })}
        </div>
      ))}
    </div>
  )
}

function LiquidationRiskPanel({
  monitor,
  isRefreshing,
  onRefresh,
}: {
  monitor?: LiquidationMonitorResponse
  isRefreshing: boolean
  onRefresh: () => void
}) {
  const positions = monitor?.positions ?? []
  const marginBalances = monitor?.marginBalances ?? []
  const adlEvents = monitor?.adlEvents ?? []
  const [activeView, setActiveView] = useState<'position' | 'margin' | 'adl'>('position')

  return (
    <div className="liquidation-block" id="risk">
      <div className="asset-totals-head">
        <h3>爆仓风险</h3>
        <span>
          {monitor?.config.monitorEnabled
            ? `监控中 · ${formatFrequency(monitor.config.checkIntervalSeconds)}`
            : '监控未开启'}
        </span>
      </div>
      <div className="risk-tabs" role="tablist" aria-label="爆仓风险视图">
        <button type="button" className={activeView === 'position' ? 'active' : ''} onClick={() => setActiveView('position')}>仓位风险</button>
        <button type="button" className={activeView === 'margin' ? 'active' : ''} onClick={() => setActiveView('margin')}>保证金余额</button>
        <button type="button" className={activeView === 'adl' ? 'active' : ''} onClick={() => setActiveView('adl')}>ADL 检测</button>
      </div>
      {activeView === 'position' ? (
        <div className="risk-list" aria-label="爆仓风险仓位">
          {positions.length > 0 ? (
            positions.map((position) => (
              <div key={position.id} className={`risk-row risk-status-${position.status}`}>
                <div className="risk-main">
                  <strong>{`${position.channelName} · ${position.symbol}`}</strong>
                  <span>{`${position.side} · ${humanizeRiskStatus(position.status)}`}</span>
                </div>
                <div className="risk-metric">
                  <span>距离</span>
                  <strong>{formatLiquidationRiskPercent(position.distancePercent)}</strong>
                </div>
                <div className="risk-metric">
                  <span>标记价</span>
                  <strong>{formatUsd(position.markPrice)}</strong>
                </div>
                <div className="risk-metric">
                  <span>清算价</span>
                  <strong>{formatLiquidationPrice(position.liquidationPrice)}</strong>
                </div>
                <div className="risk-alert">
                  {humanizeAlertStatus(position.lastAlertStatus)}
                </div>
              </div>
            ))
          ) : (
            <p className="empty-copy">无合约仓位风险</p>
          )}
        </div>
      ) : activeView === 'margin' ? (
        <div className="risk-list" aria-label="爆仓风险保证金余额">
          {marginBalances.length > 0 ? (
            marginBalances.map((item) => (
              <div key={item.id} className={`risk-row risk-status-${item.status}`}>
                <div className="risk-main">
                  <strong>{`${item.channelName} · ${humanizeRiskProvider(item.provider)}`}</strong>
                  <span>{humanizeRiskStatus(item.status)}</span>
                </div>
                <div className="risk-metric">
                  <span>风险比率</span>
                  <strong>{formatPercent(item.riskPercent)}</strong>
                </div>
                <div className="risk-metric">
                  <span>钱包余额</span>
                  <strong>{formatUsd(item.walletBalance)}</strong>
                </div>
                <div className="risk-metric">
                  <span>保证金余额</span>
                  <strong>{formatUsd(item.marginBalance)}</strong>
                </div>
                <div className="risk-alert">
                  {humanizeAlertStatus(item.lastAlertStatus)}
                </div>
              </div>
            ))
          ) : (
            <p className="empty-copy">无保证金余额风险</p>
          )}
        </div>
      ) : (
        <div className="risk-list" aria-label="ADL 检测事件">
          {adlEvents.length > 0 ? (
            adlEvents.map((item) => (
              <div key={item.id} className="risk-row risk-status-warning">
                <div className="risk-main">
                  <strong>{`${item.channelName} · ${item.symbol}`}</strong>
                  <span>{`${item.side} · ${humanizeAdlStatus(item.status)}`}</span>
                </div>
                <div className="risk-metric">
                  <span>减少</span>
                  <strong>{formatPercent(item.dropPercent)}</strong>
                </div>
                <div className="risk-metric">
                  <span>原数量</span>
                  <strong>{item.previousQuantity}</strong>
                </div>
                <div className="risk-metric">
                  <span>现数量</span>
                  <strong>{item.currentQuantity}</strong>
                </div>
                <div className="risk-alert">
                  {formatSnapshotTime(item.detectedAt)}
                </div>
              </div>
            ))
          ) : (
            <p className="empty-copy">无 ADL 检测事件</p>
          )}
        </div>
      )}
      <button
        type="button"
        className="button button-secondary"
        onClick={onRefresh}
        disabled={isRefreshing}
      >
        {isRefreshing ? '刷新中...' : '刷新爆仓风险'}
      </button>
    </div>
  )
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="metric-card">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  )
}

function FundingFeePanel({
  summary,
  selectedDate,
  isLoading,
  error,
  onDateChange,
}: {
  summary?: FundingFeeSummaryResponse
  selectedDate: string
  isLoading: boolean
  error?: string
  onDateChange: (value: string) => void
}) {
  const channels = summary?.channels ?? []

  return (
    <div className="funding-fee-panel" aria-label="资金费统计">
      <div className="asset-totals-head funding-fee-head">
        <div>
          <h3>资金费统计</h3>
          <span>{isLoading ? '统计中' : `${summary?.recordsCount ?? 0} 条结算记录`}</span>
        </div>
        <label className="field funding-date-field">
          <span>资金费日期</span>
          <input
            type="date"
            value={selectedDate}
            onChange={(event) => onDateChange(event.target.value)}
          />
        </label>
      </div>
      {error ? <p className="form-error">{error}</p> : null}
      <div className="funding-summary-grid">
        <Metric label="资金费收取" value={formatUsd(summary?.received ?? '0')} />
        <Metric label="资金费付出" value={formatUsd(summary?.paid ?? '0')} />
        <Metric label="净资金费" value={formatUsd(summary?.net ?? '0')} />
      </div>
      <div className="funding-channel-list" role="list" aria-label="渠道资金费明细">
        {channels.length > 0 ? (
          channels.map((channel) => (
            <div key={channel.channelId} className={`funding-channel-row status-${channel.status}`} role="listitem">
              <div>
                <strong>{channel.channelName}</strong>
                <span>{`${humanizeProvider(channel.provider)} · ${fundingStatusText(channel.status)} · ${channel.recordsCount} 条`}</span>
                {channel.error ? <em>{channel.error}</em> : null}
              </div>
              <b>{formatUsd(channel.received)}</b>
              <b>{formatUsd(channel.paid)}</b>
              <strong>{formatUsd(channel.net)}</strong>
            </div>
          ))
        ) : (
          <p className="empty-copy">暂无资金费记录。</p>
        )}
      </div>
    </div>
  )
}

function fundingStatusText(value: string) {
  if (value === 'success') return '已统计'
  if (value === 'disabled') return '已停用'
  if (value === 'failed') return '失败'
  return value
}

function ChannelList({
  channels,
  onTest,
  onDelete,
  onEdit,
}: {
  channels: ChannelResponse[]
  onTest: (channelId: number) => void
  onDelete: (channelId: number) => void
  onEdit: (channel: ChannelResponse) => void
}) {
  const [pendingDeleteId, setPendingDeleteId] = useState<number | null>(null)

  if (channels.length === 0) {
    return (
        <div className="channel-list">
        <div className="empty-state channel-empty-state">
          <strong>还没有渠道</strong>
          <span>添加一个交易所或链上钱包开始使用。</span>
        </div>
      </div>
    )
  }

  return (
    <div className="channel-list">
      {channels.map((channel) => (
        <div key={channel.id} className="channel-card">
          <div>
            <p>{humanizeProvider(channel.provider)}</p>
            <strong>{channel.name}</strong>
          </div>
          <span>{humanizeStatus(channel.lastTestStatus)}</span>
          <button
            type="button"
            className="button button-secondary"
            aria-label={`测试 ${channel.name}`}
            onClick={() => onTest(channel.id)}
          >
            测试
          </button>
          <button
            type="button"
            className="button button-secondary"
            aria-label={`编辑 ${channel.name}`}
            onClick={() => onEdit(channel)}
          >
            编辑
          </button>
          {pendingDeleteId === channel.id ? (
            <>
              <button
                type="button"
                className="button button-danger"
                aria-label={`确认删除 ${channel.name}`}
                onClick={() => {
                  onDelete(channel.id)
                  setPendingDeleteId(null)
                }}
              >
                确认
              </button>
              <button
                type="button"
                className="button button-secondary"
                onClick={() => setPendingDeleteId(null)}
              >
                取消
              </button>
            </>
          ) : (
            <button
              type="button"
              className="button button-secondary"
              aria-label={`删除 ${channel.name}`}
              onClick={() => setPendingDeleteId(channel.id)}
            >
              删除
            </button>
          )}
        </div>
      ))}
    </div>
  )
}

function ChannelForm({
  onSubmit,
  isSaving,
  editingChannel,
  onCancelEdit,
}: {
  onSubmit: (payload: CreateChannelPayload) => void
  isSaving: boolean
  editingChannel?: ChannelResponse | null
  onCancelEdit?: () => void
}) {
  const editingProvider = channelSchema.shape.provider.safeParse(editingChannel?.provider)
  const editingKind = channelSchema.shape.kind.safeParse(editingChannel?.kind)
  const form = useForm<ChannelFormValues>({
    resolver: zodResolver(channelSchema),
    defaultValues: editingChannel
      ? {
          name: editingChannel.name,
          provider: editingProvider.success ? editingProvider.data : 'binance',
          kind: editingKind.success ? editingKind.data : 'cex',
          apiKey: editingChannel.secretConfigMask.apiKey || '',
          apiSecret: editingChannel.secretConfigMask.apiSecret || '',
          passphrase: editingChannel.secretConfigMask.passphrase || '',
          asterUser: editingChannel.secretConfigMask.user || '',
          asterSigner: editingChannel.secretConfigMask.signer || '',
          asterPrivateKey: editingChannel.secretConfigMask.privateKey || '',
          walletAddresses: (editingChannel.publicConfig.walletAddresses as string[])?.join('\n') ?? '',
          chainIndexes: (editingChannel.publicConfig.chainIndexes as string[]) ?? [],
        }
      : {
          name: '',
          provider: 'binance',
          kind: 'cex',
          apiKey: '',
          apiSecret: '',
          passphrase: '',
          asterUser: '',
          asterSigner: '',
          asterPrivateKey: '',
          walletAddresses: '',
          chainIndexes: [],
        },
  })

  const { register, handleSubmit, formState: { errors }, control, setValue } = form
  const provider = useWatch({ control, name: 'provider' })
  const selectedChainIndexes = useWatch({ control, name: 'chainIndexes' }) ?? []
  const onchainChainsQuery = useQuery({
    queryKey: ['onchain-chains'],
    queryFn: api.getOnchainChains,
    enabled: provider === 'onchain',
  })

  useEffect(() => {
    if (editingChannel) {
      const p = channelSchema.shape.provider.safeParse(editingChannel.provider)
      const k = channelSchema.shape.kind.safeParse(editingChannel.kind)
      form.reset({
        name: editingChannel.name,
        provider: p.success ? p.data : 'binance',
        kind: k.success ? k.data : 'cex',
        apiKey: editingChannel.secretConfigMask.apiKey || '',
        apiSecret: editingChannel.secretConfigMask.apiSecret || '',
        passphrase: editingChannel.secretConfigMask.passphrase || '',
        asterUser: editingChannel.secretConfigMask.user || '',
        asterSigner: editingChannel.secretConfigMask.signer || '',
        asterPrivateKey: editingChannel.secretConfigMask.privateKey || '',
        walletAddresses: (editingChannel.publicConfig.walletAddresses as string[])?.join('\n') ?? '',
        chainIndexes: (editingChannel.publicConfig.chainIndexes as string[]) ?? [],
      })
    } else {
      form.reset({
        name: '',
        provider: 'binance',
        kind: 'cex',
        apiKey: '',
        apiSecret: '',
        passphrase: '',
        asterUser: '',
        asterSigner: '',
        asterPrivateKey: '',
        walletAddresses: '',
        chainIndexes: [],
      })
    }
  }, [editingChannel, form])

  useEffect(() => {
    if (provider !== 'onchain' || selectedChainIndexes.length > 0) {
      return
    }
    const defaultIndexes = (onchainChainsQuery.data ?? [])
      .filter((chain: OnchainChainOption) => chain.defaultSelected)
      .map((chain: OnchainChainOption) => chain.chainIndex)
    if (defaultIndexes.length > 0) {
      setValue('chainIndexes', defaultIndexes, { shouldDirty: true })
    }
  }, [onchainChainsQuery.data, provider, selectedChainIndexes.length, setValue])

  const apiKey = useWatch({ control, name: 'apiKey' })
  const apiSecret = useWatch({ control, name: 'apiSecret' })
  const isOnChain = provider === 'onchain'
  const isAster = provider === 'aster'
  const usesWalletAddress = isOnChain || isAster
  const isPassphraseProvider = provider === 'okx' || provider === 'bitget'
  const hasCexData = !!(apiKey || apiSecret)

  return (
    <form
      className="editor-form"
      onSubmit={handleSubmit((values) => {
        const publicConfig: Record<string, unknown> = {}
        const secretConfig: Record<string, string> = {}

        if (usesWalletAddress) {
          publicConfig.walletAddresses = (values.walletAddresses ?? '')
            .split('\n')
            .map((item) => item.trim())
            .filter(Boolean)
          if (isOnChain) {
            publicConfig.chainIndexes = values.chainIndexes ?? []
          }
        }

        if (isAster) {
          const masked = editingChannel?.secretConfigMask ?? {}
          if (values.asterUser && values.asterUser !== masked.user) {
            secretConfig.user = values.asterUser
          }
          if (values.asterSigner && values.asterSigner !== masked.signer) {
            secretConfig.signer = values.asterSigner
          }
          if (values.asterPrivateKey && values.asterPrivateKey !== masked.privateKey) {
            secretConfig.privateKey = values.asterPrivateKey
          }
        } else if (!isOnChain) {
          const masked = editingChannel?.secretConfigMask ?? {}
          if (values.apiKey && values.apiKey !== masked.apiKey) {
            secretConfig.apiKey = values.apiKey
          }
          if (values.apiSecret && values.apiSecret !== masked.apiSecret) {
            secretConfig.apiSecret = values.apiSecret
          }
          if (isPassphraseProvider && values.passphrase && values.passphrase !== masked.passphrase) {
            secretConfig.passphrase = values.passphrase
          }
          publicConfig.accountType = 'spot'
        }

        onSubmit({
          provider: values.provider,
          kind: isOnChain ? 'chain' : values.kind,
          name: values.name,
          publicConfig,
          secretConfig,
        })
      })}
    >
      <Field label="名称" error={errors.name?.message}>
        <input {...register('name')} />
      </Field>
      <Field label="渠道" error={errors.provider?.message}>
        <select {...register('provider')}>
          <option value="binance">Binance</option>
          <option value="gate">Gate</option>
          <option value="okx">OKX</option>
          <option value="bitget">Bitget</option>
          <option value="bybit">Bybit</option>
          <option value="aster">Aster</option>
          <option value="onchain">On Chain</option>
        </select>
      </Field>

      {usesWalletAddress ? (
        <div className="field-switch">
          {isOnChain && hasCexData ? (
            <p className="field-switch-notice" role="alert">
              已切换到钱包地址模式，之前输入的 API 密钥字段将被忽略。
            </p>
          ) : null}
          <Field label="钱包地址" error={errors.walletAddresses?.message}>
            <textarea rows={3} {...register('walletAddresses')} />
          </Field>
          {isOnChain ? (
            <fieldset className="chain-picker">
              <legend>EVM 链</legend>
              {onchainChainsQuery.isError ? (
                <p className="field-error" role="alert">
                  EVM 链列表加载失败。
                </p>
              ) : null}
              <div className="chain-picker-grid">
                {(onchainChainsQuery.data ?? []).map((chain) => (
                  <label key={chain.chainIndex} className="chain-option">
                    <input
                      type="checkbox"
                      value={chain.chainIndex}
                      {...register('chainIndexes')}
                    />
                    <span>{chain.chainName}</span>
                    <em>{chain.shortName}</em>
                  </label>
                ))}
              </div>
            </fieldset>
          ) : null}
          {isAster ? (
            <>
              <Field label="User Wallet" error={errors.asterUser?.message}>
                <input {...register('asterUser')} />
              </Field>
              <Field label="Signer Wallet" error={errors.asterSigner?.message}>
                <input {...register('asterSigner')} />
              </Field>
              <Field label="Private Key" error={errors.asterPrivateKey?.message}>
                <input type="password" {...register('asterPrivateKey')} />
              </Field>
            </>
          ) : null}
        </div>
      ) : (
        <div className="field-switch">
          <Field label="API Key" error={errors.apiKey?.message}>
            <input {...register('apiKey')} />
          </Field>
          <Field label="API Secret" error={errors.apiSecret?.message}>
            <input type="password" {...register('apiSecret')} />
          </Field>
          {isPassphraseProvider ? (
            <Field label="Passphrase" error={errors.passphrase?.message}>
              <input type="password" {...register('passphrase')} />
            </Field>
          ) : null}
          {editingChannel ? (
            <p className="field-hint secret-hint">
              密钥已脱敏显示；留空或保持原样不会修改现有配置。
            </p>
          ) : null}
        </div>
      )}

      <div className="form-action-row">
        <button type="submit" className="button button-primary" disabled={isSaving}>
          {isSaving ? '保存中...' : editingChannel ? '更新渠道' : '保存渠道'}
        </button>
        {editingChannel ? (
          <button type="button" className="button button-secondary" onClick={onCancelEdit}>
            取消
          </button>
        ) : null}
      </div>
    </form>
  )
}

function LiquidationMonitorForm({
  monitor,
  onSubmit,
  onTestMiaotixingAlert,
  onTestBarkAlert,
  isSaving,
  isTestingMiaotixingAlert,
  isTestingBarkAlert,
}: {
  monitor?: LiquidationMonitorResponse
  onSubmit: (payload: UpdateLiquidationMonitorPayload) => void
  onTestMiaotixingAlert: () => void
  onTestBarkAlert: () => void
  isSaving: boolean
  isTestingMiaotixingAlert: boolean
  isTestingBarkAlert: boolean
}) {
  const config = monitor?.config
  const form = useForm<LiquidationMonitorFormInput, undefined, LiquidationMonitorFormValues>({
    resolver: zodResolver(liquidationMonitorSchema),
    defaultValues: {
      positionMonitorEnabled: config?.positionMonitorEnabled ?? config?.monitorEnabled ?? false,
      positionThresholdPercent: formatIntegerInputValue(
        config?.positionThresholdPercent ?? config?.thresholdPercent,
        '5',
      ),
      marginBalanceMonitorEnabled: config?.marginBalanceMonitorEnabled ?? false,
      marginBalanceThresholdPercent: formatIntegerInputValue(config?.marginBalanceThresholdPercent, '70'),
      adlMonitorEnabled: config?.adlMonitorEnabled ?? false,
      adlThresholdPercent: formatIntegerInputValue(config?.adlThresholdPercent, '40'),
      adlWindowSeconds: config?.adlWindowSeconds ?? 60,
      adlSampleIntervalSeconds: config?.adlSampleIntervalSeconds ?? 30,
      adlStartTime: config?.adlStartTime ?? '00:00',
      adlEndTime: config?.adlEndTime ?? '23:59',
      checkIntervalSeconds: config?.checkIntervalSeconds ?? 60,
      alertIntervalSeconds: config?.alertIntervalSeconds ?? 900,
      miaoCode: config?.miaoCode ?? '',
      barkPushUrl: config?.barkPushUrl ?? '',
    },
  })
  const { register, handleSubmit, reset, formState: { errors } } = form

  useEffect(() => {
    reset({
      positionMonitorEnabled: config?.positionMonitorEnabled ?? config?.monitorEnabled ?? false,
      positionThresholdPercent: formatIntegerInputValue(
        config?.positionThresholdPercent ?? config?.thresholdPercent,
        '5',
      ),
      marginBalanceMonitorEnabled: config?.marginBalanceMonitorEnabled ?? false,
      marginBalanceThresholdPercent: formatIntegerInputValue(config?.marginBalanceThresholdPercent, '70'),
      adlMonitorEnabled: config?.adlMonitorEnabled ?? false,
      adlThresholdPercent: formatIntegerInputValue(config?.adlThresholdPercent, '40'),
      adlWindowSeconds: config?.adlWindowSeconds ?? 60,
      adlSampleIntervalSeconds: config?.adlSampleIntervalSeconds ?? 30,
      adlStartTime: config?.adlStartTime ?? '00:00',
      adlEndTime: config?.adlEndTime ?? '23:59',
      checkIntervalSeconds: config?.checkIntervalSeconds ?? 60,
      alertIntervalSeconds: config?.alertIntervalSeconds ?? 900,
      miaoCode: config?.miaoCode ?? '',
      barkPushUrl: config?.barkPushUrl ?? '',
    })
  }, [config, reset])

  return (
    <form
      className="liquidation-form"
      onSubmit={handleSubmit((values) => {
        const miaoCode = values.miaoCode?.trim()
        const barkPushUrl = values.barkPushUrl?.trim()
        onSubmit({
          monitorEnabled: values.positionMonitorEnabled || values.marginBalanceMonitorEnabled || values.adlMonitorEnabled,
          positionMonitorEnabled: values.positionMonitorEnabled,
          positionThresholdPercent: values.positionThresholdPercent,
          marginBalanceMonitorEnabled: values.marginBalanceMonitorEnabled,
          marginBalanceThresholdPercent: values.marginBalanceThresholdPercent,
          adlMonitorEnabled: values.adlMonitorEnabled,
          adlThresholdPercent: values.adlThresholdPercent,
          adlWindowSeconds: values.adlWindowSeconds,
          adlSampleIntervalSeconds: values.adlSampleIntervalSeconds,
          adlStartTime: values.adlStartTime,
          adlEndTime: values.adlEndTime,
          checkIntervalSeconds: values.checkIntervalSeconds,
          alertIntervalSeconds: values.alertIntervalSeconds,
          miaoCode,
          barkPushUrl,
        })
      })}
    >
      <div className="toggle-row">
        <label className="toggle-label">
          <input type="checkbox" {...register('positionMonitorEnabled')} />
          开启仓位风险监控
        </label>
        <label className="toggle-label">
          <input type="checkbox" {...register('marginBalanceMonitorEnabled')} />
          开启保证金余额监控
        </label>
        <label className="toggle-label">
          <input type="checkbox" {...register('adlMonitorEnabled')} />
          开启 ADL 检测
        </label>
      </div>
      <Field label="仓位风险阈值" error={errors.positionThresholdPercent?.message}>
        <input type="number" step="1" min="1" {...register('positionThresholdPercent')} />
      </Field>
      <Field label="保证金余额阈值" error={errors.marginBalanceThresholdPercent?.message}>
        <input type="number" step="1" min="1" {...register('marginBalanceThresholdPercent')} />
      </Field>
      <Field label="ADL 减仓阈值" error={errors.adlThresholdPercent?.message}>
        <input type="number" step="1" min="1" {...register('adlThresholdPercent')} />
      </Field>
      <Field label="ADL 检测窗口" error={errors.adlWindowSeconds?.message}>
        <input type="number" step="1" min="1" {...register('adlWindowSeconds', { valueAsNumber: true })} />
      </Field>
      <Field label="ADL 采样间隔" error={errors.adlSampleIntervalSeconds?.message}>
        <input type="number" step="1" min="1" {...register('adlSampleIntervalSeconds', { valueAsNumber: true })} />
      </Field>
      <Field label="ADL 开始时间" error={errors.adlStartTime?.message}>
        <input type="time" {...register('adlStartTime')} />
      </Field>
      <Field label="ADL 结束时间" error={errors.adlEndTime?.message}>
        <input type="time" {...register('adlEndTime')} />
      </Field>
      <Field label="监控频率" error={errors.checkIntervalSeconds?.message}>
        <input type="number" step="1" min="1" {...register('checkIntervalSeconds', { valueAsNumber: true })} />
      </Field>
      <Field label="提醒频率" error={errors.alertIntervalSeconds?.message}>
        <input type="number" step="1" min="1" {...register('alertIntervalSeconds', { valueAsNumber: true })} />
      </Field>
      <Field label="喵码" error={errors.miaoCode?.message}>
        <input
          autoComplete="off"
          spellCheck={false}
          {...register('miaoCode')}
          placeholder="输入喵码"
        />
      </Field>
      <Field label="Bark Push URL" error={errors.barkPushUrl?.message}>
        <input
          autoComplete="off"
          spellCheck={false}
          {...register('barkPushUrl')}
          placeholder="https://bark.example.com/device-key"
        />
      </Field>
      <div className="form-actions">
        <button type="submit" className="button button-primary" disabled={isSaving}>
          {isSaving ? '保存中...' : '保存爆仓监控'}
        </button>
        <button
          type="button"
          className="button button-secondary"
          onClick={onTestMiaotixingAlert}
          disabled={isTestingMiaotixingAlert}
        >
          {isTestingMiaotixingAlert ? '测试中...' : '测试喵提醒'}
        </button>
        <button
          type="button"
          className="button button-secondary"
          onClick={onTestBarkAlert}
          disabled={isTestingBarkAlert}
        >
          {isTestingBarkAlert ? '测试中...' : '测试 Bark'}
        </button>
      </div>
    </form>
  )
}

function ScheduleForm({
  defaultValues,
  onSubmit,
  isSaving,
}: {
  defaultValues?: ScheduleResponse
  onSubmit: (payload: ScheduleResponse) => void
  isSaving: boolean
}) {
  const timeHintId = useId()
  const form = useForm<ScheduleFormInput, undefined, ScheduleFormValues>({
    resolver: zodResolver(scheduleSchema),
    defaultValues: defaultValues ?? {
      snapshotScheduleTimes: '08:00',
      okxDexApiKey: '',
      okxDexApiSecret: '',
      okxDexPassphrase: '',
    },
  })

  const { register, handleSubmit, formState: { errors } } = form

  return (
    <form className="schedule-form" onSubmit={handleSubmit((values) => onSubmit(values))}>
      <Field label="每日快照时间" error={errors.snapshotScheduleTimes?.message}>
        <input
          {...register('snapshotScheduleTimes')}
          placeholder="08:00,20:00"
          aria-describedby={timeHintId}
        />
        <span id={timeHintId} className="field-hint">
          多个时间用逗号分隔，时区 UTC+8
        </span>
      </Field>
      <details open>
        <summary>OKX DEX 配置（用于 On Chain 渠道）</summary>
        <Field label="OKX DEX API Key" error={errors.okxDexApiKey?.message}>
          <input {...register('okxDexApiKey')} placeholder={defaultValues?.okxDexSecretConfigured ? '已配置' : '输入 API Key'} />
        </Field>
        <Field label="OKX DEX API Secret" error={errors.okxDexApiSecret?.message}>
          <input type="password" {...register('okxDexApiSecret')} placeholder={defaultValues?.okxDexSecretConfigured ? '留空则不修改' : '输入 API Secret'} />
        </Field>
        <Field label="OKX DEX Passphrase" error={errors.okxDexPassphrase?.message}>
          <input type="password" {...register('okxDexPassphrase')} placeholder={defaultValues?.okxDexSecretConfigured ? '留空则不修改' : '输入 Passphrase'} />
        </Field>
      </details>
      <button type="submit" className="button button-primary" disabled={isSaving}>
        {isSaving ? '保存中...' : '保存调度配置'}
      </button>
    </form>
  )
}

function Field({ label, error, children }: { label: string; error?: string; children: ReactNode }) {
  const errorId = useId()
  return (
    <label className="field">
      <span>{label}</span>
      {children}
      {error ? (
        <span id={errorId} className="field-error" role="alert">
          {error}
        </span>
      ) : null}
    </label>
  )
}

export default App
