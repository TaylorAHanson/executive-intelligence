#!/usr/bin/env bash
# Deploy the Executive Intelligence agent and its client app, and connect them.
#
#   ./deploy.sh -p <profile> --var data_catalog=<catalog> [--var key=value ...]
#               [-t dev|prod] [--agent-only | --app-only] [--skip-preflight]
#
# --var is passed to the bundle (see `variables:` in databricks.yml) and may
# repeat. data_catalog is required; data_schema and warehouse_id have defaults.
# scripts/preflight.sh runs first and stops the deploy if the workspace is
# missing something the app needs.
#
# The two halves deploy with different tools, because no single one covers
# both:
#
#   agent   executive-intelligence-agent/  `agentbricks deploy`. It provisions
#           the memory, session, and runtime stores declared in agent.toml,
#           tracing, and the app's grants on them. Bundles have no resource type
#           for those, so the agent is not in databricks.yml.
#   client  executive-intelligence-app/    `databricks bundle deploy`, from the
#           bundle in ./databricks.yml.
#
# Then the client's service principal is granted CAN_USE on the agent app, which
# Databricks Apps requires for one app to call another.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AGENT_DIR="$ROOT/executive-intelligence-agent"
APP_DIR="$ROOT/executive-intelligence-app"

PROFILE="${DATABRICKS_CONFIG_PROFILE:-}"
TARGET="dev"
DEPLOY_AGENT=true
DEPLOY_APP=true
PREFLIGHT=true
VAR_ARGS=()
DATA_CATALOG=""
DATA_SCHEMA="exec_intel"
WAREHOUSE_ID=""

usage() { sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'; exit "${1:-0}"; }

while [ $# -gt 0 ]; do
    case "$1" in
        -p|--profile) PROFILE="$2"; shift 2 ;;
        -t|--target) TARGET="$2"; shift 2 ;;
        --var)
            case "$2" in
                *=*) ;;
                *) echo "--var takes key=value, got: $2" >&2; exit 1 ;;
            esac
            VAR_ARGS+=(--var "$2")
            case "$2" in
                data_catalog=*) DATA_CATALOG="${2#*=}" ;;
                data_schema=*) DATA_SCHEMA="${2#*=}" ;;
                warehouse_id=*) WAREHOUSE_ID="${2#*=}" ;;
            esac
            shift 2 ;;
        --agent-only) DEPLOY_APP=false; shift ;;
        --app-only) DEPLOY_AGENT=false; shift ;;
        --skip-preflight) PREFLIGHT=false; shift ;;
        -h|--help) usage ;;
        *) echo "Unknown argument: $1" >&2; usage 1 ;;
    esac
done

if [ -z "$PROFILE" ]; then
    echo "No profile. Pass -p <profile> (see \`databricks auth profiles\`) or set DATABRICKS_CONFIG_PROFILE." >&2
    exit 1
fi

if $DEPLOY_APP && [ -z "$DATA_CATALOG" ]; then
    echo "No data catalog. Pass --var data_catalog=<catalog>: the catalog holding the dashboard views (data/contract.md)." >&2
    exit 1
fi

for tool in databricks agentbricks npm python3; do
    command -v "$tool" >/dev/null || { echo "Missing required tool: $tool" >&2; exit 1; }
done

export AGENTBRICKS_DISABLE_AGENT_HINT=1
step() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }

json_field() {
    python3 -c 'import json, sys; print(json.load(sys.stdin)[sys.argv[1]])' "$1"
}

AGENT_DEPLOYMENT="$(python3 -c 'import sys, tomllib; print(tomllib.load(open(sys.argv[1], "rb"))["agent"]["deployment_name"])' "$AGENT_DIR/agent.toml")"
AGENT_APP="agent-bricks-$AGENT_DEPLOYMENT"

