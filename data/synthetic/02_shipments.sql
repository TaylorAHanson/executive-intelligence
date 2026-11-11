-- Synthetic shipments: 36 months of history ending today, 4 to 10 per customer
-- per month. Dates are relative to current_date(), so re-running the loader
-- keeps the data current.
--
-- Revenue grows at each customer's `monthly_growth` with mild seasonality.
-- At-risk customers lose about 22 points of on-time delivery and 7% of
-- revenue a month over the last six months, enough to show in a 12-month view.

CREATE OR REPLACE TABLE `${catalog}`.`${schema}`.synthetic_shipments AS
WITH grid AS (
  SELECT
    c.*,
    CAST(m.id AS INT) AS months_ago,
    CAST(s.id AS INT) AS slot,
    add_months(trunc(current_date(), 'MM'), -CAST(m.id AS INT)) AS month_start
  FROM `${catalog}`.`${schema}`.synthetic_customers c
  CROSS JOIN range(36) m
  CROSS JOIN range(10) s
  WHERE s.id < c.shipments_per_month
),
draws AS (
  SELECT
    *,
    (abs(hash(customer_id, months_ago, slot, 'day')) % 10000) / 10000.0 AS u_day,
    (abs(hash(customer_id, months_ago, slot, 'time')) % 10000) / 10000.0 AS u_time,
    (abs(hash(customer_id, months_ago, slot, 'full')) % 10000) / 10000.0 AS u_full,
    (abs(hash(customer_id, months_ago, slot, 'size')) % 10000) / 10000.0 AS u_size,
    at_risk AND months_ago < 6 AS slipping
  FROM grid
)
SELECT
  concat(customer_id, '-', date_format(month_start, 'yyyyMM'), '-', lpad(CAST(slot AS STRING), 2, '0')) AS shipment_id,
  customer_id,
  date_add(month_start, CAST(u_day * 27 AS INT)) AS ship_date,
  CAST(base_monthly_revenue / shipments_per_month / 18 * (0.6 + u_size * 0.8) AS BIGINT) AS units,
  CAST(
    base_monthly_revenue / shipments_per_month
    * (0.7 + u_size * 0.6)
    * power(1 + monthly_growth, 35 - months_ago)
    * (1 + 0.08 * sin(2 * pi() * month(month_start) / 12))
    * CASE WHEN slipping THEN power(0.93, 6 - months_ago) ELSE 1 END
    AS DECIMAL(18, 2)
  ) AS revenue_usd,
  u_time < otif_baseline + 0.01 - CASE WHEN slipping THEN 0.22 ELSE 0 END AS on_time,
  u_full < 0.985 AS in_full
FROM draws
WHERE date_add(month_start, CAST(u_day * 27 AS INT)) <= current_date()
