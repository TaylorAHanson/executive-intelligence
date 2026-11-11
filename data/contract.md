# Dashboard data contract

The client app's dashboards read only the views below, all in one catalog and schema set by the
app's `DATA_CATALOG` and `DATA_SCHEMA` (bundle variables `data_catalog` and `data_schema`). No
dashboard query names a table directly.

That makes the views the boundary between the app and a workspace's data:

- **In this repo's dev workspace**, the views sit over synthetic tables that
  [`load.py`](load.py) generates (`synthetic_*`, in the same schema).
- **In another workspace**, create views with these names and columns over that workspace's real
  tables. The app needs no code change; set the two variables and redeploy.

Before showing any of it to a customer, read [What is not real](#what-is-not-real).

Column names and types are the contract. A view may carry extra columns, but must not rename or
retype these. Where a column's meaning is a business definition (what counts as "on time", which
revenue is recognized), the definition below is what the dashboards assume; map the real data to
it in the view rather than changing the queries.

The app's queries run as the signed-in user, so each user needs `SELECT` on these views (not on
the tables beneath them) plus `USE CATALOG` and `USE SCHEMA`. [`grants.sql`](grants.sql) grants
exactly that to one group.

## `v_customers`

One row per customer account.

| Column | Type | Meaning |
|---|---|---|
| `customer_id` | STRING | Stable account id. Joins every other view. |
| `customer_name` | STRING | Display name. |
| `region` | STRING | Sales region. Drives the dashboards' region filter. |
| `segment` | STRING | Market segment (e.g. Handset, Automotive). |
| `tier` | STRING | `Top 10`, `Strategic`, or `Core`. |

## `v_shipments`

One row per shipment to a customer.

| Column | Type | Meaning |
|---|---|---|
| `shipment_id` | STRING | Unique per shipment. |
| `customer_id` | STRING | The receiving customer. |
| `ship_date` | DATE | Date shipped. Periods filter on this. |
| `units` | BIGINT | Units in the shipment. |
| `revenue_usd` | DECIMAL(18,2) | Invoiced value of the shipment. |
| `on_time` | BOOLEAN | Delivered on or before the committed date. |
| `in_full` | BOOLEAN | Delivered the full committed quantity. |

OTIF (on time in full) is the share of shipments where both `on_time` and `in_full` are true.

## `v_revenue_monthly`

Recognized revenue per customer per month. Kept separate from shipments because finance's
recognized revenue usually differs from invoiced shipment value; map it to the finance source.

| Column | Type | Meaning |
|---|---|---|
| `month` | DATE | First day of the month. |
| `customer_id` | STRING | The customer. |
| `revenue_usd` | DECIMAL(18,2) | Revenue recognized in that month. |

## `v_design_wins`

One row per design-win opportunity.

| Column | Type | Meaning |
|---|---|---|
| `opportunity_id` | STRING | Unique per opportunity. |
| `customer_id` | STRING | The customer. |
| `segment` | STRING | Segment of the design. |
| `opened_date` | DATE | Date the opportunity opened. |
| `decided_date` | DATE | Date it was won or lost; NULL while open. Periods filter on this. |
| `status` | STRING | `won`, `lost`, or `open` (lowercase). |
| `est_lifetime_value_usd` | DECIMAL(18,2) | Estimated lifetime revenue if won. |

Design-win conversion is `won / (won + lost)` over opportunities decided in the period.

## Customer Intelligence views

The six views below feed Customer Intelligence (the top-10 briefing and the per-account page) and
its Genie space, [`genie/customer.json`](genie/customer.json). The first five stand in for
customer source systems; the source named under each is a guess at where that data lives, and
needs confirming with the customer. `v_insights` is different: it is
this system's own output, not a source to remap (see below).

Customer Intelligence covers only accounts with `tier = 'Top 10'` in `v_customers`, so that tier
must name the accounts sales and finance leadership actually review.

### `v_pipeline`

One row per sales opportunity. Source: **Salesforce** (Opportunity), possibly with the
customer's own opportunity scores.

