-- What the admin group needs to edit agent settings in the client's Settings
-- page. The page writes as the signed-in admin, so Unity Catalog enforces
-- this even if the app's own group check were bypassed. The group must match
-- the client's ADMIN_GROUP (bundle variable admin_group).

GRANT USE CATALOG ON CATALOG `${catalog}` TO `${admins}`;
GRANT USE SCHEMA ON SCHEMA `${catalog}`.`${schema}` TO `${admins}`;
GRANT SELECT, MODIFY ON TABLE `${catalog}`.`${schema}`.agent_context_settings TO `${admins}`;
