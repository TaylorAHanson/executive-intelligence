import { Link } from 'react-router-dom'
import { AlertTriangle, ArrowRight, CheckCircle2 } from 'lucide-react'
import { WidgetState, formatValue } from '../../components/dashboard'
import { money, pct, points } from '../../components/story'
import { useDashboardQuery } from '../../hooks/useDashboardQuery'
import { type AccountRow } from './shared'
import { RENEWAL_SOON_DAYS, contractAbbreviation, renewsIn, signedMoney } from './helpers'

/**
 * What needs a leader's attention before anything else: the at-risk accounts,
 * soonest renewal first, and how much of the business they carry. It reads the
 * same /accounts result as the table, so the two always agree.
 */
export default function AttentionStrip({ quarter }: { quarter?: string }) {
  const accounts = useDashboardQuery<AccountRow>('/customers/accounts')

  return (
    <WidgetState query={accounts} skeleton="table">
      {({ rows }) => {
        const flagged = rows
          .filter((a) => a.at_risk)
          .sort((a, b) => (a.days_to_renewal ?? Number.MAX_SAFE_INTEGER) - (b.days_to_renewal ?? Number.MAX_SAFE_INTEGER))
        const first = rows[0]
        if (flagged.length === 0) {
          return (
            <p className="flex items-center gap-2 rounded-xl bg-emerald-50 px-4 py-3 text-sm text-emerald-900">
              <CheckCircle2 className="h-4 w-4 shrink-0" aria-hidden="true" />
              No top-10 account has a risk signal from the last {RENEWAL_SOON_DAYS} days.
            </p>
          )
        }
        const share = (part: number | null | undefined, whole: number | null | undefined) =>
          part != null && whole ? pct(part / whole) : null
        const revenueShare = share(first?.at_risk_revenue_usd, first?.portfolio_revenue_usd)
        const renewalShare = share(first?.at_risk_renewing_usd, first?.renewing_usd_total)

        return (
          <section aria-labelledby="attention-title" className="rounded-2xl border border-accent/25 bg-accent/[0.03] p-5">
            <div className="flex items-start gap-2.5">
              <AlertTriangle className="mt-1 h-4 w-4 shrink-0 text-accent" aria-hidden="true" />
              <div className="min-w-0">
                <h3 id="attention-title" className="text-sm font-bold uppercase tracking-[0.12em] text-accent">
                  Needs attention first
                </h3>
                <p className="mt-1 text-[1.02rem] leading-relaxed text-ink">
                  <strong>
                    {flagged.length} of {rows.length}
                  </strong>{' '}
                  accounts carry a risk signal
                  {revenueShare && (
                    <>
                      {' '}
                      and <strong>{revenueShare}</strong> of top-10 revenue
                    </>
                  )}
                  {renewalShare && first?.at_risk_renewing_usd != null && (
                    <>
                      . They also hold <strong>{renewalShare}</strong> of the contract value renewing in the next{' '}
                      {RENEWAL_SOON_DAYS} days ({money(first.at_risk_renewing_usd)} of {money(first.renewing_usd_total)} a year)
                    </>
                  )}
                  .
                </p>
              </div>
            </div>

            <ExposureBar rows={rows} />

            <ul className="mt-5 grid gap-3 md:grid-cols-2 lg:grid-cols-3">
              {flagged.map((a) => (
                <li key={a.customer_id}>
                  <AttentionCard account={a} quarter={quarter} />
                </li>
              ))}
            </ul>
          </section>
        )
      }}
    </WidgetState>
  )
}

/** The ten accounts as one bar, each segment as wide as its revenue, the flagged ones in red and first. */
function ExposureBar({ rows }: { rows: AccountRow[] }) {
  const ordered = [...rows].sort((a, b) => Number(b.at_risk) - Number(a.at_risk) || (b.revenue_usd ?? 0) - (a.revenue_usd ?? 0))
  return (
    <div className="mt-4">
      <div
        className="flex h-3.5 w-full gap-0.5 overflow-hidden rounded-full"
        role="img"
        aria-label="Top-10 revenue by account; accounts with a risk signal are shown in red"
      >
        {ordered.map((a) => (
          <div
            key={a.customer_id}
            className={a.at_risk ? 'bg-accent' : 'bg-line'}
            style={{ flexGrow: a.revenue_usd ?? 0, flexBasis: 0 }}
            title={`${a.customer_name}: ${money(a.revenue_usd)} over 12 months${a.at_risk ? ', at risk' : ''}`}
          />
        ))}
      </div>
      <div className="mt-1.5 flex justify-between text-xs text-ink-muted">
        <span className="text-accent">At risk</span>
        <span>Each segment is one account, sized by its last 12 months of revenue</span>
      </div>
    </div>
  )
}

function AttentionCard({ account: a, quarter }: { account: AccountRow; quarter?: string }) {
  const soon = a.days_to_renewal != null && a.days_to_renewal <= RENEWAL_SOON_DAYS
  return (
    <Link
      to={a.customer_id}
      className="group flex h-full flex-col rounded-xl border border-line bg-white p-4 shadow-[0_1px_2px_rgba(21,21,21,.04)] hover:border-accent/50 hover:shadow-tile"
    >
      <div className="flex items-start justify-between gap-2">
        <span className="font-semibold text-ink">{a.customer_name}</span>
        <ArrowRight className="mt-0.5 h-4 w-4 shrink-0 text-ink-muted group-hover:text-ink" aria-hidden="true" />
      </div>
      {a.reason && (
        <p className="mt-1 text-sm leading-snug text-ink-light">
          {a.reason}
          {a.reason_source && (
            <span className="text-ink-muted">
              {' '}
              ({a.reason_source}
              {a.reason_date ? `, ${formatValue(a.reason_date, 'date').replace(/, \d{4}$/, '')}` : ''})
            </span>
          )}
        </p>
      )}
      <dl className="mt-3 grid grid-cols-2 gap-x-3 gap-y-2 border-t border-line pt-3 text-sm">
        <div>
          <dt className="text-xs text-ink-muted">Contract ends in</dt>
          <dd className={`font-semibold tabular-nums ${soon ? 'text-accent' : 'text-ink'}`}>{renewsIn(a.days_to_renewal)}</dd>
          {a.renewal_type && (
            <dd className="text-xs text-ink-muted">
              {contractAbbreviation(a.renewal_type)} · {money(a.renewal_usd)} a year
            </dd>
          )}
        </div>
        <div>
          <dt className="text-xs text-ink-muted">{quarter ?? 'Next quarter'} vs plan</dt>
          <dd className={`font-semibold tabular-nums ${(a.nq_gap_usd ?? 0) > 0 ? 'text-accent' : 'text-ink'}`}>
            {signedMoney(a.nq_gap_usd == null ? null : -a.nq_gap_usd)}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-ink-muted">Revenue vs plan</dt>
          <dd className="tabular-nums text-ink">{pct(a.plan_attainment)}</dd>
        </div>
        <div>
          <dt className="text-xs text-ink-muted">Device share</dt>
          <dd className="tabular-nums text-ink">
            {pct(a.device_share)} <span className="text-xs text-accent">{points(a.device_share_change)}</span>
          </dd>
        </div>
      </dl>
    </Link>
  )
}
