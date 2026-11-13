import { Figure, FigureSkeleton, money, pct } from '../../components/story'
import { formatValue } from '../../components/dashboard'
import { RENEWAL_SOON_DAYS, contractAbbreviation, renewsIn, signedMoney } from './helpers'
import type { ContractRow, ProfileRow } from './types'
import type { CoverageRow } from './CoverageBar'

/**
 * The four numbers that decide whether this account needs a leader this
 * month, above the narrative: when a contract ends, how it is tracking, how
 * much of its new device business we hold, and what the quarter looks like.
 */
export default function Vitals({
  profile,
  contracts,
  coverage,
}: {
  profile: ProfileRow | undefined
  contracts: ContractRow[] | undefined
  coverage: CoverageRow | undefined
}) {
  if (!profile) {
    return (
      <div className="grid grid-cols-2 gap-6 lg:grid-cols-4">
        <FigureSkeleton />
        <FigureSkeleton />
        <FigureSkeleton />
        <FigureSkeleton />
      </div>
    )
  }

  const next = contracts?.[0]
  const soon = next != null && next.days_to_end <= RENEWAL_SOON_DAYS
  const attainmentTone =
    profile.plan_attainment_prior == null || profile.plan_attainment == null
      ? 'flat'
      : profile.plan_attainment >= profile.plan_attainment_prior
        ? 'up'
        : 'down'
  const gap = profile.nq_gap_usd
  const open = coverage
    ? (coverage.stage_commit_usd ?? 0) + (coverage.stage_proposal_usd ?? 0) + (coverage.stage_qualified_usd ?? 0) + (coverage.stage_lead_usd ?? 0)
    : null

  return (
    <div className="grid grid-cols-2 gap-x-6 gap-y-6 border-y border-line py-6 lg:grid-cols-4">
      {next ? (
        <Figure
          size="md"
          label="Next contract ends in"
          value={renewsIn(next.days_to_end)}
          was={`${contractAbbreviation(next.contract_type)}, ${money(next.annual_value_usd)} a year, ${formatValue(next.end_date, 'date').replace(/, \d{4}$/, '')}`}
          tone={soon ? 'alert' : 'flat'}
        />
      ) : (
        <Figure size="md" label="Next contract ends in" value="–" was="No live contracts on record" />
      )}
      <Figure
        size="md"
        label="Revenue against plan"
        value={pct(profile.plan_attainment)}
        was={profile.plan_attainment_prior == null ? undefined : `was ${pct(profile.plan_attainment_prior)} the year before`}
        tone={attainmentTone}
      />
      <Figure
        size="md"
        label="Its new devices using our products"
        value={pct(profile.device_share)}
        was={`was ${pct(profile.device_share_prior)} a year ago`}
        tone={(profile.device_share ?? 0) >= (profile.device_share_prior ?? 0) ? 'up' : 'down'}
      />
      <Figure
        size="md"
        label={`${profile.quarter} commit against plan`}
        value={signedMoney(gap == null ? null : -gap)}
        was={open == null ? undefined : `${money(open)} of open deals close in it`}
        tone="flat"
      />
    </div>
  )
}
