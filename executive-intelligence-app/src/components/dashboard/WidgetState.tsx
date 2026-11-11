import type { ReactNode } from 'react'
import { AlertTriangle, RefreshCw } from 'lucide-react'
import { ApiError, type WidgetResult } from '../../api'
import type { DashboardQuery } from '../../hooks/useDashboardQuery'

interface WidgetStateProps<Row> {
  query: DashboardQuery<Row>
  children: (result: WidgetResult<Row>) => ReactNode
  /** Skeleton shape while the first result loads. */
  skeleton?: 'kpi' | 'chart' | 'table'
  emptyMessage?: string
}

/**
 * Loading, error, empty, and truncated states for one widget.
 *
 * Every widget renders through this, so none of them can quietly show a
 * partial result as if it were complete: a truncated result always carries
 * a banner saying how much is missing.
 */
export default function WidgetState<Row>({
  query,
  children,
  skeleton = 'chart',
  emptyMessage = 'No data for these filters.',
}: WidgetStateProps<Row>) {
  if (query.isPending) return <Skeleton shape={skeleton} />
  if (query.isError) return <WidgetError error={query.error} onRetry={() => void query.refetch()} />

  const result = query.data
  if (result.rows.length === 0) {
    return <p className="flex flex-1 items-center justify-center py-8 text-sm text-ink-muted">{emptyMessage}</p>
  }

  return (
    // Previous filters' result stays visible, dimmed, while new filters load.
    <div className={`flex flex-1 flex-col transition-opacity ${query.isPlaceholderData ? 'opacity-50' : ''}`}>
      {children(result)}
      {result.truncated && <TruncationBanner result={result} />}
    </div>
  )
}

function TruncationBanner({ result }: { result: WidgetResult<unknown> }) {
  const of = result.total_rows !== null ? ` of ${result.total_rows.toLocaleString()}` : ''
  return (
    <p className="mt-3 flex items-start gap-1.5 rounded-lg bg-accent/5 px-2.5 py-1.5 text-xs text-ink-light" role="status">
      <AlertTriangle className="mt-px h-3.5 w-3.5 shrink-0 text-accent" aria-hidden="true" />
      Showing the first {result.returned_rows.toLocaleString()}
      {of} rows. Anything computed from these rows on this page is incomplete.
    </p>
  )
}

function WidgetError({ error, onRetry }: { error: Error; onRetry: () => void }) {
  const expired = error instanceof ApiError && error.sessionExpired
  return (
    <div className="flex flex-1 flex-col items-start justify-center gap-2 rounded-lg bg-red-50 px-3 py-3 text-sm text-red-800" role="alert">
      <span>{error.message}</span>
      <button
        type="button"
        className="inline-flex items-center gap-1 rounded-md border border-red-200 bg-white px-2 py-1 text-xs font-medium hover:bg-red-100"
        onClick={expired ? () => window.location.reload() : onRetry}
      >
        <RefreshCw className="h-3 w-3" aria-hidden="true" />
        {expired ? 'Reload page' : 'Retry'}
      </button>
    </div>
  )
}

function Skeleton({ shape }: { shape: 'kpi' | 'chart' | 'table' }) {
  if (shape === 'kpi') {
    return (
      <div className="animate-pulse space-y-2" aria-label="Loading">
        <div className="h-8 w-2/3 rounded bg-canvas-dark" />
        <div className="h-4 w-1/3 rounded bg-canvas-dark" />
      </div>
    )
  }
  if (shape === 'table') {
    return (
      <div className="animate-pulse space-y-2" aria-label="Loading">
        {Array.from({ length: 6 }, (_, i) => (
          <div key={i} className="h-5 rounded bg-canvas-dark" />
        ))}
      </div>
    )
  }
  return <div className="h-64 animate-pulse rounded-lg bg-canvas-dark" aria-label="Loading" />
}
