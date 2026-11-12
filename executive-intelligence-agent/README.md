# Executive Intelligence agent

Built from the Agent Bricks LangGraph template. One deployment serves every section of the client app
in `../executive-intelligence-app`; see [App contexts](#app-contexts) and `../architecture.md`.

A LangGraph agent served by `databricks_agentkit.DurableAgentServer`. The managed runtime keeps invocation state and events in
memory during `agentbricks dev`. Deployment attaches a persistent Runtime Store, so invocation state and
events survive process loss and interrupted work can be recovered.

The generated project separates portable agent execution from the managed HTTP protocol:

```text
client -> runtime/main.py -> runtime/adapter.py -> agent/agent.py:run_agent
```

- `agent/agent.py` owns the framework-native agent, sessions, tools, MCP lifetime, and `run_agent`.
- `runtime/adapter.py` owns the agent-author integration hooks: runtime input/output translation plus
  `invoke` and `recover`.
- `runtime/main.py` constructs the server and registers those hooks.

To bring an existing LangGraph agent, run `agentbricks init --framework langgraph --existing .` in its
project and follow the generated prompt in your coding agent. The migration skill and this template share
[AGENTKIT_CONTRACT.md](AGENTKIT_CONTRACT.md), which owns integration requirements. This README owns
configuration and client examples; [AGENTS.md](AGENTS.md) provides the development map.

## Run locally

```bash
agentbricks dev
```

The API is available at `http://localhost:8000/api/invocations`, or on the port you pass with
`--app-port`. Requests can fail for a few seconds while the server starts; wait for
`Uvicorn running on ...` in the log.

Every request supplies a UUID `id`.
That ID is the invocation identifier and idempotency key. Supply the stable application session as
the top-level `session_id`; agent-specific values live inside the opaque `input` object:

```bash
SESSION_ID=$(uuidgen)
INVOCATION_ID=$(uuidgen)

curl -sS http://localhost:8000/api/invocations \
  -H 'Content-Type: application/json' \
  -d "{\"id\":\"$INVOCATION_ID\",\"session_id\":\"$SESSION_ID\",\"input\":{\"messages\":[{\"role\":\"user\",\"content\":\"What time is it? Use your tool.\"}]}}"
```

Reuse `SESSION_ID` for multi-turn conversation state. Generate a new `INVOCATION_ID` for each turn.
Retrying the same request with the same invocation ID returns the persisted result; changing the
request while reusing the ID returns `409`.

## App contexts

Send the client section as `input.context`. `agent/contexts.py` maps it to a prompt section (added to
`BASE_PROMPT`) and fnmatch patterns over tool names; memory tools are always offered. A missing or
unknown context uses `general`, which offers every tool.

```bash
curl -sS http://localhost:8000/api/invocations \
  -H 'Content-Type: application/json' \
  -d "{\"id\":\"$(uuidgen)\",\"session_id\":\"$SESSION_ID\",\"input\":{\"messages\":[{\"role\":\"user\",\"content\":\"Which tools can you call?\"}],\"context\":\"signals\"}}"
```

## Long-term memory

The Session Store keeps one conversation's state, keyed by the top-level `session_id`. The Memory Store
keeps facts the agent recalls across conversations, keyed by `actor`: `runtime/adapter.py` reads
`input.actor` and passes it to `memory_tools(actor)`. If you leave out `actor`, it defaults to the
`session_id`, so long-term memory won't carry across sessions. For memory that persists, pass a stable
`actor`, such as the end user's ID, from trusted application context. With request-user auth
(`[auth.user]` in `agent.toml`), the adapter also namespaces a supplied `actor` to the signed-in user; see
[Request-user authorization](#request-user-authorization).

Memory is off by default under `agentbricks dev`, so try it against the deployed app: two
invocations with different `session_id`s and the same `actor`.

```bash
ACTOR=user-123

# Conversation 1: the agent saves a fact with its memory tool.
agentbricks --profile <profile> endpoint invoke agent-bricks-<name> --path /api/invocations \
  --json "{\"id\":\"$(uuidgen)\",\"session_id\":\"$(uuidgen)\",\"input\":{\"actor\":\"$ACTOR\",\"messages\":[{\"role\":\"user\",\"content\":\"Remember that I prefer answers as bullet points.\"}]}}"

# Conversation 2: a new session_id, same actor, so the agent can recall it.
agentbricks --profile <profile> endpoint invoke agent-bricks-<name> --path /api/invocations \
  --json "{\"id\":\"$(uuidgen)\",\"session_id\":\"$(uuidgen)\",\"input\":{\"actor\":\"$ACTOR\",\"messages\":[{\"role\":\"user\",\"content\":\"How do I like my answers formatted?\"}]}}"
```

## Invocation modes

- Foreground: omit `background` and `stream`; the response contains the agent result under `output`.
- Foreground streaming: set `stream: true`; the response is SSE backed by persisted events.
- Background: set `background: true`; poll the returned `status_url`.
- Background streaming: set both flags; the `202` response includes `status_url` and `events_url`.

```bash
INVOCATION_ID=$(uuidgen)
curl -sN http://localhost:8000/api/invocations \
  -H 'Content-Type: application/json' \
  -d "{\"id\":\"$INVOCATION_ID\",\"session_id\":\"$SESSION_ID\",\"input\":{\"messages\":[{\"role\":\"user\",\"content\":\"Count to three.\"}]},\"stream\":true}"

INVOCATION_ID=$(uuidgen)
curl -sS http://localhost:8000/api/invocations \
  -H 'Content-Type: application/json' \
  -d "{\"id\":\"$INVOCATION_ID\",\"session_id\":\"$SESSION_ID\",\"input\":{\"messages\":[{\"role\":\"user\",\"content\":\"Summarize durable agents.\"}]},\"background\":true}" | jq
curl -sS "http://localhost:8000/api/invocations/$INVOCATION_ID" | jq
```

SSE records contain events translated by `runtime/adapter.py`: token `delta`s, completed `message`s,
and HITL `interrupt`s. Replay from a cursor with
`GET /api/invocations/{id}/events?after={sequence}`.

A message's `content` is its answer text. Models that reason (Claude 5.x) add a separate
`{"role": "assistant", "content": [{"type": "reasoning", ...}]}` message before the answer.

## Human approval

`send_message` is gated by `HumanInTheLoopMiddleware`. Start a turn asking the agent to use that
tool. When the output or event stream contains an `interrupt`, submit a new invocation with the same
application session:

```json
{
  "id": "<new-uuid>",
  "session_id": "<same-session-id>",
  "input": {
    "resume": {"decisions": [{"type": "approve"}]}
  }
}
```

For OBO tools (`auth = "user"`), the same signed-in user submits the approval as a new
invocation. Keep the same `session_id` and, if supplied, `input.actor`. The new request supplies
its own user credentials; the paused invocation's credentials are discarded. The browser normally
uses its existing authenticated session, so approval does not require a page refresh or another
login unless that session has expired. Automatic crash recovery still cannot recover OBO work.

Malformed middleware decisions return `INVALID_APPROVAL` before the resume value is checkpointed,
so the user can correct the decision and submit it with a new invocation ID.

The default checkpointer is process-local. A managed Session Store preserves multi-turn and paused
LangGraph state across restarts. This project binds `exec-intel-agent-sessions` in `agent.toml`, and
the deployed agent uses it (session stores are off by default in `agentbricks dev`).

## Crash recovery

Deployment with a Runtime Store supports invocation recovery after worker loss. Graph checkpoint
persistence requires a Session Store separately. Recovery can replay work, so tools must tolerate
repeated side effects. See [Recovery and durability](AGENTKIT_CONTRACT.md#recovery-and-durability).

## Chat app

The browser UI is included by default. It generates a stable application session ID in local
storage, sends it as the top-level `session_id`, and generates a fresh invocation UUID per turn.
Use `agentbricks init --framework langgraph --disable-chat-app` for API-only output.

## Configure and deploy

- Change the model, instructions, tools, graph, and framework-native execution in `agent/agent.py`.
- Change `runtime/adapter.py` only to map a different application input/output contract.
- Add local tools under `agent/tools/`; modules are auto-discovered.
- Add MCP servers in `agent/mcps.py` or with `agentbricks tools add mcp`.
- Each context's prompt, built-in tools, and Genie spaces can be overridden per turn by
  `input.settings`, which the client app builds from its Settings page and its `genie_bindings`
  bundle variable, and which the agent merges over the defaults in `agent/contexts.py`.
  `GET /api/contexts` returns those defaults. A Genie space named `<name>` becomes the tools
  `<name>_ask`, `<name>_poll`, and `<name>_query_result`; the usual bindings are `exec_data` for
  `executive` and `ci_data` for `customer-intelligence` (`../data/genie.py` prints each entry).
  No space is bound in `agent.toml`. Settings come from the caller, which is safe because Genie runs
  as the signed-in user, whose token the client app forwards: a caller can only reach data they
  could query anyway. `[auth.user]` in `agent.toml` keeps the `genie` scope in the client's
  `user_api_scopes`; without it the request arrives with no user.
- Traces go to Unity Catalog tables rather than the experiment's artifact store, because Databricks
  Apps in some workspaces cannot reach the artifact store's regional storage proxy.
  `scripts/trace_storage.py` links the experiment in `agent.toml` `[tracing]`; MLflow links only an
  experiment with no traces yet, so run it before that experiment's first deploy.
- Bind long-term memory with `agentbricks memory bind <store>`; `agentbricks deploy` creates the
  store if it doesn't exist. Memory and session stores are off by default in `agentbricks dev` (the
  chat app shows "Not connected" for memory locally) and connect after deploy. To start with
  memories already in the store, create it and add entries before you bind and deploy:

  ```bash
  agentbricks memory stores create --name <store>    # prints a Store ID
  agentbricks memory entries create --store <Store ID> --actor-id you@example.com \
    --path /preferences/style.md --content "Prefers concise answers."
  ```

  `--path` is the entry's key in the store, not a file on your machine; the deployed chat app uses
  the signed-in user's email as the actor.
- Route the agent's model through a Unity Gateway model service you own with
  `agentbricks experimental models bind`, then search for a better model and prompt on your own
  eval set with `agentbricks experimental models upgrade`. These commands are experimental, so
  their flags may change between releases.

```bash
agentbricks --profile <profile> deploy
```

This deploys as `agent-bricks-exec-intel-agent` (the `deployment_name` in `agent.toml`). To deploy
the agent and the client app together, run `../deploy.sh -p <profile> --var data_catalog=<catalog>`
from the repo root.

When deployment provisions a dedicated Runtime Store, only the app-owned
`databricks_agentkit_runtime_<hash>` schema and runtime tables are added. Managed Runtime Store
deployments use their own default schema.

To keep a session on one app replica (sticky routing), set the `X-Routing-Key` request header to your
stable session id on every call. It is a routing hint only: non-blank, no more than 128 UTF-8 bytes,
used verbatim, and it takes precedence over the legacy `__Host-databricks-app-router` cookie. It is not
authentication and is never used as the application's session id. Send that separately as the
top-level `session_id` in the request body.

# Request-user authorization

Declared tools in `agent.toml` select `auth = "user"` or `auth = "app"`; legacy missing auth
continues to use the application/default identity. Deployed user tools require the request resolver
and never fall back to application credentials. Model, memory-service, session-service, and custom
MCP server credentials are unchanged.

`runtime/main.py` derives the invocation policy after `configure()`. The runtime adapter namespaces
public session IDs and actor values for the request owner, then passes only `workspace_client_for`
to the framework-native agent. Internal session keys are never returned to clients.

User-policy invocations use the existing Runtime for synchronous, streaming, and background calls,
including status polling, event replay, and invocation-ID idempotency. The Runtime Store persists no
credential; request-user authentication remains process-local for the active first attempt. A
replacement attempt fails with `MCP_USER_AUTH_RECOVERY_UNSUPPORTED` before agent code runs.
Interactive approval uses a new authenticated invocation and rebuilds tools with that request's
credentials. The agent's existing namespaced memory, conversation store, and checkpointer behavior
is unchanged; OBO does not add another saver.

Existing generated projects must update their copies of `agent/agent.py` and `runtime/adapter.py`
to remove the OBO pause/resume rejection guards. Upgrading the installed package alone does not
rewrite these files. Keep the runtime's automatic-recovery guard.
