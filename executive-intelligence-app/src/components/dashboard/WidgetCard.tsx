import type { ReactNode } from 'react'
import AskAboutButton from './AskAboutButton'

/** Columns out of 12 on wide screens. Every widget is full width on narrow ones. */
export type WidgetSpan = 3 | 4 | 6 | 8 | 12

// Spelled out, because Tailwind only generates classes it finds verbatim.
const SPAN_CLASS: Record<WidgetSpan, string> = {
  3: 'lg:col-span-3',
  4: 'lg:col-span-4',
  6: 'lg:col-span-6',
  8: 'lg:col-span-8',
  12: 'lg:col-span-12',
}

export interface WidgetFrameProps {
  title: string
  subtitle?: string
  span?: WidgetSpan
  /** A question about this widget for the agent tray. Adds an Ask button. */
  askAbout?: string
}

/** The card every dashboard widget sits in. */
export default function WidgetCard({
  title,
  subtitle,
  span = 6,
  askAbout,
  children,
}: WidgetFrameProps & { children: ReactNode }) {
  return (
    <section className={`col-span-12 flex min-w-0 flex-col rounded-xl border border-line bg-white p-4 shadow-tile ${SPAN_CLASS[span]}`}>
      <header className="mb-3 flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <h3 className="truncate text-sm font-semibold text-ink">{title}</h3>
          {subtitle && <p className="truncate text-xs text-ink-muted">{subtitle}</p>}
        </div>
        {askAbout && <AskAboutButton question={askAbout} />}
      </header>
      <div className="flex min-h-0 flex-1 flex-col">{children}</div>
    </section>
  )
}
