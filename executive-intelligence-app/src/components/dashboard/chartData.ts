export interface Series {
  key: string
  label: string
}

export type ChartRow = Record<string, unknown>

/** Pivot long rows into one row per `x` with a column per series, keeping first-seen order. */
export function pivotRows(rows: ChartRow[], x: string, seriesKey: string, valueKey: string) {
  const byX = new Map<unknown, ChartRow>()
  const series: Series[] = []
  for (const row of rows) {
    const name = String(row[seriesKey] ?? '')
    if (!series.some((s) => s.key === name)) series.push({ key: name, label: name })
    const wide = byX.get(row[x]) ?? { [x]: row[x] }
    wide[name] = row[valueKey]
    byX.set(row[x], wide)
  }
  return { rows: [...byX.values()], series }
}
