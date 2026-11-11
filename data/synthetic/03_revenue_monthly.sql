-- Synthetic recognized revenue: shipment value by customer and month. Real
-- recognized revenue comes from finance and differs from invoiced shipments;
-- here they agree, which is enough to exercise the dashboards.

CREATE OR REPLACE TABLE `${catalog}`.`${schema}`.synthetic_revenue_monthly AS
SELECT
  trunc(ship_date, 'MM') AS month,
  customer_id,
  CAST(SUM(revenue_usd) AS DECIMAL(18, 2)) AS revenue_usd
FROM `${catalog}`.`${schema}`.synthetic_shipments
GROUP BY trunc(ship_date, 'MM'), customer_id
