import { useDashboardQuery } from '../../hooks/useDashboardQuery'

/** One row of v_insights (data/contract.md): a sentence of the briefing, or a recommendation. */
export interface InsightRow {
  insight_id: string
  chapter: 'headline' | 'know' | 'measure' | 'anticipate' | 'act'
  position: number
  title: string | null
  body: string | null
  cause: string | null
  effect: string | null
  action: string | null
  owner: string | null
  /** JSON array of {kind, ref, label}. */
  evidence: string | null
  generated_at: string
  generated_by: string
}

export interface Evidence {
  kind: 'signal' | 'contract' | 'opportunity' | 'metric' | string
  ref: string
  label: string
}

export function parseEvidence(value: string | null): Evidence[] {
  if (!value) return []
  try {
    const parsed = JSON.parse(value)
    return Array.isArray(parsed) ? parsed.filter((e) => e && typeof e.label === 'string') : []
  } catch {
    return []
  }
}

/** The insight records for `scope` ("portfolio" or a customer_id), grouped by chapter. */
export function useBriefing(scope: string) {
  const query = useDashboardQuery<InsightRow>('/customers/briefing', { scope })
  const rows = query.data?.rows ?? []
  const first = (chapter: InsightRow['chapter']) => rows.find((r) => r.chapter === chapter)
  return {
    query,
    headline: first('headline')?.body ?? null,
    soWhat: (chapter: InsightRow['chapter']) => first(chapter)?.body ?? null,
    actions: rows.filter((r) => r.chapter === 'act'),
    generatedAt: rows[0]?.generated_at ?? null,
    generatedBy: rows[0]?.generated_by ?? null,
  }
}
