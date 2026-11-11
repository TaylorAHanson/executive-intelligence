import { keepPreviousData, useQuery, type UseQueryResult } from '@tanstack/react-query'
import { getWidget, type WidgetParams, type WidgetResult } from '../api'

/**
 * One widget's data from `/api/dashboards{path}`.
 *
 * Results are cached by path and params, so widgets that read the same
 * endpoint with the same filters share one request. While new filters load,
 * the previous result stays on screen (`isPlaceholderData` is true) rather
 * than flashing back to a skeleton.
 *
 * Render the result through `WidgetState`, which handles loading, errors,
 * empty results, and truncation consistently.
 */
export function useDashboardQuery<Row = Record<string, unknown>>(path: string, params: WidgetParams = {}) {
  return useQuery<WidgetResult<Row>>({
    queryKey: ['dashboard', path, params],
    queryFn: () => getWidget<Row>(path, params),
    placeholderData: keepPreviousData,
  })
}

export type DashboardQuery<Row = Record<string, unknown>> = UseQueryResult<WidgetResult<Row>>
