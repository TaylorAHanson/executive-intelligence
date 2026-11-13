import { History } from 'lucide-react'
import type { SinceLastVisit } from './lastVisit'

/** What moved since the reader last looked, or a plain statement that nothing did. Nothing on a first visit. */
export default function WhatChanged({ visit }: { visit: SinceLastVisit | null }) {
  if (!visit) return null
  const { since, changes } = visit
  return (
    <section aria-label="What changed" className="rounded-xl bg-canvas px-4 py-3">
      <div className="flex items-start gap-2.5">
        <History className="mt-0.5 h-4 w-4 shrink-0 text-ink-muted" aria-hidden="true" />
        <div className="min-w-0 text-sm">
          <div className="font-semibold text-ink">
            {changes.length ? `Since you last looked, ${since}` : `Nothing has moved since you last looked, ${since}`}
          </div>
          {changes.length > 0 && (
            <ul className="mt-1 list-disc space-y-0.5 pl-4 text-ink-light">
              {changes.map((c) => (
                <li key={c}>{c}</li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </section>
  )
}
