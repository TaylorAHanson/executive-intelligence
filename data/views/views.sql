-- The contract views (contract.md) over the synthetic tables.
--
-- In another workspace, replace this file's SELECTs with ones over that
-- workspace's tables, keeping the view names, column names, and types.

CREATE OR REPLACE VIEW `${catalog}`.`${schema}`.v_customers
COMMENT 'Dashboard data contract: customers. See data/contract.md.'
AS SELECT customer_id, customer_name, region, segment, tier
FROM `${catalog}`.`${schema}`.synthetic_customers;

CREATE OR REPLACE VIEW `${catalog}`.`${schema}`.v_shipments
COMMENT 'Dashboard data contract: shipments. See data/contract.md.'
AS SELECT shipment_id, customer_id, ship_date, units, revenue_usd, on_time, in_full
FROM `${catalog}`.`${schema}`.synthetic_shipments;

CREATE OR REPLACE VIEW `${catalog}`.`${schema}`.v_revenue_monthly
COMMENT 'Dashboard data contract: recognized revenue by customer and month. See data/contract.md.'
AS SELECT month, customer_id, revenue_usd
FROM `${catalog}`.`${schema}`.synthetic_revenue_monthly;

CREATE OR REPLACE VIEW `${catalog}`.`${schema}`.v_design_wins
COMMENT 'Dashboard data contract: design-win opportunities. See data/contract.md.'
AS SELECT opportunity_id, customer_id, segment, opened_date, decided_date, status, est_lifetime_value_usd
FROM `${catalog}`.`${schema}`.synthetic_design_wins;

-- Customer Intelligence sources. Each stands in for one system in the
-- Market Intelligence plan; contract.md names the system.

CREATE OR REPLACE VIEW `${catalog}`.`${schema}`.v_pipeline
COMMENT 'Dashboard data contract: sales opportunities (Salesforce). See data/contract.md.'
AS SELECT opportunity_id, customer_id, product_line, stage, forecast_category, amount_usd, created_date, close_date
FROM `${catalog}`.`${schema}`.synthetic_pipeline;

CREATE OR REPLACE VIEW `${catalog}`.`${schema}`.v_revenue_outlook
COMMENT 'Dashboard data contract: finance plan and forecast by customer and month. See data/contract.md.'
AS SELECT month, customer_id, plan_usd, commit_usd, best_case_usd
FROM `${catalog}`.`${schema}`.synthetic_revenue_outlook;

CREATE OR REPLACE VIEW `${catalog}`.`${schema}`.v_contracts
COMMENT 'Dashboard data contract: customer contracts (contract management system). See data/contract.md.'
AS SELECT contract_id, customer_id, contract_type, start_date, end_date, annual_value_usd, status
FROM `${catalog}`.`${schema}`.synthetic_contracts;

CREATE OR REPLACE VIEW `${catalog}`.`${schema}`.v_device_footprint
COMMENT 'Dashboard data contract: customer device models using our products, by quarter (device database). See data/contract.md.'
AS SELECT quarter, customer_id, product_line, device_models, device_models_with_us
FROM `${catalog}`.`${schema}`.synthetic_device_footprint;

CREATE OR REPLACE VIEW `${catalog}`.`${schema}`.v_customer_signals
COMMENT 'Dashboard data contract: themed market and account intelligence per customer. See data/contract.md.'
AS SELECT signal_id, customer_id, theme, direction, headline, summary, source_type, source_name, source_url, published_date
FROM `${catalog}`.`${schema}`.synthetic_customer_signals;
