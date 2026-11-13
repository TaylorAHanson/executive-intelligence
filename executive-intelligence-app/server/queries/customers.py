"""Customer Intelligence widgets: the top-10 briefing and one account's briefing.

Same rules as queries/executive.py: contract views only, through `data_object`;
every value a `:name` parameter; aggregate in SQL.

The briefing has no filters. Its windows are fixed and stated on the page:

- the last 12 complete months (`:start`, `:end`) against the 12 before
  (`:prior_start`), as on Executive Insights;
- "next quarter", the calendar quarter after the current one (`:nq_start`,
  `:nq_end`);
- an account is "at risk" when it has a `risk` signal published on or after
  `:risk_since` (120 days back). data/insights.py uses the same rule, so the
  numbers here and the sentences it writes agree;
- a contract "renews soon" when it ends before `:renewal_until` (120 days
  ahead), and the renewal ladder looks a year ahead, to `:ladder_end`.

"Top 10" means `tier = 'Top 10'` in v_customers.
"""
import datetime
from dataclasses import dataclass

from services.dashboards import DEFAULT_PERIOD_MONTHS, Period, _add_months, data_object

RISK_SIGNAL_DAYS = 120
RENEWAL_SOON_DAYS = 120
LADDER_DAYS = 365
CHAPTERS = ("headline", "know", "measure", "anticipate", "act")
TOP_DEALS = 5


@dataclass(frozen=True)
class Windows:
    period: Period
    nq_start: datetime.date
    nq_end: datetime.date
    risk_since: datetime.date
    renewal_until: datetime.date
    ladder_end: datetime.date

    def params(self) -> dict:
        return {
            **self.period.params(),
            "nq_start": self.nq_start,
            "nq_end": self.nq_end,
            "risk_since": self.risk_since,
            "renewal_until": self.renewal_until,
            "ladder_end": self.ladder_end,
        }

    @property
    def next_quarter(self) -> str:
        return f"Q{(self.nq_start.month - 1) // 3 + 1} {self.nq_start.year}"


