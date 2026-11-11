import { ArrowDownRight, ArrowUpRight } from 'lucide-react'

interface FigureProps {
  label: string
  value: string
  /** Comparison, in words: "was 107% a year earlier". */
  was?: string
  /** Whether the change is good news, bad news, or neither. */
  tone?: 'up' | 'down' | 'flat'
}

/** A headline number set in type rather than in a card. */
export default function Figure({ label, value, was, tone = 'flat' }: FigureProps) {
  const Arrow = tone === 'down' ? ArrowDownRight : ArrowUpRight
  const toneClass = tone === 'down' ? 'text-accent' : tone === 'up' ? 'text-emerald-700' : 'text-ink-muted'
  return (
    <div>
      <div className="text-sm text-ink-light">{label}</div>
      <div className="mt-1 text-[2.4rem] font-semibold leading-none tracking-[-0.02em] text-ink tabular-nums">{value}</div>
      {was && (
        <div className={`mt-2 inline-flex items-center gap-1 text-sm ${toneClass}`}>
          {tone !== 'flat' && <Arrow className="h-4 w-4" aria-hidden="true" />}
          {was}
        </div>
      )}
    </div>
  )
}

export function FigureSkeleton() {
  return (
    <div className="animate-pulse space-y-2" aria-label="Loading">
      <div className="h-4 w-1/2 rounded bg-canvas-dark" />
      <div className="h-10 w-2/3 rounded bg-canvas-dark" />
    </div>
  )
}
