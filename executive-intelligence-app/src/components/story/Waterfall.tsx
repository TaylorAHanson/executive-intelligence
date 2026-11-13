import { ACCENT_COLOR } from '../../brand'
import { useElementWidth } from '../../hooks/useElementWidth'
import { money } from './format'

/** A total stands on the baseline; a change floats from the running total. */
export interface WaterfallStep {
  label: string
  /** A second, smaller line under the label. */
  detail?: string
  value: number
  kind: 'total' | 'change'
  /** Draw this total heavier than the others: the number the story turns on. */
  emphasis?: boolean
}

const HEIGHT = 230
const TOP = 28
const BOTTOM = 56
const GOOD = '#0E7C66'
const NEUTRAL = '#9AA1AB'
const STRONG = '#151515'

/** A scale floor that leaves room below the lowest level, on a round number. */
function floorFor(lowest: number, highest: number): number {
  const range = highest - lowest || highest * 0.1 || 1
  const unit = 10 ** Math.floor(Math.log10(range))
  return Math.max(0, Math.floor((lowest - range * 2) / unit) * unit)
}

/**
 * A bridge from one total to another through the changes between them: plan to
 * commit to best case. The scale starts above zero so the changes are visible
 * beside totals of several hundred million, and the chart says so in words.
 */
export default function Waterfall({ steps, summary }: { steps: WaterfallStep[]; summary: string }) {
  const [ref, width] = useElementWidth<HTMLDivElement>()

  // Each step starts from where the one before it ended; a total stands on the baseline.
  const bars = steps.reduce<{ step: WaterfallStep; from: number; to: number }[]>((all, step) => {
    const running = all.length ? all[all.length - 1].to : 0
    const from = step.kind === 'total' ? 0 : running
    const to = step.kind === 'total' ? step.value : running + step.value
    return [...all, { step, from, to }]
  }, [])
  const levels = bars.flatMap((b) => [b.from === 0 ? b.to : b.from, b.to])
  const lowest = Math.min(...levels)
  const highest = Math.max(...levels)
  const floor = floorFor(lowest, highest)

  const plotHeight = HEIGHT - TOP - BOTTOM
  const y = (value: number) => TOP + plotHeight - ((Math.max(value, floor) - floor) / (highest - floor || 1)) * plotHeight
  const slot = width > 0 ? width / bars.length : 0
  const barWidth = Math.min(72, slot * 0.58)

  return (
    <div ref={ref} className="w-full">
      {width > 0 && (
        <svg width={width} height={HEIGHT} role="img" aria-label={summary} className="block overflow-visible">
          <line x1={0} x2={width} y1={y(floor)} y2={y(floor)} stroke="#DDE1E6" />
          {bars.map(({ step, from, to }, i) => {
            const x = i * slot + (slot - barWidth) / 2
            const top = y(Math.max(from, to))
            const bottom = y(Math.min(from, to))
            const isTotal = step.kind === 'total'
            const color = isTotal ? (step.emphasis ? STRONG : NEUTRAL) : step.value < 0 ? ACCENT_COLOR : GOOD
            const signed = `${step.value >= 0 ? '+' : '−'}${money(Math.abs(step.value))}`
            const next = bars[i + 1]
            return (
              <g key={`${step.label}-${i}`}>
                {next && (
                  <line
                    x1={x + barWidth}
                    x2={(i + 1) * slot + (slot - barWidth) / 2}
                    y1={y(to)}
                    y2={y(to)}
                    stroke="#9AA1AB"
                    strokeDasharray="3 3"
                  />
                )}
                <rect x={x} y={top} width={barWidth} height={Math.max(2, bottom - top)} rx={3} fill={color} />
                <text
                  x={x + barWidth / 2}
                  y={top - 8}
                  textAnchor="middle"
                  className="tabular-nums"
                  fontSize={isTotal && step.emphasis ? 17 : 13}
                  fontWeight={isTotal ? 700 : 600}
                  fill={isTotal ? STRONG : color}
                >
                  {isTotal ? money(step.value) : signed}
                </text>
                <text x={x + barWidth / 2} y={HEIGHT - BOTTOM + 20} textAnchor="middle" fontSize={12} fontWeight={600} fill="#151515">
                  {step.label}
                </text>
                {step.detail && (
                  <text x={x + barWidth / 2} y={HEIGHT - BOTTOM + 36} textAnchor="middle" fontSize={11} fill="#666666">
                    {step.detail}
                  </text>
                )}
              </g>
            )
          })}
        </svg>
      )}
      {floor > 0 && <p className="mt-1 text-xs text-ink-muted">Scale starts at {money(floor)}, not zero, so the changes show.</p>}
    </div>
  )
}
