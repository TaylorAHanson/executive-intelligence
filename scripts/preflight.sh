#!/usr/bin/env bash
# Check that a workspace has what Executive Intelligence needs. Read-only.
#
#   scripts/preflight.sh -p <profile> --catalog <catalog> [--schema exec_intel] [--warehouse <id>]
#                        [--app exec-intel-app] [--before-deploy]
#
# Prints one line per check and exits 1 if any check FAILs. `deploy.sh` runs it
# with --before-deploy, which reports checks that only a deploy can satisfy
# (the app's user scopes, the agent grant) as WARN rather than FAIL.
#
# What it cannot check: whether each USER has SELECT on the views and CAN_USE
# on the warehouse. Those are per-user; see data/grants.sql.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROFILE="${DATABRICKS_CONFIG_PROFILE:-}"
CATALOG=""
SCHEMA="exec_intel"
WAREHOUSE=""
WAREHOUSE_NAME="Serverless Starter Warehouse"
CLIENT_APP="exec-intel-app"
BEFORE_DEPLOY=false
# Keep in step with DATA_OBJECTS in executive-intelligence-app/server/config/settings.py.
CONTRACT_VIEWS="v_customers v_shipments v_revenue_monthly v_design_wins v_pipeline v_revenue_outlook v_contracts v_device_footprint v_customer_signals v_insights"

usage() { sed -n '2,5p' "$0" | sed 's/^# \{0,1\}//'; exit "${1:-0}"; }

while [ $# -gt 0 ]; do
    case "$1" in
        -p|--profile) PROFILE="$2"; shift 2 ;;
        --catalog) CATALOG="$2"; shift 2 ;;
        --schema) SCHEMA="$2"; shift 2 ;;
        --warehouse) WAREHOUSE="$2"; shift 2 ;;
        --app) CLIENT_APP="$2"; shift 2 ;;
        --before-deploy) BEFORE_DEPLOY=true; shift ;;
        -h|--help) usage ;;
        *) echo "Unknown argument: $1" >&2; usage 1 ;;
    esac
done

[ -n "$PROFILE" ] || { echo "No profile. Pass -p <profile>." >&2; exit 1; }
[ -n "$CATALOG" ] || { echo "No catalog. Pass --catalog <catalog> (the data_catalog bundle variable)." >&2; exit 1; }

export AGENTBRICKS_DISABLE_AGENT_HINT=1
AGENT_DEPLOYMENT="$(python3 -c 'import sys, tomllib; print(tomllib.load(open(sys.argv[1], "rb"))["agent"]["deployment_name"])' "$ROOT/executive-intelligence-agent/agent.toml")"
AGENT_APP="agent-bricks-$AGENT_DEPLOYMENT"
# The agent's default model (agent/agent.py) is served by this endpoint.
MODEL_ENDPOINT="databricks-claude-sonnet-5-5"

FAILURES=0
report() {
    # report STATUS CHECK DETAIL
    local color
    case "$1" in
        PASS) color='\033[0;32m' ;;
        FAIL) color='\033[0;31m'; FAILURES=$((FAILURES + 1)) ;;
        *) color='\033[1;33m' ;;
    esac
    printf "${color}%-5s\033[0m %-34s %s\n" "$1" "$2" "$3"
}
# Checks a deploy fixes are warnings before one, failures after.
report_deployable() { if $BEFORE_DEPLOY; then report WARN "$@"; else report FAIL "$@"; fi; }

