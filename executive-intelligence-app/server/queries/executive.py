"""Executive Insights widgets.

Each function returns `(statement, parameters)` for `run_widget`. Rules:

- Read only contract views, through `data_object` (data/contract.md).
- Every value is a `:name` parameter. Only `data_object` names are spliced in.
- Aggregate in SQL. A widget's result should be a handful of rows; anything a
  KPI shows is computed here, never summed in Python or the browser.

Periods are half-open: `[:start, :end)`, with the comparison period
`[:prior_start, :start)`. `:regions` is '' or a comma-separated list.
"""
from services.dashboards import Period, data_object

_REGION_MATCH = "(:regions = '' OR array_contains(split(:regions, ','), c.region))"

#: Rows in the top-customers table. Ranked in SQL, so the table is complete.
TOP_CUSTOMERS = 25


def _params(period: Period, regions: str) -> dict:
    return {**period.params(), "regions": regions}


def kpis(period: Period, regions: str) -> tuple[str, dict]:
    """One row: revenue, OTIF, and design-win rate, each for the period and the prior period."""
    customers = data_object("v_customers")
    revenue = data_object("v_revenue_monthly")
    shipments = data_object("v_shipments")
    design_wins = data_object("v_design_wins")
    statement = f"""
WITH cust AS (
  SELECT c.customer_id FROM {customers} c WHERE {_REGION_MATCH}
),
rev AS (
  SELECT
    SUM(CASE WHEN r.month >= :start THEN r.revenue_usd END) AS revenue_usd,
    SUM(CASE WHEN r.month < :start THEN r.revenue_usd END) AS revenue_usd_prior
  FROM {revenue} r JOIN cust USING (customer_id)
  WHERE r.month >= :prior_start AND r.month < :end
),
otif AS (
  SELECT
    AVG(CASE WHEN s.ship_date >= :start THEN CAST(s.on_time AND s.in_full AS INT) END) AS otif,
    AVG(CASE WHEN s.ship_date < :start THEN CAST(s.on_time AND s.in_full AS INT) END) AS otif_prior
  FROM {shipments} s JOIN cust USING (customer_id)
  WHERE s.ship_date >= :prior_start AND s.ship_date < :end
),
dw AS (
  SELECT
    COUNT_IF(d.decided_date >= :start AND d.status = 'won')
      / NULLIF(COUNT_IF(d.decided_date >= :start AND d.status IN ('won', 'lost')), 0) AS win_rate,
    COUNT_IF(d.decided_date < :start AND d.status = 'won')
      / NULLIF(COUNT_IF(d.decided_date < :start AND d.status IN ('won', 'lost')), 0) AS win_rate_prior
  FROM {design_wins} d JOIN cust USING (customer_id)
  WHERE d.decided_date >= :prior_start AND d.decided_date < :end
)
SELECT * FROM rev CROSS JOIN otif CROSS JOIN dw
"""
    return statement, _params(period, regions)


def monthly(period: Period, regions: str) -> tuple[str, dict]:
    """One row per month of the period, every month present: revenue, OTIF, win rate. Drives sparklines."""
    customers = data_object("v_customers")
    revenue = data_object("v_revenue_monthly")
    shipments = data_object("v_shipments")
    design_wins = data_object("v_design_wins")
    statement = f"""
WITH months AS (
  SELECT explode(sequence(:start, add_months(:end, -1), INTERVAL 1 MONTH)) AS month
),
cust AS (
  SELECT c.customer_id FROM {customers} c WHERE {_REGION_MATCH}
),
rev AS (
  SELECT r.month, SUM(r.revenue_usd) AS revenue_usd
  FROM {revenue} r JOIN cust USING (customer_id)
  WHERE r.month >= :start AND r.month < :end
  GROUP BY r.month
),
otif AS (
  SELECT trunc(s.ship_date, 'MM') AS month, AVG(CAST(s.on_time AND s.in_full AS INT)) AS otif
  FROM {shipments} s JOIN cust USING (customer_id)
  WHERE s.ship_date >= :start AND s.ship_date < :end
  GROUP BY 1
),
dw AS (
  SELECT
    trunc(d.decided_date, 'MM') AS month,
    COUNT_IF(d.status = 'won') / NULLIF(COUNT_IF(d.status IN ('won', 'lost')), 0) AS win_rate
  FROM {design_wins} d JOIN cust USING (customer_id)
  WHERE d.decided_date >= :start AND d.decided_date < :end
  GROUP BY 1
)
SELECT m.month, rev.revenue_usd, otif.otif, dw.win_rate
FROM months m
LEFT JOIN rev USING (month)
LEFT JOIN otif USING (month)
LEFT JOIN dw USING (month)
ORDER BY m.month
"""
    return statement, _params(period, regions)


