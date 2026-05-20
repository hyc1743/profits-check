const usdFormatter = new Intl.NumberFormat('en-US', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
})

export function formatUsd(value: string | number | null | undefined): string {
  if (value === null || value === undefined) {
    return '未估值'
  }
  const numeric = typeof value === 'number' ? value : Number(value)
  if (Number.isNaN(numeric)) {
    return '未估值'
  }
  return `${numeric.toFixed(2)} USD`
}

export function formatUsdCompact(value: string | number | null | undefined): string {
  if (value === null || value === undefined) {
    return '未估值'
  }
  const numeric = typeof value === 'number' ? value : Number(value)
  if (Number.isNaN(numeric)) {
    return '未估值'
  }
  return `$${usdFormatter.format(numeric)}`
}

export function humanizeProvider(value: string): string {
  const names: Record<string, string> = {
    onchain: 'On Chain',
  }
  return names[value.toLowerCase()] ?? value.toUpperCase()
}

export function humanizeStatus(value: string | null | undefined): string {
  if (!value) {
    return '未检测'
  }

  const normalized = value.toLowerCase()
  if (normalized === 'ok' || normalized === 'success') {
    return '正常'
  }
  if (normalized === 'loading') {
    return '加载中'
  }
  if (normalized === 'running') {
    return '执行中'
  }
  if (normalized === 'failed' || normalized === 'error') {
    return '失败'
  }
  if (normalized === 'untested') {
    return '未检测'
  }

  return value
}

export function humanizeAccountScope(value: string): string {
  const normalized = value.toLowerCase()
  if (normalized === 'unified') {
    return '统一账户'
  }
  if (normalized === 'spot') {
    return '现货'
  }
  if (normalized === 'futures') {
    return '合约'
  }
  if (normalized === 'earn') {
    return '理财'
  }
  if (normalized === 'token_total') {
    return '链上代币总估值'
  }
  return value
}
