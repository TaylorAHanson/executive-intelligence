#!/bin/bash
#
# Run the whole app locally: FastAPI on :8010, Vite on :5180.
#
#   ./dev.sh
#
# Self-healing by design — it creates the venv, installs anything missing, and
# frees the ports before starting. Running it twice in a row is safe.
#
# Server output goes to backend.log / frontend.log rather than this terminal, so
# that Ctrl+C stays responsive and the startup summary doesn't scroll away.
# READ THOSE FILES when something won't start.

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

# Deliberately uncommon ports. The obvious choices (8000/8001, 5173/5174) are
# what every other local app picks, and the port-clearing step below is happy to
# kill whatever it finds — so a collision means stomping on a different project's
# dev server. Change these if they clash with something of yours, and change the
# proxy target in vite.config.ts to match.
BACKEND_PORT=8010
FRONTEND_PORT=5180

cd "$(dirname "$0")" || exit 1

# --- Platform differences ----------------------------------------------------
#
# This script runs under Git Bash on Windows as well as macOS and Linux, and the
# three places they differ are all load-bearing:
#
#   1. A virtualenv puts its executables in `bin/` on Unix and `Scripts/` (with
#      `.exe`) on Windows. Hardcoding `venv/bin/python` is the single most common
#      reason this script fails on Windows, so nothing below hardcodes it.
#   2. The interpreter is `python3` on Unix. On Windows it is usually `python`,
#      and `python3` may exist as a Microsoft Store stub that prints nothing and
#      exits 0 — so a plain `command -v python3` test is not enough.
#   3. `lsof` does not exist on Windows; freeing a port needs netstat + taskkill.

# Locate an executable inside the venv, whichever layout it uses. Prints the
# path and returns 0, or returns 1 if the venv has no such executable yet.
venv_exe() {
    local name=$1 candidate
    for candidate in \
        "server/venv/bin/$name" \
        "server/venv/Scripts/$name.exe" \
        "server/venv/Scripts/$name"
    do
        [ -x "$candidate" ] && { printf '%s' "$candidate"; return 0; }
    done
    return 1
}

# Find an interpreter that is really Python 3. Asking it for its version rather
# than trusting the name is what rejects the Store stub, which satisfies
# `command -v` but cannot create a venv.
find_host_python() {
    local candidate major
    for candidate in python3 python; do
        command -v "$candidate" >/dev/null 2>&1 || continue
        major=$("$candidate" -c 'import sys; print(sys.version_info[0])' 2>/dev/null)
        [ "$major" = "3" ] && { printf '%s' "$candidate"; return 0; }
    done
    return 1
}

HOST_PYTHON=$(find_host_python)
if [ -z "$HOST_PYTHON" ]; then
    echo -e "${RED}✗ No working Python 3 found.${NC}"
    echo -e "${YELLOW}  Install Python 3.11+ and make sure 'python3' or 'python' runs it.${NC}"
    echo -e "${YELLOW}  On Windows, install from python.org rather than the Microsoft Store —${NC}"
    echo -e "${YELLOW}  the Store build ships a stub that cannot create virtual environments.${NC}"
    exit 1
fi

# Kill whatever is listening on a port, on either platform.
free_port() {
    local port=$1 pids pid
    if command -v lsof >/dev/null 2>&1; then
        # One PID per line, and a reloading uvicorn holds the port with two
        # processes — so this has to loop. Passing the whole multi-line string
        # to `kill` as one argument fails silently, and the only symptom is a
        # confusing "Address already in use" further down.
        pids=$(lsof -ti:"$port" 2>/dev/null)
    elif command -v netstat >/dev/null 2>&1; then
        # Windows. The PID is the last column of a LISTENING row; anchoring the
        # match to the end of the address avoids matching a longer port number.
        pids=$(netstat -ano 2>/dev/null \
            | awk -v p="$port" '/LISTENING/ && $2 ~ (":" p "$") { print $NF }' \
            | sort -u)
    else
        return 0
    fi

    [ -z "$pids" ] && return 0
    echo -e "${YELLOW}Freeing port $port (PID $(echo "$pids" | tr '\n' ' '))...${NC}"
    for pid in $pids; do
        # `//F` rather than `/F`: Git Bash rewrites a single leading slash as a
        # path. taskkill is absent on Unix, where kill does the job alone.
        taskkill //F //PID "$pid" >/dev/null 2>&1 || kill -9 "$pid" 2>/dev/null
    done
    sleep 1
}