| Column | Type | Meaning |
|---|---|---|
| `opportunity_id` | STRING | Unique per opportunity. |
| `customer_id` | STRING | The customer. |
| `product_line` | STRING | What is being sold (e.g. `Infotainment`, `Wi-Fi 7`). |
| `stage` | STRING | `Lead`, `Qualified`, `Proposal`, `Commit` (open), or `Closed Won`, `Closed Lost`, `Disqualified` (closed). |
| `forecast_category` | STRING | `Pipeline`, `Best Case`, `Commit`, `Closed`, or `Omitted`. |
| `amount_usd` | DECIMAL(18,2) | First-year revenue the opportunity adds if won. |
| `created_date` | DATE | Date the opportunity was created. Leads count on this. |
| `close_date` | DATE | Expected close date while open; actual close date once closed. |

Lead-to-win conversion is `Closed Won / (Closed Won + Closed Lost + Disqualified)` over
opportunities with `close_date` in the period. Leads are opportunities with `created_date` in the
period. Map the customer's own stage names to these seven in the view.

### `v_revenue_outlook`

Plan and forecast per customer per month. Source: **finance** (the FP&A plan and the sales
forecast roll-up).

| Column | Type | Meaning |
|---|---|---|
| `month` | DATE | First day of the month. |
| `customer_id` | STRING | The customer. |
| `plan_usd` | DECIMAL(18,2) | Revenue in the annual operating plan for that month. |
| `commit_usd` | DECIMAL(18,2) | Committed forecast. NULL for months already closed. |
| `best_case_usd` | DECIMAL(18,2) | Best-case forecast, at least `commit_usd`. NULL for months already closed. |

Plan attainment is `v_revenue_monthly` revenue divided by `plan_usd` over the same customers and
months. The forecast shown is for the next calendar quarter.

### `v_contracts`

One row per customer contract. Source: **contract management system**.

| Column | Type | Meaning |
|---|---|---|
| `contract_id` | STRING | Unique per contract. |
| `customer_id` | STRING | The customer. |
| `contract_type` | STRING | E.g. `Master supply agreement`, `Volume pricing agreement`, `Software license`. |
| `start_date` | DATE | Start of the current term. |
| `end_date` | DATE | End of the current term. The briefing flags contracts ending within 120 days. |
| `annual_value_usd` | DECIMAL(18,2) | Annual contract value. |
| `status` | STRING | E.g. `Active`, `Renewal in negotiation`. Shown as is. |

### `v_device_footprint`

Customer device models and how many use our products, per quarter. Source: **device database**.

| Column | Type | Meaning |
|---|---|---|
| `quarter` | DATE | First day of the quarter. |
| `customer_id` | STRING | The customer. |
| `product_line` | STRING | The device category. |
| `device_models` | INT | Device models the customer launched or had in development that quarter. |
| `device_models_with_us` | INT | Of those, models using our products. |

Device share is `device_models_with_us / device_models`. The briefing compares the latest quarter
with the same quarter a year earlier.

### `v_customer_signals`

One row per piece of market or account intelligence, already reduced to a theme. Source: **MI
data**, the unstructured sources (analyst reports, earnings calls, news, account-team notes) that
the RAG/MCP pipeline is meant to index. That pipeline does not exist yet; something has to turn
documents into these rows (see "What is not real").

| Column | Type | Meaning |
|---|---|---|
| `signal_id` | STRING | Unique per signal. |
| `customer_id` | STRING | The customer it is about. |
| `theme` | STRING | Short theme shared across accounts (e.g. `On-device AI`, `Second sourcing`). The briefing groups by it. |
| `direction` | STRING | `opportunity` or `risk`. |
| `headline` | STRING | One-line statement of the signal. |
| `summary` | STRING | Two or three sentences. |
| `source_type` | STRING | E.g. `Earnings call`, `Analyst report`, `News`, `Account team note`. |
| `source_name` | STRING | The publication or document, shown as the citation. |
| `source_url` | STRING | Link to the source; NULL when there is none. |
| `published_date` | DATE | Date of the source. |

An account is **at risk** when it has a `risk` signal published in the last 120 days.

### `v_insights`

