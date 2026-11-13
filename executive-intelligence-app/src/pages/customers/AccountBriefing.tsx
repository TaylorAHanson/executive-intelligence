import { useMemo } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ArrowLeft } from 'lucide-react'
import { WidgetState, formatValue } from '../../components/dashboard'
import { ASSISTANT_NAME } from '../../brand'
import { Chapter, Recommendation, StoryPage, money, pct, useBriefing } from '../../components/story'
import { useDashboardQuery } from '../../hooks/useDashboardQuery'
import { useAgentTray } from '../../providers/agentTray'
import CoverageBar, { type CoverageRow } from './CoverageBar'
import RevenueChart from './RevenueChart'
import { DealList, SignalItem, type DealRow, type SignalRow } from './shared'
import { RENEWAL_SOON_DAYS, renewsIn } from './helpers'
import { useSinceLastVisit, type Snapshot } from './lastVisit'
import type { ContractRow, FootprintRow, ProfileRow } from './types'
import Vitals from './Vitals'
import WhatChanged from './WhatChanged'
import { accountQuestions, periodText, provenance } from './text'

export default function AccountBriefing() {
  const { customerId = '' } = useParams()
  const tray = useAgentTray()
  const profile = useDashboardQuery<ProfileRow>('/customers/profile', { customer: customerId })
  const contracts = useDashboardQuery<ContractRow>('/customers/contracts', { customer: customerId })
  const coverage = useDashboardQuery<CoverageRow>('/customers/coverage', { customer: customerId })
  const briefing = useBriefing(customerId)
  const p = profile.data?.rows[0]
  const name = p?.customer_name ?? 'this account'
  const about = `About ${name} (${customerId}): `

  const snapshot = useMemo<Snapshot | null>(
    () =>
      p
        ? {
            quarter: p.quarter,
            plan: p.nq_plan_usd,
            commit: p.nq_commit_usd,
            attainment: p.plan_attainment,
            deviceShare: p.device_share,
            atRisk: p.at_risk ? [{ id: p.customer_id, name: p.customer_name }] : [],
          }
        : null,
    [p],
  )
  const visit = useSinceLastVisit(customerId, snapshot)

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

  const next = contracts.data?.rows[0]
  const summary = () =>
    briefing.summary(
      `Customer Intelligence: ${name}`,
      next ? [`Next contract: ${next.contract_type}, ends in ${renewsIn(next.days_to_end)} (${formatValue(next.end_date, 'date')}).`] : [],
    )

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
      onAsk={() => tray.ask(about)}
      suggestions={accountQuestions(name)}
      onSuggest={(question) => tray.ask(`${about}${question}`)}
      summary={summary}
      provenance={provenance(briefing.generatedBy, briefing.generatedAt)}
      lead={
        <>
          <WhatChanged visit={visit} />
          <Vitals profile={p} contracts={contracts.data?.rows} coverage={coverage.data?.rows[0]} />
        </>
      }
    >
      <Chapter id="know" title={`What ${name} is focused on`} soWhat={briefing.soWhat('know')}>
        <Signals customer={customerId} />
      </Chapter>

      <Chapter id="measure" title={`How we are doing with ${name}`} soWhat={briefing.soWhat('measure')}>
        <RevenueChart customer={customerId} />
        <Footprint customer={customerId} />
      </Chapter>

      <Chapter id="anticipate" title="What is coming" soWhat={briefing.soWhat('anticipate')}>
        <CoverageBar customer={customerId} />
        <Contracts customer={customerId} />
        <AccountDeals customer={customerId} quarter={p?.quarter} />
      </Chapter>

      <Chapter id="act" title="What we recommend" soWhat={null}>
        <WidgetState query={briefing.query} skeleton="table" emptyMessage="No recommendation for this account yet.">
          {() => (
            <div className="space-y-4">
              {briefing.actions.map((insight, i) => (
                <Recommendation
                  key={insight.insight_id}
                  insight={insight}
                  number={i + 1}
                  onAsk={() => tray.ask(`${about}about the recommendation "${insight.title}": why this one, and what could go wrong if we do it?`)}
                />
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

/** Signals by theme, risks first. Each theme leads with its newest; the rest are one click away. */
function Signals({ customer }: { customer: string }) {
  const signals = useDashboardQuery<SignalRow>('/customers/signals', { customer })
  return (
    <WidgetState query={signals} skeleton="table" emptyMessage="No market or account signals for this account.">
      {({ rows }) => {
        const themes = [...new Set(rows.map((s) => s.theme))].sort(
          (a, b) =>
            Number(rows.some((s) => s.theme === b && s.direction === 'risk')) -
            Number(rows.some((s) => s.theme === a && s.direction === 'risk')),
        )
        return (
          <div className="space-y-5">
            {themes.map((theme) => {
              const [latest, ...earlier] = rows.filter((s) => s.theme === theme)
              const risk = [latest, ...earlier].some((s) => s.direction === 'risk')
              return (
                <div key={theme}>
                  <div className={`text-sm font-semibold ${risk ? 'text-accent' : 'text-ink'}`}>{theme}</div>
                  <ul className="divide-y divide-line">
                    <SignalItem signal={latest} />
                  </ul>
                  {earlier.length > 0 && (
                    <details className="group">
                      <summary className="cursor-pointer list-none text-xs font-medium text-brand hover:text-brand-dark">
                        <span className="group-open:hidden">Show {earlier.length} earlier</span>
                        <span className="hidden group-open:inline">Hide earlier</span>
                      </summary>
                      <ul className="divide-y divide-line">
                        {earlier.map((signal) => (
                          <SignalItem key={signal.signal_id} signal={signal} />
                        ))}
                      </ul>
                    </details>
                  )}
                </div>
              )
            })}
          </div>
        )
      }}
    </WidgetState>
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
                  <span className={`text-xs tabular-nums ${falling ? 'font-semibold text-accent' : 'text-ink-light'}`}>{pct(share)}</span>
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
              const soon = c.days_to_end <= RENEWAL_SOON_DAYS
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
