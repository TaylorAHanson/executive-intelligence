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
  numbers here and the sentences it writes agree.

"Top 10" means `tier = 'Top 10'` in v_customers.
"""
import datetime
from dataclasses import dataclass

from services.dashboards import DEFAULT_PERIOD_MONTHS, Period, _add_months, data_object

RISK_SIGNAL_DAYS = 120
CHAPTERS = ("headline", "know", "measure", "anticipate", "act")
TOP_DEALS = 5


@dataclass(frozen=True)
class Windows:
    period: Period
    nq_start: datetime.date
    nq_end: datetime.date
    risk_since: datetime.date

    def params(self) -> dict:
        return {
            **self.period.params(),
            "nq_start": self.nq_start,
            "nq_end": self.nq_end,
            "risk_since": self.risk_since,
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
    )


def _top10() -> str:
    return f"SELECT customer_id, customer_name, region, segment FROM {data_object('v_customers')} WHERE tier = 'Top 10'"


def _at_risk() -> str:
    """customer_ids with a recent risk signal."""
    return f"SELECT DISTINCT customer_id FROM {data_object('v_customer_signals')} WHERE direction = 'risk' AND published_date >= :risk_since"


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
    """What the top 10 are focused on: one row per theme, with the accounts behind it."""
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
ORDER BY CASE MAX(s.direction) WHEN 'risk' THEN 1 ELSE 0 END, accounts DESC, latest DESC
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
    """The top 10, largest first: revenue and its trend, plan attainment, device share, focus, and risk."""
    revenue = data_object("v_revenue_monthly")
    outlook = data_object("v_revenue_outlook")
    footprint = data_object("v_device_footprint")
    sig = data_object("v_customer_signals")
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
)
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
  risk.customer_id IS NOT NULL AS at_risk
FROM top
LEFT JOIN rev USING (customer_id)
LEFT JOIN plan USING (customer_id)
LEFT JOIN share USING (customer_id)
LEFT JOIN focus USING (customer_id)
LEFT JOIN risk USING (customer_id)
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
  share.device_share,
  share.device_share_prior,
  plan.nq_plan_usd,
  plan.nq_commit_usd,
  plan.nq_best_case_usd,
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
