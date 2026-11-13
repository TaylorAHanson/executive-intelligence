import {
  lazy,
  Suspense,
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent,
  type PointerEvent as ReactPointerEvent,
} from 'react'
import { Check, Loader2, RotateCcw, Send, ShieldAlert, Sparkles, Wrench, X } from 'lucide-react'
import {
  ApiError,
  resumeAgent,
  sendAgentMessage,
  type AgentMessage,
  type AgentTurn,
  type ApprovalDecision,
  type PendingAction,
} from '../api'
import { AGENT_CONTEXTS } from '../agentContexts'
import { ASSISTANT_NAME } from '../brand'
import { useMediaQuery } from '../hooks/useMediaQuery'
import { TRAY_OVERLAY_QUERY, useAgentTray } from '../providers/agentTray'

// Loaded on the first agent reply rather than with every page.
const Markdown = lazy(() => import('./Markdown'))

const DEFAULT_WIDTH = 420
const MIN_WIDTH = 340
const WIDTH_KEY = 'agentTray.width'
// Leave the page at least this much room beside the tray.
const MIN_PAGE_WIDTH = 480

const clampWidth = (width: number) =>
  Math.round(Math.min(Math.max(width, MIN_WIDTH), Math.max(MIN_WIDTH, window.innerWidth - MIN_PAGE_WIDTH)))

const savedWidth = () => {
  const saved = Number(localStorage.getItem(WIDTH_KEY))
  return saved ? clampWidth(saved) : DEFAULT_WIDTH
}

interface Conversation {
  /** Browser-side id only; the backend hashes it with the user's identity. */
  sessionId: string
  messages: AgentMessage[]
  pending: PendingAction[] | null
}

const newConversation = (): Conversation => ({
  sessionId: crypto.randomUUID(),
  messages: [],
  pending: null,
})

/**
 * The agent, docked on the right of every page. Open it, or ask it something,
 * through `useAgentTray()`.
 *
 * One conversation per app context, so switching sections doesn't mix threads;
 * long-term memory is shared across them on the agent side. Conversations live
 * in component state and reset on reload.
 */
