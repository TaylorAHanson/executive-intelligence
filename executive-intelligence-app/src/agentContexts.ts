/**
 * The sections of the app the agent can be "in".
 *
 * Each id must match a context in
 * `executive-intelligence-agent/agent/contexts.py`, which owns the prompt and
 * tools for it. An id the agent doesn't know falls back to its default, so a
 * section can ship here before the agent is redeployed.
 *
 * A dashboard section sets its context through `agentContext` in `sections.ts`,
 * so the tray follows the route. The landing page lets the user choose. Add a
 * context here with the page that uses it, so nobody can pick a section that
 * isn't built.
 */
export interface AgentContext {
  id: string
  label: string
}

export const AGENT_CONTEXTS: AgentContext[] = [
  { id: 'general', label: 'General' },
  { id: 'executive', label: 'Executive Insights' },
  { id: 'customer-intelligence', label: 'Customer Intelligence' },
]

export const DEFAULT_AGENT_CONTEXT = AGENT_CONTEXTS[0].id
