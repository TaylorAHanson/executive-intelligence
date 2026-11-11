import type { ReactNode } from 'react'
import { Link, NavLink } from 'react-router-dom'
import { BarChart3, Home, Sparkles } from 'lucide-react'
import { APP_TITLE, ASSISTANT_NAME, LOGO_URL } from '../brand'
import { SECTIONS } from '../sections'
import { useAgentTray } from '../providers/agentTray'
import { useSession } from '../providers/session'
import AgentTray from './AgentTray'

interface LayoutProps {
  children: ReactNode
  title: string
}

const navClass = ({ isActive }: { isActive: boolean }) =>
  `flex items-center gap-1.5 whitespace-nowrap rounded-lg px-3 py-1.5 text-sm font-medium transition-colors ${
    isActive ? 'bg-brand/10 text-brand' : 'text-ink-light hover:bg-canvas hover:text-ink'
  }`

export default function Layout({ children, title }: LayoutProps) {
  const { user, environment, syntheticData } = useSession()
  const tray = useAgentTray()

  return (
    <div className="flex h-screen flex-col">
      <header className="flex h-16 shrink-0 items-center gap-3 border-b border-line bg-white px-6 text-ink">
        <Link to="/" className="flex shrink-0 items-center gap-3">
          {LOGO_URL ? (
            <img src={LOGO_URL} alt={APP_TITLE} className="block h-10 w-auto shrink-0" />
          ) : (
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-brand text-white">
              <BarChart3 className="h-5 w-5" aria-hidden="true" />
            </span>
          )}
          <div className="border-l border-line pl-3">
            <h1 className="text-[1.2rem] font-bold leading-tight tracking-[-0.005em]">{title}</h1>
            {title !== 'Executive Intelligence' && <p className="text-[0.72rem] text-ink-muted">Executive Intelligence</p>}
          </div>
        </Link>

        {/* Anything that isn't prod is badged, so nobody mistakes a dev
            deployment for the real one. */}
        {environment && environment !== 'prod' && (
          <span className="rounded bg-accent px-2 py-0.5 text-xs font-semibold uppercase tracking-wide text-white">
            {environment}
          </span>
        )}
        {/* Every figure and sentence on screen is invented until the contract
            views read real tables; see data/contract.md. */}
        {syntheticData && (
          <span
            className="whitespace-nowrap rounded border border-accent/40 px-2 py-0.5 text-xs font-medium text-accent"
            title="The dashboards read synthetic data. Companies, figures, and sources are invented."
          >
            Synthetic data
          </span>
        )}

        <nav className="ml-4 flex min-w-0 items-center gap-1 overflow-x-auto" aria-label="Dashboards">
          <NavLink to="/" end className={navClass}>
            <Home className="h-4 w-4" aria-hidden="true" />
            Home
          </NavLink>
          {SECTIONS.map(({ id, path, label, icon: Icon }) => (
            <NavLink key={id} to={path} className={navClass}>
              <Icon className="h-4 w-4" aria-hidden="true" />
              {label}
            </NavLink>
          ))}
        </nav>

        <div className="ml-auto flex shrink-0 items-center gap-4 text-sm text-ink-light">
          {user ? (
            <span title={user.local_dev ? 'Local development session' : 'Signed in through Databricks Apps'}>
              {user.email}
              {user.local_dev && ' (local)'}
            </span>
          ) : (
            <span>Not signed in</span>
          )}
          {!tray.isOpen && (
            <button
              type="button"
              className="flex items-center gap-1.5 rounded-lg bg-brand px-3 py-1.5 font-medium text-white hover:bg-brand-bright"
              onClick={() => tray.open()}
            >
              <Sparkles className="h-4 w-4" aria-hidden="true" />
              Ask {ASSISTANT_NAME}
            </button>
          )}
        </div>
      </header>

      <div className="flex min-h-0 flex-1">
        <main className="min-w-0 flex-1 overflow-y-auto">{children}</main>
        {/* Hidden rather than unmounted, so closing the tray keeps its conversations. */}
        <div className={tray.isOpen ? 'contents' : 'hidden'}>
          <AgentTray />
        </div>
      </div>
    </div>
  )
}
