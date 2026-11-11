-- Synthetic customer contracts (stands in for the contract management system) for the top 10 and
-- strategic accounts: a master supply agreement, a yearly volume pricing
-- agreement, and, for segments that license software, a software license.
--
-- Second-sourcing accounts (top 10 with falling revenue) have their master
-- supply agreement ending in the next 40-130 days, so the renewal lands inside
-- the risk the briefing describes. Dates are relative to current_date().

CREATE OR REPLACE TABLE `${catalog}`.`${schema}`.synthetic_contracts AS
WITH accounts AS (
  SELECT
    customer_id,
    segment,
    base_monthly_revenue,
    tier = 'Top 10' AND monthly_growth < 0 AS second_sourcing
  FROM `${catalog}`.`${schema}`.synthetic_customers
  WHERE tier IN ('Top 10', 'Strategic')
),
kinds AS (
  SELECT * FROM VALUES
    ('MSA', 'Master supply agreement', 0.6),
    ('VPA', 'Volume pricing agreement', 0.3),
    ('SWL', 'Software license', 0.05)
  AS k(code, contract_type, value_share)
),
dated AS (
  SELECT
    a.*,
    k.code,
    k.contract_type,
    k.value_share,
    CASE
      WHEN k.code = 'MSA' AND a.second_sourcing THEN date_add(current_date(), 40 + CAST(abs(hash(a.customer_id, 'msa')) % 90 AS INT))
      WHEN k.code = 'MSA' THEN date_add(current_date(), 180 + CAST(abs(hash(a.customer_id, 'msa')) % 900 AS INT))
      WHEN k.code = 'VPA' THEN date_add(current_date(), 20 + CAST(abs(hash(a.customer_id, 'vpa')) % 345 AS INT))
      ELSE date_add(current_date(), 120 + CAST(abs(hash(a.customer_id, 'swl')) % 600 AS INT))
    END AS end_date,
    CASE k.code WHEN 'MSA' THEN 3 + CAST(abs(hash(a.customer_id, 'term')) % 3 AS INT) WHEN 'VPA' THEN 1 ELSE 2 END AS term_years
  FROM accounts a
  CROSS JOIN kinds k
  WHERE k.code <> 'SWL' OR a.segment IN ('Handset', 'Automotive', 'XR', 'Compute')
)
SELECT
  concat('AG-', customer_id, '-', code) AS contract_id,
  customer_id,
  contract_type,
  add_months(end_date, -12 * term_years) AS start_date,
  end_date,
  CAST(base_monthly_revenue * 12 * value_share AS DECIMAL(18, 2)) AS annual_value_usd,
  CASE WHEN datediff(end_date, current_date()) <= 120 THEN 'Renewal in negotiation' ELSE 'Active' END AS status
FROM dated
