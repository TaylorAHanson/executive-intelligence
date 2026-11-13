#!/usr/bin/env python3
"""Write the Customer Intelligence insight records from the contract views.

    python data/insights.py -p <profile> --catalog <catalog> --schema <schema> --warehouse <id>

Also runs as load.py's `insights` step.

THIS IS A STAND-IN. The briefing's narrative is meant to come from the
signal-finding loop, which reads the sources, decides what changed and why, and
writes insight records. Until that exists, this script fills fixed English
templates from the contract views: no model, no judgment. Its rules are below
and deliberately simple:

- An account is "at risk" when it has a `risk` signal in the last 120 days.
- The focus theme is the `opportunity` theme the most top-10 accounts share.
- "Next quarter" is the calendar quarter after the current one.
- Every figure in a record is computed here from the views; nothing is typed in.

Because it reads only the contract views it runs unchanged on real data, but
its sentences will read oddly where real data does not match the templates'
assumptions (for example, no risk signals at all). Every record carries
generated_by = "template:data/insights.py" so the app and readers can tell.
"""
import argparse
import datetime
import json
import re
import sys
import time
from collections import defaultdict
from typing import Any, Optional

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import StatementParameterListItem, StatementState

from load import NAME_RE, TERMINAL

GENERATED_BY = "template:data/insights.py"
RISK_SIGNAL_DAYS = 120
TOP_N = 10

_SCHEMA = (
    "ARRAY<STRUCT<insight_id: STRING, scope: STRING, chapter: STRING, position: INT, title: STRING, "
    "body: STRING, cause: STRING, effect: STRING, action: STRING, owner: STRING, evidence: STRING>>"
)


# --- Reading -------------------------------------------------------------------


def query(client: WorkspaceClient, warehouse: str, sql: str, params: Optional[dict] = None) -> list[dict]:
    """Rows as dicts, numbers and dates converted by column type."""
    parameters = [StatementParameterListItem(name=k, value=str(v)) for k, v in (params or {}).items()]
    response = client.statement_execution.execute_statement(
        warehouse_id=warehouse, statement=sql, parameters=parameters or None, wait_timeout="50s"
    )
    while response.status.state not in TERMINAL:
        time.sleep(2)
        response = client.statement_execution.get_statement(response.statement_id)
    if response.status.state != StatementState.SUCCEEDED:
        message = response.status.error.message if response.status.error else response.status.state
        raise RuntimeError(f"{message}\n--- statement ---\n{sql}")
    columns = response.manifest.schema.columns
    out = []
    for raw in (response.result.data_array if response.result else None) or []:
        out.append({c.name: _convert(v, c.type_name.value if c.type_name else None) for c, v in zip(columns, raw)})
    return out


def _convert(value: Optional[str], type_name: Optional[str]) -> Any:
    if value is None:
        return None
    if type_name in {"INT", "LONG", "SHORT", "BYTE"}:
        return int(value)
    if type_name in {"DECIMAL", "DOUBLE", "FLOAT"}:
        return float(value)
    if type_name == "DATE":
        return datetime.date.fromisoformat(value)
    return value


