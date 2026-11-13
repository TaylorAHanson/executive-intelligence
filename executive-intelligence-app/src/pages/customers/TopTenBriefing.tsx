import { useMemo, useState } from 'react'
import { ChevronDown } from 'lucide-react'
import { WidgetState } from '../../components/dashboard'
import { ASSISTANT_NAME } from '../../brand'
import {
  Chapter,
  Figure,
  FigureSkeleton,
  Recommendation,
  StoryPage,
  Waterfall,
  money,
  pct,
  useBriefing,
  type WaterfallStep,
} from '../../components/story'
import { useDashboardQuery } from '../../hooks/useDashboardQuery'
import { useAgentTray } from '../../providers/agentTray'
import AccountsTable from './AccountsTable'
import AttentionStrip from './AttentionStrip'
import CoverageBar from './CoverageBar'
import PortfolioMap from './PortfolioMap'
import RenewalLadder, { type RenewalRow } from './RenewalLadder'
import { DealList, SignalItem, type AccountRow, type DealRow, type SignalRow } from './shared'
import { renewsIn } from './helpers'
import { useSinceLastVisit, type Snapshot } from './lastVisit'
import WhatChanged from './WhatChanged'
import { PORTFOLIO_QUESTIONS, periodText, provenance } from './text'

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
/** Themes shown before "Show all": the risks come first, so the ones that matter are always in view. */
const THEMES_SHOWN = 6

export default function TopTenBriefing() {
  const tray = useAgentTray()
  const briefing = useBriefing('portfolio')
  const outlook = useDashboardQuery<OutlookRow>('/customers/outlook')
  const accounts = useDashboardQuery<AccountRow>('/customers/accounts')
  const kpis = useDashboardQuery<KpiRow>('/customers/kpis')
  const quarter = outlook.data?.rows[0]?.quarter

  const snapshot = useMemo<Snapshot | null>(() => {
    const o = outlook.data?.rows[0]
    const k = kpis.data?.rows[0]
    const rows = accounts.data?.rows
    if (!o || !k || !rows) return null
    return {
      quarter: o.quarter,
      plan: o.plan_usd,
      commit: o.commit_usd,
      attainment: k.plan_attainment,
      deviceShare: k.device_share,
      atRisk: rows.filter((a) => a.at_risk).map((a) => ({ id: a.customer_id, name: a.customer_name })),
    }
  }, [outlook.data, kpis.data, accounts.data])
  const visit = useSinceLastVisit('portfolio', snapshot)

  const summary = () =>
    briefing.summary(
      'Customer Intelligence: top 10 accounts',
      (accounts.data?.rows ?? [])
        .filter((a) => a.at_risk)
        .map(
          (a) =>
            `Needs attention: ${a.customer_name}, contract ends in ${renewsIn(a.days_to_renewal)}${a.reason ? `. ${a.reason}` : ''}`,
        ),
    )

  return (
    <StoryPage
      eyebrow="Customer Intelligence · Top 10 accounts"
      headline={briefing.headline}
      meta={`${periodText()}${quarter ? ` · Outlook for ${quarter}` : ''}`}
      askLabel={`Ask ${ASSISTANT_NAME} about this briefing`}
      onAsk={() => tray.ask('About the top-10 customer briefing: ')}
      suggestions={PORTFOLIO_QUESTIONS}
      onSuggest={(question) => tray.ask(`About the top-10 customer briefing: ${question}`)}
      summary={summary}
      provenance={provenance(briefing.generatedBy, briefing.generatedAt)}
      lead={
        <>
          <WhatChanged visit={visit} />
          <AttentionStrip quarter={quarter} />
        </>
      }
    >
      <Chapter id="know" title="What our top 10 are focused on" soWhat={briefing.soWhat('know')}>
        <Themes />
      </Chapter>

      <Chapter id="measure" title="How we are doing with them" soWhat={briefing.soWhat('measure')}>
        <Measures />
        <WidgetState query={accounts} skeleton="chart">
          {({ rows }) => <PortfolioMap accounts={rows} />}
        </WidgetState>
        <Accounts quarter={quarter} />
      </Chapter>

      <Chapter id="anticipate" title={`Where ${quarter ?? 'next quarter'} lands`} soWhat={briefing.soWhat('anticipate')}>
        <WidgetState query={outlook} skeleton="chart">
          {({ rows: [row] }) => <Bridge outlook={row} />}
        </WidgetState>
        <CoverageBar />
        <Renewals />
        <DecisiveDeals />
      </Chapter>

      <Chapter id="act" title="What we recommend" soWhat={null}>
        <WidgetState query={briefing.query} skeleton="table" emptyMessage="No recommendations yet.">
          {() => (
            <div className="space-y-4">
              {briefing.actions.map((insight, i) => (
                <Recommendation
                  key={insight.insight_id}
                  insight={insight}
                  number={i + 1}
                  onAsk={() =>
                    tray.ask(`About the top-10 recommendation "${insight.title}": why this one, and what could go wrong if we do it?`)
                  }
                />
              ))}
            </div>
          )}
        </WidgetState>
      </Chapter>
    </StoryPage>
  )
}

