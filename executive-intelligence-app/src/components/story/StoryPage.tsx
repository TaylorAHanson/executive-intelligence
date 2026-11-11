import { useEffect, useState, type ReactNode } from 'react'
import { Sparkles } from 'lucide-react'
import { CHAPTERS, chapter as chapterDef, type ChapterDef } from './chapters'
import Rich from './Rich'

interface StoryPageProps {
  /** Small line above the headline: what this briefing covers. */
  eyebrow: ReactNode
  /** The one sentence an executive should leave with. Null while it loads. */
  headline: string | null
  /** Which windows the numbers cover. */
  meta: string
  children: ReactNode
  askLabel: string
  onAsk: () => void
  /** Where the narrative came from, shown under the Ask button. */
  provenance?: ReactNode
}

/**
 * A briefing rather than a dashboard: one headline, then four chapters read top
 * to bottom, each ending in what it means. No filters, no grid. The only
 * control is a single Ask at the end.
 */
export default function StoryPage({ eyebrow, headline, meta, children, askLabel, onAsk, provenance }: StoryPageProps) {
  return (
    <div className="min-h-full bg-white">
      <div className="mx-auto max-w-[1000px] px-8 pb-6 pt-10">
        <div className="mb-4 text-[0.78rem] font-semibold uppercase tracking-[0.12em] text-brand">{eyebrow}</div>
        {headline ? (
          <h2 className="max-w-[880px] text-[2rem] font-semibold leading-[1.22] tracking-[-0.015em] text-ink">
            <Rich text={headline} strong="text-brand" />
          </h2>
        ) : (
          <div className="max-w-[820px] animate-pulse space-y-3" aria-label="Loading">
            <div className="h-8 rounded bg-canvas-dark" />
            <div className="h-8 w-3/4 rounded bg-canvas-dark" />
          </div>
        )}
        <p className="mt-4 text-sm text-ink-muted">{meta}</p>
      </div>

      <ChapterNav />

      <div className="mx-auto max-w-[1000px] space-y-16 px-8 pb-12 pt-10">{children}</div>

      <footer className="mx-auto flex max-w-[1000px] flex-col items-center gap-3 border-t border-line px-8 py-10">
        <button
          type="button"
          className="inline-flex items-center gap-2 rounded-full bg-brand px-5 py-2.5 text-sm font-semibold text-white shadow-tile hover:bg-brand-bright"
          onClick={onAsk}
        >
          <Sparkles className="h-4 w-4" aria-hidden="true" />
          {askLabel}
        </button>
        {provenance && <p className="max-w-[640px] text-center text-xs leading-relaxed text-ink-muted">{provenance}</p>}
      </footer>
    </div>
  )
}

/** The four chapters as a quiet rail that tracks where the reader is. */
function ChapterNav() {
  const [active, setActive] = useState<ChapterDef['id']>('know')

  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries.filter((e) => e.isIntersecting)
        if (visible.length) setActive(visible[0].target.id as ChapterDef['id'])
      },
      { rootMargin: '-25% 0px -65% 0px' },
    )
    for (const c of CHAPTERS) {
      const element = document.getElementById(c.id)
      if (element) observer.observe(element)
    }
    return () => observer.disconnect()
  }, [])

  return (
    <nav className="sticky top-0 z-10 border-y border-line bg-white/90 backdrop-blur" aria-label="Briefing chapters">
      <ol className="mx-auto flex max-w-[1000px] items-center px-8 py-3">
        {CHAPTERS.map((c, i) => {
          const isActive = c.id === active
          return (
            <li key={c.id} className="flex flex-1 items-center last:flex-none">
              <a
                href={`#${c.id}`}
                className={`flex items-center gap-2 text-sm font-semibold transition-colors ${isActive ? 'text-ink' : 'text-ink-muted hover:text-ink-light'}`}
                aria-current={isActive ? 'step' : undefined}
                onClick={(event) => {
                  event.preventDefault()
                  document.getElementById(c.id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
                }}
              >
                <span
                  className="h-2.5 w-2.5 rounded-full transition-shadow"
                  style={{ background: c.color, boxShadow: isActive ? `0 0 0 4px color-mix(in srgb, ${c.color} 22%, transparent)` : undefined }}
                />
                {c.verb}
              </a>
              {i < CHAPTERS.length - 1 && <span className="mx-4 h-px flex-1 bg-line" aria-hidden="true" />}
            </li>
          )
        })}
      </ol>
    </nav>
  )
}

interface ChapterProps {
  id: ChapterDef['id']
  /** The question this chapter answers, in the reader's words. */
  title: string
  /** The chapter's conclusion from the insight records. */
  soWhat: string | null
  children: ReactNode
}

export function Chapter({ id, title, soWhat, children }: ChapterProps) {
  const c = chapterDef(id)
  const number = CHAPTERS.indexOf(c) + 1
  return (
    <section id={id} className="scroll-mt-20" aria-labelledby={`${id}-title`}>
      <div className="mb-5 flex items-baseline gap-3">
        <span className="text-xs font-bold uppercase tracking-[0.14em]" style={{ color: c.color }}>
          {String(number).padStart(2, '0')} · {c.verb}
        </span>
      </div>
      <h3 id={`${id}-title`} className="mb-6 text-[1.45rem] font-semibold tracking-[-0.01em] text-ink">
        {title}
      </h3>
      <div className="space-y-6">{children}</div>
      {soWhat && <SoWhat color={c.color} text={soWhat} />}
    </section>
  )
}

function SoWhat({ color, text }: { color: string; text: string }) {
  return (
    <div
      className="mt-7 rounded-r-xl border-l-4 px-5 py-4"
      style={{ borderColor: color, background: `color-mix(in srgb, ${color} 6%, white)` }}
    >
      <div className="mb-1 text-[0.7rem] font-bold uppercase tracking-[0.14em]" style={{ color }}>
        So what
      </div>
      <p className="text-[1.05rem] leading-relaxed text-ink">
        <Rich text={text} />
      </p>
    </div>
  )
}