cleanup() {
    echo -e "\n${YELLOW}Shutting down...${NC}"
    [ -n "$FRONTEND_PID" ] && kill "$FRONTEND_PID" 2>/dev/null
    [ -n "$BACKEND_PID" ] && kill "$BACKEND_PID" 2>/dev/null
    wait "$FRONTEND_PID" "$BACKEND_PID" 2>/dev/null
    echo -e "${GREEN}Stopped.${NC}"
    exit 0
}
trap cleanup SIGINT SIGTERM

# --- First-run setup helpers -------------------------------------------------
#
# A newcomer cloning this repo has no way to guess which workspace to point at,
# which CLI profile carries the login, or what a warehouse id looks like. Rather
# than printing "not authenticated" and leaving them to it, the functions below
# offer the choices that actually exist on their machine and write the answers
# into .env. Everything here is skipped once .env is populated, and skipped
# entirely when stdin is not a terminal (CI, or `./dev.sh &`).

# Write KEY=VALUE into .env, replacing any existing line, and export it so the
# servers started below inherit it. Done without `sed -i`, whose syntax differs
# between macOS and Linux.
set_env_var() {
    local key=$1 value=$2 tmp
    if [ -f .env ] && grep -q "^${key}=" .env; then
        tmp=$(mktemp)
        while IFS= read -r line || [ -n "$line" ]; do
            case "$line" in
                "${key}="*) printf '%s=%s\n' "$key" "$value" ;;
                *) printf '%s\n' "$line" ;;
            esac
        done < .env > "$tmp"
        mv "$tmp" .env
    else
        printf '%s=%s\n' "$key" "$value" >> .env
    fi
    export "${key}=${value}"
}

# Print "profile<TAB>host<TAB>valid|invalid" for each configured profile.
#
# This asks the CLI rather than parsing ~/.databrickscfg by hand. The file looked
# easy to read and was not: on Windows it is written with CRLF line endings, and
# the CLI locates it via USERPROFILE while Git Bash reports a different $HOME —
# so the hand-rolled parser found no profiles at all and the menu offered only
# "enter a different URL". Letting the CLI answer also reports validity for every
# profile in one call instead of one call each.
list_profiles() {
    databricks auth profiles -o json 2>/dev/null | "$HOST_PYTHON" -c '
import json, sys

raw = sys.stdin.read()
# The CLI can precede its JSON with warnings, so start at the first brace.
start = raw.find("{")
if start < 0:
    sys.exit(0)
try:
    data = json.loads(raw[start:])
except Exception:
    sys.exit(0)

for profile in data.get("profiles", []):
    name = (profile.get("name") or "").strip()
    host = (profile.get("host") or "").strip()
    if name and host:
        print("\t".join([name, host, "valid" if profile.get("valid") else "invalid"]))
'
}

# Does this profile currently hold a valid token?
#
# DATABRICKS_HOST is unset for the check on purpose. It is exported from .env a
# few lines below, and the CLI treats an env host that disagrees with the
# profile's host as a conflict — so a stale or trailing-slash value in .env makes
# a perfectly good login look broken, and the script then re-prompts for a
# workspace that was already configured.
profile_works() {
    ( unset DATABRICKS_HOST DATABRICKS_TOKEN
      databricks current-user me -p "$1" >/dev/null 2>&1 )
}

# Trim whitespace, a stray CR, and any trailing slash from a workspace URL. The
# trailing slash matters: it makes the host mismatch the profile's own value.
normalize_host() {
    printf '%s' "$1" | tr -d '\r' | sed -e 's#[[:space:]]##g' -e 's#/*$##'
}

