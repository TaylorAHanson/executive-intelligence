-- What a dashboard user needs. The app queries as the signed-in user, so these
-- go to the users' group, not to the app's service principal.
--
-- SELECT is on the views only. A view reads its tables with its owner's
-- rights, so users never need access to the tables beneath.
--
-- Users also need CAN_USE on the app's SQL warehouse; that is a warehouse
-- permission, not a grant, and is set in the warehouse's Permissions dialog.

GRANT USE CATALOG ON CATALOG `${catalog}` TO `${group}`;
GRANT USE SCHEMA ON SCHEMA `${catalog}`.`${schema}` TO `${group}`;
GRANT SELECT ON VIEW `${catalog}`.`${schema}`.v_customers TO `${group}`;
GRANT SELECT ON VIEW `${catalog}`.`${schema}`.v_shipments TO `${group}`;
GRANT SELECT ON VIEW `${catalog}`.`${schema}`.v_revenue_monthly TO `${group}`;
GRANT SELECT ON VIEW `${catalog}`.`${schema}`.v_design_wins TO `${group}`;
GRANT SELECT ON VIEW `${catalog}`.`${schema}`.v_pipeline TO `${group}`;
GRANT SELECT ON VIEW `${catalog}`.`${schema}`.v_revenue_outlook TO `${group}`;
GRANT SELECT ON VIEW `${catalog}`.`${schema}`.v_contracts TO `${group}`;
GRANT SELECT ON VIEW `${catalog}`.`${schema}`.v_device_footprint TO `${group}`;
GRANT SELECT ON VIEW `${catalog}`.`${schema}`.v_customer_signals TO `${group}`;
GRANT SELECT ON VIEW `${catalog}`.`${schema}`.v_insights TO `${group}`;
-- The tray reads the current context's agent settings as the user.
GRANT SELECT ON TABLE `${catalog}`.`${schema}`.agent_context_settings TO `${group}`;