dbx() { databricks "$@" -p "$PROFILE" -o json 2>/dev/null; }
field() { python3 -c 'import json, sys
d = json.load(sys.stdin)
for k in sys.argv[1].split("."):
    d = d.get(k) if isinstance(d, dict) else None
print("" if d is None else (" ".join(d) if isinstance(d, list) else d))' "$1"; }

echo "Preflight for profile $PROFILE, data in $CATALOG.$SCHEMA"
echo

# --- Identity ------------------------------------------------------------------
if ME="$(dbx current-user me)"; then
    HOST="$(databricks auth env --profile "$PROFILE" 2>/dev/null | python3 -c 'import json, sys
print(json.load(sys.stdin).get("env", {}).get("DATABRICKS_HOST", "?"))' 2>/dev/null)"
    report PASS "CLI login" "$(echo "$ME" | field userName) on ${HOST:-?}"
else
    report FAIL "CLI login" "run: databricks auth login --profile $PROFILE"
    exit 1
fi

# --- Agent previews ------------------------------------------------------------
if ! command -v agentbricks >/dev/null; then
    report WARN "Agent Memory Sessions preview" "agentbricks CLI not installed; cannot check"
elif OUT="$(cd "$ROOT/executive-intelligence-agent" && agentbricks -p "$PROFILE" memory stores list 2>&1)"; then
    report PASS "Agent Memory Sessions preview" "memory store API answers"
elif echo "$OUT" | grep -qi "FEATURE_DISABLED\|not enabled"; then
    report FAIL "Agent Memory Sessions preview" "disabled: an admin enables it under profile menu > Previews"
else
    report FAIL "Agent Memory Sessions preview" "$(echo "$OUT" | tail -1 | cut -c1-90)"
fi

if [ "$(dbx serving-endpoints get "$MODEL_ENDPOINT" | field state.ready)" = "READY" ]; then
    report PASS "Agent model endpoint" "$MODEL_ENDPOINT is ready"
else
    report FAIL "Agent model endpoint" "$MODEL_ENDPOINT missing or not ready; change MODEL in agent/agent.py"
fi

# --- Warehouse -------------------------------------------------------------------
if [ -z "$WAREHOUSE" ]; then
    WAREHOUSE="$(dbx warehouses list | python3 -c 'import json, sys
name = sys.argv[1]
print(next((w["id"] for w in json.load(sys.stdin) if w["name"] == name), ""))' "$WAREHOUSE_NAME")"
fi
if [ -z "$WAREHOUSE" ]; then
    report FAIL "SQL warehouse" "no \"$WAREHOUSE_NAME\"; pass --warehouse <id> (and --var warehouse_id=<id> to deploy)"
elif WH="$(dbx warehouses get "$WAREHOUSE")"; then
    report PASS "SQL warehouse" "$(echo "$WH" | field name) ($WAREHOUSE), $(echo "$WH" | field state)"
else
    report FAIL "SQL warehouse" "$WAREHOUSE not found or not visible to you"
fi

# --- Data contract ---------------------------------------------------------------
if dbx catalogs get "$CATALOG" >/dev/null; then
    report PASS "Catalog" "$CATALOG"
    if dbx schemas get "$CATALOG.$SCHEMA" >/dev/null; then
        report PASS "Schema" "$CATALOG.$SCHEMA"
        for view in $CONTRACT_VIEWS; do
            if dbx tables get "$CATALOG.$SCHEMA.$view" >/dev/null; then
                report PASS "Contract view $view" "$(dbx tables get "$CATALOG.$SCHEMA.$view" | field table_type)"
            else
                report FAIL "Contract view $view" "missing; see data/contract.md (data/load.py creates synthetic ones)"
            fi
        done
    else
        report FAIL "Schema" "$CATALOG.$SCHEMA missing; data/load.py creates it"
    fi
else
    report FAIL "Catalog" "$CATALOG missing or not visible to you"
fi

# --- Agent tools and traces --------------------------------------------------------
# Genie space ids bound in agent.toml are workspace-specific.
AGENT_TOML="$ROOT/executive-intelligence-agent/agent.toml"
GENIE_SPACES="$(python3 -c 'import sys, tomllib
for t in tomllib.load(open(sys.argv[1], "rb")).get("tools", []):
    if t.get("source", {}).get("kind") == "genie_agent":
        print(t["id"], t["source"]["space_id"])' "$AGENT_TOML")"
while read -r TOOL_ID SPACE_ID; do
    [ -n "$SPACE_ID" ] || continue
    if SPACE="$(dbx genie get-space "$SPACE_ID")"; then
        report PASS "Genie space ($TOOL_ID)" "$(echo "$SPACE" | field title) ($SPACE_ID)"
    else
        report FAIL "Genie space ($TOOL_ID)" "$SPACE_ID not in this workspace; run data/genie.py and rebind (README step 7)"
    fi
done <<< "$GENIE_SPACES"

EXPERIMENT="$(python3 -c 'import sys, tomllib; print(tomllib.load(open(sys.argv[1], "rb"))["tracing"]["experiment_name"])' "$AGENT_TOML")"
TRACE_TABLES="$(dbx experiments get-by-name "$EXPERIMENT" | python3 -c 'import json, sys
tags = {t["key"]: t["value"] for t in json.load(sys.stdin).get("experiment", {}).get("tags", [])}
print(tags.get("mlflow.experiment.databricksTraceDestinationPath", ""))' 2>/dev/null)"
if [ -n "$TRACE_TABLES" ]; then
    report PASS "Trace storage" "$EXPERIMENT -> $TRACE_TABLES"
else
    report WARN "Trace storage" "$EXPERIMENT not linked to Unity Catalog; scripts/trace_storage.py (README step 8)"
fi

# --- Apps --------------------------------------------------------------------------
APP_JSON="$(dbx apps get "$CLIENT_APP")" || APP_JSON=""
CLIENT_SP=""
if [ -n "$APP_JSON" ]; then
    CLIENT_SP="$(echo "$APP_JSON" | field service_principal_client_id)"
    SCOPES="$(echo "$APP_JSON" | field effective_user_api_scopes)"
    case " $SCOPES " in
        *" sql "*) report PASS "User authorization (OBO)" "$CLIENT_APP has the sql scope" ;;
        *) report_deployable "User authorization (OBO)" "$CLIENT_APP lacks the sql scope: deploy, and ask an admin to enable user authorization for apps" ;;
    esac
else
    report WARN "User authorization (OBO)" "$CLIENT_APP not deployed yet; rerun after deploying"
fi

if dbx apps get "$AGENT_APP" >/dev/null; then
    if [ -n "$CLIENT_SP" ] && dbx apps get-permissions "$AGENT_APP" | grep -q "$CLIENT_SP"; then
        report PASS "Client may call agent" "$CLIENT_APP's service principal has access to $AGENT_APP"
    else
        report_deployable "Client may call agent" "no CAN_USE for $CLIENT_APP on $AGENT_APP; deploy.sh grants it"
    fi
    AGENT_SP="$(dbx apps get "$AGENT_APP" | field service_principal_client_id)"
    while read -r TOOL_ID SPACE_ID; do
        [ -n "$SPACE_ID" ] || continue
        if dbx permissions get genie "$SPACE_ID" | grep -q "$AGENT_SP"; then
            report PASS "Agent may use Genie ($TOOL_ID)" "$AGENT_APP's service principal has access"
        else
            report_deployable "Agent may use Genie ($TOOL_ID)" "run data/genie.py ... --grant-app $AGENT_APP (README step 11)"
        fi
    done <<< "$GENIE_SPACES"
else
    report_deployable "Agent app" "$AGENT_APP not deployed; ./deploy.sh deploys it"
fi

echo
if [ "$FAILURES" -gt 0 ]; then
    echo "$FAILURES check(s) failed."
    exit 1
fi
echo "All required checks passed."
