/**
 * The briefing toolkit: for pages that tell a story in four chapters (Know,
 * Measure, Anticipate, Act) rather than lay out a grid of widgets. Customer
 * Intelligence is the reference. The narrative comes from insight records
 * (v_insights); the numbers beside it from widget endpoints, as on any dashboard.
 */
export { CHAPTERS, chapter, type ChapterDef } from './chapters'
export { default as Figure, FigureSkeleton } from './Figure'
export { parseEvidence, useBriefing, type Evidence, type InsightRow } from './insights'
export { default as Recommendation } from './Recommendation'
export { default as Rich } from './Rich'
export { default as Sparkline } from './Sparkline'
export { default as StoryPage, Chapter } from './StoryPage'
export { pct, points, money } from './format'
