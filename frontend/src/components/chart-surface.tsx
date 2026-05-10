import { useEffect, useRef } from 'react'
import * as echarts from 'echarts'
import type { EChartsOption } from 'echarts'
import type { ReactNode } from 'react'

interface ChartSurfaceProps {
  ariaLabel: string
  option: EChartsOption
  children?: ReactNode
}

export function ChartSurface({ ariaLabel, option, children }: ChartSurfaceProps) {
  const containerRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    if (!containerRef.current) {
      return
    }

    const chart = echarts.init(containerRef.current)
    chart.setOption(option)

    const observer = new ResizeObserver(() => {
      chart.resize()
    })

    observer.observe(containerRef.current)

    return () => {
      observer.disconnect()
      chart.dispose()
    }
  }, [option])

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
