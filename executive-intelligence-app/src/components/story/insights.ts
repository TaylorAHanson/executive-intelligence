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

const plain = (text: string | null) => (text ?? '').replace(/\*\*(.+?)\*\*/g, '$1')

const CHAPTER_LABELS: [InsightRow['chapter'], string][] = [
  ['know', 'Know'],
  ['measure', 'Measure'],
  ['anticipate', 'Anticipate'],
]

/**
 * The briefing as plain text for an email or a chat message: the headline, each
 * chapter's takeaway, and the recommendations. `extra` lines (what needs
 * attention, say) go under the headline.
 */
export function briefingSummary(title: string, rows: InsightRow[], extra: string[] = []): string {
  const first = (chapter: InsightRow['chapter']) => rows.find((r) => r.chapter === chapter)?.body ?? null
  const lines = [title, '', plain(first('headline'))]
  if (extra.length) lines.push('', ...extra)
  for (const [chapter, label] of CHAPTER_LABELS) {
    const body = first(chapter)
    if (body) lines.push('', `${label}: ${plain(body)}`)
  }
  const actions = rows.filter((r) => r.chapter === 'act')
  if (actions.length) lines.push('', 'Recommended actions')
  actions.forEach((a, i) => {
    lines.push(`${i + 1}. ${a.title ?? ''}`.trimEnd())
    if (a.cause) lines.push(`   Because: ${plain(a.cause)}`)
    if (a.effect) lines.push(`   Which means: ${plain(a.effect)}`)
    if (a.action) lines.push(`   So we: ${plain(a.action)}`)
    if (a.owner) lines.push(`   Owner: ${a.owner}`)
  })
  return lines.join('\n')
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
    summary: (title: string, extra?: string[]) => briefingSummary(title, rows, extra),
  }
}
