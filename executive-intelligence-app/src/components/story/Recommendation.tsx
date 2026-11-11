import { ArrowRight, BarChart3, ChevronDown, FileSignature, FileText, Target, UserRound } from 'lucide-react'
import { chapter } from './chapters'
import { parseEvidence, type InsightRow } from './insights'

const EVIDENCE_ICON = {
  signal: FileText,
  contract: FileSignature,
  opportunity: Target,
  metric: BarChart3,
} as const

/** One recommendation as cause, effect, and action, with its owner and the evidence behind it. */
export default function Recommendation({ insight, number }: { insight: InsightRow; number: number }) {
  const { color } = chapter('act')
  const evidence = parseEvidence(insight.evidence)
  const steps = [
    { label: 'Because', text: insight.cause },
    { label: 'Which means', text: insight.effect },
    { label: 'So we', text: insight.action },
  ].filter((step) => step.text)

  return (
    <article className="rounded-2xl border border-line bg-white p-6 shadow-[0_1px_2px_rgba(21,21,21,.04)]">
      <div className="flex items-start gap-3">
        <span
          className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-sm font-bold text-white"
          style={{ background: color }}
        >
          {number}
        </span>
        <h4 className="text-[1.15rem] font-semibold leading-snug text-ink">{insight.title}</h4>
      </div>

      <dl className="mt-5 grid gap-5 md:grid-cols-[1fr_auto_1fr_auto_1fr] md:gap-3">
        {steps.map((step, i) => (
          <div key={step.label} className="contents">
            <div>
              <dt className="mb-1 text-[0.7rem] font-bold uppercase tracking-[0.12em] text-ink-muted">{step.label}</dt>
              <dd className={`text-[0.95rem] leading-relaxed ${i === steps.length - 1 ? 'font-medium text-ink' : 'text-ink-light'}`}>
                {step.text}
              </dd>
            </div>
            {i < steps.length - 1 && (
              <ArrowRight className="mt-6 hidden h-4 w-4 text-line md:block" aria-hidden="true" />
            )}
          </div>
        ))}
      </dl>

      <div className="mt-5 flex flex-wrap items-start justify-between gap-3 border-t border-line pt-4 text-sm">
        {insight.owner && (
          <span className="inline-flex items-center gap-1.5 text-ink-light">
            <UserRound className="h-4 w-4 text-ink-muted" aria-hidden="true" />
            {insight.owner}
          </span>
        )}
        {evidence.length > 0 && (
          <details className="group ml-auto max-w-full text-right">
            <summary className="inline-flex cursor-pointer list-none items-center gap-1 text-ink-muted hover:text-ink">
              Evidence ({evidence.length})
              <ChevronDown className="h-4 w-4 transition-transform group-open:rotate-180" aria-hidden="true" />
            </summary>
            <ul className="mt-3 space-y-2 text-left">
              {evidence.map((item) => {
                const Icon = EVIDENCE_ICON[item.kind as keyof typeof EVIDENCE_ICON] ?? FileText
                return (
                  <li key={`${item.kind}-${item.ref}`} className="flex items-start gap-2 text-[0.85rem] text-ink-light">
                    <Icon className="mt-0.5 h-3.5 w-3.5 shrink-0 text-ink-muted" aria-hidden="true" />
                    {item.label}
                  </li>
                )
              })}
            </ul>
          </details>
        )}
      </div>
    </article>
  )
}
