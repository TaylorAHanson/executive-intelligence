/** Rows of the account page's widgets, as the backend returns them. */

export interface ProfileRow {
  customer_id: string
  customer_name: string
  region: string
  segment: string
  revenue_usd: number | null
  revenue_growth: number | null
  plan_attainment: number | null
  plan_attainment_prior: number | null
  device_share: number | null
  device_share_prior: number | null
  nq_plan_usd: number | null
  nq_commit_usd: number | null
  nq_best_case_usd: number | null
  nq_gap_usd: number | null
  quarter: string
  at_risk: boolean
}

export interface RevenueRow {
  month: string
  revenue_usd: number | null
  plan_usd: number | null
  commit_usd: number | null
  best_case_usd: number | null
}

export interface FootprintRow {
  quarter: string
  device_models: number
  device_models_with_us: number
  device_share: number | null
}

export interface ContractRow {
  contract_id: string
  contract_type: string
  start_date: string
  end_date: string
  annual_value_usd: number
  status: string
  days_to_end: number
}