export default function AgentTray() {
  const { context, contextLocked, setContext, close, focusRequest } = useAgentTray()
  const overlay = useMediaQuery(TRAY_OVERLAY_QUERY)
  const [conversations, setConversations] = useState<Record<string, Conversation>>({})
  const [draft, setDraft] = useState(focusRequest?.draft ?? '')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [width, setWidth] = useState(savedWidth)
  const scrollRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)

  // Adopt a new request's draft during render rather than in an effect, so the
  // input never renders a frame with the stale draft.
  const [handledFocus, setHandledFocus] = useState(focusRequest)
  if (focusRequest !== handledFocus) {
    setHandledFocus(focusRequest)
    if (focusRequest?.draft !== undefined) setDraft(focusRequest.draft)
  }

  const conversation = conversations[context] ?? null
  const messages = conversation?.messages ?? []
  const pending = conversation?.pending ?? null
  const contextLabel = AGENT_CONTEXTS.find((c) => c.id === context)?.label ?? context

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
  }, [messages.length, pending, busy])

  useEffect(() => {
    if (focusRequest) inputRef.current?.focus()
  }, [focusRequest])

  const update = (id: string, change: (current: Conversation) => Conversation) =>
    setConversations((all) => ({ ...all, [id]: change(all[id] ?? newConversation()) }))

  const applyTurn = (id: string, turn: AgentTurn) =>
    update(id, (current) => ({
      ...current,
      messages: [...current.messages, ...turn.messages],
      pending: turn.status === 'interrupted' ? (turn.interrupt?.actions ?? []) : null,
    }))

  const run = async (id: string, call: () => Promise<AgentTurn>) => {
    setBusy(true)
    setError(null)
    try {
      applyTurn(id, await call())
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'The agent could not be reached.')
    } finally {
      setBusy(false)
    }
  }

  const send = async (event?: FormEvent) => {
    event?.preventDefault()
    const message = draft.trim()
    if (!message || busy || pending) return

    const id = context
    const sessionId = (conversations[id] ?? newConversation()).sessionId
    setDraft('')
    update(id, (current) => ({
      ...current,
      sessionId,
      messages: [...current.messages, { role: 'user', content: message }],
    }))
    await run(id, () => sendAgentMessage(sessionId, id, message))
  }

  const decide = async (type: ApprovalDecision['type']) => {
    if (!conversation || !pending) return
    const id = context
    const decisions: ApprovalDecision[] = pending.map(() =>
      type === 'approve' ? { type } : { type, message: 'Rejected by the user in the agent tray.' },
    )
    update(id, (current) => ({ ...current, pending: null }))
    await run(id, () => resumeAgent(conversation.sessionId, id, decisions))
  }

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      void send()
    }
  }

  const resize = (next: number) => {
    const clamped = clampWidth(next)
    setWidth(clamped)
    localStorage.setItem(WIDTH_KEY, String(clamped))
  }

  // The tray is docked to the right edge, so its width is the distance from the pointer to it.
  const onResizeStart = (event: ReactPointerEvent<HTMLDivElement>) => {
    event.preventDefault()
    event.currentTarget.setPointerCapture(event.pointerId)
  }
  const onResizeMove = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (event.currentTarget.hasPointerCapture(event.pointerId)) resize(window.innerWidth - event.clientX)
  }
  const onResizeKey = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === 'ArrowLeft') resize(width + 32)
    else if (event.key === 'ArrowRight') resize(width - 32)
    else return
    event.preventDefault()
  }

  return (
    <aside
      className={
        overlay
          ? 'fixed inset-y-0 right-0 z-40 flex flex-col border-l border-line bg-canvas shadow-supervisor'
          : 'relative flex h-full shrink-0 flex-col border-l border-line bg-canvas'
      }
      style={
        overlay
          ? { width: `min(${width}px, calc(100vw - 1.5rem))` }
          : { width, maxWidth: `max(${MIN_WIDTH}px, calc(100vw - ${MIN_PAGE_WIDTH}px))` }
      }
      aria-label="Agent"
    >
      <div
        role="separator"
        aria-orientation="vertical"
        aria-label="Resize agent tray"
        aria-valuenow={width}
        aria-valuemin={MIN_WIDTH}
        tabIndex={0}
        title="Drag to resize; double-click to reset"
        className="absolute inset-y-0 -left-1 z-10 w-2 cursor-col-resize touch-none hover:bg-brand/20 focus:bg-brand/30 focus:outline-none"
        onPointerDown={onResizeStart}
        onPointerMove={onResizeMove}
        onKeyDown={onResizeKey}
        onDoubleClick={() => resize(DEFAULT_WIDTH)}
      />
      <div className="flex items-center gap-2 border-b border-line bg-white px-4 py-3">
        <Sparkles className="h-5 w-5 text-brand" aria-hidden="true" />
        <h2 className="whitespace-nowrap text-sm font-bold text-ink">{ASSISTANT_NAME}</h2>

        {contextLocked ? (
          // On a dashboard the section decides the context, so the agent
          // always knows which page the question is about.
          <span
            className="ml-2 min-w-0 flex-1 truncate rounded-lg bg-brand/10 px-2 py-1 text-sm font-medium text-brand"
            title="Set by the page you are on"
          >
            {contextLabel}
          </span>
        ) : (
          <select
            className="ml-2 min-w-0 flex-1 rounded-lg border border-line bg-white px-2 py-1 text-sm text-ink focus:border-brand focus:outline-none"
            value={context}
            onChange={(e) => setContext(e.target.value)}
            disabled={busy}
            aria-label="App section the agent is working in"
          >
            {AGENT_CONTEXTS.map((c) => (
              <option key={c.id} value={c.id}>
                {c.label}
              </option>
            ))}
          </select>
        )}

        <button
          type="button"
          className="rounded-lg p-1.5 text-ink-muted hover:bg-canvas-dark hover:text-ink disabled:opacity-40"
          onClick={() => setConversations((all) => ({ ...all, [context]: newConversation() }))}
          disabled={busy || messages.length === 0}
          title="New conversation"
        >
          <RotateCcw className="h-4 w-4" />
        </button>
        <button
          type="button"
          className="rounded-lg p-1.5 text-ink-muted hover:bg-canvas-dark hover:text-ink"
          onClick={close}
          title="Close agent"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      <div ref={scrollRef} className="flex-1 space-y-3 overflow-y-auto px-4 py-4">
        {messages.length === 0 && !busy && (
          <p className="pt-8 text-center text-sm text-ink-muted">Ask {ASSISTANT_NAME} anything about {contextLabel}.</p>
        )}

        {messages.map((message, index) => (
          <MessageView key={index} message={message} />
        ))}

        {pending && <ApprovalCard actions={pending} busy={busy} onDecide={(type) => void decide(type)} />}

        {busy && (
          <div className="flex items-center gap-2 text-sm text-ink-muted">
            <Loader2 className="h-4 w-4 animate-spin text-brand" aria-hidden="true" />
            Thinking…
          </div>
        )}

        {error && (
          <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800" role="alert">
            {error}
          </div>
        )}
      </div>

      <form onSubmit={send} className="border-t border-line bg-white p-3">
        <div className="flex items-end gap-2">
          <textarea
            ref={inputRef}
            className="min-h-[44px] flex-1 resize-none rounded-lg border border-line bg-white px-3 py-2 text-sm text-ink focus:border-brand focus:outline-none focus:ring-2 focus:ring-brand/20"
            rows={2}
            placeholder={pending ? 'Approve or reject the pending action first' : `Ask ${ASSISTANT_NAME} (${contextLabel})`}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={onKeyDown}
            disabled={busy || Boolean(pending)}
            maxLength={8000}
          />
          <button
            type="submit"
            className="rounded-lg bg-brand p-2.5 text-white hover:bg-brand-bright disabled:opacity-40"
            disabled={busy || Boolean(pending) || !draft.trim()}
            title="Send"
          >
            <Send className="h-4 w-4" />
          </button>
        </div>
      </form>
    </aside>
  )
}

