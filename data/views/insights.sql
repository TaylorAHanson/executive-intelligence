-- Insight records: the narrative the Customer Intelligence briefing shows.
--
-- Unlike the other views this is not a customer source to remap. It is this
-- system's own output, written by data/insights.py today (templates filled
-- from the contract views) and by the signal-finding loop later. Keep this
-- file when views.sql is replaced in another workspace.

CREATE TABLE IF NOT EXISTS `${catalog}`.`${schema}`.insight_records (
  insight_id STRING NOT NULL,
  scope STRING NOT NULL COMMENT '"portfolio" for the top-10 briefing, or a customer_id',
  chapter STRING NOT NULL COMMENT 'headline, know, measure, anticipate, or act',
  position INT NOT NULL COMMENT 'Order within the chapter',
  title STRING,
  body STRING COMMENT 'Prose; may use **bold** for figures',
  cause STRING,
  effect STRING,
  action STRING,
  owner STRING,
  evidence STRING COMMENT 'JSON array of {kind, ref, label}',
  generated_at TIMESTAMP NOT NULL,
  generated_by STRING NOT NULL COMMENT 'What wrote the record, e.g. template:data/insights.py'
)
COMMENT 'Customer Intelligence insight records. Written by data/insights.py until the signal loop replaces it.';

CREATE OR REPLACE VIEW `${catalog}`.`${schema}`.v_insights
COMMENT 'Dashboard data contract: Customer Intelligence insight records. See data/contract.md.'
AS SELECT insight_id, scope, chapter, position, title, body, cause, effect, action, owner, evidence, generated_at, generated_by
FROM `${catalog}`.`${schema}`.insight_records;
