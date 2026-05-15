import { useEffect, useRef } from 'react'
import type { EChartsOption, EChartsType } from 'echarts'
import type { ReactNode } from 'react'

import { loadEcharts } from '../lib/load-echarts'

interface ChartSurfaceProps {
  ariaLabel: string
  option: EChartsOption
  children?: ReactNode
}

export function ChartSurface({ ariaLabel, option, children }: ChartSurfaceProps) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const chartRef = useRef<EChartsType | null>(null)
  const latestOptionRef = useRef(option)

  useEffect(() => {
    latestOptionRef.current = option
    chartRef.current?.setOption(option)
  }, [option])

  useEffect(() => {
    const container = containerRef.current
    if (!container) {
      return
    }

    let isMounted = true
    let observer: ResizeObserver | null = null

    void loadEcharts().then((echarts) => {
      if (!isMounted) {
        return
      }

      const chart = echarts.init(container)
      chartRef.current = chart
      chart.setOption(latestOptionRef.current)

      observer = new ResizeObserver(() => {
        chart.resize()
      })
      observer.observe(container)
    })

    return () => {
      isMounted = false
      observer?.disconnect()
      chartRef.current?.dispose()
      chartRef.current = null
    }
  }, [])

  return (
    <figure className="chart-figure">
      <div
        ref={containerRef}
        className="chart-surface"
        role="img"
        aria-label={ariaLabel}
      />
      {children ? <div className="sr-only">{children}</div> : null}
    </figure>
  )
}