def windows(today: datetime.date | None = None) -> Windows:
    """The briefing's fixed windows as of `today`: the same 12 months period_filter defaults to."""
    today = today or datetime.date.today()
    end = today.replace(day=1)
    start = _add_months(end, -DEFAULT_PERIOD_MONTHS)
    quarter_start = datetime.date(today.year, (today.month - 1) // 3 * 3 + 1, 1)
    nq_start = _add_months(quarter_start, 3)
    return Windows(
        period=Period(start=start, end=end, prior_start=_add_months(start, -DEFAULT_PERIOD_MONTHS)),
        nq_start=nq_start,
        nq_end=_add_months(nq_start, 3),
        risk_since=today - datetime.timedelta(days=RISK_SIGNAL_DAYS),
        renewal_until=today + datetime.timedelta(days=RENEWAL_SOON_DAYS),
        ladder_end=today + datetime.timedelta(days=LADDER_DAYS),
    )


def _top10() -> str:
    return f"SELECT customer_id, customer_name, region, segment FROM {data_object('v_customers')} WHERE tier = 'Top 10'"


def _at_risk() -> str:
    """customer_ids with a recent risk signal."""
    return f"SELECT DISTINCT customer_id FROM {data_object('v_customer_signals')} WHERE direction = 'risk' AND published_date >= :risk_since"


def _next_renewal(contracts: str) -> str:
    """Each customer's soonest live contract: customer_id, next_renewal, renewal_type, renewal_usd."""
    return f"""SELECT customer_id, end_date AS next_renewal, contract_type AS renewal_type, annual_value_usd AS renewal_usd
  FROM (
    SELECT customer_id, end_date, contract_type, annual_value_usd,
      ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY end_date) AS n
    FROM {contracts}
    WHERE end_date >= current_date()
  )
  WHERE n = 1"""


def _renewing_soon(contracts: str) -> str:
    """Annual value of each customer's contracts that end before :renewal_until."""
    return f"""SELECT customer_id, SUM(annual_value_usd) AS renewing_usd
  FROM {contracts}
  WHERE end_date >= current_date() AND end_date < :renewal_until
  GROUP BY customer_id"""


def _quarter_gap(outlook: str) -> str:
    """Next quarter's plan less commit per customer; positive means commit falls short of plan."""
    return f"""SELECT customer_id, SUM(plan_usd) - SUM(commit_usd) AS nq_gap_usd
  FROM {outlook}
  WHERE month >= :nq_start AND month < :nq_end
  GROUP BY customer_id"""


def _latest_risk(sig: str) -> str:
    """Each at-risk customer's newest risk signal: why the account is flagged."""
    return f"""SELECT customer_id, headline AS reason, source_name AS reason_source, published_date AS reason_date
  FROM (
    SELECT customer_id, headline, source_name, published_date,
      ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY published_date DESC) AS n
    FROM {sig}
    WHERE direction = 'risk' AND published_date >= :risk_since
  )
  WHERE n = 1"""


# --- Shared by both screens -------------------------------------------------------


def briefing(w: Windows, scope: str) -> tuple[str, dict]:
    """The insight records for `scope` ("portfolio" or a customer_id), in reading order."""
    insights = data_object("v_insights")
    order = " ".join(f"WHEN '{c}' THEN {n}" for n, c in enumerate(CHAPTERS))
    statement = f"""
SELECT insight_id, chapter, position, title, body, cause, effect, action, owner, evidence, generated_at, generated_by
FROM {insights}
WHERE scope = :scope
ORDER BY CASE chapter {order} ELSE 99 END, position
"""
    return statement, {"scope": scope}


def signals(w: Windows, customer: str) -> tuple[str, dict]:
    """Market and account signals for the top 10, or for one customer when `customer` is set."""
    sig = data_object("v_customer_signals")
    statement = f"""
WITH top AS ({_top10()})
SELECT s.signal_id, s.customer_id, top.customer_name, s.theme, s.direction, s.headline, s.summary,
  s.source_type, s.source_name, s.source_url, s.published_date
FROM {sig} s JOIN top USING (customer_id)
WHERE (:customer = '' OR s.customer_id = :customer)
ORDER BY s.published_date DESC
"""
    return statement, {"customer": customer}


def deals(w: Windows, customer: str) -> tuple[str, dict]:
    """Open opportunities closing next quarter, largest first."""
    pipeline = data_object("v_pipeline")
    statement = f"""
WITH top AS ({_top10()})
SELECT p.opportunity_id, p.customer_id, top.customer_name, p.product_line, p.stage, p.forecast_category,
  p.amount_usd, p.close_date
FROM {pipeline} p JOIN top USING (customer_id)
WHERE p.stage IN ('Lead', 'Qualified', 'Proposal', 'Commit')
  AND p.close_date >= :nq_start AND p.close_date < :nq_end
  AND (:customer = '' OR p.customer_id = :customer)
ORDER BY p.amount_usd DESC
LIMIT {TOP_DEALS}
"""
    return statement, {**w.params(), "customer": customer}


# --- The top-10 briefing ------------------------------------------------------------


def themes(w: Windows) -> tuple[str, dict]:
    """What the top 10 are focused on: one row per theme, risks first, with the accounts behind it."""
    sig = data_object("v_customer_signals")
    statement = f"""
WITH top AS ({_top10()})
SELECT
  s.theme,
  MAX(s.direction) AS direction,
  COUNT(DISTINCT s.customer_id) AS accounts,
  concat_ws(', ', sort_array(collect_set(top.customer_name))) AS account_names,
  COUNT(*) AS signals,
  MAX(s.published_date) AS latest
FROM {sig} s JOIN top USING (customer_id)
GROUP BY s.theme
ORDER BY CASE MAX(s.direction) WHEN 'risk' THEN 0 ELSE 1 END, accounts DESC, latest DESC
"""
    return statement, {}


def kpis(w: Windows) -> tuple[str, dict]:
    """One row for the top 10: revenue vs plan, share of new devices, and lead-to-win conversion, now and prior."""
    revenue = data_object("v_revenue_monthly")
    outlook = data_object("v_revenue_outlook")
    footprint = data_object("v_device_footprint")
    pipeline = data_object("v_pipeline")
    statement = f"""
WITH top AS ({_top10()}),
rev AS (
  SELECT
    SUM(CASE WHEN r.month >= :start THEN r.revenue_usd END) AS revenue_usd,
    SUM(CASE WHEN r.month < :start THEN r.revenue_usd END) AS revenue_usd_prior
  FROM {revenue} r JOIN top USING (customer_id)
  WHERE r.month >= :prior_start AND r.month < :end
),
plan AS (
  SELECT
    SUM(CASE WHEN o.month >= :start THEN o.plan_usd END) AS plan_usd,
    SUM(CASE WHEN o.month < :start THEN o.plan_usd END) AS plan_usd_prior
  FROM {outlook} o JOIN top USING (customer_id)
  WHERE o.month >= :prior_start AND o.month < :end
),
quarters AS (SELECT MAX(quarter) AS latest FROM {footprint}),
share AS (
  SELECT
    SUM(CASE WHEN f.quarter = q.latest THEN f.device_models_with_us END)
      / NULLIF(SUM(CASE WHEN f.quarter = q.latest THEN f.device_models END), 0) AS device_share,
    SUM(CASE WHEN f.quarter = add_months(q.latest, -12) THEN f.device_models_with_us END)
      / NULLIF(SUM(CASE WHEN f.quarter = add_months(q.latest, -12) THEN f.device_models END), 0) AS device_share_prior,
    MAX(q.latest) AS share_quarter
  FROM {footprint} f JOIN top USING (customer_id) CROSS JOIN quarters q
),
conv AS (
  SELECT
    COUNT_IF(p.close_date >= :start AND p.close_date < :end AND p.stage = 'Closed Won')
      / NULLIF(COUNT_IF(p.close_date >= :start AND p.close_date < :end
          AND p.stage IN ('Closed Won', 'Closed Lost', 'Disqualified')), 0) AS conversion,
    COUNT_IF(p.close_date >= :prior_start AND p.close_date < :start AND p.stage = 'Closed Won')
      / NULLIF(COUNT_IF(p.close_date >= :prior_start AND p.close_date < :start
          AND p.stage IN ('Closed Won', 'Closed Lost', 'Disqualified')), 0) AS conversion_prior,
    COUNT_IF(p.created_date >= :start AND p.created_date < :end) AS leads,
    COUNT_IF(p.created_date >= :prior_start AND p.created_date < :start) AS leads_prior
  FROM {pipeline} p JOIN top USING (customer_id)
  WHERE (p.close_date >= :prior_start AND p.close_date < :end)
     OR (p.created_date >= :prior_start AND p.created_date < :end)
)
SELECT
  rev.revenue_usd / NULLIF(plan.plan_usd, 0) AS plan_attainment,
  rev.revenue_usd_prior / NULLIF(plan.plan_usd_prior, 0) AS plan_attainment_prior,
  rev.revenue_usd,
  plan.plan_usd,
  share.device_share,
  share.device_share_prior,
  share.share_quarter,
  conv.conversion,
  conv.conversion_prior,
  conv.leads,
  conv.leads_prior
FROM rev CROSS JOIN plan CROSS JOIN share CROSS JOIN conv
"""
    return statement, w.params()


def accounts(w: Windows) -> tuple[str, dict]:
    """The top 10, largest first: revenue and its trend, plan attainment, device share, focus, and risk.

    Also what an executive needs to triage them: why an at-risk account is flagged, when its next
    contract ends, and how far next quarter's commit falls short of plan. The `portfolio_*` and
    `*_total` columns repeat on every row: sums over the ten, computed here so the page never adds
    rows up itself.
    """
    revenue = data_object("v_revenue_monthly")
    outlook = data_object("v_revenue_outlook")
    footprint = data_object("v_device_footprint")
    sig = data_object("v_customer_signals")
    contracts = data_object("v_contracts")
    statement = f"""
WITH top AS ({_top10()}),
risk AS ({_at_risk()}),
rev AS (
  SELECT customer_id,
    SUM(CASE WHEN month >= :start THEN revenue_usd END) AS revenue_usd,
    SUM(CASE WHEN month < :start THEN revenue_usd END) AS revenue_usd_prior
  FROM {revenue}
  WHERE month >= :prior_start AND month < :end
  GROUP BY customer_id
),
plan AS (
  SELECT customer_id, SUM(plan_usd) AS plan_usd
  FROM {outlook}
  WHERE month >= :start AND month < :end
  GROUP BY customer_id
),
quarters AS (SELECT MAX(quarter) AS latest FROM {footprint}),
share AS (
  SELECT f.customer_id,
    SUM(CASE WHEN f.quarter = q.latest THEN f.device_models_with_us END)
      / NULLIF(SUM(CASE WHEN f.quarter = q.latest THEN f.device_models END), 0) AS device_share,
    SUM(CASE WHEN f.quarter = add_months(q.latest, -12) THEN f.device_models_with_us END)
      / NULLIF(SUM(CASE WHEN f.quarter = add_months(q.latest, -12) THEN f.device_models END), 0) AS device_share_prior
  FROM {footprint} f CROSS JOIN quarters q
  GROUP BY f.customer_id
),
focus AS (
  SELECT customer_id, theme AS focus
  FROM (
    SELECT customer_id, theme,
      ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY CASE direction WHEN 'risk' THEN 0 ELSE 1 END, published_date DESC) AS n
    FROM {sig}
  )
  WHERE n = 1
),
renewal AS ({_next_renewal(contracts)}),
renewing AS ({_renewing_soon(contracts)}),
gap AS ({_quarter_gap(outlook)}),
why AS ({_latest_risk(sig)})
SELECT
  top.customer_id,
  top.customer_name,
  top.region,
  top.segment,
  rev.revenue_usd,
  (rev.revenue_usd - rev.revenue_usd_prior) / NULLIF(rev.revenue_usd_prior, 0) AS revenue_growth,
  rev.revenue_usd / NULLIF(plan.plan_usd, 0) AS plan_attainment,
  share.device_share,
  share.device_share - share.device_share_prior AS device_share_change,
  focus.focus,
  risk.customer_id IS NOT NULL AS at_risk,
  why.reason,
  why.reason_source,
  why.reason_date,
  renewal.next_renewal,
  datediff(renewal.next_renewal, current_date()) AS days_to_renewal,
  renewal.renewal_type,
  renewal.renewal_usd,
  gap.nq_gap_usd,
  SUM(rev.revenue_usd) OVER () AS portfolio_revenue_usd,
  SUM(CASE WHEN risk.customer_id IS NOT NULL THEN rev.revenue_usd END) OVER () AS at_risk_revenue_usd,
  SUM(renewing.renewing_usd) OVER () AS renewing_usd_total,
  SUM(CASE WHEN risk.customer_id IS NOT NULL THEN renewing.renewing_usd END) OVER () AS at_risk_renewing_usd
FROM top
LEFT JOIN rev USING (customer_id)
LEFT JOIN plan USING (customer_id)
LEFT JOIN share USING (customer_id)
LEFT JOIN focus USING (customer_id)
LEFT JOIN risk USING (customer_id)
LEFT JOIN why USING (customer_id)
LEFT JOIN renewal USING (customer_id)
LEFT JOIN renewing USING (customer_id)
LEFT JOIN gap USING (customer_id)
ORDER BY rev.revenue_usd DESC NULLS LAST
"""
    return statement, w.params()


def accounts_monthly(w: Windows) -> tuple[str, dict]:
    """Long rows (customer_id, month, revenue_usd) over the period, for the accounts' sparklines."""
    revenue = data_object("v_revenue_monthly")
    statement = f"""
WITH top AS ({_top10()})
SELECT r.customer_id, r.month, r.revenue_usd
FROM {revenue} r JOIN top USING (customer_id)
WHERE r.month >= :start AND r.month < :end
ORDER BY r.customer_id, r.month
"""
    return statement, w.params()


def outlook(w: Windows) -> tuple[str, dict]:
    """Next quarter for the top 10: plan, commit, and best case, split by at-risk and the rest."""
    out = data_object("v_revenue_outlook")
    statement = f"""
WITH top AS ({_top10()}),
risk AS ({_at_risk()})
SELECT
  SUM(o.plan_usd) AS plan_usd,
  SUM(o.commit_usd) AS commit_usd,
  SUM(o.best_case_usd) AS best_case_usd,
  SUM(CASE WHEN risk.customer_id IS NOT NULL THEN o.plan_usd END) AS at_risk_plan_usd,
  SUM(CASE WHEN risk.customer_id IS NOT NULL THEN o.commit_usd END) AS at_risk_commit_usd,
  COUNT(DISTINCT risk.customer_id) AS at_risk_accounts,
  :nq_label AS quarter
FROM {out} o
JOIN top USING (customer_id)
LEFT JOIN risk USING (customer_id)
WHERE o.month >= :nq_start AND o.month < :nq_end
"""
    return statement, {**w.params(), "nq_label": w.next_quarter}


def renewals(w: Windows) -> tuple[str, dict]:
    """Every top-10 contract that ends in the next 12 months, soonest first, for the renewal ladder."""
    contracts = data_object("v_contracts")
    statement = f"""
WITH top AS ({_top10()}),
risk AS ({_at_risk()})
SELECT c.contract_id, c.customer_id, top.customer_name, c.contract_type, c.end_date, c.annual_value_usd, c.status,
  datediff(c.end_date, current_date()) AS days_to_end,
  risk.customer_id IS NOT NULL AS at_risk
FROM {contracts} c
JOIN top USING (customer_id)
LEFT JOIN risk USING (customer_id)
WHERE c.end_date >= current_date() AND c.end_date < :ladder_end
ORDER BY c.end_date
"""
    return statement, w.params()


def coverage(w: Windows, customer: str) -> tuple[str, dict]:
    """Next quarter's gap to plan beside the open deals that close in it, by stage.

    One row for the top 10, or for one account when `customer` is set. `amount_usd` is a deal's
    first-year revenue, not what lands in the quarter, so the page presents coverage as an upper bound.
    """
    outlook = data_object("v_revenue_outlook")
    pipeline = data_object("v_pipeline")
    statement = f"""
WITH top AS ({_top10()}),
gap AS (
  SELECT SUM(o.plan_usd) - SUM(o.commit_usd) AS gap_usd
  FROM {outlook} o
  JOIN top USING (customer_id)
  WHERE o.month >= :nq_start AND o.month < :nq_end
    AND (:customer = '' OR o.customer_id = :customer)
),
deals_open AS (
  SELECT
    SUM(CASE WHEN p.stage = 'Commit' THEN p.amount_usd END) AS stage_commit_usd,
    SUM(CASE WHEN p.stage = 'Proposal' THEN p.amount_usd END) AS stage_proposal_usd,
    SUM(CASE WHEN p.stage = 'Qualified' THEN p.amount_usd END) AS stage_qualified_usd,
    SUM(CASE WHEN p.stage = 'Lead' THEN p.amount_usd END) AS stage_lead_usd,
    COUNT(*) AS deals
  FROM {pipeline} p
  JOIN top USING (customer_id)
  WHERE p.stage IN ('Lead', 'Qualified', 'Proposal', 'Commit')
    AND p.close_date >= :nq_start AND p.close_date < :nq_end
    AND (:customer = '' OR p.customer_id = :customer)
)
SELECT gap.gap_usd, deals_open.stage_commit_usd, deals_open.stage_proposal_usd, deals_open.stage_qualified_usd,
  deals_open.stage_lead_usd, deals_open.deals, :nq_label AS quarter
FROM gap CROSS JOIN deals_open
"""
    return statement, {**w.params(), "customer": customer, "nq_label": w.next_quarter}


# --- One account ----------------------------------------------------------------------


def profile(w: Windows, customer: str) -> tuple[str, dict]:
    """One top-10 account's headline numbers. No row when `customer` is not in the top 10."""
    revenue = data_object("v_revenue_monthly")
    out = data_object("v_revenue_outlook")
    footprint = data_object("v_device_footprint")
    statement = f"""
WITH top AS ({_top10()}),
risk AS ({_at_risk()}),
rev AS (
  SELECT
    SUM(CASE WHEN month >= :start THEN revenue_usd END) AS revenue_usd,
    SUM(CASE WHEN month < :start THEN revenue_usd END) AS revenue_usd_prior
  FROM {revenue}
  WHERE customer_id = :customer AND month >= :prior_start AND month < :end
),
plan AS (
  SELECT
    SUM(CASE WHEN month >= :start AND month < :end THEN plan_usd END) AS plan_usd,
    SUM(CASE WHEN month >= :prior_start AND month < :start THEN plan_usd END) AS plan_usd_prior,
    SUM(CASE WHEN month >= :nq_start AND month < :nq_end THEN plan_usd END) AS nq_plan_usd,
    SUM(CASE WHEN month >= :nq_start AND month < :nq_end THEN commit_usd END) AS nq_commit_usd,
    SUM(CASE WHEN month >= :nq_start AND month < :nq_end THEN best_case_usd END) AS nq_best_case_usd
  FROM {out}
  WHERE customer_id = :customer
),
quarters AS (SELECT MAX(quarter) AS latest FROM {footprint}),
share AS (
  SELECT
    SUM(CASE WHEN f.quarter = q.latest THEN f.device_models_with_us END)
      / NULLIF(SUM(CASE WHEN f.quarter = q.latest THEN f.device_models END), 0) AS device_share,
    SUM(CASE WHEN f.quarter = add_months(q.latest, -12) THEN f.device_models_with_us END)
      / NULLIF(SUM(CASE WHEN f.quarter = add_months(q.latest, -12) THEN f.device_models END), 0) AS device_share_prior
  FROM {footprint} f CROSS JOIN quarters q
  WHERE f.customer_id = :customer
)
SELECT
  top.customer_id,
  top.customer_name,
  top.region,
  top.segment,
  rev.revenue_usd,
  (rev.revenue_usd - rev.revenue_usd_prior) / NULLIF(rev.revenue_usd_prior, 0) AS revenue_growth,
  rev.revenue_usd / NULLIF(plan.plan_usd, 0) AS plan_attainment,
  rev.revenue_usd_prior / NULLIF(plan.plan_usd_prior, 0) AS plan_attainment_prior,
  share.device_share,
  share.device_share_prior,
  plan.nq_plan_usd,
  plan.nq_commit_usd,
  plan.nq_best_case_usd,
  plan.nq_plan_usd - plan.nq_commit_usd AS nq_gap_usd,
  :nq_label AS quarter,
  risk.customer_id IS NOT NULL AS at_risk
FROM top
CROSS JOIN rev CROSS JOIN plan CROSS JOIN share
LEFT JOIN risk ON risk.customer_id = top.customer_id
WHERE top.customer_id = :customer
"""
    return statement, {**w.params(), "customer": customer, "nq_label": w.next_quarter}


def revenue(w: Windows, customer: str) -> tuple[str, dict]:
    """One account by month: actual revenue over the period, plan throughout, forecast through next quarter."""
    rev = data_object("v_revenue_monthly")
    out = data_object("v_revenue_outlook")
    statement = f"""
SELECT o.month, r.revenue_usd, o.plan_usd, o.commit_usd, o.best_case_usd
FROM {out} o
LEFT JOIN {rev} r ON r.customer_id = o.customer_id AND r.month = o.month AND r.month < :end
WHERE o.customer_id = :customer AND o.month >= :start AND o.month < :nq_end
ORDER BY o.month
"""
    return statement, {**w.params(), "customer": customer}


def footprint(w: Windows, customer: str) -> tuple[str, dict]:
    """One account's share of new device models using our products, by quarter."""
    fp = data_object("v_device_footprint")
    statement = f"""
SELECT quarter, SUM(device_models) AS device_models, SUM(device_models_with_us) AS device_models_with_us,
  SUM(device_models_with_us) / NULLIF(SUM(device_models), 0) AS device_share
FROM {fp}
WHERE customer_id = :customer
GROUP BY quarter
ORDER BY quarter
"""
    return statement, {"customer": customer}


def contracts(w: Windows, customer: str) -> tuple[str, dict]:
    """One account's live contracts, soonest to end first."""
    ct = data_object("v_contracts")
    statement = f"""
SELECT contract_id, contract_type, start_date, end_date, annual_value_usd, status,
  datediff(end_date, current_date()) AS days_to_end
FROM {ct}
WHERE customer_id = :customer AND end_date >= current_date()
ORDER BY end_date
"""
    return statement, {"customer": customer}
