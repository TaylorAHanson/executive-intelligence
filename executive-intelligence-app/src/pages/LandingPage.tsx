import { Link } from 'react-router-dom'
import { ArrowRight, Sparkles } from 'lucide-react'
import { DEFAULT_AGENT_CONTEXT } from '../agentContexts'
import { APP_TITLE, ASSISTANT_NAME } from '../brand'
import { useAgentTray } from '../providers/agentTray'
import { SECTIONS } from '../sections'

/** One tile per dashboard in `SECTIONS`, plus the assistant. */
export default function LandingPage() {
  const tray = useAgentTray()

  return (
    <div className="flex min-h-full justify-center bg-landing-glow px-8 py-12">
      <div className="w-full max-w-[1080px]">
        <div className="mb-10 text-center">
          <div className="mb-[22px] inline-block rounded-full bg-brand/10 px-7 py-3.5 text-[2rem] font-extrabold uppercase tracking-[0.1em] text-brand">
            {APP_TITLE}
          </div>
          <h1 className="mb-3 text-[2.4rem] font-extrabold leading-[1.15] tracking-[-0.012em] text-ink">
            Different personas. Different questions.
            <br />
            <span className="text-brand">One app to answer them all.</span>
          </h1>
          <p className="mx-auto max-w-[720px] leading-normal text-ink-light">
            Each dashboard has its own data and its own agent context. Open one, or ask {ASSISTANT_NAME} from anywhere:
            it answers from the data behind the page you are on.
          </p>
        </div>

        <button
          type="button"
          className="mb-8 flex w-full items-center gap-5 rounded-[18px] bg-gradient-to-br from-brand-bright to-brand-dark px-7 py-6 text-left text-white shadow-supervisor transition-shadow hover:shadow-supervisor-hover"
          onClick={() => tray.open(DEFAULT_AGENT_CONTEXT)}
        >
          <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-white/[.18]">
            <Sparkles className="h-6 w-6" aria-hidden="true" />
          </span>
          <span className="min-w-0 flex-1">
            <span className="block text-[1.45rem] font-extrabold leading-tight">Ask {ASSISTANT_NAME}</span>
            <span className="mt-1 block text-[0.9rem] opacity-85">
              Questions about any dashboard, answered from the same views the dashboard reads.
            </span>
          </span>
          <ArrowRight className="h-5 w-5 shrink-0" aria-hidden="true" />
        </button>

        <div className="grid gap-5 md:grid-cols-2">
          {SECTIONS.map(({ id, path, label, description, icon: Icon }) => (
            <Link
              key={id}
              to={path}
              className="group flex flex-col gap-3 rounded-[14px] border border-line bg-white px-6 py-5 shadow-tile transition hover:border-brand hover:shadow-tile-hover"
            >
              <span className="inline-flex h-11 w-11 items-center justify-center rounded-xl bg-brand text-white">
                <Icon className="h-[22px] w-[22px]" aria-hidden="true" />
              </span>
              <span className="text-[1.15rem] font-bold text-ink">{label}</span>
              <span className="text-[0.92rem] leading-snug text-ink-light">{description}</span>
              <span className="mt-auto inline-flex items-center gap-1 text-[0.88rem] font-semibold text-brand">
                Open dashboard <ArrowRight className="h-3.5 w-3.5 transition-transform group-hover:translate-x-0.5" aria-hidden="true" />
              </span>
            </Link>
          ))}
        </div>
      </div>
    </div>
  )
}
