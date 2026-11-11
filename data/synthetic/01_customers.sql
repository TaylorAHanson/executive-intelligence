-- Synthetic customers. 60 accounts: 10 "Top 10", 15 "Strategic", 35 "Core".
--
-- Randomness comes from hash() of stable inputs rather than rand(), so every
-- run produces the same customers. The generator columns after `tier`
-- (revenue scale, growth, OTIF baseline, risk flag) drive the other synthetic
-- tables and are not part of the contract: v_customers leaves them out.
--
-- Three accounts (C003, C007, C018) are seeded "at risk": their OTIF drops and
-- revenue declines over the last six months, so the dashboards and the agent
-- have something real to find.

CREATE OR REPLACE TABLE `${catalog}`.`${schema}`.synthetic_customers AS
WITH base AS (
  SELECT
    id + 1 AS n,
    (abs(hash(id, 'revenue')) % 10000) / 10000.0 AS u_revenue,
    (abs(hash(id, 'growth')) % 10000) / 10000.0 AS u_growth,
    (abs(hash(id, 'otif')) % 10000) / 10000.0 AS u_otif
  FROM range(60)
)
SELECT
  format_string('C%03d', n) AS customer_id,
  concat(
    element_at(
      array('Apex', 'Nimbus', 'Vertex', 'Orion', 'Helix', 'Quantum', 'Summit', 'Atlas',
            'Nova', 'Pioneer', 'Zenith', 'Cobalt', 'Lumen', 'Strata', 'Vanguard'),
      CAST(n % 15 AS INT) + 1),
    ' ',
    element_at(
      array('Mobile', 'Automotive', 'Devices', 'Systems', 'Networks', 'Electronics', 'Labs', 'Technologies'),
      CAST((n * 7) % 8 AS INT) + 1)
  ) AS customer_name,
  element_at(
    array('North America', 'Europe', 'Greater China', 'Asia Pacific', 'Japan & Korea', 'India'),
    CAST((n * 5) % 6 AS INT) + 1) AS region,
  element_at(
    array('Handset', 'Automotive', 'IoT', 'Compute', 'XR', 'Networking'),
    CAST((n * 11 + 3) % 6 AS INT) + 1) AS segment,
  CASE WHEN n <= 10 THEN 'Top 10' WHEN n <= 25 THEN 'Strategic' ELSE 'Core' END AS tier,
  -- Monthly revenue at the start of the history, in USD.
  CASE
    WHEN n <= 10 THEN 8000000 + u_revenue * 17000000
    WHEN n <= 25 THEN 1500000 + u_revenue * 3500000
    ELSE 200000 + u_revenue * 1000000
  END AS base_monthly_revenue,
  -- Month-over-month growth, -1% to +2%.
  -0.01 + u_growth * 0.03 AS monthly_growth,
  CASE WHEN n <= 10 THEN 10 WHEN n <= 25 THEN 7 ELSE 4 END AS shipments_per_month,
  0.90 + u_otif * 0.08 AS otif_baseline,
  n IN (3, 7, 18) AS at_risk
FROM base
