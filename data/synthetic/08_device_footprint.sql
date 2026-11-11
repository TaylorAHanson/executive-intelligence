-- Synthetic device footprint (stands in for the device database): per
-- customer, product line, and quarter, how many device models the customer
-- launched and how many of them use our products. Last 8 complete quarters,
-- top 10 and strategic accounts.
--
-- Second-sourcing accounts (top 10 with falling revenue) lose about 8 points
-- of share a quarter over the last four quarters; fast growers gain a little.

CREATE OR REPLACE TABLE `${catalog}`.`${schema}`.synthetic_device_footprint AS
WITH quarters AS (
  SELECT
    add_months(trunc(current_date(), 'QUARTER'), -3 * CAST(id AS INT)) AS quarter,
    CAST(id AS INT) AS quarters_ago
  FROM range(1, 9)
),
lines AS (
  SELECT
    c.customer_id,
    c.tier,
    c.monthly_growth,
    c.tier = 'Top 10' AND c.monthly_growth < 0 AS second_sourcing,
    explode(CASE c.segment
      WHEN 'Handset' THEN array('Mobile platform', 'Connectivity')
      WHEN 'Automotive' THEN array('Infotainment', 'Driver assist')
      WHEN 'IoT' THEN array('Industrial IoT', 'Edge AI module')
      WHEN 'XR' THEN array('XR platform', 'Edge AI module')
      WHEN 'Compute' THEN array('PC platform', 'Edge AI module')
      ELSE array('Wi-Fi 7', '5G fixed wireless')
    END) AS product_line
  FROM `${catalog}`.`${schema}`.synthetic_customers c
  WHERE c.tier IN ('Top 10', 'Strategic')
),
grid AS (
  SELECT
    l.*,
    q.quarter,
    q.quarters_ago,
    CASE WHEN l.tier = 'Top 10' THEN 6 ELSE 3 END + CAST(abs(hash(l.customer_id, l.product_line, q.quarter)) % 6 AS INT) AS device_models,
    0.62 + (abs(hash(l.customer_id, l.product_line)) % 1000) / 4000.0 AS base_share
  FROM lines l
  CROSS JOIN quarters q
),
shared AS (
  SELECT
    *,
    least(0.97, greatest(0.05,
      base_share
      - CASE WHEN second_sourcing AND quarters_ago <= 4 THEN 0.08 * (5 - quarters_ago) ELSE 0 END
      + CASE WHEN monthly_growth > 0.015 THEN 0.015 * (8 - quarters_ago) ELSE 0 END
    )) AS share
  FROM grid
)
SELECT
  quarter,
  customer_id,
  product_line,
  device_models,
  CAST(round(device_models * share) AS INT) AS device_models_with_us
FROM shared
