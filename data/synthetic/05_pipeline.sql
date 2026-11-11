-- Synthetic sales pipeline (stands in for Salesforce opportunities): leads
-- created over the last 24 months, each moving Lead -> Qualified -> Proposal
-- -> Commit -> Closed Won / Closed Lost, or Disqualified as a lead.
--
-- `amount_usd` is the first-year revenue the opportunity would add if won.
-- The top 10 get 60 opportunities each, everyone else 12. Opportunities whose
-- close date has passed are closed; the rest are open at a stage set by how
-- far through their sales cycle they are.
--
-- "Second-sourcing" accounts (top 10 with falling revenue, as in the other
-- synthetic files) lose more of what closed in the last nine months. That is
-- the cause the Customer Intelligence briefing traces; it is invented.

CREATE OR REPLACE TABLE `${catalog}`.`${schema}`.synthetic_pipeline AS
WITH ids AS (
  SELECT
    CAST(id AS INT) AS n,
    CASE WHEN id < 600 THEN CAST(id % 10 AS INT) + 1 ELSE CAST((id - 600) % 50 AS INT) + 11 END AS c
  FROM range(1200)
),
draws AS (
  SELECT
    i.n,
    cu.customer_id,
    cu.segment,
    cu.tier,
    cu.base_monthly_revenue,
    cu.tier = 'Top 10' AND cu.monthly_growth < 0 AS second_sourcing,
    (abs(hash(i.n, 'created')) % 10000) / 10000.0 AS u_created,
    (abs(hash(i.n, 'cycle')) % 10000) / 10000.0 AS u_cycle,
    (abs(hash(i.n, 'qualify')) % 10000) / 10000.0 AS u_qualify,
    (abs(hash(i.n, 'win')) % 10000) / 10000.0 AS u_win,
    (abs(hash(i.n, 'size')) % 10000) / 10000.0 AS u_size,
    (abs(hash(i.n, 'line')) % 2) + 1 AS line_pick
  FROM ids i
  JOIN `${catalog}`.`${schema}`.synthetic_customers cu ON cu.customer_id = concat('C', lpad(CAST(i.c AS STRING), 3, '0'))
),
dated AS (
  SELECT
    *,
    date_sub(current_date(), CAST(u_created * 730 AS INT)) AS created_date,
    CAST(45 + u_cycle * 225 AS INT) AS cycle_days
  FROM draws
),
staged AS (
  SELECT
    *,
    date_add(created_date, cycle_days) AS close_date,
    datediff(current_date(), created_date) / cycle_days AS progress
  FROM dated
)
SELECT
  concat('OP', lpad(CAST(n AS STRING), 5, '0')) AS opportunity_id,
  customer_id,
  element_at(
    CASE segment
      WHEN 'Handset' THEN array('Mobile platform', 'Connectivity')
      WHEN 'Automotive' THEN array('Infotainment', 'Driver assist')
      WHEN 'IoT' THEN array('Industrial IoT', 'Edge AI module')
      WHEN 'XR' THEN array('XR platform', 'Edge AI module')
      WHEN 'Compute' THEN array('PC platform', 'Edge AI module')
      ELSE array('Wi-Fi 7', '5G fixed wireless')
    END,
    CAST(line_pick AS INT)
  ) AS product_line,
  CASE
    WHEN close_date > current_date() THEN
      CASE WHEN progress < 0.25 THEN 'Lead' WHEN progress < 0.5 THEN 'Qualified' WHEN progress < 0.75 THEN 'Proposal' ELSE 'Commit' END
    WHEN u_qualify < 0.3 THEN 'Disqualified'
    WHEN u_win < CASE WHEN second_sourcing AND close_date > date_sub(current_date(), 270) THEN 0.28 ELSE 0.58 END THEN 'Closed Won'
    ELSE 'Closed Lost'
  END AS stage,
  CASE
    WHEN close_date > current_date() THEN
      CASE WHEN progress < 0.5 THEN 'Pipeline' WHEN progress < 0.75 THEN 'Best Case' ELSE 'Commit' END
    WHEN u_qualify < 0.3 THEN 'Omitted'
    WHEN u_win < CASE WHEN second_sourcing AND close_date > date_sub(current_date(), 270) THEN 0.28 ELSE 0.58 END THEN 'Closed'
    ELSE 'Omitted'
  END AS forecast_category,
  CAST(
    base_monthly_revenue * CASE WHEN tier = 'Top 10' THEN 0.2 ELSE 0.3 END * (0.4 + u_size * 1.6)
    AS DECIMAL(18, 2)
  ) AS amount_usd,
  created_date,
  close_date
FROM staged
