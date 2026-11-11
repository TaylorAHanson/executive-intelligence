/**
 * Every dashboard in the app, in nav order.
 *
 * The router, the header nav, and the landing page's tiles are all
 * generated from this list, so adding a dashboard is one entry here plus its
 * page under `pages/`. See "Adding a dashboard" in `src/AGENTS.md`.
 */
import { lazy, type ComponentType, type LazyExoticComponent } from 'react'
import { matchPath } from 'react-router-dom'
import { Briefcase, Compass, type LucideIcon } from 'lucide-react'

export interface Section {
  id: string
  /** Route path, without a trailing slash. The page may route beneath it (`/customers/:id`). */
  path: string
  label: string
  description: string
  icon: LucideIcon
  /** Context sent to the agent while this section is open. Must exist in `agentContexts.ts`. */
  agentContext: string
  /** Offered as one-click questions at the top of a `DashboardPage`. Briefings (`StoryPage`) don't show them. */
  suggestedQuestions: string[]
  /** Lazy, so each dashboard's charts load only when it is opened. */
  component: LazyExoticComponent<ComponentType>
}

export const SECTIONS: Section[] = [
  {
    id: 'executive',
    path: '/executive',
    label: 'Executive Insights',
    description: 'Revenue, on-time-in-full delivery, and design-win conversion across the customer base.',
    icon: Briefcase,
    agentContext: 'executive',
    suggestedQuestions: [
      'Which top-10 customer is at risk and why?',
      'Where is OTIF slipping, and since when?',
      'Which segments are converting design wins best?',
    ],
    component: lazy(() => import('./pages/ExecutiveInsightsPage')),
  },
  {
    id: 'customers',
    path: '/customers',
    label: 'Customer Intelligence',
    description: 'What the top 10 accounts are focused on, how we are doing with them, and what to do next.',
    icon: Compass,
    agentContext: 'customer-intelligence',
    suggestedQuestions: [],
    component: lazy(() => import('./pages/customers/CustomerIntelligencePage')),
  },
]

/** The section whose route contains `pathname`, or undefined (landing, 404). */
export function sectionForPath(pathname: string): Section | undefined {
  return SECTIONS.find((section) => matchPath({ path: section.path, end: false }, pathname))
}
