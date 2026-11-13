import { WidgetState } from '../../components/dashboard'
import { money, pct } from '../../components/story'
import { useDashboardQuery } from '../../hooks/useDashboardQuery'

export interface CoverageRow {
  gap_usd: number | null
  stage_commit_usd: number | null
  stage_proposal_usd: number | null
  stage_qualified_usd: number | null
  stage_lead_usd: number | null
  deals: number
  quarter: string
}

const STAGES = [
  { key: 'stage_commit_usd', label: 'Commit', opacity: 1 },
  { key: 'stage_proposal_usd', label: 'Proposal', opacity: 0.72 },
  { key: 'stage_qualified_usd', label: 'Qualified', opacity: 0.45 },
  { key: 'stage_lead_usd', label: 'Lead', opacity: 0.22 },
] as const

/**
 * Next quarter's shortfall to plan beside the open deals that close in it, by
 * stage, on one scale: can the pipeline plausibly cover the gap? It is an upper
 * bound, because a deal's value is its first-year revenue and only part of that
 * can land in the quarter.
 */
export default function CoverageBar({ customer = '' }: { customer?: string }) {
  const coverage = useDashboardQuery<CoverageRow>('/customers/coverage', { customer })
  return (
    <WidgetState query={coverage} skeleton="kpi">
      {({ rows: [row] }) => <Coverage row={row} />}
    </WidgetState>
  )
}

function Coverage({ row }: { row: CoverageRow }) {
  const gap = row.gap_usd ?? 0
  const stages = STAGES.map((s) => ({ ...s, value: row[s.key] ?? 0 }))
  const open = stages.reduce((sum, s) => sum + s.value, 0)
  const advanced = stages[0].value + stages[1].value
  const scale = Math.max(gap, open, 1)

  if (gap <= 0) {
    return (
      <p className="text-sm text-ink-light">
        {row.quarter} commit is at or above plan, so there is no gap for open deals to cover. {row.deals} open deal
        {row.deals === 1 ? '' : 's'}, {money(open)}, close in the quarter.
      </p>
    )
  }

  return (
    <div>
      <div className="mb-2 text-sm font-medium text-ink-light">Can the open deals cover the gap?</div>
      <div className="space-y-2.5">
        <div className="flex items-center gap-3">
          <span className="w-44 shrink-0 text-sm text-ink-light">{row.quarter} gap to plan</span>
          <div className="flex h-7 min-w-0 flex-1 items-center">
            <div className="flex h-full items-center rounded-md bg-accent px-2 text-sm font-semibold tabular-nums text-white" style={{ width: `${(gap / scale) * 100}%`, minWidth: '3.5rem' }}>
              {money(gap)}
            </div>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <span className="w-44 shrink-0 text-sm text-ink-light">
            Open deals closing in {row.quarter}
            <span className="block text-xs text-ink-muted">
              {row.deals} deal{row.deals === 1 ? '' : 's'}, first-year value
            </span>
          </span>
          <div className="flex h-7 min-w-0 flex-1 items-center">
            <div className="flex h-full gap-px overflow-hidden rounded-md" style={{ width: `${(open / scale) * 100}%` }}>
              {stages
                .filter((s) => s.value > 0)
                .map((s) => (
                  <div
                    key={s.key}
                    className="flex h-full items-center justify-center overflow-hidden bg-brand text-xs font-medium tabular-nums text-white"
                    style={{ flexGrow: s.value, flexBasis: 0, opacity: s.opacity }}
                    title={`${s.label}: ${money(s.value)}`}
                  >
                    {s.value / scale > 0.07 ? money(s.value) : ''}
                  </div>
                ))}
            </div>
            <span className="ml-2 shrink-0 text-sm font-semibold tabular-nums text-ink">{money(open)}</span>
          </div>
        </div>
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 pl-[11.75rem] text-xs text-ink-muted">
        {stages
          .filter((s) => s.value > 0)
          .map((s) => (
            <span key={s.key} className="inline-flex items-center gap-1.5">
              <span className="h-2.5 w-2.5 rounded-sm bg-brand" style={{ opacity: s.opacity }} aria-hidden="true" />
              {s.label} {money(s.value)}
            </span>
          ))}
      </div>
      <p className="mt-3 text-sm leading-relaxed text-ink-light">
        {open >= gap ? (
          <>
            On paper the open deals are worth <strong className="text-ink">{(open / gap).toFixed(1)}×</strong> the gap, but only{' '}
            <strong className="text-ink">{money(advanced)}</strong> is at Proposal or Commit.
          </>
        ) : (
          <>
            Even if every open deal closed, they would cover only <strong className="text-ink">{pct(open / gap)}</strong> of the gap, and
            only <strong className="text-ink">{money(advanced)}</strong> is at Proposal or Commit.
          </>
        )}{' '}
        Deal values are first-year revenue, so this overstates what can land in {row.quarter}.
      </p>
    </div>
  )
}