def revenue_by_region(period: Period, regions: str) -> tuple[str, dict]:
    """Long rows (month, region, revenue_usd), for a stacked chart pivoted in the browser."""
    customers = data_object("v_customers")
    revenue = data_object("v_revenue_monthly")
    statement = f"""
SELECT r.month, c.region, SUM(r.revenue_usd) AS revenue_usd
FROM {revenue} r JOIN {customers} c USING (customer_id)
WHERE r.month >= :start AND r.month < :end AND {_REGION_MATCH}
GROUP BY r.month, c.region
ORDER BY r.month, c.region
"""
    return statement, _params(period, regions)


def top_customers(period: Period, regions: str) -> tuple[str, dict]:
    """The period's largest customers by revenue, with growth, OTIF, open pipeline, and a health flag."""
    customers = data_object("v_customers")
    revenue = data_object("v_revenue_monthly")
    shipments = data_object("v_shipments")
    design_wins = data_object("v_design_wins")
    statement = f"""
WITH rev AS (
  SELECT
    customer_id,
    SUM(CASE WHEN month >= :start THEN revenue_usd END) AS revenue_usd,
    SUM(CASE WHEN month < :start THEN revenue_usd END) AS revenue_usd_prior
  FROM {revenue}
  WHERE month >= :prior_start AND month < :end
  GROUP BY customer_id
),
ship AS (
  SELECT customer_id, AVG(CAST(on_time AND in_full AS INT)) AS otif
  FROM {shipments}
  WHERE ship_date >= :start AND ship_date < :end
  GROUP BY customer_id
),
pipe AS (
  SELECT customer_id, COUNT(*) AS open_opportunities
  FROM {design_wins}
  WHERE status = 'open'
  GROUP BY customer_id
),
ranked AS (
  SELECT
    c.customer_id,
    c.customer_name,
    c.region,
    c.segment,
    c.tier,
    rev.revenue_usd,
    (rev.revenue_usd - rev.revenue_usd_prior) / NULLIF(rev.revenue_usd_prior, 0) AS revenue_growth,
    ship.otif,
    COALESCE(pipe.open_opportunities, 0) AS open_opportunities
  FROM {customers} c
  JOIN rev USING (customer_id)
  LEFT JOIN ship USING (customer_id)
  LEFT JOIN pipe USING (customer_id)
  WHERE rev.revenue_usd IS NOT NULL AND {_REGION_MATCH}
)
SELECT
  *,
  CASE
    WHEN otif < 0.85 OR revenue_growth < -0.10 THEN 'At risk'
    WHEN otif < 0.92 OR revenue_growth < 0 THEN 'Watch'
    ELSE 'Healthy'
  END AS health
FROM ranked
ORDER BY revenue_usd DESC
LIMIT {TOP_CUSTOMERS}
"""
    return statement, _params(period, regions)


def regions() -> tuple[str, dict]:
    """Filter options: every region with at least one customer."""
    customers = data_object("v_customers")
    return f"SELECT DISTINCT region FROM {customers} ORDER BY region", {}
