-- Synthetic market and account intelligence (stands in for the unstructured
-- sources the RAG/MCP team will index: analyst reports, earnings calls, news,
-- account team notes), already reduced to one row per signal with a theme.
--
-- EVERY ROW IS INVENTED. The companies are fictional, and no row quotes or
-- paraphrases a real publication. Source names say "(synthetic)" so a
-- screenshot cannot be mistaken for real intelligence.
--
-- Each top-10 account gets its segment's two themes. Second-sourcing accounts
-- (top 10 with falling revenue) also get two cost-down signals, which are the
-- cause the Customer Intelligence briefing traces.

CREATE OR REPLACE TABLE `${catalog}`.`${schema}`.synthetic_customer_signals AS
WITH templates AS (
  SELECT * FROM VALUES
    ('Handset', 1, 'On-device AI', 'opportunity', 'Earnings call', 21,
      '{name} puts generative AI on its next flagship phones',
      'On its latest earnings call, {name} said its next flagship phones will run generative AI on the device instead of in the cloud, and that neural processing performance is now a top-three selection criterion.'),
    ('Handset', 2, 'Premium tier refresh', 'opportunity', 'Analyst report', 48,
      '{name} pulls its premium refresh forward a quarter',
      'An analyst note expects {name} to launch its premium phones a quarter earlier than last year, which brings its sourcing decisions into the coming quarter.'),
    ('Automotive', 1, 'Software-defined vehicles', 'opportunity', 'Analyst report', 30,
      '{name} moves vehicle software onto central compute',
      'An analyst report says {name} is replacing dozens of separate controllers with a central compute platform for its 2028 models, and will choose suppliers over the next two quarters.'),
    ('Automotive', 2, 'Cockpit consolidation', 'opportunity', 'News', 62,
      '{name} plans one digital cockpit across its lineup',
      '{name} announced a single digital cockpit platform for every trim level, replacing three supplier-specific designs.'),
    ('IoT', 1, 'Industrial edge AI', 'opportunity', 'News', 35,
      '{name} launches edge AI modules for factory inspection',
      '{name} launched a line of camera modules that run defect detection on the device, aimed at factories that cannot send video to the cloud.'),
    ('IoT', 2, 'On-device AI', 'opportunity', 'Analyst report', 70,
      '{name} bets on on-device vision',
      'An analyst report expects {name} to put vision AI in most of its modules within two years, which favors suppliers with low-power AI accelerators.'),
    ('XR', 1, 'Lightweight AR glasses', 'opportunity', 'News', 18,
      '{name} previews all-day AR glasses',
      '{name} previewed lightweight AR glasses designed for all-day wear, with launch planned for next year.'),
    ('XR', 2, 'On-device AI', 'opportunity', 'Earnings call', 55,
      '{name} wants its assistant to run without a phone',
      'On its earnings call, {name} said its headsets and glasses should run assistant features locally, without a tethered phone.'),
    ('Compute', 1, 'AI PCs', 'opportunity', 'Analyst report', 27,
      '{name} expects AI PCs to be half its laptops by 2028',
      'An analyst note says {name} plans for AI PCs to be half of its laptop shipments by 2028.'),
    ('Compute', 2, 'On-device AI', 'opportunity', 'Earnings call', 64,
      '{name} names battery life and AI performance as what buyers want',
      'On its earnings call, {name} said battery life and on-device AI performance are now the two criteria its enterprise buyers rank first.'),
    ('Networking', 1, 'Wi-Fi 7 rollout', 'opportunity', 'News', 24,
      '{name} moves its enterprise access points to Wi-Fi 7',
      '{name} said its next enterprise access points will all be Wi-Fi 7, starting with deliveries next year.'),
    ('Networking', 2, '5G fixed wireless', 'opportunity', 'Analyst report', 58,
      '{name} takes 5G home gateways into new markets',
      'An analyst report says {name} is expanding its 5G fixed wireless gateways into three new markets.'),
    ('second-sourcing', 1, 'Second sourcing', 'risk', 'Account team note', 14,
      '{name} is qualifying a second supplier',
      'The account team reports that {name} has started qualifying a second supplier for its next {line} designs, with a target of 12% lower bill-of-materials cost.'),
    ('second-sourcing', 2, 'Second sourcing', 'risk', 'News', 40,
      '{name} announces a cost-reduction program',
      '{name} announced a company-wide cost-reduction program that includes fewer suppliers and renegotiated component prices.')
  AS t(applies_to, slot, theme, direction, source_type, days_ago, headline, summary)
),
accounts AS (
  SELECT
    customer_id,
    customer_name,
    segment,
    monthly_growth < 0 AS second_sourcing,
    CASE segment
      WHEN 'Handset' THEN 'mobile platform'
      WHEN 'Automotive' THEN 'digital cockpit'
      WHEN 'IoT' THEN 'industrial IoT'
      WHEN 'XR' THEN 'XR platform'
      WHEN 'Compute' THEN 'PC platform'
      ELSE 'Wi-Fi 7'
    END AS line
  FROM `${catalog}`.`${schema}`.synthetic_customers
  WHERE tier = 'Top 10'
)
SELECT
  concat('SIG-', a.customer_id, '-', CASE WHEN t.applies_to = 'second-sourcing' THEN 'R' ELSE 'T' END, t.slot) AS signal_id,
  a.customer_id,
  t.theme,
  t.direction,
  replace(t.headline, '{name}', a.customer_name) AS headline,
  replace(replace(t.summary, '{name}', a.customer_name), '{line}', a.line) AS summary,
  t.source_type,
  CASE t.source_type
    WHEN 'Earnings call' THEN concat(a.customer_name, ' earnings call (synthetic)')
    WHEN 'Account team note' THEN 'Account team note (synthetic)'
    WHEN 'News' THEN 'Newswire (synthetic)'
    ELSE 'Analyst note (synthetic)'
  END AS source_name,
  CAST(NULL AS STRING) AS source_url,
  date_sub(current_date(), t.days_ago + CAST(abs(hash(a.customer_id, t.slot)) % 9 AS INT)) AS published_date
FROM accounts a
JOIN templates t ON t.applies_to = a.segment OR (t.applies_to = 'second-sourcing' AND a.second_sourcing)
