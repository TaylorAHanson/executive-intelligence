/**
 * The single place this app talks to its backend.
 *
 * Two rules, both load-bearing:
 *
 * 1. **Relative paths only.** `API_BASE` is `/api`, never a hostname. In dev,
 *    Vite proxies that to the local backend; in production FastAPI serves this
 *    bundle itself, so the same path hits the same origin. A hardcoded host
 *    works on your laptop and breaks the moment it is deployed — and the same
 *    built assets get promoted across environments, so a build-time URL would
 *    be wrong everywhere except where it was built.
 *
 * 2. **No credentials in here.** No tokens, no API keys, no connection strings —
 *    not in code, not in `localStorage`. Anything in this file ships to the
 *    browser and is readable by anyone who opens devtools. The user's Databricks
 *    token lives server-side only; the browser never sees or sends it. If a
 *    feature needs a secret, it needs a backend endpoint.
 *
 * Add typed helpers here rather than scattering raw `fetch` calls through
 * components.
 */

const API_BASE = '/api'

export interface HealthResponse {
  status: string
  environment: string
  /** The contract views sit over synthetic data (bundle variable `synthetic_data`). */
  synthetic_data: boolean
  sql_warehouse_configured: boolean
  agent_configured: boolean
}

export interface CurrentUser {
  email: string
  username: string
  /** True only when a user token was forwarded, which needs `user_api_scopes`. */
  on_behalf_of: boolean
  /** True on a laptop, where the app acts as your CLI login. */
  local_dev: boolean
  /** In the admin group: shows Settings. The backend checks again on every settings call. */
  is_admin: boolean
}

export interface GenieSpaceSetting {
  /** Tools are `<name>_ask`, `<name>_poll` and `<name>_query_result`. */
  name: string
  space_id: string
  /** From Genie when saved. */
  title?: string
  description: string
}

export interface ContextAgentSettings {
  id: string
  label: string
  default_prompt: string
  default_builtin_tools: string[]
  /** null: the default prompt applies. */
  prompt: string | null
  /** null: the default built-in tools apply. */
  builtin_tools: string[] | null
  genie_spaces: GenieSpaceSetting[]
  updated_by: string | null
  updated_at: string | null
}

export interface AgentSettings {
  base_prompt: string
  builtin_tools: { name: string; description: string }[]
  contexts: ContextAgentSettings[]
}

export interface ContextAgentSettingsUpdate {
  prompt: string | null
  builtin_tools: string[] | null
  genie_spaces: Omit<GenieSpaceSetting, 'title'>[]
}

export type AgentMessage =
  | { role: 'user'; content: string }
  | { role: 'assistant'; content: string }
  | { role: 'tool'; name: string; content: string }

export interface PendingAction {
  name: string
  args: Record<string, unknown>
}

export interface AgentTurn {
  /** `interrupted` means the agent paused for approval of `interrupt.actions`. */
  status: 'completed' | 'interrupted' | string
  messages: AgentMessage[]
  interrupt: { actions: PendingAction[] } | null
}

export interface ApprovalDecision {
  type: 'approve' | 'reject'
  message?: string
}

/**
 * One dashboard widget's data: the `run_query` shape from `server/services/sql.py`.
 *
 * `rows` can be a subset of what the query matched. Check `truncated` before
 * presenting anything that assumes completeness; `WidgetState` does this for
 * every widget.
 */
export interface WidgetResult<Row = Record<string, unknown>> {
  columns: string[]
  rows: Row[]
  returned_rows: number
  total_rows: number | null
  truncated: boolean
  statement_id: string | null
}

/** Query-string values for a widget endpoint. Empty strings and undefined are omitted. */
export type WidgetParams = Record<string, string | number | undefined>

/** Thrown for any non-2xx response, carrying the backend's `detail` message. */
export class ApiError extends Error {
  status: number
  /** The Apps sign-in lapsed. Retrying cannot help; only a reload can. */
  sessionExpired: boolean

  constructor(message: string, status: number, sessionExpired = false) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.sessionExpired = sessionExpired
  }
}

// When the Databricks Apps sign-in expires, the proxy answers API calls with a
// redirect to the login page. The browser blocks that cross-origin redirect, so
// fetch fails without a response, or (same-origin) returns HTML. Only a reload
// signs the user back in.
const SESSION_EXPIRED =
  'Could not reach the app. If this tab has been open a while, your sign-in may have expired: reload the page.'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: {
        'Content-Type': 'application/json',
        ...init?.headers,
      },
    })
  } catch {
    throw new ApiError(SESSION_EXPIRED, 0, true)
  }

  if (!response.ok) {
    // FastAPI puts the human-readable reason in `detail`. Surfacing it beats a
    // bare status code, which tells a user nothing they can act on.
    let detail = `Request failed with status ${response.status}`
    try {
      const body = await response.json()
      if (typeof body?.detail === 'string') detail = body.detail
    } catch {
      // Body was not JSON; the status-based message stands.
    }
    throw new ApiError(detail, response.status)
  }

  try {
    return (await response.json()) as T
  } catch {
    throw new ApiError(SESSION_EXPIRED, response.status, true)
  }
}

export const getHealth = () => request<HealthResponse>('/health')

/**
 * Fetch one widget from `/api/dashboards/...`. Use `useDashboardQuery` in
 * components rather than calling this directly, so results are cached and
 * shared between widgets that read the same endpoint.
 */
export function getWidget<Row>(path: string, params: WidgetParams = {}) {
  const query = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== '') query.set(key, String(value))
  }
  const suffix = query.size ? `?${query}` : ''
  return request<WidgetResult<Row>>(`/dashboards${path}${suffix}`)
}

export const getCurrentUser = () => request<CurrentUser>('/user/me')

/**
 * One chat turn. Identity is not sent: the backend takes it from the Apps
 * proxy, so the browser cannot ask on someone else's behalf.
 */
export const sendAgentMessage = (sessionId: string, context: string, message: string) =>
  request<AgentTurn>('/agent/chat', {
    method: 'POST',
    body: JSON.stringify({ session_id: sessionId, context, message }),
  })

export const getAgentSettings = () => request<AgentSettings>('/settings/agent')

export const saveAgentSettings = (contextId: string, update: ContextAgentSettingsUpdate) =>
  request<{ status: string }>(`/settings/agent/${encodeURIComponent(contextId)}`, {
    method: 'PUT',
    body: JSON.stringify(update),
  })

export const resetAgentSettings = (contextId: string) =>
  request<{ status: string }>(`/settings/agent/${encodeURIComponent(contextId)}`, { method: 'DELETE' })

export const lookupGenieSpace = (spaceId: string) =>
  request<{ space_id: string; title: string; description: string }>(
    `/settings/genie-spaces/${encodeURIComponent(spaceId)}`,
  )

/** Answer a paused approval: one decision per pending action, in order. */
export const resumeAgent = (sessionId: string, context: string, decisions: ApprovalDecision[]) =>
  request<AgentTurn>('/agent/resume', {
    method: 'POST',
    body: JSON.stringify({ session_id: sessionId, context, decisions }),
  })