def facts(client: WorkspaceClient, warehouse: str, catalog: str, schema: str) -> dict:
    s = f"`{catalog}`.`{schema}`"
    accounts = query(client, warehouse, f"""
        WITH b AS (SELECT trunc(current_date(), 'MM') AS m, add_months(trunc(current_date(), 'QUARTER'), 3) AS q),
        rev AS (
          SELECT customer_id,
            SUM(CASE WHEN month >= add_months(b.m, -12) THEN revenue_usd END) AS revenue_12m,
            SUM(CASE WHEN month < add_months(b.m, -12) THEN revenue_usd END) AS revenue_prior_12m
          FROM {s}.v_revenue_monthly CROSS JOIN b
          WHERE month >= add_months(b.m, -24) AND month < b.m
          GROUP BY customer_id),
        outlook AS (
          SELECT customer_id,
            SUM(CASE WHEN month >= add_months(b.m, -12) AND month < b.m THEN plan_usd END) AS plan_12m,
            SUM(CASE WHEN month >= b.q AND month < add_months(b.q, 3) THEN plan_usd END) AS nq_plan,
            SUM(CASE WHEN month >= b.q AND month < add_months(b.q, 3) THEN commit_usd END) AS nq_commit,
            SUM(CASE WHEN month >= b.q AND month < add_months(b.q, 3) THEN best_case_usd END) AS nq_best
          FROM {s}.v_revenue_outlook CROSS JOIN b
          GROUP BY customer_id),
        fp AS (
          SELECT customer_id, quarter, SUM(device_models) AS models, SUM(device_models_with_us) AS with_us
          FROM {s}.v_device_footprint GROUP BY customer_id, quarter),
        latest AS (SELECT MAX(quarter) AS q FROM {s}.v_device_footprint),
        share AS (
          SELECT fp.customer_id,
            SUM(CASE WHEN fp.quarter = latest.q THEN with_us END) AS with_us_now,
            SUM(CASE WHEN fp.quarter = latest.q THEN models END) AS models_now,
            SUM(CASE WHEN fp.quarter = add_months(latest.q, -12) THEN with_us END) AS with_us_year_ago,
            SUM(CASE WHEN fp.quarter = add_months(latest.q, -12) THEN models END) AS models_year_ago
          FROM fp CROSS JOIN latest GROUP BY fp.customer_id)
        SELECT c.customer_id, c.customer_name, c.segment, c.region,
          rev.revenue_12m, rev.revenue_prior_12m, outlook.plan_12m, outlook.nq_plan, outlook.nq_commit, outlook.nq_best,
          share.with_us_now, share.models_now, share.with_us_year_ago, share.models_year_ago
        FROM {s}.v_customers c
        LEFT JOIN rev USING (customer_id)
        LEFT JOIN outlook USING (customer_id)
        LEFT JOIN share USING (customer_id)
        WHERE c.tier = 'Top 10'
        ORDER BY rev.revenue_12m DESC NULLS LAST
        LIMIT {TOP_N}""")
    ids = [a["customer_id"] for a in accounts]
    id_list = ",".join(ids)
    signals = query(client, warehouse, f"""
        SELECT signal_id, customer_id, theme, direction, headline, source_name, published_date
        FROM {s}.v_customer_signals
        WHERE array_contains(split(:ids, ','), customer_id)
        ORDER BY published_date DESC""", {"ids": id_list})
    contracts = query(client, warehouse, f"""
        SELECT contract_id, customer_id, contract_type, end_date, annual_value_usd, status
        FROM {s}.v_contracts
        WHERE array_contains(split(:ids, ','), customer_id) AND end_date >= current_date()
        ORDER BY end_date""", {"ids": id_list})
    deals = query(client, warehouse, f"""
        WITH b AS (SELECT add_months(trunc(current_date(), 'QUARTER'), 3) AS q)
        SELECT opportunity_id, customer_id, product_line, stage, forecast_category, amount_usd, close_date
        FROM {s}.v_pipeline CROSS JOIN b
        WHERE array_contains(split(:ids, ','), customer_id)
          AND stage IN ('Lead', 'Qualified', 'Proposal', 'Commit')
          AND close_date >= b.q AND close_date < add_months(b.q, 3)
        ORDER BY amount_usd DESC""", {"ids": id_list})
    return {"accounts": accounts, "signals": signals, "contracts": contracts, "deals": deals}


# --- Formatting ----------------------------------------------------------------


def money(value: Optional[float]) -> str:
    if value is None:
        return "n/a"
    sign = "-" if value < 0 else ""
    value = abs(value)
    if value >= 1e9:
        return f"{sign}${value / 1e9:.1f}B"
    if value >= 1e7:
        return f"{sign}${value / 1e6:.0f}M"
    if value >= 1e6:
        return f"{sign}${value / 1e6:.1f}M"
    return f"{sign}${value / 1e3:.0f}K"


def a_money(value: Optional[float]) -> str:
    """Money with its article: "a $54M", "an $817M"."""
    text = money(value)
    digits = text.lstrip("-$")
    an = digits.startswith("8") or re.match(r"1[18](\.\d)?[KMB]$", digits)
    return f"{'an' if an else 'a'} {text}"


def pct(part: Optional[float], whole: Optional[float]) -> Optional[int]:
    return round(part / whole * 100) if part is not None and whole else None


def day(value: datetime.date) -> str:
    return f"{value:%b} {value.day}"


def number(n: int) -> str:
    words = ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten")
    return words[n] if 0 <= n < len(words) else str(n)