if $PREFLIGHT && $DEPLOY_APP; then
    step "Checking the workspace (scripts/preflight.sh)"
    PREFLIGHT_ARGS=(-p "$PROFILE" --catalog "$DATA_CATALOG" --schema "$DATA_SCHEMA" --before-deploy)
    [ -n "$WAREHOUSE_ID" ] && PREFLIGHT_ARGS+=(--warehouse "$WAREHOUSE_ID")
    "$ROOT/scripts/preflight.sh" "${PREFLIGHT_ARGS[@]}" \
        || { echo "Preflight failed; fix the FAIL lines above, or rerun with --skip-preflight." >&2; exit 1; }
fi

if $DEPLOY_AGENT; then
    step "Deploying agent $AGENT_APP (Agent Bricks CLI)"
    # --no-wait plus `deployments wait` instead of a foreground deploy, so the
    # frontend can build while the agent's compute starts.
    (cd "$AGENT_DIR" && agentbricks -p "$PROFILE" deploy --no-wait)
fi

if $DEPLOY_APP; then
    step "Building the client frontend"
    (
        cd "$APP_DIR"
        # `npm ls --all` fails on a missing transitive dependency, which a
        # directory check would miss. See executive-intelligence-app/AGENTS.md.
        npm ls --all >/dev/null 2>&1 || npm install --no-audit --no-fund
        npm run build
    )
fi

if $DEPLOY_AGENT; then
    step "Waiting for the agent to answer requests"
    while true; do
        set +e
        (cd "$AGENT_DIR" && agentbricks -p "$PROFILE" deployments wait "$AGENT_APP")
        status=$?
        set -e
        case "$status" in
            0) break ;;
            75) echo "Still deploying; waiting again..." ;;
            *) echo "Agent deploy failed (exit $status). See: agentbricks -p $PROFILE deployments logs $AGENT_APP" >&2
               exit "$status" ;;
        esac
    done
fi

if ! $DEPLOY_APP; then
    exit 0
fi

AGENT_URL="$(databricks apps get "$AGENT_APP" -p "$PROFILE" -o json | json_field url)"
if [ -z "$AGENT_URL" ] || [ "$AGENT_URL" = "None" ]; then
    echo "Agent app $AGENT_APP has no URL. Deploy the agent first (drop --app-only)." >&2
    exit 1
fi

# The `+` form: an empty array is "unbound" to bash 3.2 (macOS) under set -u.
BUNDLE_ARGS=(-p "$PROFILE" -t "$TARGET" --var "agent_app_url=$AGENT_URL" ${VAR_ARGS[@]+"${VAR_ARGS[@]}"})

step "Deploying the client app (Databricks Asset Bundle, target $TARGET)"
(cd "$ROOT" && databricks bundle deploy "${BUNDLE_ARGS[@]}")

CLIENT_APP="$(cd "$ROOT" && databricks bundle summary "${BUNDLE_ARGS[@]}" -o json \
    | python3 -c 'import json, sys; print(json.load(sys.stdin)["resources"]["apps"]["app"]["name"])')"
CLIENT_SP="$(databricks apps get "$CLIENT_APP" -p "$PROFILE" -o json | json_field service_principal_client_id)"

step "Granting $CLIENT_APP's service principal CAN_USE on $AGENT_APP"
# update-permissions adds to the agent app's ACL; it does not replace it.
databricks apps update-permissions "$AGENT_APP" -p "$PROFILE" --json "{
  \"access_control_list\": [
    {\"service_principal_name\": \"$CLIENT_SP\", \"permission_level\": \"CAN_USE\"}
  ]
}" >/dev/null

step "Starting the client app"
(cd "$ROOT" && databricks bundle run app "${BUNDLE_ARGS[@]}")

CLIENT_URL="$(databricks apps get "$CLIENT_APP" -p "$PROFILE" -o json | json_field url)"
step "Done"
echo "  Client app: $CLIENT_URL"
echo "  Agent app:  $AGENT_URL"
