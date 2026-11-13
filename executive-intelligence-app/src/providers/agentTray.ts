import { createContext, useContext } from 'react'

/** Ask the tray to focus its input, optionally replacing the draft. A new `id` is a new request. */
export interface TrayFocusRequest {
  id: number
  draft?: string
}

export interface AgentTrayState {
  isOpen: boolean
  /** The agent context this turn is sent with. */
  context: string
  /** True on a dashboard route, where the section decides the context. */
  contextLocked: boolean
  focusRequest: TrayFocusRequest | null
  /** Open the tray and focus its input, keeping any draft. `context` as for `ask`. */
  open: (context?: string) => void
  close: () => void
  /**
   * Open the tray with `question` in the input, ready to send. `context` only
   * applies where the context is not locked to the route.
   */
  ask: (question: string, context?: string) => void
  /** Choose the context where it is not locked to the route. */
  setContext: (context: string) => void
}

/**
 * Below this width the tray floats over the page instead of sharing it, and starts
 * closed: beside it, a 420px tray would leave a tablet's page under 400px wide.
 */
export const TRAY_OVERLAY_QUERY = '(max-width: 1099px)'

export const AgentTrayContext = createContext<AgentTrayState | null>(null)

/** Open the agent tray from anywhere, or read which context it is in. */
export function useAgentTray(): AgentTrayState {
  const tray = useContext(AgentTrayContext)
  if (!tray) throw new Error('useAgentTray must be used inside <AgentTrayProvider>')
  return tray
}