def phrase(theme: str) -> str:
    """A theme as it reads mid-sentence: "On-device AI" -> "on-device AI", "Wi-Fi 7" unchanged."""
    first, _, rest = theme.partition(" ")
    if re.fullmatch(r"[A-Z][a-z]+(-[a-z]+)*", first):
        first = first.lower()
    return f"{first} {rest}".strip()


def possessive(name: str) -> str:
    return f"{name}'" if name.endswith("s") else f"{name}'s"


def points(delta: int) -> str:
    if delta == 0:
        return "unchanged from a year ago"
    return f"{'up' if delta > 0 else 'down'} {abs(delta)} point{'s' if abs(delta) != 1 else ''} from a year ago"


def names(items: list[str]) -> str:
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def quarter_label(today: datetime.date) -> str:
    index = today.year * 4 + (today.month - 1) // 3 + 1
    return f"Q{index % 4 + 1} {index // 4}"


def evidence(*items: tuple[str, str, str]) -> str:
    return json.dumps([{"kind": kind, "ref": ref, "label": label} for kind, ref, label in items])


def signal_evidence(signal: dict) -> tuple[str, str, str]:
    return ("signal", signal["signal_id"], f"{signal['source_name']}, {day(signal['published_date'])}: {signal['headline']}")


# --- Templates -----------------------------------------------------------------


