import { Link, useParams } from 'react-router-dom'
import { ArrowLeft } from 'lucide-react'
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { WidgetState, formatValue } from '../../components/dashboard'
import { ASSISTANT_NAME, BRAND_COLOR } from '../../brand'
import { Chapter, Figure, FigureSkeleton, Recommendation, StoryPage, money, pct, useBriefing } from '../../components/story'
import { useDashboardQuery } from '../../hooks/useDashboardQuery'
import { useAgentTray } from '../../providers/agentTray'
import { DealList, SignalItem, type DealRow, type SignalRow } from './shared'
import { periodText, provenance } from './text'

interface ProfileRow {
  customer_id: string
  customer_name: string
  region: string
  segment: string
  revenue_usd: number | null
  revenue_growth: number | null
  plan_attainment: number | null
  device_share: number | null
  device_share_prior: number | null
  nq_plan_usd: number | null
  nq_commit_usd: number | null
  nq_best_case_usd: number | null
  quarter: string
  at_risk: boolean
}

interface RevenueRow {
  month: string
  revenue_usd: number | null
  plan_usd: number | null
  commit_usd: number | null
  best_case_usd: number | null
}

interface FootprintRow {
  quarter: string
  device_models: number
  device_models_with_us: number
  device_share: number | null
}

interface ContractRow {
  contract_id: string
  contract_type: string
  start_date: string
  end_date: string
  annual_value_usd: number
  status: string
  days_to_end: number
}

export default function AccountBriefing() {
  const { customerId = '' } = useParams()
  const tray = useAgentTray()
  const profile = useDashboardQuery<ProfileRow>('/customers/profile', { customer: customerId })
  const briefing = useBriefing(customerId)
  const p = profile.data?.rows[0]
  const name = p?.customer_name ?? 'this account'

  if (profile.isError) {
    return (
      <div className="mx-auto max-w-[1000px] px-8 py-12">
        <BackLink />
        <div className="mt-6">
          <WidgetState query={profile}>{() => null}</WidgetState>
        </div>
      </div>
    )
  }

  return (
    <StoryPage
      eyebrow={
        <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <BackLink />
          <span className="text-line">|</span>
          {p ? `${p.customer_name} · ${p.segment} · ${p.region}` : 'Loading'}
        </span>
      }
      headline={briefing.headline}
      meta={`${periodText()}${p ? ` · Outlook for ${p.quarter}` : ''}`}
      askLabel={`Ask ${ASSISTANT_NAME} about ${name}`}
      onAsk={() => tray.ask(`About ${name} (${customerId}): `)}
      provenance={provenance(briefing.generatedBy, briefing.generatedAt)}
    >
      <Chapter id="know" title={`What ${name} is focused on`} soWhat={briefing.soWhat('know')}>
        <Signals customer={customerId} />
      </Chapter>

      <Chapter id="measure" title={`How we are doing with ${name}`} soWhat={briefing.soWhat('measure')}>
        <div className="grid gap-8 sm:grid-cols-3">
          {!p ? (
            <>
              <FigureSkeleton />
              <FigureSkeleton />
              <FigureSkeleton />
            </>
          ) : (
            <>
              <Figure
                label="Revenue, last 12 months"
                value={money(p.revenue_usd)}
                was={`${(p.revenue_growth ?? 0) >= 0 ? 'up' : 'down'} ${pct(Math.abs(p.revenue_growth ?? 0))} on the year before`}
                tone={(p.revenue_growth ?? 0) >= 0 ? 'up' : 'down'}
              />
              <Figure label="Against plan" value={pct(p.plan_attainment)} tone="flat" />
              <Figure
                label="Its new devices using our products"
                value={pct(p.device_share)}
                was={`was ${pct(p.device_share_prior)} a year ago`}
                tone={(p.device_share ?? 0) >= (p.device_share_prior ?? 0) ? 'up' : 'down'}
              />
            </>
          )}
        </div>
        <RevenueChart customer={customerId} />
        <Footprint customer={customerId} />
      </Chapter>

      <Chapter id="anticipate" title="What is coming" soWhat={briefing.soWhat('anticipate')}>
        <Contracts customer={customerId} />
        <AccountDeals customer={customerId} quarter={p?.quarter} />
      </Chapter>

      <Chapter id="act" title="What we recommend" soWhat={null}>
        <WidgetState query={briefing.query} skeleton="table" emptyMessage="No recommendation for this account yet.">
          {() => (
            <div className="space-y-4">
              {briefing.actions.map((insight, i) => (
                <Recommendation key={insight.insight_id} insight={insight} number={i + 1} />
              ))}
            </div>
          )}
        </WidgetState>
      </Chapter>
    </StoryPage>
  )
}