choose_workspace() {
    local -a names hosts states
    local n=0

    while IFS=$'\t' read -r prof host state; do
        [ -z "$prof" ] && continue
        n=$((n + 1))
        names[$n]="$prof"
        hosts[$n]="$host"
        states[$n]="$state"
    done <<< "$(list_profiles)"

    echo -e "\n${CYAN}Which Databricks workspace should this app use?${NC}"
    if [ "$n" -eq 0 ]; then
        echo -e "${YELLOW}  (no CLI profiles found yet — option 1 sets one up)${NC}"
    fi
    for i in $(seq 1 $n); do
        if [ "${states[$i]}" = "valid" ]; then
            printf "  %2d) %-22s %s ${GREEN}(logged in)${NC}\n" "$i" "${names[$i]}" "${hosts[$i]}"
        else
            printf "  %2d) %-22s %s ${YELLOW}(needs login)${NC}\n" "$i" "${names[$i]}" "${hosts[$i]}"
        fi
    done
    printf "  %2d) enter a different workspace URL\n" $((n + 1))
    printf "  %2d) skip — the UI will load, but queries will fail\n" $((n + 2))

    local choice
    read -r -p "$(echo -e "${CYAN}Choice [1]: ${NC}")" choice
    choice=$(printf '%s' "${choice:-1}" | tr -d '\r[:space:]')

    local profile host
    if [ "$choice" = "$((n + 2))" ]; then
        echo -e "${YELLOW}Skipped. Run ./dev.sh again when you want to set this up.${NC}"
        return 1
    elif [ "$choice" = "$((n + 1))" ]; then
        read -r -p "$(echo -e "${CYAN}Workspace URL (https://...): ${NC}")" host
        host=$(normalize_host "$host")
        [ -z "$host" ] && { echo -e "${YELLOW}Nothing entered; skipping.${NC}"; return 1; }
        read -r -p "$(echo -e "${CYAN}Name for this profile [DEFAULT]: ${NC}")" profile
        profile=$(printf '%s' "${profile:-DEFAULT}" | tr -d '\r[:space:]')
    elif [ "$choice" -ge 1 ] 2>/dev/null && [ "$choice" -le "$n" ]; then
        profile="${names[$choice]}"
        host=$(normalize_host "${hosts[$choice]}")
    else
        echo -e "${YELLOW}Not a valid choice; skipping.${NC}"
        return 1
    fi

    # Log in only if the profile can't already answer. This opens a browser.
    if ! profile_works "$profile"; then
        echo -e "\n${CYAN}Logging in to ${host} — a browser window will open...${NC}"
        if ! databricks auth login --host "$host" -p "$profile"; then
            echo -e "${RED}✗ Login failed. Queries will fail until it succeeds.${NC}"
            return 1
        fi
    fi

    set_env_var DATABRICKS_HOST "$host"
    # The SDK needs to know WHICH profile holds the token; the host alone isn't
    # enough once there is more than one profile pointing at a workspace.
    set_env_var DATABRICKS_CONFIG_PROFILE "$profile"
    echo -e "${GREEN}✓ Using ${profile} (${host})${NC}"
    return 0
}

choose_warehouse() {
    local profile=${DATABRICKS_CONFIG_PROFILE:-DEFAULT}
    echo -e "\n${CYAN}Looking up SQL warehouses...${NC}"

    # Errors are shown rather than hidden. "No warehouses found" with the reason
    # swallowed sends people looking for a warehouse they already have, when the
    # actual cause was an expired token or a missing permission.
    local json errfile
    errfile=$(mktemp)
    json=$(databricks warehouses list -p "$profile" -o json 2>"$errfile")

    if [ -z "$json" ] || [ "$json" = "[]" ] || [ "$json" = "null" ]; then
        echo -e "${YELLOW}⚠ Could not list SQL warehouses.${NC}"
        if [ -s "$errfile" ]; then
            sed -e 's/^/    /' "$errfile" | head -n 4
        else
            echo -e "${YELLOW}    The workspace reported none. You may not have permission to${NC}"
            echo -e "${YELLOW}    list them even if you can use one.${NC}"
        fi
        echo -e "${CYAN}    Set it by hand in .env:${NC}"
        echo -e "${CYAN}      SQL_WAREHOUSE_ID=<id>${NC}"
        echo -e "${CYAN}    Find the id under SQL Warehouses → your warehouse →${NC}"
        echo -e "${CYAN}    Connection details → HTTP path (the part after the last '/').${NC}"
        rm -f "$errfile"
        return 1
    fi
    rm -f "$errfile"

    # Prefer a running warehouse: starting a stopped one costs the first query
    # a couple of minutes, which reads as the app hanging.
    local parsed
    parsed=$(printf '%s' "$json" | "$HOST_PYTHON" -c '
import json, sys
try:
    warehouses = json.load(sys.stdin)
except Exception:
    sys.exit(1)
warehouses.sort(key=lambda w: (w.get("state") != "RUNNING", w.get("name", "")))
for w in warehouses[:10]:
    print("\t".join([w.get("id", ""), w.get("name", "?"), w.get("state", "?")]))
') || { echo -e "${YELLOW}⚠ Could not read the warehouse list.${NC}"; return 1; }

    local -a ids
    local n=0
    echo -e "${CYAN}Which SQL warehouse should queries run on?${NC}"
    while IFS=$'\t' read -r id name state; do
        [ -z "$id" ] && continue
        n=$((n + 1))
        ids[$n]="$id"
        printf "  %2d) %-40s %s\n" "$n" "$name" "$state"
    done <<< "$parsed"

    [ "$n" -eq 0 ] && { echo -e "${YELLOW}⚠ No warehouses available.${NC}"; return 1; }

    local choice
    read -r -p "$(echo -e "${CYAN}Choice [1]: ${NC}")" choice
    choice=$(printf '%s' "${choice:-1}" | tr -d '\r[:space:]')
    if [ "$choice" -ge 1 ] 2>/dev/null && [ "$choice" -le "$n" ]; then
        set_env_var SQL_WAREHOUSE_ID "${ids[$choice]}"
        echo -e "${GREEN}✓ Warehouse set${NC}"
    else
        echo -e "${YELLOW}Skipped. Set SQL_WAREHOUSE_ID in .env when you need it.${NC}"
    fi
}

echo -e "${BLUE}╔══════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║  Executive Intelligence client — local   ║${NC}"
echo -e "${BLUE}╚══════════════════════════════════════════╝${NC}\n"

# --- Environment -------------------------------------------------------------

if [ ! -f ".env" ] && [ -f ".env.example" ]; then
    echo -e "${CYAN}First run — creating .env from .env.example...${NC}"
    cp .env.example .env
fi

# The root ../dev.sh passes the agent it started as AGENT_APP_URL, which must
# win over the value in .env.
AGENT_APP_URL_FROM_CALLER=${AGENT_APP_URL-}

if [ -f ".env" ]; then
    # Sourced with CR stripped. A .env saved by a Windows editor has CRLF line
    # endings, and sourcing it directly leaves a trailing \r on every value —
    # which turns DATABRICKS_HOST into a URL that looks right in the file and
    # fails to resolve, with nothing in the error to suggest why.
    ENV_TMP=$(mktemp)
    tr -d '\r' < .env > "$ENV_TMP"
    set -a
    # shellcheck disable=SC1091
    source "$ENV_TMP"
    set +a
    rm -f "$ENV_TMP"
    echo -e "${GREEN}✓ Loaded .env${NC}"
fi
if [ -n "$AGENT_APP_URL_FROM_CALLER" ]; then
    export AGENT_APP_URL="$AGENT_APP_URL_FROM_CALLER"
fi
[ -n "${AGENT_APP_URL:-}" ] && echo -e "${GREEN}✓ Tray calls the agent at ${AGENT_APP_URL}${NC}"

# The app authenticates as you via the Databricks CLI during local dev, so a
# missing or expired login has to be dealt with here — otherwise it surfaces
# later as a 401 from a button click, which is a much worse place to learn about it.
if [ -t 0 ]; then
    if [ -z "$DATABRICKS_HOST" ] || ! profile_works "${DATABRICKS_CONFIG_PROFILE:-DEFAULT}"; then
        choose_workspace && [ -z "$SQL_WAREHOUSE_ID" ] && choose_warehouse
        echo
    else
        echo -e "${GREEN}✓ Databricks authenticated (${DATABRICKS_CONFIG_PROFILE:-DEFAULT})${NC}"
        [ -z "$SQL_WAREHOUSE_ID" ] && choose_warehouse
    fi
else
    # Not a terminal, so there is nobody to answer a prompt. Say what's wrong
    # and carry on rather than hanging forever on a `read`.
    if ! databricks current-user me >/dev/null 2>&1; then
        echo -e "${YELLOW}⚠ Not logged in to Databricks, and no terminal to ask.${NC}"
        echo -e "${YELLOW}  Run ./dev.sh from a terminal to set this up interactively.${NC}"
    fi
fi

# --- Free the ports ----------------------------------------------------------

for port in $BACKEND_PORT $FRONTEND_PORT; do
    free_port "$port"
done

# --- Python environment ------------------------------------------------------

# Resolved by searching, never hardcoded — see "Platform differences" above.
VENV_PYTHON=$(venv_exe python || true)

# Treat a venv whose interpreter is missing or broken as no venv at all. This
# happens more than you'd expect — an interrupted create, or a Homebrew Python
# upgrade that leaves the symlinks pointing at a version that no longer exists.
if [ -d "server/venv" ] && { [ -z "$VENV_PYTHON" ] || ! "$VENV_PYTHON" --version >/dev/null 2>&1; }; then
    echo -e "${YELLOW}Virtual environment is broken. Recreating...${NC}"
    rm -rf server/venv
    VENV_PYTHON=""
fi

if [ ! -d "server/venv" ]; then
    echo -e "${CYAN}Creating virtual environment (server/venv)...${NC}"
    "$HOST_PYTHON" -m venv server/venv || {
        echo -e "${RED}✗ Could not create the virtual environment${NC}"
        exit 1
    }
    # Re-resolve: the layout depends on which platform just created it.
    VENV_PYTHON=$(venv_exe python || true)
    echo -e "${GREEN}✓ Virtual environment created${NC}"
fi

if [ -z "$VENV_PYTHON" ]; then
    echo -e "${RED}✗ Created server/venv but found no interpreter inside it.${NC}"
    echo -e "${YELLOW}  Looked for bin/python, Scripts/python.exe, and Scripts/python.${NC}"
    echo -e "${YELLOW}  Contents:${NC}"
    ls server/venv 2>/dev/null | sed 's/^/    /'
    exit 1
fi

# Check an import rather than a marker file, so a venv created before a
# dependency was added to requirements.txt still gets it installed.
if ! "$VENV_PYTHON" -c "import fastapi, uvicorn, databricks.sdk, psycopg2, pixeltable_pgserver" 2>/dev/null; then
    echo -e "${CYAN}Installing Python dependencies (first run takes a minute)...${NC}"
    "$VENV_PYTHON" -m pip install --upgrade pip >/dev/null 2>&1
    "$VENV_PYTHON" -m pip install -r requirements.txt -r requirements-dev.txt || { echo -e "${RED}✗ pip install failed${NC}"; exit 1; }
    echo -e "${GREEN}✓ Python dependencies installed${NC}"
else
    echo -e "${GREEN}✓ Python dependencies present${NC}"
fi

# The deployed app keeps Settings in its Lakebase. Locally the backend starts a
# bundled Postgres in .pgdata instead (server/database.py), unless .env points
# PGHOST somewhere else. Delete .pgdata to start over.
if [ -z "${PGHOST:-}" ]; then
    export LOCAL_POSTGRES_DIR="$PWD/.pgdata"
    echo -e "${GREEN}✓ App database: local Postgres in .pgdata${NC}"
fi

# --- Backend -----------------------------------------------------------------

echo -e "\n${GREEN}→ Starting backend...${NC}"
echo "=== Backend started at $(date) ===" > backend.log
# Absolute, because the next line changes directory. Run from server/ so the flat
# imports (`from routes import health`) resolve the same way they do in the
# deployed app, where PYTHONPATH includes server/.
VENV_PYTHON_ABS="$PWD/$VENV_PYTHON"
# `python -m uvicorn` rather than the uvicorn script, so there is one executable
# to locate instead of two — and the console script is named uvicorn.exe on
# Windows anyway.
(cd server && PYTHONUNBUFFERED=1 "$VENV_PYTHON_ABS" -m uvicorn main:app --reload --port $BACKEND_PORT >> ../backend.log 2>&1) &
BACKEND_PID=$!

sleep 3
if ! kill -0 $BACKEND_PID 2>/dev/null; then
    echo -e "${RED}✗ Backend failed to start. Last lines of backend.log:${NC}"
    tail -n 20 backend.log
    exit 1
fi

# --- Frontend ----------------------------------------------------------------

if ! command -v npm >/dev/null 2>&1; then
    echo -e "${RED}✗ npm not found. Install Node 20+ from https://nodejs.org${NC}"
    kill $BACKEND_PID 2>/dev/null
    exit 1
fi

# A node_modules directory that exists is not the same as one that works, which
# is the same trap as a venv directory with no interpreter in it. An interrupted
# or partly failed install leaves the directory in place with packages missing,
# and gating on `[ -d node_modules ]` alone means every later run skips the
# repair — so the tree stays broken indefinitely and the failure surfaces as
# Vite's "Cannot find module '@babel/types'", which reads like a code problem
# rather than an install problem.
#
# `npm ls --all` walks the whole tree without touching the network (~250ms) and
# exits non-zero on anything unmet. `--depth=0` is NOT sufficient: it validates
# only the top level and reports success while a transitive dependency is
# missing, which is exactly this case — @babel/types arrives via @babel/core,
# two levels below the @vitejs/plugin-react entry in package.json.
npm_tree_ok() {
    [ -d node_modules ] && npm ls --all >/dev/null 2>&1
}

if npm_tree_ok; then
    echo -e "${GREEN}✓ npm dependencies present${NC}"
else
    if [ -d node_modules ]; then
        echo -e "${YELLOW}npm dependencies are incomplete — reinstalling...${NC}"
    else
        echo -e "${CYAN}Installing npm dependencies...${NC}"
    fi
    npm install || {
        echo -e "${RED}✗ npm install failed${NC}"
        kill $BACKEND_PID 2>/dev/null
        exit 1
    }
    # npm can exit 0 having left the tree unsatisfiable, so confirm rather than
    # assume. Starting Vite on a broken tree only moves the error later, to a
    # place where it looks like the app's fault.
    if ! npm_tree_ok; then
        echo -e "${RED}✗ npm install succeeded but the tree is still incomplete:${NC}"
        npm ls --all 2>&1 | grep -iE "UNMET|missing|invalid" | head -n 5 | sed 's/^/    /'
        echo -e "${YELLOW}  Try: rm -rf node_modules && npm install${NC}"
        kill $BACKEND_PID 2>/dev/null
        exit 1
    fi
    echo -e "${GREEN}✓ npm dependencies installed${NC}"
fi

echo -e "${GREEN}→ Starting frontend...${NC}"
echo "=== Frontend started at $(date) ===" > frontend.log
npm run dev >> frontend.log 2>&1 &
FRONTEND_PID=$!

sleep 3
if ! kill -0 $FRONTEND_PID 2>/dev/null; then
    echo -e "${RED}✗ Frontend failed to start. Last lines of frontend.log:${NC}"
    tail -n 20 frontend.log
    kill $BACKEND_PID 2>/dev/null
    exit 1
fi

# --- Ready -------------------------------------------------------------------

echo -e "\n${GREEN}✓ Running${NC}\n"
echo -e "  ${CYAN}App:${NC}      ${BLUE}http://localhost:$FRONTEND_PORT${NC}   ← open this"
echo -e "  ${CYAN}API:${NC}      ${BLUE}http://localhost:$BACKEND_PORT${NC}"
echo -e "  ${CYAN}API docs:${NC} ${BLUE}http://localhost:$BACKEND_PORT/api/docs${NC}"
echo -e "\n  ${CYAN}Logs:${NC} tail -f backend.log frontend.log"
echo -e "\n${YELLOW}Press Ctrl+C to stop.${NC}\n"

wait $FRONTEND_PID $BACKEND_PID
