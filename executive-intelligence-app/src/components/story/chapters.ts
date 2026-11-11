/**
 * The briefing's four chapters, in reading order. Colors follow the Market
 * Intelligence 360 journey (Know blue, Measure green, Anticipate orange, Act
 * red) and are used for chapter markers only; everything else stays in the
 * brand palette.
 */
export interface ChapterDef {
  id: 'know' | 'measure' | 'anticipate' | 'act'
  verb: string
  color: string
}

export const CHAPTERS: ChapterDef[] = [
  { id: 'know', verb: 'Know', color: '#1F7AE0' },
  { id: 'measure', verb: 'Measure', color: '#12946A' },
  { id: 'anticipate', verb: 'Anticipate', color: '#E07F0A' },
  { id: 'act', verb: 'Act', color: '#D52F45' },
]

export function chapter(id: ChapterDef['id']): ChapterDef {
  return CHAPTERS.find((c) => c.id === id) ?? CHAPTERS[0]
}
