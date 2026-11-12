import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { ChevronDown, ScrollText, Settings, User } from 'lucide-react'
import { LATEST_VERSION, useUnreadRelease } from '../releaseNotes'
import { useSession } from '../providers/session'

/** "jane.doe@example.com" -> "JD"; "admin@example.com" -> "AD". */
function initials(email: string): string {
  const parts = email.split('@')[0].split(/[._\-+]+/).filter(Boolean)
  const letters = parts.length >= 2 ? parts[0][0] + parts[1][0] : (parts[0] ?? '?').slice(0, 2)
  return letters.toUpperCase()
}

const itemClass =
  'flex w-full items-center gap-2.5 px-4 py-2 text-left text-sm text-ink hover:bg-canvas focus-visible:bg-canvas focus-visible:outline-none'

export default function AccountMenu() {
  const { user } = useSession()
  const unread = useUnreadRelease()
  const [open, setOpen] = useState(false)
  const root = useRef<HTMLDivElement>(null)
  const trigger = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    if (!open) return
    root.current?.querySelector<HTMLElement>('[role="menuitem"]')?.focus()
    const onPointer = (e: PointerEvent) => {
      if (!root.current?.contains(e.target as Node)) setOpen(false)
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setOpen(false)
        trigger.current?.focus()
      }
    }
    document.addEventListener('pointerdown', onPointer)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('pointerdown', onPointer)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  return (
    <div ref={root} className="relative">
      <button
        ref={trigger}
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={user ? `Account menu for ${user.email}` : 'Account menu'}
        title={user?.email}
        className="flex items-center gap-1 rounded-full p-0.5 pr-1.5 text-ink-light hover:bg-canvas focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand"
        onClick={() => setOpen((o) => !o)}
      >
        <span className="relative flex h-8 w-8 items-center justify-center rounded-full bg-brand text-xs font-semibold text-white">
          {user ? initials(user.email) : <User className="h-4 w-4" aria-hidden="true" />}
          {unread && (
            <span className="absolute -right-0.5 -top-0.5 h-2.5 w-2.5 rounded-full bg-accent ring-2 ring-white" aria-hidden="true" />
          )}
        </span>
        <ChevronDown className={`h-4 w-4 transition-transform ${open ? 'rotate-180' : ''}`} aria-hidden="true" />
      </button>

      {open && (
        <div
          role="menu"
          aria-label="Account"
          className="absolute right-0 top-full z-50 mt-2 w-72 overflow-hidden rounded-xl border border-line bg-white py-1 shadow-tile-hover"
        >
          <div className="border-b border-line px-4 py-3">
            <p className="truncate text-sm font-semibold text-ink">{user ? user.email : 'Not signed in'}</p>
            {user && (
              <p className="mt-0.5 text-xs text-ink-muted">
                {user.local_dev ? 'Local development, as your CLI login' : 'Signed in through Databricks'}
              </p>
            )}
          </div>

          <div className="py-1">
            {user?.is_admin && (
              <Link to="/settings" role="menuitem" className={itemClass} onClick={() => setOpen(false)}>
                <Settings className="h-4 w-4 text-ink-light" aria-hidden="true" />
                <span className="flex-1">Settings</span>
              </Link>
            )}
            <Link to="/release-notes" role="menuitem" className={itemClass} onClick={() => setOpen(false)}>
              <ScrollText className="h-4 w-4 text-ink-light" aria-hidden="true" />
              <span className="flex-1">Release notes</span>
              {unread && <span className="rounded-full bg-accent px-1.5 py-0.5 text-[0.65rem] font-semibold text-white">New</span>}
            </Link>
          </div>

          <p className="border-t border-line px-4 py-2 text-xs text-ink-muted">Version {LATEST_VERSION}</p>
        </div>
      )}
    </div>
  )
}
