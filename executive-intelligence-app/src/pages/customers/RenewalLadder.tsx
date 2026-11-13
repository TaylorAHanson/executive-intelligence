import { Link } from 'react-router-dom'
import { ACCENT_COLOR, BRAND_COLOR } from '../../brand'
import { formatValue } from '../../components/dashboard'
import { money } from '../../components/story'
import { useElementWidth } from '../../hooks/useElementWidth'
import { RENEWAL_SOON_DAYS, contractAbbreviation, renewsIn } from './helpers'

export interface RenewalRow {
  contract_id: string
  customer_id: string
  customer_name: string
  contract_type: string
  end_date: string
  annual_value_usd: number
  status: string
  days_to_end: number
  at_risk: boolean
}

const DAY = 86_400_000
const HORIZON_DAYS = 365
const LABEL_WIDTH = 188
const ROW = 40
const AXIS = 26
const COMPACT_BELOW = 560

/** The radius of a contract's marker: area follows annual value. */
const radius = (value: number) => Math.min(13, Math.max(5, Math.sqrt(value / 1e6) * 0.95))

/**
 * Every top-10 contract that ends in the next year, one row per account, on a
 * single time axis. Marker area is annual value; red is an account with a risk
 * signal. The accounts whose renewals are both close and at risk are the ones
 * at the top.
 */
export default function RenewalLadder({ contracts }: { contracts: RenewalRow[] }) {
  const [ref, width] = useElementWidth<HTMLDivElement>()
  if (contracts.length === 0) return null

  // Group by account: at-risk accounts first, then whoever renews soonest.
  const groups = new Map<string, RenewalRow[]>()
  for (const c of contracts) groups.set(c.customer_id, [...(groups.get(c.customer_id) ?? []), c])
  const accounts = [...groups.values()].sort(
    (a, b) => Number(b[0].at_risk) - Number(a[0].at_risk) || a[0].days_to_end - b[0].days_to_end,
  )

  const compact = width > 0 && width < COMPACT_BELOW
  if (compact) {
    return (
      <div ref={ref}>
        <ul className="divide-y divide-line border-y border-line">
          {accounts.map((rows) => (
            <li key={rows[0].customer_id} className="py-2.5">
              <Link to={rows[0].customer_id} className="font-medium text-ink hover:underline">
                {rows[0].customer_name}
              </Link>
              {rows.map((c) => (
                <div key={c.contract_id} className="flex justify-between text-sm">
                  <span className="text-ink-light">
                    {contractAbbreviation(c.contract_type)} · {money(c.annual_value_usd)} a year
                  </span>
                  <span className={c.days_to_end <= RENEWAL_SOON_DAYS ? 'font-medium text-accent' : 'text-ink-muted'}>
                    {renewsIn(c.days_to_end)}
                  </span>
                </div>
              ))}
            </li>
          ))}
        </ul>
      </div>
    )
  }

  // Today is the first contract's end date less its days to go, so the ladder needs no clock of its own.
  const today = Date.parse(`${contracts[0].end_date}T00:00:00Z`) - contracts[0].days_to_end * DAY
  const plotWidth = Math.max(0, width - LABEL_WIDTH - 28)
  const x = (days: number) => LABEL_WIDTH + (Math.min(days, HORIZON_DAYS) / HORIZON_DAYS) * plotWidth
  const height = AXIS + accounts.length * ROW + 20

  const start = new Date(today)
  const ticks: { days: number; label: string }[] = []
  for (let i = 1; i <= 13; i++) {
    const t = Date.UTC(start.getUTCFullYear(), start.getUTCMonth() + i, 1)
    const days = (t - today) / DAY
    if (days > HORIZON_DAYS) break
    const d = new Date(t)
    const month = d.toLocaleString('en-US', { month: 'short', timeZone: 'UTC' })
    ticks.push({ days, label: d.getUTCMonth() === 0 ? `${month} ’${String(d.getUTCFullYear()).slice(2)}` : month })
  }

  return (
    <div ref={ref} className="w-full">
      {width > 0 && (
        <svg
          width={width}
          height={height}
          role="img"
          aria-label={`Renewal ladder: ${contracts.length} top-10 contracts ending in the next year`}
          className="block"
        >
          <rect x={x(0)} y={AXIS - 6} width={x(RENEWAL_SOON_DAYS) - x(0)} height={height - AXIS + 6} fill={ACCENT_COLOR} opacity={0.06} />
          <text x={x(0) + 6} y={height - 6} fontSize={11} fontWeight={600} fill={ACCENT_COLOR}>
            Next {RENEWAL_SOON_DAYS} days
          </text>
          {ticks.map((t) => (
            <g key={t.label + t.days}>
              <line x1={x(t.days)} x2={x(t.days)} y1={AXIS - 6} y2={height} stroke="#EAECEF" />
              <text x={x(t.days)} y={AXIS - 10} fontSize={11} textAnchor="middle" fill="#666666">
                {t.label}
              </text>
            </g>
          ))}
          <line x1={x(0)} x2={x(0)} y1={AXIS - 6} y2={height} stroke="#151515" strokeWidth={1.5} />
          {accounts.map((rows, i) => {
            const cy = AXIS + i * ROW + ROW / 2
            const a = rows[0]
            return (
              <g key={a.customer_id}>
                {i > 0 && <line x1={0} x2={width} y1={AXIS + i * ROW} y2={AXIS + i * ROW} stroke="#EAECEF" />}
                <Link to={a.customer_id}>
                  <text x={0} y={cy - 2} fontSize={13} fontWeight={600} fill="#151515" className="hover:underline">
                    {a.customer_name}
                  </text>
                  <text x={0} y={cy + 13} fontSize={11} fill={a.at_risk ? ACCENT_COLOR : '#666666'}>
                    {a.at_risk ? 'Risk signal · ' : ''}
                    {contractAbbreviation(a.contract_type)} {formatValue(a.end_date, 'date').replace(/, \d{4}$/, '')}
                  </text>
                </Link>
                {rows.map((c) => {
                  const r = radius(c.annual_value_usd)
                  const cx = x(c.days_to_end)
                  const flip = cx + r + 52 > width
                  return (
                    <g key={c.contract_id}>
                      <title>
                        {c.customer_name}: {c.contract_type}, {money(c.annual_value_usd)} a year, ends {formatValue(c.end_date, 'date')} ({c.status})
                      </title>
                      <circle cx={cx} cy={cy} r={r} fill={c.at_risk ? ACCENT_COLOR : BRAND_COLOR} fillOpacity={0.8} stroke="#fff" strokeWidth={1.5} />
                      <text
                        x={flip ? cx - r - 5 : cx + r + 5}
                        y={cy + 4}
                        fontSize={11}
                        textAnchor={flip ? 'end' : 'start'}
                        fill="#151515"
                        className="tabular-nums"
                      >
                        {money(c.annual_value_usd)}
                      </text>
                    </g>
                  )
                })}
              </g>
            )
          })}
        </svg>
      )}
      <p className="mt-1 text-xs text-ink-muted">Marker size is the contract’s annual value. Red accounts have a risk signal from the last 120 days.</p>
    </div>
  )
}
