-- Agent context settings: each app context's prompt and tools, edited in the
-- client's Settings page and sent to the agent on every turn.
--
-- Like insight_records this is the system's own state, not a customer source
-- to remap. Keep this file when views.sql is replaced in another workspace.
-- Created only if missing, so reloading data never resets what admins chose.
--
-- Users need SELECT (grants.sql) for the tray to apply a context's settings;
-- only the admin group gets MODIFY (admin_grants.sql).

CREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.agent_context_settings (
  context_id STRING NOT NULL COMMENT 'An id from agent/contexts.py, e.g. customer-intelligence',
  prompt STRING COMMENT 'Replaces the context''s default prompt section; NULL keeps the default',
  tools STRING COMMENT 'JSON: {"builtin": [names] or null for the default, "genie": [{name, space_id, title, description}]}',
  updated_by STRING NOT NULL,
  updated_at TIMESTAMP NOT NULL
)
COMMENT 'Executive Intelligence agent settings per app context. Edited in the client app''s Settings page.';