function MessageView({ message }: { message: AgentMessage }) {
  if (message.role === 'tool') {
    return (
      <details className="text-xs text-ink-muted">
        <summary className="flex cursor-pointer list-none items-center gap-1.5">
          <Wrench className="h-3.5 w-3.5" aria-hidden="true" />
          Used <code className="font-mono">{message.name}</code>
        </summary>
        <pre className="mt-1 max-h-40 overflow-auto whitespace-pre-wrap rounded-lg bg-canvas-dark p-2 font-mono">
          {message.content}
        </pre>
      </details>
    )
  }

  if (message.role === 'user') {
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] whitespace-pre-wrap rounded-xl bg-brand px-3 py-2 text-sm text-white">
          {message.content}
        </div>
      </div>
    )
  }
  return (
    <div className="flex justify-start">
      <div className="min-w-0 max-w-[92%] break-words rounded-xl border border-line bg-white px-3 py-2 text-sm leading-relaxed text-ink shadow-tile">
        <Suspense fallback={<div className="whitespace-pre-wrap">{message.content}</div>}>
          <Markdown>{message.content}</Markdown>
        </Suspense>
      </div>
    </div>
  )
}

interface ApprovalCardProps {
  actions: PendingAction[]
  busy: boolean
  onDecide: (type: ApprovalDecision['type']) => void
}

function ApprovalCard({ actions, busy, onDecide }: ApprovalCardProps) {
  return (
    <div className="rounded-xl border border-accent/40 bg-accent/5 p-3 text-sm">
      <div className="flex items-center gap-2 font-semibold text-ink">
        <ShieldAlert className="h-4 w-4 text-accent" aria-hidden="true" />
        The agent wants to run {actions.length === 1 ? 'an action' : `${actions.length} actions`}
      </div>
      {actions.map((action, index) => (
        <div key={index} className="mt-2">
          <code className="font-mono text-xs font-semibold text-ink">{action.name}</code>
          <pre className="mt-1 overflow-auto whitespace-pre-wrap rounded-lg bg-white/70 p-2 font-mono text-xs text-ink-light">
            {JSON.stringify(action.args, null, 2)}
          </pre>
        </div>
      ))}
      <div className="mt-3 flex gap-2">
        <button
          type="button"
          className="flex items-center gap-1 rounded-lg bg-brand px-3 py-1.5 text-white hover:bg-brand-bright disabled:opacity-40"
          onClick={() => onDecide('approve')}
          disabled={busy}
        >
          <Check className="h-4 w-4" /> Approve
        </button>
        <button
          type="button"
          className="flex items-center gap-1 rounded-lg border border-line bg-white px-3 py-1.5 text-ink-light hover:bg-canvas disabled:opacity-40"
          onClick={() => onDecide('reject')}
          disabled={busy}
        >
          <X className="h-4 w-4" /> Reject
        </button>
      </div>
    </div>
  )
}