/** Each theme, how many of the ten share it, and on request the signals behind it. Risks first. */
function Themes() {
  const themes = useDashboardQuery<ThemeRow>('/customers/themes')
  const signals = useDashboardQuery<SignalRow>('/customers/signals')
  const [showAll, setShowAll] = useState(false)

  return (
    <WidgetState query={themes} skeleton="table" emptyMessage="No market or account signals yet.">
      {({ rows }) => {
        const shown = showAll ? rows : rows.slice(0, THEMES_SHOWN)
        return (
          <div>
            <ul className="border-y border-line">
              {shown.map((theme) => {
                const risk = theme.direction === 'risk'
                const behind = (signals.data?.rows ?? []).filter((s) => s.theme === theme.theme)
                return (
                  <li key={theme.theme} className="border-b border-line last:border-b-0">
                    <details className="group">
                      <summary className="grid cursor-pointer list-none grid-cols-[minmax(0,15rem)_auto_minmax(0,1fr)_auto] items-center gap-5 py-3.5 max-md:grid-cols-[minmax(0,1fr)_auto_auto]">
                        <span className={`font-semibold ${risk ? 'text-accent' : 'text-ink'}`}>{theme.theme}</span>
                        <AccountDots count={theme.accounts} risk={risk} />
                        <span className="truncate text-sm text-ink-muted max-md:hidden">{theme.account_names}</span>
                        <ChevronDown
                          className="h-4 w-4 text-ink-muted transition-transform group-open:rotate-180"
                          aria-label={`Sources for ${theme.theme}`}
                        />
                      </summary>
                      <div className="mb-3 rounded-xl bg-canvas px-4">
                        <p className="pt-3 text-sm text-ink-muted md:hidden">{theme.account_names}</p>
                        <ul className="divide-y divide-line">
                          {behind.map((signal) => (
                            <SignalItem key={signal.signal_id} signal={signal} showCustomer />
                          ))}
                        </ul>
                      </div>
                    </details>
                  </li>
                )
              })}
            </ul>
            {rows.length > THEMES_SHOWN && (
              <button
                type="button"
                className="mt-2 text-sm font-medium text-brand hover:text-brand-dark"
                onClick={() => setShowAll((v) => !v)}
              >
                {showAll ? 'Show fewer themes' : `Show all ${rows.length} themes`}
              </button>
            )}
          </div>
        )
      }}
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

/** The ten accounts, troubled ones first. */
function Accounts({ quarter }: { quarter?: string }) {
  const accounts = useDashboardQuery<AccountRow>('/customers/accounts')
  const monthly = useDashboardQuery<MonthlyRow>('/customers/accounts-monthly')
  return (
    <WidgetState query={accounts} skeleton="table">
      {({ rows }) => <AccountsTable accounts={rows} monthly={monthly.data?.rows ?? []} quarter={quarter} />}
    </WidgetState>
  )
}

/** Plan to commit to best case: where the gap comes from, and what is still open. */
function Bridge({ outlook }: { outlook: OutlookRow }) {
  const riskGap = (outlook.at_risk_commit_usd ?? 0) - (outlook.at_risk_plan_usd ?? 0)
  const restGap = outlook.commit_usd - outlook.plan_usd - riskGap
  const upside = outlook.best_case_usd - outlook.commit_usd
  const flagged = outlook.at_risk_accounts

  const steps: WaterfallStep[] = [{ label: 'Plan', value: outlook.plan_usd, kind: 'total' }]
  if (flagged > 0) {
    steps.push({ label: 'At-risk accounts', detail: `${flagged} account${flagged === 1 ? '' : 's'}`, value: riskGap, kind: 'change' })
  }
  steps.push({ label: flagged > 0 ? 'Other accounts' : 'All accounts', value: restGap, kind: 'change' })
  steps.push({ label: 'Commit', value: outlook.commit_usd, kind: 'total', emphasis: true })
  steps.push({ label: 'Upside', detail: 'if best case closes', value: upside, kind: 'change' })
  steps.push({ label: 'Best case', value: outlook.best_case_usd, kind: 'total' })

  return (
    <div>
      <div className="mb-1 text-sm font-medium text-ink-light">
        From plan to commit to best case, {outlook.quarter}
      </div>
      <Waterfall
        steps={steps}
        summary={`${outlook.quarter}: plan ${money(outlook.plan_usd)}, commit ${money(outlook.commit_usd)}, best case ${money(outlook.best_case_usd)}`}
      />
    </div>
  )
}

function Renewals() {
  const renewals = useDashboardQuery<RenewalRow>('/customers/renewals')
  return (
    <div>
      <div className="mb-2 text-sm font-medium text-ink-light">Contracts that end in the next 12 months</div>
      <WidgetState query={renewals} skeleton="chart" emptyMessage="No top-10 contracts end in the next 12 months.">
        {({ rows }) => <RenewalLadder contracts={rows} />}
      </WidgetState>
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
