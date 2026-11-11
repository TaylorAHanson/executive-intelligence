import { formatValue } from './format'

export interface FilterOption {
  value: string
  label: string
}

/**
 * One control in a `FilterBar`. Values live in the URL through `useFilters`,
 * so every key here needs a default there.
 */
export type FilterDef =
  | { type: 'select'; key: string; label: string; options: FilterOption[] }
  /** Comma-separated in the URL. An empty value means "all". */
  | { type: 'multiselect'; key: string; label: string; options: FilterOption[] }
  | { type: 'search'; key: string; label: string; placeholder?: string }
  /** Two `YYYY-MM` values; the backend treats both ends as inclusive months. */
  | { type: 'daterange'; fromKey: string; toKey: string; label: string }

/** `YYYY-MM` for the month `monthsAgo` months before this one. */
export function monthsAgo(monthsAgo: number): string {
  const now = new Date()
  const d = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth() - monthsAgo, 1))
  return d.toISOString().slice(0, 7)
}

export const splitList = (value: string) => (value ? value.split(',').filter(Boolean) : [])

/**
 * The active filters in words, for questions sent to the agent, so it answers
 * about the same slice of data the user is looking at.
 */
export function describeFilters(defs: FilterDef[], values: Record<string, string>): string {
  const parts: string[] = []
  for (const def of defs) {
    if (def.type === 'daterange') {
      const from = values[def.fromKey]
      const to = values[def.toKey]
      if (from || to) parts.push(`${def.label}: ${formatValue(from, 'month')} to ${formatValue(to, 'month')}`)
      continue
    }
    const value = values[def.key]
    if (!value) continue
    if (def.type === 'search') {
      parts.push(`${def.label} matching "${value}"`)
    } else {
      const labels = splitList(value).map((v) => def.options.find((o) => o.value === v)?.label ?? v)
      parts.push(`${def.label}: ${labels.join(', ')}`)
    }
  }
  return parts.join('; ')
}
