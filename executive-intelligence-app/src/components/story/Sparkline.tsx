import { BRAND_COLOR } from '../../brand'

/** A trend line with no axes, for reading shape rather than values. */
export default function Sparkline({
  values,
  color = BRAND_COLOR,
  width = 112,
  height = 28,
  domain,
}: {
  values: number[]
  color?: string
  width?: number
  height?: number
  /** [min, max] to draw against, so several sparklines share one scale. Default: this line's own range. */
  domain?: [number, number]
}) {
  if (values.length < 2) return <span className="inline-block" style={{ width, height }} />
  const min = domain ? domain[0] : Math.min(...values)
  const max = domain ? domain[1] : Math.max(...values)
  const range = max - min || 1
  const points = values
    .map((v, i) => `${(i / (values.length - 1)) * (width - 4) + 2},${height - 3 - ((v - min) / range) * (height - 6)}`)
    .join(' ')
  const [lastX, lastY] = points.split(' ').at(-1)!.split(',').map(Number)
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} aria-hidden="true">
      <polyline points={points} fill="none" stroke={color} strokeWidth="1.75" strokeLinejoin="round" strokeLinecap="round" />
      <circle cx={lastX} cy={lastY} r="2.5" fill={color} />
    </svg>
  )
}
