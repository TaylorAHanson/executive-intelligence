"""Tests for insights.py's templates, on hand-made facts. No workspace needed.

    executive-intelligence-app/server/venv/bin/python data/test_insights.py
"""
import datetime
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import insights  # noqa: E402

passed = 0
failed = 0


def check(description: str, condition: bool) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  ok   {description}")
    else:
        failed += 1
        print(f"  FAIL {description}")


TODAY = datetime.date(2026, 11, 11)


def account(cid, name, revenue, plan, nq_plan, nq_commit, share_now=(8, 10), share_then=(8, 10)):
    return {
        "customer_id": cid, "customer_name": name, "segment": "Handset", "region": "Europe",
        "revenue_12m": revenue, "revenue_prior_12m": revenue * 0.9, "plan_12m": plan,
        "nq_plan": nq_plan, "nq_commit": nq_commit, "nq_best": nq_commit * 1.05,
        "with_us_now": share_now[0], "models_now": share_now[1],
        "with_us_year_ago": share_then[0], "models_year_ago": share_then[1],
    }


def signal(sid, cid, theme, direction, headline, days_ago):
    return {
        "signal_id": sid, "customer_id": cid, "theme": theme, "direction": direction, "headline": headline,
        "source_name": "Newswire (synthetic)", "published_date": TODAY - datetime.timedelta(days=days_ago),
    }


facts = {
    "accounts": [
        account("C1", "Acme Systems", 120e6, 100e6, 30e6, 33e6),
        account("C2", "Bolt Devices", 80e6, 100e6, 30e6, 20e6, share_now=(4, 10), share_then=(8, 10)),
    ],
    "signals": [
        signal("S1", "C1", "On-device AI", "opportunity", "Acme Systems bets on on-device AI", 10),
        signal("S2", "C2", "On-device AI", "opportunity", "Bolt Devices wants AI phones", 20),
        signal("S3", "C2", "Cost-down & second sourcing", "risk", "Bolt Devices is qualifying a second supplier", 5),
    ],
    "contracts": [
        {"contract_id": "K2", "customer_id": "C2", "contract_type": "Master supply agreement",
         "end_date": datetime.date(2027, 1, 24), "annual_value_usd": 50e6, "status": "Renewal in negotiation"},
    ],
    "deals": [
        {"opportunity_id": "O1", "customer_id": "C1", "product_line": "Mobile platform", "stage": "Proposal",
         "forecast_category": "Best Case", "amount_usd": 12e6, "close_date": datetime.date(2027, 2, 10)},
    ],
}

records = insights.build(facts, TODAY)
by_id = {r["insight_id"]: r for r in records}

print("\nPortfolio")
headline = by_id["portfolio-headline-1"]["body"]
check("the headline states the gap to plan", "**$7.0M short**" in headline)
check("and that the risk account explains all of it", "explain all of it" in headline)
check("next quarter is named", "Q1 2027" in headline)
check("the focus theme keeps its capitals", "on-device AI" in by_id["portfolio-know-1"]["body"])
defend = by_id["portfolio-act-1"]
check("the first action defends the at-risk account", defend["title"].startswith("Defend Bolt Devices"))
check("naming its renewal date", "Bolt Devices (Jan 24)" in defend["action"])
check("with an owner", defend["owner"])
check("its evidence is JSON naming the signal and contract", [e["ref"] for e in json.loads(defend["evidence"])] == ["S3", "K2"])
growth = by_id["portfolio-act-2"]
check("the growth action is about the focus theme", "on-device AI" in growth["title"])
check("and only claims to cover the gap when it does", "more than the second-sourcing gap" in growth["effect"])

print("\nAccounts")
check("an at-risk account leads with its risk", by_id["C2-headline-1"]["body"].startswith("Bolt Devices is qualifying a second supplier"))
check("and its share change", "**80% to 40%**" in by_id["C2-headline-1"]["body"])
check("a growing account leads with plan attainment", "**120% of plan**" in by_id["C1-headline-1"]["body"])
check("possessives drop the extra s", "Bolt Devices' priority" in by_id["C2-know-1"]["body"])
check("share changes read in words", "down 40 points from a year ago" in by_id["C2-measure-1"]["body"])
check("every account has an action", {"C1-act-1", "C2-act-1"} <= set(by_id))
check("records carry no empty bodies", all(r["body"] is None or r["body"] for r in records))

print("\nDeals")
more = {**facts, "deals": facts["deals"] + [{**facts["deals"][0], "opportunity_id": "O2", "amount_usd": 5e6}]}
growth_action = {r["insight_id"]: r for r in insights.build(more, TODAY)}["portfolio-act-2"]["action"]
check("two deals for one product read as one", growth_action.count("Mobile platform") == 1 and "2 deals, $17M" in growth_action)
check("a single deal is named plainly", "Acme Systems Mobile platform ($12M)" in by_id["portfolio-act-2"]["action"])

print("\nFormatting")
check("money: millions", insights.money(54e6) == "$54M")
check("money: small millions keep a decimal", insights.money(2.34e6) == "$2.3M")
check("money: billions", insights.money(1.25e9) == "$1.2B")
check("an $817M, a $54M", insights.a_money(817e6) == "an $817M" and insights.a_money(54e6) == "a $54M")
check("an $18M, a $1.8M", insights.a_money(18e6) == "an $18M" and insights.a_money(1.8e6) == "a $1.8M")
check("Wi-Fi keeps its capitals", insights.phrase("Wi-Fi 7 rollout") == "Wi-Fi 7 rollout")
check("AI PCs keeps its capitals", insights.phrase("AI PCs") == "AI PCs")
check("a quarter label from November", insights.quarter_label(TODAY) == "Q1 2027")
check("a quarter label from May", insights.quarter_label(datetime.date(2026, 5, 1)) == "Q3 2026")

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
