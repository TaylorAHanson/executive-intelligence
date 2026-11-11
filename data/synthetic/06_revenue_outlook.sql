-- Synthetic finance plan and forecast (stands in for FP&A's plan and the sales
-- forecast), by customer and month, from 24 months ago to 6 months ahead.
--
-- Plan: the same month a year earlier, plus 12% for the top 10 and 8% for
-- everyone else. Forecast, from the current month on only: the same month a
-- year earlier times the customer's year-over-year trend over the last three
-- complete months, less 3%, as commit; 4-9% above that as best case.
-- Second-sourcing accounts' commit falls a further 4% a month, and their best
-- case assumes half of that is won back. These rules are invented to make the
-- outlook chapter tell a story.

CREATE OR REPLACE TABLE `${catalog}`.`${schema}`.synthetic_revenue_outlook AS
WITH this AS (SELECT trunc(current_date(), 'MM') AS month),
months AS (
  SELECT add_months(this.month, CAST(id AS INT) - 24) AS month, CAST(id AS INT) - 24 AS offset
  FROM range(31) CROSS JOIN this
),
trend AS (
  SELECT
    r.customer_id,
    SUM(CASE WHEN r.month >= add_months(this.month, -3) THEN r.revenue_usd END)
      / SUM(CASE WHEN r.month < add_months(this.month, -12) THEN r.revenue_usd END) AS yoy
  FROM `${catalog}`.`${schema}`.synthetic_revenue_monthly r CROSS JOIN this
  WHERE (r.month >= add_months(this.month, -3) AND r.month < this.month)
     OR (r.month >= add_months(this.month, -15) AND r.month < add_months(this.month, -12))
  GROUP BY r.customer_id
),
rows AS (
  SELECT
    m.month,
    m.offset,
    c.customer_id,
    c.tier,
    c.tier = 'Top 10' AND c.monthly_growth < 0 AS second_sourcing,
    prior.revenue_usd AS prior_usd,
    t.yoy,
    1.04 + (abs(hash(c.customer_id, 'best')) % 100) / 2000.0 AS upside
  FROM months m
  CROSS JOIN `${catalog}`.`${schema}`.synthetic_customers c
  JOIN `${catalog}`.`${schema}`.synthetic_revenue_monthly prior
    ON prior.customer_id = c.customer_id AND prior.month = add_months(m.month, -12)
  LEFT JOIN trend t ON t.customer_id = c.customer_id
)
SELECT
  month,
  customer_id,
  CAST(prior_usd * CASE WHEN tier = 'Top 10' THEN 1.12 ELSE 1.08 END AS DECIMAL(18, 2)) AS plan_usd,
  CASE WHEN offset >= 0 THEN CAST(
    prior_usd * yoy * 0.97 * CASE WHEN second_sourcing THEN power(0.96, offset + 1) ELSE 1 END
    AS DECIMAL(18, 2)) END AS commit_usd,
  CASE WHEN offset >= 0 THEN CAST(
    prior_usd * yoy * 0.97 * CASE WHEN second_sourcing THEN power(0.98, offset + 1) * 1.03 ELSE upside END
    AS DECIMAL(18, 2)) END AS best_case_usd
FROM rows
