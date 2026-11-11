import { createContext, useContext } from 'react'

export interface DashboardContextValue {
  /** The page's active filters in words, or '' when unfiltered. */
  filterSummary: string
}

export const DashboardContext = createContext<DashboardContextValue>({ filterSummary: '' })

export const useDashboardContext = () => useContext(DashboardContext)
