import { Link } from 'react-router-dom'
import { ChevronDown, ChevronRight } from 'lucide-react'
import { WidgetState } from '../../components/dashboard'
import { ACCENT_COLOR, ASSISTANT_NAME, BRAND_COLOR } from '../../brand'
import {
  Chapter,
  Figure,
  FigureSkeleton,
  Recommendation,
  Sparkline,
  StoryPage,
  money,
  pct,
  points,
  useBriefing,
} from '../../components/story'
import { useDashboardQuery } from '../../hooks/useDashboardQuery'
import { useAgentTray } from '../../providers/agentTray'
import { DealList, SignalItem, type DealRow, type SignalRow } from './shared'
import { periodText, provenance } from './text'

interface ThemeRow {
  theme: string
  direction: 'opportunity' | 'risk'
  accounts: number
  account_names: string
  signals: number
  latest: string
}

interface KpiRow {
  plan_attainment: number | null
  plan_attainment_prior: number | null
  device_share: number | null
  device_share_prior: number | null
  conversion: number | null
  conversion_prior: number | null
}

interface AccountRow {
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
}

interface MonthlyRow {
  customer_id: string
  month: string
  revenue_usd: number
}

interface OutlookRow {
  plan_usd: number
  commit_usd: number
  best_case_usd: number
  at_risk_plan_usd: number | null
  at_risk_commit_usd: number | null
  at_risk_accounts: number
  quarter: string
}

const TOP_N = 10

