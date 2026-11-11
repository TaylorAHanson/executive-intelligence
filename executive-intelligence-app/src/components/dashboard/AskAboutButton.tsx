import { Sparkles } from 'lucide-react'
import { useAgentTray } from '../../providers/agentTray'
import { useDashboardContext } from './dashboardContext'

interface AskAboutButtonProps {
  /** The question, naming what the user is looking at. Active filters are appended. */
  question: string
  label?: string
}

/** Puts a question about this widget in the agent tray, ready to send. */
export default function AskAboutButton({ question, label = 'Ask' }: AskAboutButtonProps) {
  const tray = useAgentTray()
  const { filterSummary } = useDashboardContext()
  const full = filterSummary ? `${question} (Filters: ${filterSummary}.)` : question

  return (
    <button
      type="button"
      className="inline-flex shrink-0 items-center gap-1 rounded-md px-1.5 py-1 text-xs font-medium text-brand hover:bg-brand/10"
      onClick={() => tray.ask(full)}
      title={full}
    >
      <Sparkles className="h-3.5 w-3.5" aria-hidden="true" />
      {label}
    </button>
  )
}
