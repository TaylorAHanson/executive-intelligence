import { useCallback, useMemo } from 'react'
import { useSearchParams } from 'react-router-dom'

export interface FiltersState<K extends string = string> {
  values: Record<K, string>
  /** Change several filters in one URL update, e.g. both ends of a date range. */
  setFilters: (changes: Partial<Record<K, string>>) => void
  reset: () => void
  /** True when every filter is at its default, so there is nothing to reset. */
  isDefault: boolean
}

/**
 * Dashboard filters, stored in the URL's search params.
 *
 * Keeping them in the URL makes a filtered view shareable and lets it survive
 * a reload. A value equal to its default is removed from the URL, so a fresh
 * link stays clean. Multi-select values are comma-separated.
 *
 * Define `defaults` outside the component, so its identity is stable.
 */
export function useFilters<K extends string>(defaults: Record<K, string>): FiltersState<K> {
  const [searchParams, setSearchParams] = useSearchParams()

  const values = useMemo(() => {
    const current = { ...defaults }
    for (const key of Object.keys(defaults) as K[]) {
      const value = searchParams.get(key)
      if (value !== null) current[key] = value
    }
    return current
  }, [defaults, searchParams])

  const setFilters = useCallback(
    (changes: Partial<Record<K, string>>) =>
      setSearchParams(
        (previous) => {
          const next = new URLSearchParams(previous)
          for (const [key, value] of Object.entries(changes) as [K, string][]) {
            if (value === defaults[key]) next.delete(key)
            else next.set(key, value)
          }
          return next
        },
        { replace: true },
      ),
    [defaults, setSearchParams],
  )

  const reset = useCallback(
    () =>
      setSearchParams(
        (previous) => {
          const next = new URLSearchParams(previous)
          for (const key of Object.keys(defaults)) next.delete(key)
          return next
        },
        { replace: true },
      ),
    [defaults, setSearchParams],
  )

  const isDefault = (Object.keys(defaults) as K[]).every((key) => values[key] === defaults[key])

  return { values, setFilters, reset, isDefault }
}
