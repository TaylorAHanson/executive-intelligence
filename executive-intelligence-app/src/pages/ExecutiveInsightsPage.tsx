/**
 * Executive Insights: the reference dashboard. Every layer of the framework
 * in one small page; copy it to start a new one (see src/AGENTS.md).
 *
 * Widgets read /api/dashboards/executive/* (server/routes/dashboards/executive.py),
 * which query the contract views as the signed-in user.
 */
import {
  ChartCard,
  DashboardPage,
  DataTable,
  KpiCard,
  monthsAgo,
  type Column,
  type FilterDef,
} from '../components/dashboard'
import { useDashboardQuery } from '../hooks/useDashboardQuery'
import { useFilters } from '../hooks/useFilters'

interface KpiRow {
  revenue_usd: number | null
  revenue_usd_prior: number | null
  otif: number | null
  otif_prior: number | null
  win_rate: number | null
  win_rate_prior: number | null
}

interface MonthlyRow {
  month: string
  revenue_usd: number | null
  otif: number | null
  win_rate: number | null
}

interface CustomerRow {
  customer_id: string
  customer_name: string
  region: string
  segment: string
  tier: string
  revenue_usd: number
  revenue_growth: number | null
  otif: number | null
  open_opportunities: number
  health: 'At risk' | 'Watch' | 'Healthy'
}

// The last 12 complete months, matching the backend's default.
const DEFAULT_FILTERS = { from: monthsAgo(12), to: monthsAgo(1), regions: '' }

const HEALTH_STYLE: Record<CustomerRow['health'], string> = {
  'At risk': 'bg-accent/10 text-accent',
  Watch: 'bg-amber-100 text-amber-800',
  Healthy: 'bg-emerald-50 text-emerald-700',
}

const CUSTOMER_COLUMNS: Column<CustomerRow>[] = [
  { key: 'customer_name', label: 'Customer' },
  { key: 'tier', label: 'Tier' },
  { key: 'region', label: 'Region' },
  { key: 'segment', label: 'Segment' },
  { key: 'revenue_usd', label: 'Revenue', format: 'currencyCompact' },
  { key: 'revenue_growth', label: 'Growth', format: 'percent' },
  { key: 'otif', label: 'OTIF', format: 'percent' },
  { key: 'open_opportunities', label: 'Open design wins', format: 'number' },
  {
    key: 'health',
    label: 'Health',
    render: (row) => (
      <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${HEALTH_STYLE[row.health]}`}>{row.health}</span>
    ),
  },
]

export default function ExecutiveInsightsPage() {
  const filters = useFilters(DEFAULT_FILTERS)
  const regionOptions = useDashboardQuery<{ region: string }>('/executive/regions')

  const filterDefs: FilterDef[] = [
    { type: 'daterange', fromKey: 'from', toKey: 'to', label: 'Period' },
    {
      type: 'multiselect',
      key: 'regions',
      label: 'Region',
      options: (regionOptions.data?.rows ?? []).map(({ region }) => ({ value: region, label: region })),
    },
  ]

  const params = filters.values
  const kpis = useDashboardQuery<KpiRow>('/executive/kpis', params)
  const monthly = useDashboardQuery<MonthlyRow>('/executive/monthly', params)
  const byRegion = useDashboardQuery('/executive/revenue-by-region', params)
  const customers = useDashboardQuery<CustomerRow>('/executive/top-customers', params)

  return (
    <DashboardPage sectionId="executive" filterDefs={filterDefs} filters={filters}>
      <KpiCard
        title="Revenue"
        query={kpis}
        value={(r) => r.revenue_usd}
        previous={(r) => r.revenue_usd_prior}
        format="currencyCompact"
        trend={{ query: monthly, value: (r) => r.revenue_usd }}
        askAbout="What is driving revenue against the prior period?"
      />
      <KpiCard
        title="On time in full (OTIF)"
        query={kpis}
        value={(r) => r.otif}
        previous={(r) => r.otif_prior}
        format="percent"
        trend={{ query: monthly, value: (r) => r.otif }}
        askAbout="Which customers and regions are pulling OTIF down?"
      />
      <KpiCard
        title="Design-win conversion"
        query={kpis}
        value={(r) => r.win_rate}
        previous={(r) => r.win_rate_prior}
        format="percent"
        trend={{ query: monthly, value: (r) => r.win_rate }}
        askAbout="Why did design-win conversion change against the prior period?"
      />

      <ChartCard
        title="Revenue by region"
        subtitle="Recognized revenue per month"
        query={byRegion}
        kind="stacked-bar"
        x="month"
        xFormat="month"
        yFormat="currency"
        pivot={{ seriesKey: 'region', valueKey: 'revenue_usd' }}
        span={8}
        askAbout="Which region is growing fastest, and which is slowing?"
      />
      <ChartCard
        title="OTIF by month"
        subtitle="Share of shipments on time and in full"
        query={monthly}
        kind="line"
        x="month"
        xFormat="month"
        yFormat="percent"
        series={[{ key: 'otif', label: 'OTIF' }]}
        span={4}
        askAbout="When did OTIF start to move, and for whom?"
      />

      <DataTable
        title="Top customers"
        subtitle="The period's 25 largest by revenue. Health flags OTIF below 85% or revenue down 10%."
        query={customers}
        columns={CUSTOMER_COLUMNS}
        rowKey={(row) => row.customer_id}
        initialSort={{ key: 'revenue_usd', direction: 'desc' }}
        askAbout="Which of the top customers are at risk, and why?"
      />
    </DashboardPage>
  )
}