export default function TopTenBriefing() {
  const tray = useAgentTray()
  const briefing = useBriefing('portfolio')
  const outlook = useDashboardQuery<OutlookRow>('/customers/outlook')
  const quarter = outlook.data?.rows[0]?.quarter

  return (
    <StoryPage
      eyebrow="Customer Intelligence · Top 10 accounts"
      headline={briefing.headline}
      meta={`${periodText()}${quarter ? ` · Outlook for ${quarter}` : ''}`}
      askLabel={`Ask ${ASSISTANT_NAME} about this briefing`}
      onAsk={() => tray.ask('About the top-10 customer briefing: ')}
      provenance={provenance(briefing.generatedBy, briefing.generatedAt)}
    >
      <Chapter id="know" title="What our top 10 are focused on" soWhat={briefing.soWhat('know')}>
        <Themes />
      </Chapter>

      <Chapter id="measure" title="How we are doing with them" soWhat={briefing.soWhat('measure')}>
        <Measures />
        <Accounts />
      </Chapter>

      <Chapter id="anticipate" title={`Where ${quarter ?? 'next quarter'} lands`} soWhat={briefing.soWhat('anticipate')}>
        <WidgetState query={outlook} skeleton="kpi">
          {({ rows: [row] }) => <Bridge outlook={row} />}
        </WidgetState>
        <DecisiveDeals />
      </Chapter>

      <Chapter id="act" title="What we recommend" soWhat={null}>
        <WidgetState query={briefing.query} skeleton="table" emptyMessage="No recommendations yet.">
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

/** Each theme, how many of the ten share it, and on request the signals behind it. */
function Themes() {
  const themes = useDashboardQuery<ThemeRow>('/customers/themes')
  const signals = useDashboardQuery<SignalRow>('/customers/signals')

  return (
    <WidgetState query={themes} skeleton="table" emptyMessage="No market or account signals yet.">
      {({ rows }) => (
        <ul className="border-y border-line">
          {rows.map((theme) => {
            const risk = theme.direction === 'risk'
            const behind = (signals.data?.rows ?? []).filter((s) => s.theme === theme.theme)
            return (
              <li key={theme.theme} className="border-b border-line last:border-b-0">
                <details className="group">
                  <summary className="grid cursor-pointer list-none grid-cols-[minmax(0,15rem)_auto_minmax(0,1fr)_auto] items-center gap-5 py-3.5">
                    <span className={`font-semibold ${risk ? 'text-accent' : 'text-ink'}`}>{theme.theme}</span>
                    <AccountDots count={theme.accounts} risk={risk} />
                    <span className="truncate text-sm text-ink-muted">{theme.account_names}</span>
                    <ChevronDown
                      className="h-4 w-4 text-ink-muted transition-transform group-open:rotate-180"
                      aria-label={`Sources for ${theme.theme}`}
                    />
                  </summary>
                  <ul className="mb-3 divide-y divide-line rounded-xl bg-canvas px-4">
                    {behind.map((signal) => (
                      <SignalItem key={signal.signal_id} signal={signal} showCustomer />
                    ))}
                  </ul>
                </details>
              </li>
            )
          })}
        </ul>
      )}
    </WidgetState>
  )
}

/** Ten dots, one per top-10 account, filled for those sharing a theme. */
function AccountDots({ count, risk }: { count: number; risk: boolean }) {
  return (
    <span className="flex gap-1" role="img" aria-label={`${count} of ${TOP_N} accounts`}>
      {Array.from({ length: TOP_N }, (_, i) => (
        <span
          key={i}
          className={`h-2 w-2 rounded-full ${i < count ? (risk ? 'bg-accent' : 'bg-brand') : 'bg-canvas-dark'}`}
        />
      ))}
    </span>
  )
}

function Measures() {
  const kpis = useDashboardQuery<KpiRow>('/customers/kpis')
  const row = kpis.data?.rows[0]
  const tone = (now: number | null | undefined, then: number | null | undefined) =>
    now == null || then == null || Math.abs(now - then) < 0.005 ? 'flat' : now > then ? 'up' : 'down'

  if (kpis.isError) return <WidgetState query={kpis}>{() => null}</WidgetState>
  return (
    <div className="grid gap-8 sm:grid-cols-3">
      {!row ? (
        <>
          <FigureSkeleton />
          <FigureSkeleton />
          <FigureSkeleton />
        </>
      ) : (
        <>
          <Figure
            label="Revenue against plan"
            value={pct(row.plan_attainment)}
            was={`was ${pct(row.plan_attainment_prior)} the year before`}
            tone={tone(row.plan_attainment, row.plan_attainment_prior)}
          />
          <Figure
            label="Their new devices using our products"
            value={pct(row.device_share)}
            was={`was ${pct(row.device_share_prior)} a year ago`}
            tone={tone(row.device_share, row.device_share_prior)}
          />
          <Figure
            label="Opportunities won, of those closed"
            value={pct(row.conversion)}
            was={`was ${pct(row.conversion_prior)} the year before`}
            tone={tone(row.conversion, row.conversion_prior)}
          />
        </>
      )}
    </div>
  )
}

/** The ten accounts, each one line: trend, plan, share, and what they are focused on. */
function Accounts() {
  const accounts = useDashboardQuery<AccountRow>('/customers/accounts')
  const monthly = useDashboardQuery<MonthlyRow>('/customers/accounts-monthly')
  const series = (id: string) => (monthly.data?.rows ?? []).filter((r) => r.customer_id === id).map((r) => r.revenue_usd)

  return (
    <WidgetState query={accounts} skeleton="table">
      {({ rows }) => (
        <div>
          <div className="grid grid-cols-[minmax(0,1fr)_7.5rem_5rem_4.5rem_8.5rem_minmax(0,11rem)_1rem] gap-4 border-b border-line pb-2 text-xs font-medium text-ink-muted">
            <span>Account</span>
            <span>Last 12 months</span>
            <span className="text-right">Revenue</span>
            <span className="text-right">Of plan</span>
            <span>Device share</span>
            <span>Focus</span>
            <span />
          </div>
          <ul className="divide-y divide-line">
            {rows.map((a) => {
              const status = a.at_risk ? 'bg-accent' : (a.plan_attainment ?? 1) >= 1 ? 'bg-emerald-600' : 'bg-amber-500'
              return (
                <li key={a.customer_id}>
                  <Link
                    to={a.customer_id}
                    className="group grid grid-cols-[minmax(0,1fr)_7.5rem_5rem_4.5rem_8.5rem_minmax(0,11rem)_1rem] items-center gap-4 py-3 hover:bg-canvas"
                  >
                    <span className="flex min-w-0 items-center gap-2.5">
                      <span className={`h-2 w-2 shrink-0 rounded-full ${status}`} aria-hidden="true" />
                      <span className="min-w-0">
                        <span className="block truncate font-medium text-ink">{a.customer_name}</span>
                        <span className="block truncate text-xs text-ink-muted">
                          {a.segment} · {a.region}
                        </span>
                      </span>
                    </span>
                    <Sparkline values={series(a.customer_id)} color={a.at_risk ? ACCENT_COLOR : BRAND_COLOR} />
                    <span className="text-right tabular-nums text-ink">{money(a.revenue_usd)}</span>
                    <span
                      className={`text-right tabular-nums ${(a.plan_attainment ?? 1) < 0.95 ? 'text-accent' : 'text-ink'}`}
                    >
                      {pct(a.plan_attainment)}
                    </span>
                    <span className="text-sm tabular-nums text-ink-light">
                      {pct(a.device_share)}{' '}
                      <span className={(a.device_share_change ?? 0) <= -0.1 ? 'text-accent' : 'text-ink-muted'}>
                        {points(a.device_share_change)}
                      </span>
                    </span>
                    <span className={`truncate text-sm ${a.at_risk ? 'font-medium text-accent' : 'text-ink-light'}`}>
                      {a.focus ?? '–'}
                    </span>
                    <ChevronRight className="h-4 w-4 text-line group-hover:text-ink-muted" aria-hidden="true" />
                  </Link>
                </li>
              )
            })}
          </ul>
        </div>
      )}
    </WidgetState>
  )
}

/** Plan to commit to best case, as a sentence of numbers: where the gap comes from. */
function Bridge({ outlook }: { outlook: OutlookRow }) {
  const riskGap = (outlook.at_risk_commit_usd ?? 0) - (outlook.at_risk_plan_usd ?? 0)
  const restGap = outlook.commit_usd - outlook.plan_usd - riskGap
  const upside = outlook.best_case_usd - outlook.commit_usd
  const signed = (n: number) => `${n >= 0 ? '+' : '−'}${money(Math.abs(n))}`

  return (
    <div className="flex flex-wrap items-end gap-x-6 gap-y-5">
      <Total label="Plan" value={outlook.plan_usd} />
      {outlook.at_risk_accounts > 0 && (
        <Step
          value={signed(riskGap)}
          label={`${outlook.at_risk_accounts} second-sourcing account${outlook.at_risk_accounts === 1 ? '' : 's'}`}
          bad={riskGap < 0}
        />
      )}
      <Step value={signed(restGap)} label={outlook.at_risk_accounts > 0 ? 'the other accounts' : 'all accounts'} bad={restGap < 0} />
      <Total label="Commit" value={outlook.commit_usd} emphasis />
      <Step value={signed(upside)} label="if best case closes" bad={upside < 0} />
      <Total label="Best case" value={outlook.best_case_usd} />
    </div>
  )
}

function Total({ label, value, emphasis = false }: { label: string; value: number; emphasis?: boolean }) {
  return (
    <div>
      <div className="text-sm text-ink-light">{label}</div>
      <div className={`mt-1 font-semibold tabular-nums tracking-[-0.02em] ${emphasis ? 'text-[2.4rem] leading-none text-ink' : 'text-[1.6rem] leading-none text-ink-light'}`}>
        {money(value)}
      </div>
    </div>
  )
}

function Step({ value, label, bad }: { value: string; label: string; bad: boolean }) {
  return (
    <div className="pb-0.5">
      <div className={`text-[1.05rem] font-semibold tabular-nums ${bad ? 'text-accent' : 'text-emerald-700'}`}>{value}</div>
      <div className="text-xs text-ink-muted">{label}</div>
    </div>
  )
}

function DecisiveDeals() {
  const deals = useDashboardQuery<DealRow>('/customers/deals')
  return (
    <div>
      <div className="mb-2 text-sm font-medium text-ink-light">The largest open deals that close in the quarter</div>
      <WidgetState query={deals} skeleton="table" emptyMessage="No open deals close next quarter.">
        {({ rows }) => <DealList deals={rows} showCustomer />}
      </WidgetState>
    </div>
  )
}