function BackLink() {
  return (
    <Link to="/customers" className="inline-flex items-center gap-1 hover:text-brand-dark">
      <ArrowLeft className="h-3.5 w-3.5" aria-hidden="true" />
      Top 10
    </Link>
  )
}

function Signals({ customer }: { customer: string }) {
  const signals = useDashboardQuery<SignalRow>('/customers/signals', { customer })
  return (
    <WidgetState query={signals} skeleton="table" emptyMessage="No market or account signals for this account.">
      {({ rows }) => {
        const themes = [...new Set(rows.map((s) => s.theme))]
        return (
          <div className="space-y-5">
            {themes.map((theme) => {
              const items = rows.filter((s) => s.theme === theme)
              const risk = items.some((s) => s.direction === 'risk')
              return (
                <div key={theme}>
                  <div className={`text-sm font-semibold ${risk ? 'text-accent' : 'text-ink'}`}>{theme}</div>
                  <ul className="divide-y divide-line">
                    {items.map((signal) => (
                      <SignalItem key={signal.signal_id} signal={signal} />
                    ))}
                  </ul>
                </div>
              )
            })}
          </div>
        )
      }}
    </WidgetState>
  )
}

/** Actual revenue against plan, with the forecast carrying the line through next quarter. */
function RevenueChart({ customer }: { customer: string }) {
  const revenue = useDashboardQuery<RevenueRow>('/customers/revenue', { customer })
  return (
    <div>
      <div className="mb-1 flex flex-wrap items-baseline justify-between gap-2">
        <span className="text-sm font-medium text-ink-light">Revenue by month</span>
        <span className="flex gap-4 text-xs text-ink-muted">
          <Key color={BRAND_COLOR} label="Actual" />
          <Key color={BRAND_COLOR} label="Commit" dashed />
          <Key color="#9AA1AB" label="Plan" dashed />
        </span>
      </div>
      <WidgetState query={revenue}>
        {({ rows }) => (
          <div className="h-56">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={rows} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
                <CartesianGrid stroke="#EAECEF" vertical={false} />
                <XAxis
                  dataKey="month"
                  tickFormatter={(v) => formatValue(v, 'month').replace(/ \d{2}(\d{2})$/, " '$1")}
                  tick={{ fontSize: 11, fill: '#666666' }}
                  axisLine={false}
                  tickLine={false}
                  interval="preserveStartEnd"
                  minTickGap={24}
                />
                <YAxis
                  tickFormatter={(v) => money(v)}
                  tick={{ fontSize: 11, fill: '#666666' }}
                  axisLine={false}
                  tickLine={false}
                  width={56}
                />
                <Tooltip
                  formatter={(value, key) => [money(value), String(key).replace('_usd', '').replace('_', ' ')]}
                  labelFormatter={(v) => formatValue(v, 'month')}
                />
                <Line dataKey="plan_usd" stroke="#9AA1AB" strokeWidth={1.5} strokeDasharray="4 4" dot={false} isAnimationActive={false} />
                <Line dataKey="revenue_usd" stroke={BRAND_COLOR} strokeWidth={2.25} dot={false} isAnimationActive={false} />
                <Line dataKey="commit_usd" stroke={BRAND_COLOR} strokeWidth={2} strokeDasharray="2 4" dot={false} isAnimationActive={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}
      </WidgetState>
    </div>
  )
}

function Key({ color, label, dashed = false }: { color: string; label: string; dashed?: boolean }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <svg width="18" height="6" aria-hidden="true">
        <line x1="0" y1="3" x2="18" y2="3" stroke={color} strokeWidth="2" strokeDasharray={dashed ? '3 3' : undefined} />
      </svg>
      {label}
    </span>
  )
}

/** Share of its new device models using our products, one bar per quarter. */
function Footprint({ customer }: { customer: string }) {
  const footprint = useDashboardQuery<FootprintRow>('/customers/footprint', { customer })
  return (
    <div>
      <div className="mb-3 text-sm font-medium text-ink-light">
        New device models using our products, by quarter. Red is more than 10 points below a year earlier.
      </div>
      <WidgetState query={footprint} skeleton="table" emptyMessage="No device data for this account.">
        {({ rows }) => (
          <div className="flex items-end gap-2">
            {rows.map((q, i) => {
              const share = q.device_share ?? 0
              const yearAgo = i >= 4 ? rows[i - 4].device_share : null
              const falling = yearAgo !== null && share < yearAgo - 0.1
              return (
                <div key={q.quarter} className="flex flex-1 flex-col items-center gap-1.5">
                  <span className="text-xs tabular-nums text-ink-light">{pct(share)}</span>
                  <div className="flex h-24 w-full items-end rounded-md bg-canvas">
                    <div
                      className={`w-full rounded-md ${falling ? 'bg-accent/80' : 'bg-brand/80'}`}
                      style={{ height: `${Math.max(4, share * 100)}%` }}
                      title={`${q.device_models_with_us} of ${q.device_models} models`}
                    />
                  </div>
                  <span className="text-[0.7rem] text-ink-muted">{quarterLabel(q.quarter)}</span>
                </div>
              )
            })}
          </div>
        )}
      </WidgetState>
    </div>
  )
}

function quarterLabel(iso: string): string {
  const [year, month] = iso.split('-').map(Number)
  return `Q${Math.floor((month - 1) / 3) + 1} '${String(year).slice(2)}`
}

function Contracts({ customer }: { customer: string }) {
  const contracts = useDashboardQuery<ContractRow>('/customers/contracts', { customer })
  return (
    <div>
      <div className="mb-2 text-sm font-medium text-ink-light">Contracts</div>
      <WidgetState query={contracts} skeleton="table" emptyMessage="No live contracts on record.">
        {({ rows }) => (
          <ul className="divide-y divide-line border-y border-line">
            {rows.map((c) => {
              const soon = c.days_to_end <= 120
              return (
                <li key={c.contract_id} className="flex flex-wrap items-baseline gap-x-4 gap-y-1 py-2.5 text-[0.95rem]">
                  <span className="min-w-0 flex-1 font-medium text-ink">{c.contract_type}</span>
                  <span className="w-28 text-right tabular-nums text-ink-light">{money(c.annual_value_usd)} a year</span>
                  <span className={`w-48 text-right text-sm ${soon ? 'font-medium text-accent' : 'text-ink-muted'}`}>
                    ends {formatValue(c.end_date, 'date')}
                    {soon && ` · ${c.days_to_end} days`}
                  </span>
                  <span className="w-44 text-right text-xs text-ink-muted">{c.status}</span>
                </li>
              )
            })}
          </ul>
        )}
      </WidgetState>
    </div>
  )
}

function AccountDeals({ customer, quarter }: { customer: string; quarter?: string }) {
  const deals = useDashboardQuery<DealRow>('/customers/deals', { customer })
  return (
    <div>
      <div className="mb-2 text-sm font-medium text-ink-light">Open deals closing in {quarter ?? 'next quarter'}</div>
      <WidgetState query={deals} skeleton="table" emptyMessage="No open deals close next quarter.">
        {({ rows }) => <DealList deals={rows} />}
      </WidgetState>
    </div>
  )
}
