import { useState, type ReactNode } from 'react'
import { ArrowDown, ArrowUp } from 'lucide-react'
import type { DashboardQuery } from '../../hooks/useDashboardQuery'
import { formatValue, toNumber, type ValueFormat } from './format'
import WidgetCard, { type WidgetFrameProps } from './WidgetCard'
import WidgetState from './WidgetState'

export interface Column<Row> {
  key: keyof Row & string
  label: string
  format?: ValueFormat
  /** Defaults to right for numeric formats, left otherwise. */
  align?: 'left' | 'right'
  /** Custom cell content. Sorting still uses the raw value. */
  render?: (row: Row) => ReactNode
}

type Sort<Row> = { key: keyof Row & string; direction: 'asc' | 'desc' }

interface DataTableProps<Row> extends WidgetFrameProps {
  query: DashboardQuery<Row>
  columns: Column<Row>[]
  rowKey: (row: Row) => string
  /** Rows shown before "Show all". The backend's own cap is separate. */
  rowCap?: number
  initialSort?: Sort<Row>
}

const NUMERIC: ValueFormat[] = ['number', 'compact', 'currency', 'currencyCompact', 'percent']

function compare(a: unknown, b: unknown) {
  const na = toNumber(a)
  const nb = toNumber(b)
  if (na !== null && nb !== null) return na - nb
  if (a === null || a === undefined) return 1
  if (b === null || b === undefined) return -1
  return String(a).localeCompare(String(b))
}

/**
 * A sortable table. Sorting happens in the browser over the rows returned, so
 * on a truncated result it orders only those rows; the truncation banner
 * already says so. For a "top N", sort and limit in SQL instead.
 */
export default function DataTable<Row>({
  query,
  columns,
  rowKey,
  rowCap = 25,
  initialSort,
  span = 12,
  ...frame
}: DataTableProps<Row>) {
  const [sort, setSort] = useState<Sort<Row> | undefined>(initialSort)
  const [showAll, setShowAll] = useState(false)

  const toggleSort = (key: keyof Row & string) =>
    setSort((current) =>
      current?.key === key ? { key, direction: current.direction === 'asc' ? 'desc' : 'asc' } : { key, direction: 'desc' },
    )

  return (
    <WidgetCard span={span} {...frame}>
      <WidgetState query={query} skeleton="table">
        {({ rows }) => {
          const sorted = sort
            ? [...rows].sort((a, b) => compare(a[sort.key], b[sort.key]) * (sort.direction === 'asc' ? 1 : -1))
            : rows
          const visible = showAll ? sorted : sorted.slice(0, rowCap)
          return (
            <>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-line text-xs uppercase tracking-wide text-ink-muted">
                      {columns.map((column) => {
                        const right = (column.align ?? (NUMERIC.includes(column.format ?? 'text') ? 'right' : 'left')) === 'right'
                        const active = sort?.key === column.key
                        const SortIcon = sort?.direction === 'asc' ? ArrowUp : ArrowDown
                        return (
                          <th key={column.key} className={`px-2 py-2 font-semibold ${right ? 'text-right' : 'text-left'}`}>
                            <button
                              type="button"
                              className={`inline-flex items-center gap-1 hover:text-ink ${active ? 'text-ink' : ''}`}
                              onClick={() => toggleSort(column.key)}
                            >
                              {column.label}
                              {active && <SortIcon className="h-3 w-3" aria-hidden="true" />}
                            </button>
                          </th>
                        )
                      })}
                    </tr>
                  </thead>
                  <tbody>
                    {visible.map((row) => (
                      <tr key={rowKey(row)} className="border-b border-line/60 last:border-0 hover:bg-canvas">
                        {columns.map((column) => {
                          const right = (column.align ?? (NUMERIC.includes(column.format ?? 'text') ? 'right' : 'left')) === 'right'
                          return (
                            <td key={column.key} className={`px-2 py-2 ${right ? 'text-right tabular-nums' : 'text-left'}`}>
                              {column.render ? column.render(row) : formatValue(row[column.key], column.format)}
                            </td>
                          )
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {sorted.length > rowCap && (
                <button
                  type="button"
                  className="mt-2 self-start text-xs font-medium text-brand hover:underline"
                  onClick={() => setShowAll((v) => !v)}
                >
                  {showAll ? `Show first ${rowCap}` : `Show all ${sorted.length} rows`}
                </button>
              )}
            </>
          )
        }}
      </WidgetState>
    </WidgetCard>
  )
}
