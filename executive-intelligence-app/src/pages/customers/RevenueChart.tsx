import { Area, CartesianGrid, ComposedChart, Line, ReferenceArea, ReferenceDot, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { ACCENT_COLOR, BRAND_COLOR, CHART_AXIS, CHART_GRID } from '../../brand'
import { WidgetState, formatValue } from '../../components/dashboard'
import { money } from '../../components/story'
import { useDashboardQuery } from '../../hooks/useDashboardQuery'
import { type SignalRow } from './shared'
import { RENEWAL_SOON_DAYS, contractAbbreviation } from './helpers'
import type { ContractRow, RevenueRow } from './types'

const PLAN_COLOR = '#9AA1AB'

/** "2027-01-24" -> "2027-01-01": the month axis's own value for a date. */
const monthOf = (iso: string) => `${iso.slice(0, 7)}-01`

interface Point {
  month: string
  revenue: number | null
  plan: number | null
  forecast: number | null
  band: [number, number] | null
}

/**
 * One account's revenue against plan, with what is known to be coming laid on
 * the same time axis: where the forecast starts, the commit-to-best-case range,
 * the months its contracts end, and when risk signals arrived. The cause and
 * its effect read in one picture instead of three.
 */
export default function RevenueChart({ customer }: { customer: string }) {
  const revenue = useDashboardQuery<RevenueRow>('/customers/revenue', { customer })
  // The same requests as the Signals and Contracts sections, so React Query serves them from one fetch.
  const signals = useDashboardQuery<SignalRow>('/customers/signals', { customer })
  const contracts = useDashboardQuery<ContractRow>('/customers/contracts', { customer })

  return (
    <div>
      <div className="mb-1 flex flex-wrap items-baseline justify-between gap-2">
        <span className="text-sm font-medium text-ink-light">Revenue by month, with what is coming</span>
        <Key />
      </div>
      <WidgetState query={revenue}>
        {({ rows }) => <Chart rows={rows} signals={signals.data?.rows ?? []} contracts={contracts.data?.rows ?? []} />}
      </WidgetState>
    </div>
  )
}

function Chart({ rows, signals, contracts }: { rows: RevenueRow[]; signals: SignalRow[]; contracts: ContractRow[] }) {
  const lastActual = rows.reduce((last, r, i) => (r.revenue_usd != null ? i : last), -1)
  const data: Point[] = rows.map((r, i) => {
    // The forecast line starts where the actuals stop, so the two read as one line.
    const joins = i === lastActual && r.revenue_usd != null
    const forecast = r.commit_usd ?? (joins ? r.revenue_usd : null)
    const best = r.best_case_usd ?? (joins ? r.revenue_usd : null)
    return {
      month: r.month,
      revenue: r.revenue_usd,
      plan: r.plan_usd,
      forecast,
      band: forecast != null && best != null ? [forecast, best] : null,
    }
  })

  const first = data[0]?.month
  const last = data.at(-1)?.month
  const today = data[lastActual + 1]?.month
  const inRange = (month: string) => first != null && last != null && month >= first && month <= last
  const valueAt = (month: string) => {
    const p = data.find((d) => d.month === month)
    return p?.revenue ?? p?.forecast ?? p?.plan ?? null
  }

  const ends = contracts.filter((c) => inRange(monthOf(c.end_date)))
  const risks = signals.filter((s) => s.direction === 'risk' && inRange(monthOf(s.published_date)) && valueAt(monthOf(s.published_date)) != null)

  return (
    <div className="h-64">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={data} margin={{ top: 22, right: 12, bottom: 0, left: 0 }}>
          <CartesianGrid stroke={CHART_GRID} vertical={false} />
          <XAxis
            dataKey="month"
            tickFormatter={(v: string) => formatValue(v, 'month').replace(/ \d{2}(\d{2})$/, " '$1")}
            tick={{ fontSize: 11, fill: CHART_AXIS }}
            axisLine={false}
            tickLine={false}
            interval="preserveStartEnd"
            minTickGap={24}
          />
          <YAxis tickFormatter={(v: number) => money(v)} tick={{ fontSize: 11, fill: CHART_AXIS }} axisLine={false} tickLine={false} width={56} domain={[0, 'auto']} />
          <Tooltip content={<ChartTooltip />} />
          {today && last && <ReferenceArea x1={today} x2={last} fill={BRAND_COLOR} fillOpacity={0.05} ifOverflow="extendDomain" />}
          <Area dataKey="band" stroke="none" fill={BRAND_COLOR} fillOpacity={0.14} isAnimationActive={false} connectNulls={false} />
          <Line dataKey="plan" stroke={PLAN_COLOR} strokeWidth={1.5} strokeDasharray="4 4" dot={false} isAnimationActive={false} />
          <Line dataKey="revenue" stroke={BRAND_COLOR} strokeWidth={2.5} dot={false} isAnimationActive={false} />
          <Line dataKey="forecast" stroke={BRAND_COLOR} strokeWidth={2} strokeDasharray="2 4" dot={false} isAnimationActive={false} />
          {today && (
            <ReferenceLine x={today} stroke="#151515" strokeWidth={1} label={{ value: 'Today', position: 'insideTopLeft', fontSize: 11, fill: '#151515' }} />
          )}
          {ends.map((c) => {
            const soon = c.days_to_end <= RENEWAL_SOON_DAYS
            return (
              <ReferenceLine
                key={c.contract_id}
                x={monthOf(c.end_date)}
                stroke={soon ? ACCENT_COLOR : PLAN_COLOR}
                strokeDasharray="5 3"
                strokeWidth={1.5}
                label={{
                  value: `${contractAbbreviation(c.contract_type)} ends`,
                  position: 'insideTopRight',
                  fontSize: 11,
                  fill: soon ? ACCENT_COLOR : CHART_AXIS,
                }}
              />
            )
          })}
          {risks.map((s) => (
            <ReferenceDot
              key={s.signal_id}
              x={monthOf(s.published_date)}
              y={valueAt(monthOf(s.published_date)) as number}
              r={6}
              fill={ACCENT_COLOR}
              stroke="#fff"
              strokeWidth={2}
              ifOverflow="extendDomain"
              shape={(props: { cx?: number; cy?: number }) => (
                <g>
                  <title>
                    {s.headline} ({s.source_name}, {formatValue(s.published_date, 'date')})
                  </title>
                  <circle cx={props.cx} cy={props.cy} r={6} fill={ACCENT_COLOR} stroke="#fff" strokeWidth={2} />
                </g>
              )}
            />
          ))}
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  )
}

const NAMES: Record<string, string> = { revenue: 'Actual', plan: 'Plan', forecast: 'Commit' }

function ChartTooltip({ active, payload, label }: { active?: boolean; payload?: { dataKey?: string; value?: unknown; payload?: Point }[]; label?: string }) {
  if (!active || !payload?.length) return null
  const point = payload[0]?.payload
  const lines = payload.filter((p) => p.dataKey && NAMES[p.dataKey] && typeof p.value === 'number')
  return (
    <div className="rounded-lg border border-line bg-white px-3 py-2 text-xs shadow-tile">
      <div className="mb-1 font-semibold text-ink">{formatValue(label, 'month')}</div>
      {lines.map((p) => (
        <div key={p.dataKey} className="flex justify-between gap-4 text-ink-light">
          <span>{NAMES[p.dataKey as string]}</span>
          <span className="tabular-nums text-ink">{money(p.value)}</span>
        </div>
      ))}
      {point?.band && (
        <div className="flex justify-between gap-4 text-ink-light">
          <span>Best case</span>
          <span className="tabular-nums text-ink">{money(point.band[1])}</span>
        </div>
      )}
    </div>
  )
}

function Key() {
  const swatch = (color: string, dash?: string) => (
    <svg width="18" height="6" aria-hidden="true">
      <line x1="0" y1="3" x2="18" y2="3" stroke={color} strokeWidth="2" strokeDasharray={dash} />
    </svg>
  )
  return (
    <span className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-ink-muted">
      <span className="inline-flex items-center gap-1.5">{swatch(BRAND_COLOR)} Actual</span>
      <span className="inline-flex items-center gap-1.5">{swatch(BRAND_COLOR, '2 4')} Commit</span>
      <span className="inline-flex items-center gap-1.5">
        <span className="h-2.5 w-4 rounded-sm" style={{ background: BRAND_COLOR, opacity: 0.2 }} aria-hidden="true" /> To best case
      </span>
      <span className="inline-flex items-center gap-1.5">{swatch(PLAN_COLOR, '3 3')} Plan</span>
      <span className="inline-flex items-center gap-1.5">
        <span className="h-2.5 w-2.5 rounded-full" style={{ background: ACCENT_COLOR }} aria-hidden="true" /> Risk signal
      </span>
      <span className="inline-flex items-center gap-1.5">{swatch(ACCENT_COLOR, '4 2')} Contract ends</span>
    </span>
  )
}
