-- Synthetic design-win opportunities: about 30 per customer opened over the
-- last three years. Each is decided 30 to 240 days after opening; one not yet
-- decided by today is open. Win rates differ by segment, so the dashboards
-- show a spread.

CREATE OR REPLACE TABLE `${catalog}`.`${schema}`.synthetic_design_wins AS
WITH base AS (
  SELECT
    id,
    format_string('C%03d', CAST(id % 60 AS INT) + 1) AS customer_id,
    (abs(hash(id, 'opened')) % 10000) / 10000.0 AS u_opened,
    (abs(hash(id, 'cycle')) % 10000) / 10000.0 AS u_cycle,
    (abs(hash(id, 'won')) % 10000) / 10000.0 AS u_won,
    (abs(hash(id, 'value')) % 10000) / 10000.0 AS u_value
  FROM range(60 * 30)
),
opportunities AS (
  SELECT
    b.*,
    c.segment,
    c.tier,
    date_add(add_months(trunc(current_date(), 'MM'), -36), CAST(b.u_opened * 36 * 30.4 AS INT)) AS opened_date,
    CASE c.segment
      WHEN 'Automotive' THEN 0.48
      WHEN 'Handset' THEN 0.42
      WHEN 'Compute' THEN 0.36
      WHEN 'Networking' THEN 0.34
      WHEN 'IoT' THEN 0.30
      ELSE 0.24
    END AS win_probability
  FROM base b
  JOIN `${catalog}`.`${schema}`.synthetic_customers c USING (customer_id)
),
decided AS (
  SELECT *, date_add(opened_date, 30 + CAST(u_cycle * 210 AS INT)) AS decision_date
  FROM opportunities
  WHERE opened_date <= current_date()
)
SELECT
  format_string('DW%05d', id) AS opportunity_id,
  customer_id,
  segment,
  opened_date,
  CASE WHEN decision_date <= current_date() THEN decision_date END AS decided_date,
  CASE
    WHEN decision_date > current_date() THEN 'open'
    WHEN u_won < win_probability THEN 'won'
    ELSE 'lost'
  END AS status,
  CAST(
    CASE tier WHEN 'Top 10' THEN 20000000 WHEN 'Strategic' THEN 6000000 ELSE 1500000 END
    * (0.4 + u_value * 1.2)
    AS DECIMAL(18, 2)
  ) AS est_lifetime_value_usd
FROM decided
