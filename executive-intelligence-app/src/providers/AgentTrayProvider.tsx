import { useMemo, useState, type ReactNode } from 'react'
import { useLocation } from 'react-router-dom'
import { DEFAULT_AGENT_CONTEXT } from '../agentContexts'
import { sectionForPath } from '../sections'
import { AgentTrayContext, TRAY_OVERLAY_QUERY, type AgentTrayState, type TrayFocusRequest } from './agentTray'

/**
 * Tray visibility and context. Must sit inside the router: on a dashboard
 * route the section's `agentContext` wins over the user's choice.
 */
export default function AgentTrayProvider({ children }: { children: ReactNode }) {
  const { pathname } = useLocation()
  const section = sectionForPath(pathname)
  // Docked open on a desktop; closed on a tablet, where it would cover the page.
  const [isOpen, setIsOpen] = useState(() => !window.matchMedia(TRAY_OVERLAY_QUERY).matches)
  const [chosenContext, setChosenContext] = useState(DEFAULT_AGENT_CONTEXT)
  const [focusRequest, setFocusRequest] = useState<TrayFocusRequest | null>(null)

  const value = useMemo<AgentTrayState>(() => {
    const show = (draft: string | undefined, context: string | undefined) => {
      if (context) setChosenContext(context)
      setIsOpen(true)
      setFocusRequest({ id: Date.now(), draft })
    }
    return {
      isOpen,
      context: section?.agentContext ?? chosenContext,
      contextLocked: Boolean(section),
      focusRequest,
      open: (context) => show(undefined, context),
      close: () => setIsOpen(false),
      ask: (question, context) => show(question, context),
      setContext: setChosenContext,
    }
  }, [isOpen, section, chosenContext, focusRequest])

  return <AgentTrayContext.Provider value={value}>{children}</AgentTrayContext.Provider>
}
