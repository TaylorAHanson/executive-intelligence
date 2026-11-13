import { BRAND_COLOR } from '../../brand'

/**
 * The briefing's four chapters, in reading order. Every chapter shares the
 * brand color on purpose: red, amber, and green are reserved for status (an
 * account at risk, a figure below plan), so a chapter's color never competes
 * with what the numbers inside it are saying.
 */
export interface ChapterDef {
  id: 'know' | 'measure' | 'anticipate' | 'act'
  verb: string
  color: string
}

export const CHAPTERS: ChapterDef[] = [
  { id: 'know', verb: 'Know', color: BRAND_COLOR },
  { id: 'measure', verb: 'Measure', color: BRAND_COLOR },
  { id: 'anticipate', verb: 'Anticipate', color: BRAND_COLOR },
  { id: 'act', verb: 'Act', color: BRAND_COLOR },
]

export function chapter(id: ChapterDef['id']): ChapterDef {
  return CHAPTERS.find((c) => c.id === id) ?? CHAPTERS[0]
}
