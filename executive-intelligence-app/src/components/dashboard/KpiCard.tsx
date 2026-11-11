import { Line, LineChart, ResponsiveContainer } from 'recharts'
import { ArrowDownRight, ArrowUpRight, Minus } from 'lucide-react'
import { SERIES_COLORS } from '../../brand'
import type { DashboardQuery } from '../../hooks/useDashboardQuery'
import { formatValue, toNumber, type ValueFormat } from './format'
import WidgetCard, { type WidgetFrameProps } from './WidgetCard'
import WidgetState from './WidgetState'

interface KpiCardProps<Row, TrendRow> extends WidgetFrameProps {
  /** A one-row query. Several cards can share one query. */
  query: DashboardQuery<Row>
  value: (row: Row) => unknown
  /** The comparison period's value, for the delta. */
  previous?: (row: Row) => unknown
  format?: ValueFormat
  /** What the delta compares against, e.g. "vs prior period". */
  deltaLabel?: string
  /** False for metrics where a rise is bad (returns, days late). */
  higherIsBetter?: boolean
  /** A query whose rows, in order, draw the sparkline. */
  trend?: { query: DashboardQuery<TrendRow>; value: (row: TrendRow) => unknown }
}

export default function KpiCard<Row, TrendRow = Row>({
  query,
  value,
  previous,
  format = 'number',
  deltaLabel = 'vs prior period',
  higherIsBetter = true,
  trend,
  span = 4,
  ...frame
}: KpiCardProps<Row, TrendRow>) {
  return (
    <WidgetCard span={span} {...frame}>
      <WidgetState query={query} skeleton="kpi">
        {({ rows }) => {
          const current = toNumber(value(rows[0]))
          const prior = previous ? toNumber(previous(rows[0])) : null
          return (
            <div className="flex items-end gap-3">
              <div className="min-w-0 flex-1">
                <div className="text-[1.9rem] font-extrabold leading-none tracking-[-0.01em] text-ink">
                  {formatValue(current, format)}
                </div>
                {previous && (
                  <Delta current={current} prior={prior} format={format} label={deltaLabel} higherIsBetter={higherIsBetter} />
                )}
              </div>
              {trend && <Sparkline trend={trend} />}
            </div>
          )
        }}
      </WidgetState>
    </WidgetCard>
  )
}

interface DeltaProps {
  current: number | null
  prior: number | null
  format: ValueFormat
  label: string
  higherIsBetter: boolean
}

function Delta({ current, prior, format, label, higherIsBetter }: DeltaProps) {
  if (current === null || prior === null) return <p className="mt-2 text-xs text-ink-muted">No comparison {label}</p>

  // A ratio's change reads in points (93.1% to 91.4% is -1.7 pts), anything
  // else's as a relative change.
  const points = format === 'percent'
  const change = points ? (current - prior) * 100 : prior === 0 ? null : (current - prior) / Math.abs(prior)
  if (change === null) return <p className="mt-2 text-xs text-ink-muted">No comparison {label}</p>

  const flat = Math.abs(change) < (points ? 0.05 : 0.0005)
  const good = flat ? null : change > 0 === higherIsBetter
  const Icon = flat ? Minus : change > 0 ? ArrowUpRight : ArrowDownRight
  const text = points ? `${change > 0 ? '+' : ''}${change.toFixed(1)} pts` : `${change > 0 ? '+' : ''}${formatValue(change, 'percent')}`

  return (
    <p className="mt-2 flex items-center gap-1 text-xs">
      <span
        className={`inline-flex items-center gap-0.5 font-semibold ${
          good === null ? 'text-ink-muted' : good ? 'text-emerald-700' : 'text-accent'
        }`}
      >
        <Icon className="h-3.5 w-3.5" aria-hidden="true" />
        {text}
      </span>
      <span className="text-ink-muted">{label}</span>
    </p>
  )
}

function Sparkline<TrendRow>({ trend }: { trend: NonNullable<KpiCardProps<unknown, TrendRow>['trend']> }) {
  const rows = trend.query.data?.rows
  if (!rows?.length) return null
  const points = rows.map((row) => ({ v: toNumber(trend.value(row)) }))
  return (
    <div className="h-10 w-24 shrink-0" aria-hidden="true">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={points} margin={{ top: 4, right: 2, bottom: 4, left: 2 }}>
          <Line type="monotone" dataKey="v" stroke={SERIES_COLORS[0]} strokeWidth={2} dot={false} isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}