def build(f: dict, today: datetime.date) -> list[dict]:
    accounts = f["accounts"]
    by_id = {a["customer_id"]: a for a in accounts}
    signals = defaultdict(list)
    for sig in f["signals"]:
        signals[sig["customer_id"]].append(sig)
    contracts = defaultdict(list)
    for c in f["contracts"]:
        contracts[c["customer_id"]].append(c)
    deals = defaultdict(list)
    for d in f["deals"]:
        deals[d["customer_id"]].append(d)

    cutoff = today - datetime.timedelta(days=RISK_SIGNAL_DAYS)
    risk_ids = [
        a["customer_id"]
        for a in accounts
        if any(s["direction"] == "risk" and s["published_date"] >= cutoff for s in signals[a["customer_id"]])
    ]
    steady_ids = [a["customer_id"] for a in accounts if a["customer_id"] not in risk_ids]

    theme_accounts: dict[str, list[str]] = defaultdict(list)
    for a in accounts:
        for theme in dict.fromkeys(s["theme"] for s in signals[a["customer_id"]] if s["direction"] == "opportunity"):
            theme_accounts[theme].append(a["customer_id"])
    focus_theme, focus_ids = max(theme_accounts.items(), key=lambda kv: len(kv[1]), default=("", []))

    def total(ids: list[str], key: str) -> float:
        return sum(by_id[i][key] or 0 for i in ids)

    next_q = quarter_label(today)
    all_ids = [a["customer_id"] for a in accounts]
    records: list[dict] = []

    def add(scope: str, chapter: str, position: int, body: str, **extra: str) -> None:
        records.append({
            "insight_id": f"{scope}-{chapter}-{position}",
            "scope": scope,
            "chapter": chapter,
            "position": position,
            "title": extra.get("title"),
            "body": body or None,
            "cause": extra.get("cause"),
            "effect": extra.get("effect"),
            "action": extra.get("action"),
            "owner": extra.get("owner"),
            "evidence": extra.get("evidence"),
        })

    # Portfolio: the top-10 briefing.
    plan, commit, best = (total(all_ids, k) for k in ("nq_plan", "nq_commit", "nq_best"))
    gap = plan - commit
    risk_gap = total(risk_ids, "nq_plan") - total(risk_ids, "nq_commit")
    steady_gap = total(steady_ids, "nq_plan") - total(steady_ids, "nq_commit")
    att_12m = pct(total(all_ids, "revenue_12m"), total(all_ids, "plan_12m"))
    risk_names = [by_id[i]["customer_name"] for i in risk_ids]
    risk_share_now = pct(total(risk_ids, "with_us_now"), total(risk_ids, "models_now"))
    risk_share_then = pct(total(risk_ids, "with_us_year_ago"), total(risk_ids, "models_year_ago"))
    risk_att = pct(total(risk_ids, "revenue_12m"), total(risk_ids, "plan_12m"))
    steady_att = pct(total(steady_ids, "revenue_12m"), total(steady_ids, "plan_12m"))
    count_word = number(len(risk_ids))
    # Risk accounts in renewal order, soonest first.
    risk_ids.sort(key=lambda i: contracts[i][0]["end_date"] if contracts[i] else datetime.date.max)
    risk_names = [by_id[i]["customer_name"] for i in risk_ids]

    if risk_ids and gap > 0:
        explains = "explain all of it" if risk_gap >= gap else f"explain {money(risk_gap)} of it"
        headline = (
            f"The top 10 are at **{att_12m}% of plan** this year, but {next_q} commit is **{money(gap)} short**, "
            f"and {count_word} accounts qualifying second suppliers {explains}."
        )
    elif gap > 0:
        headline = f"The top 10 are at **{att_12m}% of plan** this year, and {next_q} commit is **{money(gap)} short** of plan."
    else:
        headline = f"The top 10 are at **{att_12m}% of plan** this year, and {next_q} commit is **{money(-gap)} ahead** of plan."
    add("portfolio", "headline", 1, headline)

    know = f"**{number(len(focus_ids)).capitalize()} of the top {len(accounts)}** are building toward {phrase(focus_theme)}, where our position is strongest."
    if risk_ids:
        know += f" The risk is narrower: **{names(risk_names)}** are cutting cost and qualifying second suppliers."
    add("portfolio", "know", 1, know)

    if risk_ids:
        measure = (
            f"Where customers are second-sourcing, it already shows: our share of their new devices fell from "
            f"**{risk_share_then}% to {risk_share_now}%** in a year, and they are at **{risk_att}% of plan**. "
            f"The other {number(len(steady_ids))} are at **{steady_att}%**."
        )
    else:
        measure = f"Revenue across the top 10 is at **{att_12m}% of plan** over the last 12 months."
    add("portfolio", "measure", 1, measure)

    anticipate = f"{next_q} commit is **{money(commit)} against {a_money(plan)} plan**."
    if risk_ids:
        over_under = f"**{money(-steady_gap)} over**" if steady_gap < 0 else f"**{money(steady_gap)} under**"
        anticipate += (
            f" The {count_word} second-sourcing accounts are **{money(risk_gap)} under** their plan; "
            f"the other {number(len(steady_ids))} are {over_under}."
        )
    anticipate += f" Best case reaches **{money(best)}**."
    add("portfolio", "anticipate", 1, anticipate)

    position = 1
    if risk_ids:
        renewals = []
        refs = []
        for i in risk_ids:
            first = contracts[i][0] if contracts[i] else None
            if first:
                renewals.append(f"{by_id[i]['customer_name']} ({day(first['end_date'])})")
                refs.append(("contract", first["contract_id"], f"{by_id[i]['customer_name']}: {first['contract_type']} ends {day(first['end_date'])}"))
            risk_signal = next(s for s in signals[i] if s["direction"] == "risk")
            refs.insert(0, signal_evidence(risk_signal))
        add(
            "portfolio", "act", position, "",
            title=f"Defend {names(risk_names)} before their renewals",
            cause=(
                f"All {count_word} are qualifying second suppliers to cut cost." if len(risk_ids) > 2
                else "Both are qualifying second suppliers to cut cost." if len(risk_ids) == 2
                else "It is qualifying a second supplier to cut cost."
            ),
            effect=f"Our share of their new devices fell from {risk_share_then}% to {risk_share_now}%, and they are {money(risk_gap)} below plan for {next_q}.",
            action=f"Put an executive sponsor on each renewal, {names(renewals)}, with multi-year volume pricing offered before the second supplier qualifies.",
            owner="Sales leadership, with each account GM",
            evidence=evidence(*refs),
        )
        position += 1

    # One entry per account and product line, so two deals for the same product read as one.
    by_product = defaultdict(list)
    for i in focus_ids:
        if i not in risk_ids:
            for d in deals[i]:
                by_product[(i, d["product_line"])].append(d)
    focus_groups = sorted(by_product.values(), key=lambda g: -sum(d["amount_usd"] for d in g))[:3]
    focus_deals = [d for group in focus_groups for d in group]
    if focus_theme and focus_deals:
        focus_names = [by_id[i]["customer_name"] for i in focus_ids if i not in risk_ids]
        open_total = sum(d["amount_usd"] for i in focus_ids if i not in risk_ids for d in deals[i])
        deal_text = names([
            f"{by_id[g[0]['customer_id']]['customer_name']} {g[0]['product_line']} "
            f"({f'{len(g)} deals, ' if len(g) > 1 else ''}{money(sum(d['amount_usd'] for d in g))})"
            for g in focus_groups
        ])
        theme_signal = next(s for i in focus_ids for s in signals[i] if s["theme"] == focus_theme)
        add(
            "portfolio", "act", position, "",
            title=f"Put our best engineers on {phrase(focus_theme)} deals",
            cause=f"{number(len(focus_ids)).capitalize()} of the top {len(accounts)} say {phrase(focus_theme)} decides their next designs.",
            effect=(
                f"{money(open_total)} of first-year revenue at {names(focus_names)} is decided in {next_q}"
                + (", more than the second-sourcing gap." if risk_ids and open_total >= risk_gap
                   else ", the biggest lever for growth beyond plan.")
            ),
            action=f"Prioritize engineering support on the largest: {deal_text}.",
            owner="Sales leadership",
            evidence=evidence(signal_evidence(theme_signal), *(
                ("opportunity", d["opportunity_id"], f"{by_id[d['customer_id']]['customer_name']}: {d['product_line']}, {d['stage']}, closes {day(d['close_date'])}")
                for d in focus_deals
            )),
        )
        position += 1

    if gap > 0:
        add(
            "portfolio", "act", position, "",
            title=f"Forecast {next_q} at commit, not plan",
            cause=f"Commit is {money(gap)} below plan{', concentrated in the second-sourcing accounts' if risk_ids else ''}.",
            effect=f"Planning at plan overstates {next_q} revenue by {pct(gap, commit)}%.",
            action=f"Plan at {money(commit)} with {money(best - commit)} of upside, and revisit after the first renewal closes.",
            owner="Finance (FP&A)",
            evidence=evidence(("metric", "nq_commit", f"{next_q} commit {money(commit)}, plan {money(plan)}, best case {money(best)}")),
        )

    # One briefing per account.
    for a in accounts:
        i = a["customer_id"]
        name = a["customer_name"]
        att = pct(a["revenue_12m"], a["plan_12m"])
        growth = pct((a["revenue_12m"] or 0) - (a["revenue_prior_12m"] or 0), a["revenue_prior_12m"])
        share_now = pct(a["with_us_now"], a["models_now"])
        share_then = pct(a["with_us_year_ago"], a["models_year_ago"])
        nq_gap = (a["nq_plan"] or 0) - (a["nq_commit"] or 0)
        own_signals = signals[i]
        risk_signal = next((s for s in own_signals if s["direction"] == "risk"), None)
        opp_signal = next((s for s in own_signals if s["direction"] == "opportunity"), None)
        theme = opp_signal["theme"] if opp_signal else None
        renewal = contracts[i][0] if contracts[i] else None
        top_deal = deals[i][0] if deals[i] else None
        open_total = sum(d["amount_usd"] for d in deals[i])

        if i in risk_ids and risk_signal:
            headline = (
                f"{risk_signal['headline']}, and our share of its new devices fell from "
                f"**{share_then}% to {share_now}%** in a year."
            )
            if renewal:
                headline += f" Its {renewal['contract_type'].lower()} ends on **{day(renewal['end_date'])}**."
        elif att is not None and att >= 105:
            headline = f"{name} is at **{att}% of plan** and growing **{growth}%** a year" + (f", led by {phrase(theme)}." if theme else ".")
        else:
            direction = "up" if (growth or 0) >= 0 else "down"
            headline = f"{name} is at **{att}% of plan**, with revenue {direction} **{abs(growth or 0)}%** over the last 12 months."
        add(i, "headline", 1, headline)

        if risk_signal:
            know = f"**Cost is now {possessive(name)} priority**"
            know += f", even though its roadmap still centers on {phrase(theme)}." if theme else "."
            know += " Our pitch has to be total cost, not features."
        elif theme:
            know = f"{possessive(name)} next designs will be decided on **{phrase(theme)}**. That is where our roadmap has to land."
        else:
            know = f"No recent market or account signals for {name}."
        add(i, "know", 1, know)

        share_text = points((share_now or 0) - (share_then or 0))
        add(i, "measure", 1, f"Revenue is at **{att}% of plan** over the last 12 months, and **{share_now}%** of its new devices use our products, {share_text}.")

        nq_pct = pct(-nq_gap, a["nq_plan"]) or 0
        anticipate = f"{next_q} commit is **{money(a['nq_commit'])} against {a_money(a['nq_plan'])} plan**"
        anticipate += f", {abs(nq_pct)}% {'above' if nq_pct > 0 else 'below'}." if nq_pct else ", on plan."
        if deals[i]:
            anticipate += f" {len(deals[i])} open deal{'s' if len(deals[i]) != 1 else ''} worth **{money(open_total)}** close in {next_q}."
        add(i, "anticipate", 1, anticipate)

        if risk_signal:
            refs = [signal_evidence(risk_signal)]
            renewal_text = ""
            if renewal:
                refs.append(("contract", renewal["contract_id"], f"{renewal['contract_type']} ends {day(renewal['end_date'])}, {money(renewal['annual_value_usd'])} a year"))
                renewal_text = f" tied to the {renewal['contract_type'].lower()} renewal ({day(renewal['end_date'])})"
            add(
                i, "act", 1, "",
                title="Put an executive sponsor on the renewal",
                cause=f"{risk_signal['headline']}.",
                effect=f"Our share of its new devices fell from {share_then}% to {share_now}%, and {next_q} commit is {money(nq_gap)} below plan.",
                action=f"Offer multi-year volume pricing{renewal_text}, and bring the {phrase(theme) if theme else 'product'} roadmap to its engineering leads.",
                owner="Account GM, with sales leadership",
                evidence=evidence(*refs),
            )
        elif top_deal:
            refs = [signal_evidence(opp_signal)] if opp_signal else []
            refs.append(("opportunity", top_deal["opportunity_id"], f"{top_deal['product_line']}, {top_deal['stage']}, closes {day(top_deal['close_date'])}"))
            add(
                i, "act", 1, "",
                title=f"Lead with {phrase(theme)}" if theme else "Close the largest open deal",
                cause=f"{opp_signal['headline']}." if opp_signal else f"{name} has {money(open_total)} of pipeline closing in {next_q}.",
                effect=f"Its largest open deal, {top_deal['product_line']} ({money(top_deal['amount_usd'])}), closes on {day(top_deal['close_date'])}.",
                action=f"Bring the {phrase(theme) if theme else 'product'} roadmap and engineering support to that deal before it closes.",
                owner="Account GM",
                evidence=evidence(*refs),
            )
    return records


