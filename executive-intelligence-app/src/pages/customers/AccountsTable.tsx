import { useMemo, useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { AlertTriangle, ArrowDown, ArrowUp, ChevronRight } from 'lucide-react'
import { ACCENT_COLOR, BRAND_COLOR } from '../../brand'
import { Sparkline, money, pct, points } from '../../components/story'
import { useElementWidth } from '../../hooks/useElementWidth'
import { type AccountRow } from './shared'
import { RENEWAL_SOON_DAYS, renewsIn, signedMoney } from './helpers'

interface MonthlyRow {
  customer_id: string
  month: string
  revenue_usd: number
}

type SortKey = 'attention' | 'name' | 'revenue' | 'plan' | 'share' | 'gap' | 'renewal'

/** Below this width the table becomes one card per account: the columns need about 800px. */
const COMPACT_BELOW = 780

const COLUMNS =
  'grid-cols-[minmax(0,1fr)_6.5rem_4.5rem_3.75rem_7rem_4.75rem_4.75rem_1rem]'

/** Higher sorts first. Missing values sort last either way. */
const VALUE: Record<Exclude<SortKey, 'attention'>, (a: AccountRow) => number | string | null> = {
  name: (a) => a.customer_name.toLowerCase(),
  revenue: (a) => a.revenue_usd,
  plan: (a) => a.plan_attainment,
  share: (a) => a.device_share_change,
  gap: (a) => a.nq_gap_usd,
  renewal: (a) => a.days_to_renewal,
}

function sortAccounts(rows: AccountRow[], key: SortKey, descending: boolean): AccountRow[] {
  const sorted = [...rows]
  if (key === 'attention') {
    // Trouble first, soonest renewal first among the troubled, then by size.
    const renewal = (a: AccountRow) => a.days_to_renewal ?? Number.MAX_SAFE_INTEGER
    return sorted.sort((a, b) => {
      if (a.at_risk !== b.at_risk) return a.at_risk ? -1 : 1
      if (a.at_risk && renewal(a) !== renewal(b)) return renewal(a) - renewal(b)
      return (b.revenue_usd ?? 0) - (a.revenue_usd ?? 0)
    })
  }
  const value = VALUE[key]
  return sorted.sort((a, b) => {
    const x = value(a)
    const y = value(b)
    if (x === null && y === null) return 0
    if (x === null) return 1
    if (y === null) return -1
    const order = x < y ? -1 : x > y ? 1 : 0
    return descending ? -order : order
  })
}

/** What to look at first for one account: the reason it is flagged, else what it is building toward. */
function Why({ a }: { a: AccountRow }) {
  if (a.at_risk && a.reason) {
    return (
      <span className="flex min-w-0 items-center gap-1 text-xs font-medium text-accent">
        <AlertTriangle className="h-3 w-3 shrink-0" aria-hidden="true" />
        <span className="truncate">{a.reason}</span>
      </span>
    )
  }
  return <span className="block truncate text-xs text-ink-muted">{a.focus ?? `${a.segment} · ${a.region}`}</span>
}

function statusColor(a: AccountRow): string {
  return a.at_risk ? 'bg-accent' : (a.plan_attainment ?? 1) >= 1 ? 'bg-emerald-600' : 'bg-amber-500'
}

const statusLabel = (a: AccountRow) =>
  a.at_risk ? 'At risk' : (a.plan_attainment ?? 1) >= 1 ? 'At or above plan' : 'Below plan'

function GapCell({ gap }: { gap: number | null }) {
  if (gap == null) return <span className="text-ink-muted">–</span>
  // The gap is plan less commit, so a positive gap is a shortfall.
  const short = gap > 0
  return <span className={short ? 'font-medium text-accent' : 'text-emerald-700'}>{signedMoney(-gap)}</span>
}

function RenewalCell({ a }: { a: AccountRow }) {
  const soon = a.days_to_renewal != null && a.days_to_renewal <= RENEWAL_SOON_DAYS
  return (
    <span
      className={soon ? 'font-medium text-accent' : 'text-ink-light'}
      title={a.next_renewal ? `${a.renewal_type}, ${money(a.renewal_usd)} a year, ends ${a.next_renewal}` : undefined}
    >
      {renewsIn(a.days_to_renewal)}
    </span>
  )
}

/**
 * The ten accounts, troubled ones first. Each row carries what a leader needs to
 * decide where to look: trend, size, plan, share of new devices, the quarter's
 * gap to plan, and how soon a contract ends. Click a heading to sort.
 */
export default function AccountsTable({
  accounts,
  monthly,
  quarter,
}: {
  accounts: AccountRow[]
  monthly: MonthlyRow[]
  quarter?: string
}) {
  const [ref, width] = useElementWidth<HTMLDivElement>()
  const [sort, setSort] = useState<{ key: SortKey; descending: boolean }>({ key: 'attention', descending: true })
  const rows = useMemo(() => sortAccounts(accounts, sort.key, sort.descending), [accounts, sort])

  // Revenue indexed to its level a year ago, on one scale, so trends compare across rows
  // whose revenue differs by a factor of five.
  const { series, domain } = useMemo(() => {
    const byAccount = new Map<string, number[]>()
    for (const r of monthly) {
      const list = byAccount.get(r.customer_id) ?? []
      list.push(r.revenue_usd)
      byAccount.set(r.customer_id, list)
    }
    const indexed = new Map<string, number[]>()
    const all: number[] = []
    for (const [id, values] of byAccount) {
      const base = values[0] || 1
      const scaled = values.map((v) => (v / base) * 100)
      indexed.set(id, scaled)
      all.push(...scaled)
    }
    return { series: indexed, domain: [Math.min(...all, 100), Math.max(...all, 100)] as [number, number] }
  }, [monthly])

  const compact = width > 0 && width < COMPACT_BELOW
  const gapLabel = `${quarter ?? 'Next qtr'} gap`

  const toggle = (key: SortKey, firstDescending = true) =>
    setSort((s) => (s.key === key ? { key, descending: !s.descending } : { key, descending: firstDescending }))

  const heading = (key: SortKey, label: string, align: 'left' | 'right' = 'right', firstDescending = true) => {
    const active = sort.key === key
    return (
      <button
        type="button"
        onClick={() => toggle(key, firstDescending)}
        className={`flex items-center gap-0.5 text-xs font-medium hover:text-ink ${align === 'right' ? 'justify-end' : ''} ${active ? 'text-ink' : 'text-ink-muted'}`}
        aria-label={`Sort by ${label}`}
        aria-pressed={active}
      >
        {label}
        {active && key !== 'attention' && (sort.descending ? <ArrowDown className="h-3 w-3" /> : <ArrowUp className="h-3 w-3" />)}
      </button>
    )
  }

  return (
    <div ref={ref}>
      {compact ? (
        <ul className="space-y-3">
          {rows.map((a) => (
            <li key={a.customer_id}>
              <Link
                to={a.customer_id}
                className={`block rounded-xl border border-line p-4 hover:bg-canvas ${a.at_risk ? 'bg-accent/[0.04]' : 'bg-white'}`}
              >
                <div className="flex items-center gap-2.5">
                  <span className={`h-2.5 w-2.5 shrink-0 rounded-full ${statusColor(a)}`} role="img" aria-label={statusLabel(a)} />
                  <span className="min-w-0 flex-1 truncate font-semibold text-ink">{a.customer_name}</span>
                  <ChevronRight className="h-4 w-4 shrink-0 text-ink-muted" aria-hidden="true" />
                </div>
                <div className="mt-1 pl-5">
                  <Why a={a} />
                </div>
                <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2 pl-5 text-sm">
                  <Stat label="Revenue" value={money(a.revenue_usd)} />
                  <Stat
                    label="Of plan"
                    value={pct(a.plan_attainment)}
                    tone={(a.plan_attainment ?? 1) < 0.95 ? 'bad' : undefined}
                  />
                  <Stat
                    label="Device share"
                    value={`${pct(a.device_share)} · ${points(a.device_share_change)}`}
                    tone={(a.device_share_change ?? 0) <= -0.1 ? 'bad' : undefined}
                  />
                  <Stat label={gapLabel} value={<GapCell gap={a.nq_gap_usd} />} />
                  <Stat label="Renews in" value={<RenewalCell a={a} />} />
                </dl>
              </Link>
            </li>
          ))}
        </ul>
      ) : (
        <div>
          <div className={`grid ${COLUMNS} items-end gap-3 border-b border-line pb-2`}>
            {heading('name', 'Account', 'left', false)}
            <span className="text-xs font-medium text-ink-muted">12 months</span>
            {heading('revenue', 'Revenue')}
            {heading('plan', 'Of plan')}
            {heading('share', 'Device share')}
            {heading('gap', gapLabel)}
            {heading('renewal', 'Renews in', 'right', false)}
            <span />
          </div>
          <ul className="divide-y divide-line">
            {rows.map((a) => (
              <li key={a.customer_id} className={a.at_risk ? 'bg-accent/[0.04]' : undefined}>
                <Link to={a.customer_id} className={`group grid ${COLUMNS} items-center gap-3 py-3 hover:bg-canvas`}>
                  <span className="flex min-w-0 items-center gap-2.5 pl-2">
                    <span className={`h-2 w-2 shrink-0 rounded-full ${statusColor(a)}`} role="img" aria-label={statusLabel(a)} />
                    <span className="min-w-0">
                      <span className="block truncate font-medium text-ink">{a.customer_name}</span>
                      <Why a={a} />
                    </span>
                  </span>
                  <Sparkline
                    values={series.get(a.customer_id) ?? []}
                    domain={domain}
                    width={104}
                    color={a.at_risk ? ACCENT_COLOR : BRAND_COLOR}
                  />
                  <span className="text-right tabular-nums text-ink">{money(a.revenue_usd)}</span>
                  <span className={`text-right tabular-nums ${(a.plan_attainment ?? 1) < 0.95 ? 'font-medium text-accent' : 'text-ink'}`}>
                    {pct(a.plan_attainment)}
                  </span>
                  <span className="text-right text-sm tabular-nums text-ink-light">
                    {pct(a.device_share)}{' '}
                    <span className={(a.device_share_change ?? 0) <= -0.1 ? 'font-medium text-accent' : 'text-ink-muted'}>
                      {(a.device_share_change ?? 0) === 0 ? '±0' : `${(a.device_share_change ?? 0) > 0 ? '+' : '−'}${Math.abs(Math.round((a.device_share_change ?? 0) * 100))}`}
                    </span>
                  </span>
                  <span className="text-right tabular-nums">
                    <GapCell gap={a.nq_gap_usd} />
                  </span>
                  <span className="text-right text-sm tabular-nums">
                    <RenewalCell a={a} />
                  </span>
                  <ChevronRight className="h-4 w-4 text-line group-hover:text-ink-muted" aria-hidden="true" />
                </Link>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-1 text-xs text-ink-muted">
        <Legend color="bg-accent" label="At risk: a risk signal in the last 120 days" />
        <Legend color="bg-amber-500" label="Below plan" />
        <Legend color="bg-emerald-600" label="At or above plan" />
        <span className="ml-auto">
          {sort.key === 'attention' ? (
            'At-risk accounts first, then by size.'
          ) : (
            <button type="button" className="underline hover:text-ink" onClick={() => setSort({ key: 'attention', descending: true })}>
              Back to at-risk first
            </button>
          )}{' '}
          Trend lines are revenue indexed to a year ago, on one scale. Device share change is in points.
        </span>
      </div>
    </div>
  )
}

function Legend({ color, label }: { color: string; label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className={`h-2 w-2 rounded-full ${color}`} aria-hidden="true" />
      {label}
    </span>
  )
}

function Stat({ label, value, tone }: { label: string; value: ReactNode; tone?: 'bad' }) {
  return (
    <div>
      <dt className="text-xs text-ink-muted">{label}</dt>
      <dd className={`tabular-nums ${tone === 'bad' ? 'font-medium text-accent' : 'text-ink'}`}>{value}</dd>
    </div>
  )
}
