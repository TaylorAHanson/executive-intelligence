import { Link } from 'react-router-dom'
import { formatValue } from '../../components/dashboard'
import { money } from '../../components/story'

/** One v_customer_signals row, as /customers/signals returns it. */
export interface SignalRow {
  signal_id: string
  customer_id: string
  customer_name: string
  theme: string
  direction: 'opportunity' | 'risk'
  headline: string
  summary: string
  source_type: string
  source_name: string
  source_url: string | null
  published_date: string
}

export interface DealRow {
  opportunity_id: string
  customer_id: string
  customer_name: string
  product_line: string
  stage: string
  forecast_category: string
  amount_usd: number
  close_date: string
}

/** One top-10 account, as /customers/accounts returns it. The `*_total` and `portfolio_*` columns repeat on every row. */
export interface AccountRow {
  customer_id: string
  customer_name: string
  region: string
  segment: string
  revenue_usd: number | null
  revenue_growth: number | null
  plan_attainment: number | null
  device_share: number | null
  device_share_change: number | null
  focus: string | null
  at_risk: boolean
  reason: string | null
  reason_source: string | null
  reason_date: string | null
  next_renewal: string | null
  days_to_renewal: number | null
  renewal_type: string | null
  renewal_usd: number | null
  /** Next quarter's plan less commit: positive means commit falls short. */
  nq_gap_usd: number | null
  portfolio_revenue_usd: number | null
  at_risk_revenue_usd: number | null
  renewing_usd_total: number | null
  at_risk_renewing_usd: number | null
}

/** A signal and where it came from. */
export function SignalItem({ signal, showCustomer = false }: { signal: SignalRow; showCustomer?: boolean }) {
  const risk = signal.direction === 'risk'
  return (
    <li className="py-3">
      <div className="flex items-start gap-3">
        <span className={`mt-2 h-1.5 w-1.5 shrink-0 rounded-full ${risk ? 'bg-accent' : 'bg-brand'}`} aria-hidden="true" />
        <div className="min-w-0">
          <div className="font-medium text-ink">{signal.headline}</div>
          <p className="mt-0.5 text-[0.92rem] leading-relaxed text-ink-light">{signal.summary}</p>
          <div className="mt-1 text-xs text-ink-muted">
            {showCustomer && `${signal.customer_name} · `}
            {signal.source_url ? (
              <a href={signal.source_url} target="_blank" rel="noopener noreferrer" className="underline hover:text-ink">
                {signal.source_name}
              </a>
            ) : (
              signal.source_name
            )}
            {' · '}
            {formatValue(signal.published_date, 'date')}
          </div>
        </div>
      </div>
    </li>
  )
}

/** Open deals, largest first. With `showCustomer`, each row names its account and links to it. */
export function DealList({ deals, showCustomer = false }: { deals: DealRow[]; showCustomer?: boolean }) {
  return (
    <ul className="divide-y divide-line border-y border-line">
      {deals.map((deal) => (
        <li key={deal.opportunity_id} className="flex flex-wrap items-baseline gap-x-4 gap-y-1 py-2.5 text-[0.95rem]">
          <span className="min-w-0 flex-1 text-ink">
            {showCustomer && (
              <Link to={`/customers/${deal.customer_id}`} className="font-medium hover:underline">
                {deal.customer_name}{' '}
              </Link>
            )}
            <span className={showCustomer ? 'text-ink-light' : 'font-medium'}>{deal.product_line}</span>
            <span className="ml-2 text-xs tabular-nums text-ink-muted" title="Opportunity id in the CRM">
              {deal.opportunity_id}
            </span>
          </span>
          <span className="w-24 text-sm text-ink-muted">{deal.stage}</span>
          <span className="w-20 text-right font-medium tabular-nums text-ink">{money(deal.amount_usd)}</span>
          <span className="w-28 text-right text-sm text-ink-muted">closes {formatValue(deal.close_date, 'date').replace(/, \d{4}$/, '')}</span>
        </li>
      ))}
    </ul>
  )
}