The briefing's narrative: one row per sentence-level insight or recommendation. Created by
[`views/insights.sql`](views/insights.sql) over the table `insight_records`, which
[`insights.py`](insights.py) writes. Keep both files when `views.sql` is replaced.

| Column | Type | Meaning |
|---|---|---|
| `insight_id` | STRING | Unique per record. |
| `scope` | STRING | `portfolio` for the top-10 briefing, or a `customer_id`. |
| `chapter` | STRING | `headline`, `know`, `measure`, `anticipate`, or `act`. |
| `position` | INT | Order within the chapter. |
| `title` | STRING | Recommendation title (act records). |
| `body` | STRING | Prose; `**bold**` marks figures. |
| `cause`, `effect`, `action` | STRING | A recommendation's "Because", "Which means", and "So we". |
| `owner` | STRING | Who should act. |
| `evidence` | STRING | JSON array of `{kind, ref, label}` naming the rows the insight rests on. |
| `generated_at` | TIMESTAMP | When it was written. |
| `generated_by` | STRING | What wrote it, e.g. `template:data/insights.py`. The page shows it. |

## What is not real

Everything below is a placeholder in this repo's dev workspace. Each item says what has to happen
before a customer sees it.

**Data**

- **Every `synthetic_*` table is invented**, including the 60 companies, their names, revenue,
  plans, forecasts, opportunities, contracts, and device counts. The app's header shows a
  "Synthetic data" badge while the bundle variable `synthetic_data` is `"true"` (the default). Set
  `--var synthetic_data=false` only once every view reads real tables.
- **Every signal is invented.** No row in `synthetic_customer_signals` quotes or paraphrases a real
  publication. `source_name` ends in "(synthetic)" and `source_url` is NULL, so the page shows no
  links. Real signals need real source names and URLs.
- **The story is built into the data.** The three "second-sourcing" accounts (top 10 with falling
  revenue: C003, C007, C010) were given risk signals, falling device share, MSAs ending in 40 to
  130 days, lower recent win rates, and a forecast decaying 4% a month, so that cause and effect
  line up. Real data will not line up this neatly, and the narrative has to say so when it doesn't.
- **Plan and forecast rules are invented.** Plan is the same month a year earlier plus 12% (top 10)
  or 8%; commit and best case follow a year-over-year trend. Replace with the customer's FP&A plan
  and forecast.
- **Source systems are assumed.** Salesforce, a contract management system, a device database,
  the FP&A plan, and market-intelligence documents are guesses. Confirm which system owns each
  view, and who owns the mapping.

**Definitions to confirm with sales and finance leadership**

- The top 10 is whatever `tier = 'Top 10'` says.
- At risk means a `risk` signal in the last 120 days. Finance may want a revenue or forecast rule.
- Conversion counts `Disqualified` as a loss.
- The forecast quarter is the next calendar quarter, not the customer's fiscal quarter.
- A contract ending within 120 days is flagged; a device-share fall of more than 10 points in a
  year is shown in red.
- The "focus theme" is the opportunity theme the most top-10 accounts share.

**Narrative**

- **Templates, not the signal-finding loop.** [`insights.py`](insights.py) fills fixed sentences
  from the views; nothing reasons about the data and no person reviews it. The page footer says
  so. Some templates assume the synthetic story: they call every at-risk account
  "second-sourcing", and say its device share "fell" and its commit is "below plan" without
  checking the sign. Rerun `insights.py --dry-run` on real data and read every sentence before
  showing it. The
  signal-finding loop (architecture.md section 9) should replace it, writing the same records with
  its own `generated_by`.
- **Records go stale.** `insights.py` runs only when `load.py` does. Schedule it (or the loop)
  after the source views refresh.

**Agent and app**

- No RAG or MCP retrieval over market-intelligence documents is built; the agent reads only the signal rows.
- The agent's `send_message` tool is a stub and sends nothing.

## Adding a view

1. Document it here.
2. Add its synthetic table to `synthetic/` and its view to `views/views.sql`.
3. Add it to `grants.sql`.
4. Add its name to `DATA_OBJECTS` in `executive-intelligence-app/server/config/settings.py`, which
   refuses any other name, and to `CONTRACT_VIEWS` in `scripts/preflight.sh`.
