import type { ReactNode } from 'react'
import { Sparkles } from 'lucide-react'
import type { FiltersState } from '../../hooks/useFilters'
import { useAgentTray } from '../../providers/agentTray'
import { SECTIONS } from '../../sections'
import { DashboardContext } from './dashboardContext'
import FilterBar from './FilterBar'
import { describeFilters, type FilterDef } from './filters'

interface DashboardPageProps {
  /** The section's id in `sections.ts`; title, icon, and questions come from there. */
  sectionId: string
  filterDefs?: FilterDef[]
  filters?: FiltersState
  /** Widgets. They lay out on a 12-column grid by their `span`. */
  children: ReactNode
}

/**
 * The shell every dashboard renders in: header, suggested questions, filter
 * bar, and widget grid. It also tells each widget's Ask button which filters
 * are active, so questions to the agent carry the same slice of data.
 */
export default function DashboardPage({ sectionId, filterDefs = [], filters, children }: DashboardPageProps) {
  const tray = useAgentTray()
  const section = SECTIONS.find((s) => s.id === sectionId)
  if (!section) throw new Error(`No section "${sectionId}" in sections.ts`)
  const { icon: Icon } = section
  const filterSummary = filters ? describeFilters(filterDefs, filters.values) : ''

  const ask = (question: string) => tray.ask(filterSummary ? `${question} (Filters: ${filterSummary}.)` : question)

  return (
    <DashboardContext.Provider value={{ filterSummary }}>
      <div className="min-h-full bg-canvas px-6 py-6">
        <div className="mx-auto max-w-[1400px] space-y-5">
          <header className="flex flex-wrap items-start gap-4">
            <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-brand text-white shadow-tile">
              <Icon className="h-[22px] w-[22px]" aria-hidden="true" />
            </div>
            <div className="min-w-0 flex-1">
              <h2 className="text-[1.6rem] font-extrabold leading-tight tracking-[-0.01em] text-ink">{section.label}</h2>
              <p className="text-sm text-ink-light">{section.description}</p>
            </div>
          </header>

          {section.suggestedQuestions.length > 0 && (
            <div className="flex flex-wrap gap-2">
              {section.suggestedQuestions.map((question) => (
                <button
                  key={question}
                  type="button"
                  className="inline-flex items-center gap-1.5 rounded-full border border-brand/25 bg-white px-3 py-1 text-xs font-medium text-brand hover:bg-brand/10"
                  onClick={() => ask(question)}
                >
                  <Sparkles className="h-3 w-3" aria-hidden="true" />
                  {question}
                </button>
              ))}
            </div>
          )}

          {filters && filterDefs.length > 0 && (
            <div className="rounded-xl border border-line bg-white px-4 py-3 shadow-tile">
              <FilterBar defs={filterDefs} filters={filters} />
            </div>
          )}

          <div className="grid grid-cols-12 gap-4">{children}</div>
        </div>
      </div>
    </DashboardContext.Provider>
  )
}