# --- Writing -------------------------------------------------------------------


def generate(client: WorkspaceClient, warehouse: str, catalog: str, schema: str) -> int:
    """Replace every insight record with freshly generated ones. Returns how many."""
    records = build(facts(client, warehouse, catalog, schema), datetime.date.today())
    query(
        client,
        warehouse,
        f"""INSERT OVERWRITE `{catalog}`.`{schema}`.insight_records
        SELECT r.insight_id, r.scope, r.chapter, r.position, r.title, r.body, r.cause, r.effect, r.action,
          r.owner, r.evidence, current_timestamp(), :generated_by
        FROM (SELECT inline(from_json(:records, '{_SCHEMA}'))) r""",
        {"records": json.dumps(records), "generated_by": GENERATED_BY},
    )
    return len(records)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("-p", "--profile", required=True, help="Databricks CLI profile")
    parser.add_argument("--catalog", required=True)
    parser.add_argument("--schema", required=True)
    parser.add_argument("--warehouse", required=True, help="SQL warehouse id")
    parser.add_argument("--dry-run", action="store_true", help="Print the records instead of writing them")
    args = parser.parse_args()
    for label, value in (("--catalog", args.catalog), ("--schema", args.schema)):
        if not NAME_RE.match(value):
            parser.error(f"{label} must be letters, digits, underscores, and hyphens only.")

    client = WorkspaceClient(profile=args.profile)
    if args.dry_run:
        for record in build(facts(client, args.warehouse, args.catalog, args.schema), datetime.date.today()):
            print(json.dumps({k: v for k, v in record.items() if v}, indent=2))
        return 0
    print(f"Wrote {generate(client, args.warehouse, args.catalog, args.schema)} insight records.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
