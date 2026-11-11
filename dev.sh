#!/usr/bin/env bash
# Run Executive Intelligence locally: the agent on :8000 and the client on :8010
# (API) and :5180 (open this), with the client's tray pointed at the local agent.
#
#   ./dev.sh [-p <profile>]              # local agent + client
#   ./dev.sh --deployed-agent [-p ...]   # client only; tray talks to the deployed agent
#   ./dev.sh --no-agent                  # client only; tray uses AGENT_APP_URL from .env
#
# The profile defaults to DATABRICKS_CONFIG_PROFILE in executive-intelligence-app/.env.
# The local agent has no Memory or Session Store (`agentbricks dev` keeps
# conversations in process); use --deployed-agent to test memory.
#
# The client is executive-intelligence-app/dev.sh, which reloads on save and
# can still be run on its own. The agent does not reload: Ctrl+C and rerun after
# changing it. Logs: executive-intelligence-agent/agent.log, and backend.log and
# frontend.log in executive-intelligence-app/.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AGENT_DIR="$ROOT/executive-intelligence-agent"
APP_DIR="$ROOT/executive-intelligence-app"
AGENT_APP="agent-bricks-exec-intel-agent"
AGENT_PORT=8000
AGENT_LOG="$AGENT_DIR/agent.log"
# The first run builds the agent's environment with uv, which takes a while.
AGENT_START_TIMEOUT=240

usage() { sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//'; exit "${1:-0}"; }

env_value() {
    [ -f "$APP_DIR/.env" ] && grep -E "^$1=" "$APP_DIR/.env" | tail -n 1 | cut -d= -f2- | tr -d '\r'
}

PROFILE="$(env_value DATABRICKS_CONFIG_PROFILE)"
AGENT_MODE=local
while [ $# -gt 0 ]; do
    case "$1" in
        -p|--profile) PROFILE="$2"; shift 2 ;;
        --deployed-agent) AGENT_MODE=deployed; shift ;;
        --no-agent) AGENT_MODE=none; shift ;;
        -h|--help) usage 0 ;;
        *) echo "Unknown option: $1" >&2; usage 1 ;;
    esac
done
PROFILE="${PROFILE:-DEFAULT}"

free_port() {
    local pids
    pids=$(lsof -ti:"$1" -sTCP:LISTEN 2>/dev/null)
    [ -z "$pids" ] && return 0
    echo "Freeing port $1 (PID $(echo "$pids" | tr '\n' ' '))"
    # One PID per line; kill takes each as its own argument.
    # shellcheck disable=SC2086
    kill $pids 2>/dev/null
    sleep 1
}

AGENT_PID=""
cleanup() {
    if [ -n "$AGENT_PID" ]; then
        # The agent runs in its own process group (set -m below), so this stops
        # agentbricks, the server it starts, and the local MLflow server together.
        kill -- "-$AGENT_PID" 2>/dev/null
        wait "$AGENT_PID" 2>/dev/null
        echo "Agent stopped."
    fi
}
trap cleanup EXIT

case "$AGENT_MODE" in
    local)
        command -v agentbricks >/dev/null 2>&1 || {
            echo "agentbricks not found. Install the Agent Bricks CLI, or run ./dev.sh --deployed-agent." >&2
            exit 1
        }
        free_port "$AGENT_PORT"
        echo "Starting the agent on :$AGENT_PORT with profile $PROFILE (log: ${AGENT_LOG#"$ROOT"/})"
        echo "=== Agent started at $(date) ===" > "$AGENT_LOG"
        set -m
        (cd "$AGENT_DIR" && exec agentbricks -p "$PROFILE" dev --app-port "$AGENT_PORT") >> "$AGENT_LOG" 2>&1 < /dev/null &
        AGENT_PID=$!
        set +m

        waited=0
        until [ "$(curl -s -o /dev/null -w '%{http_code}' "http://localhost:$AGENT_PORT/" 2>/dev/null)" != "000" ]; do
            if ! kill -0 "$AGENT_PID" 2>/dev/null; then
                echo "The agent exited before answering. Last lines of ${AGENT_LOG#"$ROOT"/}:" >&2
                tail -n 20 "$AGENT_LOG" >&2
                exit 1
            fi
            if [ "$waited" -ge "$AGENT_START_TIMEOUT" ]; then
                echo "The agent did not answer within ${AGENT_START_TIMEOUT}s. See ${AGENT_LOG#"$ROOT"/}." >&2
                exit 1
            fi
            sleep 2
            waited=$((waited + 2))
        done
        echo "Agent answering at http://localhost:$AGENT_PORT (chat UI and traces there too)"
        export AGENT_APP_URL="http://localhost:$AGENT_PORT"
        ;;
    deployed)
        AGENT_URL="$(databricks apps get "$AGENT_APP" -p "$PROFILE" -o json 2>/dev/null \
            | python3 -c 'import json, sys; print(json.load(sys.stdin).get("url") or "")' 2>/dev/null)"
        if [ -z "$AGENT_URL" ]; then
            echo "Could not find $AGENT_APP with profile $PROFILE. Deploy it with ./deploy.sh first." >&2
            exit 1
        fi
        echo "Tray will call the deployed agent at $AGENT_URL as your CLI login"
        export AGENT_APP_URL="$AGENT_URL"
        ;;
esac

# Not exec: the client's dev.sh exits on Ctrl+C, then the EXIT trap stops the agent.
"$APP_DIR/dev.sh"
