import { useState, type Dispatch, type ReactNode, type SetStateAction } from 'react'
import { useMutation, useQueries, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ChevronDown,
  ChevronRight,
  Database,
  Loader2,
  Plug,
  Plus,
  RefreshCw,
  Search,
  Trash2,
  Wrench,
  X,
  type LucideIcon,
} from 'lucide-react'
import {
  listGenieSpaces,
  listMcpServices,
  listMcpServiceTools,
  lookupGenieSpace,
  type GenieSpaceInfo,
  type GenieSpaceSetting,
  type McpServiceSetting,
  type McpServiceTools,
  type McpToolInfo,
} from '../../api'

const GENIE_NAME_RE = /^[a-z][a-z0-9_]{0,23}$/
const SPACE_ID_RE = /^[0-9a-f]{32}$/
const SCHEMA_RE = /^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$/
const MAX_SPACES = 10
const MAX_SERVICES = 10
const LISTING_STALE_MS = 5 * 60_000
const PREVIEW_ROWS = 8
const SEARCH_ROWS = 50

type Source = 'builtin' | 'genie' | 'mcp'
const SOURCES: { id: Source; label: string; icon: LucideIcon }[] = [
  { id: 'builtin', label: 'Built-in', icon: Wrench },
  { id: 'genie', label: 'Genie spaces', icon: Database },
  { id: 'mcp', label: 'MCP services', icon: Plug },
]
const ICONS = Object.fromEntries(SOURCES.map((s) => [s.id, s.icon])) as Record<Source, LucideIcon>
const KIND = { builtin: 'Built-in', genie: 'Genie space', mcp: 'MCP service' } as const

const message = (error: unknown) => (error instanceof Error ? error.message : 'Something went wrong.')
/** Service comments are Markdown; the picker shows them as plain text, without a trailing docs link. */
const plain = (text: string) =>
  text
    .replace(/\s*\[Documentation\]\([^)]*\)\s*$/i, '')
    .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
    .replace(/[*_`]/g, '')
const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? '' : 's'}`
const toolsKey = (service: string) => ['settings', 'mcpTools', service]

function suggestGenieName(title: string, taken: string[]) {
  const name = title.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '').slice(0, 24)
  return GENIE_NAME_RE.test(name) && !taken.includes(name) ? name : ''
}

interface Candidate {
  key: string
  source: Source
  title: string
  subtitle?: string
  description: string
  add: () => void
  /** Why it can't be added right now. */
  blocked?: string
}

export interface ToolPickerProps {
  builtinTools: { name: string; description: string }[]
  builtin: string[]
  setBuiltin: Dispatch<SetStateAction<string[]>>
  spaces: GenieSpaceSetting[]
  setSpaces: Dispatch<SetStateAction<GenieSpaceSetting[]>>
  services: McpServiceSetting[]
  setServices: Dispatch<SetStateAction<McpServiceSetting[]>>
}

/**
 * Every tool a context may use, in one list: built-in tools, Genie spaces, and Unity Catalog MCP
 * services (AI Gateway → MCPs). What is on comes first; below it, search what the signed-in admin
 * can reach and add it. Genie spaces and MCP services are listed as the admin, and both run as
 * whoever asks the assistant.
 */
export default function ToolPicker(props: ToolPickerProps) {
  const { builtinTools, builtin, setBuiltin, spaces, setSpaces, services, setServices } = props
  const [query, setQuery] = useState('')
  const [hidden, setHidden] = useState<Source[]>([])
  const [showAll, setShowAll] = useState(false)
  const [schemas, setSchemas] = useState(['system.ai'])
  const [adding, setAdding] = useState<GenieSpaceInfo | null>(null)
  const [expanded, setExpanded] = useState<string | null>(null)

  const genie = useQuery({
    queryKey: ['settings', 'genieSpaces'],
    queryFn: listGenieSpaces,
    staleTime: LISTING_STALE_MS,
    retry: false,
  })
  const mcpLists = useQueries({
    queries: schemas.map((schema) => ({
      queryKey: ['settings', 'mcpServices', schema],
      queryFn: () => listMcpServices(schema),
      staleTime: LISTING_STALE_MS,
      retry: false,
    })),
  })
  const comments = new Map(
    mcpLists.flatMap((list) => list.data?.services ?? []).map((s) => [s.service, plain(s.comment)]),
  )

  const takenNames = spaces.map((s) => s.name)
  const addService = (service: string) => {
    setServices((current) => [...current, { service, tools: null, approve: null }])
    setExpanded(service)
  }

  const q = query.trim().toLowerCase()
  const matches = (...parts: (string | undefined)[]) => !q || parts.some((p) => p?.toLowerCase().includes(q))
  const candidates: Candidate[] = [
    ...builtinTools
      .filter((t) => !builtin.includes(t.name))
      .map((t) => ({
        key: `builtin:${t.name}`,
        source: 'builtin' as const,
        title: t.name,
        description: t.description,
        add: () => setBuiltin((current) => [...current, t.name]),
      })),
    ...mcpLists
      .flatMap((list) => list.data?.services ?? [])
      .filter((s, i, all) => !services.some((x) => x.service === s.service) && all.findIndex((x) => x.service === s.service) === i)
      .map((s) => ({
        key: `mcp:${s.service}`,
        source: 'mcp' as const,
        title: s.service,
        subtitle: s.databricks_managed ? 'Run by Databricks' : undefined,
        description: plain(s.comment),
        add: () => addService(s.service),
        blocked: services.length >= MAX_SERVICES ? `A context can have ${MAX_SERVICES} MCP services.` : undefined,
      })),
    ...(genie.data?.spaces ?? [])
      .filter((s) => !spaces.some((x) => x.space_id === s.space_id))
      .map((s) => ({
        key: `genie:${s.space_id}`,
        source: 'genie' as const,
        title: s.title || s.space_id,
        description: s.description,
        add: () => setAdding(s),
        blocked: spaces.length >= MAX_SPACES ? `A context can have ${MAX_SPACES} Genie spaces.` : undefined,
      })),
  ].filter((c) => matches(c.title, c.description, c.key))

  const counts = new Map<Source, number>()
  for (const c of candidates) counts.set(c.source, (counts.get(c.source) ?? 0) + 1)
  const shown = candidates.filter((c) => !hidden.includes(c.source))
  const limit = showAll ? shown.length : q ? SEARCH_ROWS : PREVIEW_ROWS
  const loading = genie.isPending || mcpLists.some((list) => list.isPending)
  const onCount = builtin.length + spaces.length + services.length

  return (
    <div>
      <p className="mb-3 text-xs text-ink-light">
        Everything the assistant may use here. Genie spaces and MCP services run as the person asking, with their own
        access. Memory tools (remember, recall, forget) are always on.
      </p>

      <SectionLabel>On in this context · {onCount}</SectionLabel>
      {onCount === 0 ? (
        <p className="rounded-lg border border-dashed border-line px-4 py-3 text-sm text-ink-light">
          Nothing is on. The assistant can only answer from its instructions and memory here.
        </p>
      ) : (
        <ul className="divide-y divide-line rounded-lg border border-line">
          {builtinTools
            .filter((t) => builtin.includes(t.name))
            .map((t) => (
              <AttachedRow
                key={`builtin:${t.name}`}
                source="builtin"
                title={<code className="font-medium">{t.name}</code>}
                description={t.description}
                onRemove={() => setBuiltin((current) => current.filter((n) => n !== t.name))}
                removeLabel={`Turn off ${t.name}`}
              />
            ))}
          {spaces.map((s) => (
            <AttachedRow
              key={`genie:${s.name}`}
              source="genie"
              title={s.title || 'Genie space'}
              meta={<code className="text-xs text-ink-muted">{s.name}_*</code>}
              description={s.description}
              onRemove={() => setSpaces((current) => current.filter((x) => x.name !== s.name))}
              removeLabel={`Remove ${s.title || s.name}`}
            />
          ))}
          {services.map((s) => (
            <McpServiceRow
              key={`mcp:${s.service}`}
              setting={s}
              comment={comments.get(s.service)}
              open={expanded === s.service}
              onToggle={() => setExpanded((current) => (current === s.service ? null : s.service))}
              onChange={(next) => setServices((current) => current.map((x) => (x.service === s.service ? next : x)))}
              onRemove={() => setServices((current) => current.filter((x) => x.service !== s.service))}
            />
          ))}
        </ul>
      )}
      {spaces.length === 0 && services.length === 0 && (
        <p className="mt-2 text-xs text-ink-muted">No data tools: the assistant can't quote figures in this context.</p>
      )}

      <div className="mt-6">
        <SectionLabel>Add</SectionLabel>
        <div className="relative">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-muted" aria-hidden="true" />
          <input
            value={query}
            onChange={(e) => {
              setQuery(e.target.value)
              setShowAll(false)
            }}
            placeholder="Search built-in tools, Genie spaces and MCP services…"
            aria-label="Search tools to add"
            className="w-full rounded-lg border border-line py-2 pl-8 pr-3 text-sm text-ink focus:border-brand focus:outline-none"
          />
        </div>
        <div className="mt-2 flex flex-wrap items-center gap-1.5">
          {SOURCES.map(({ id, label }) => {
            const on = !hidden.includes(id)
            return (
              <button
                key={id}
                type="button"
                aria-pressed={on}
                onClick={() => setHidden((current) => (on ? [...current, id] : current.filter((x) => x !== id)))}
                className={`rounded-full border px-2.5 py-0.5 text-xs ${
                  on ? 'border-brand/40 bg-brand/10 text-brand' : 'border-line bg-white text-ink-muted hover:text-ink'
                }`}
              >
                {label} · {counts.get(id) ?? 0}
              </button>
            )
          })}
          {loading && <Loader2 className="h-3.5 w-3.5 animate-spin text-ink-muted" aria-label="Loading what you can add" />}
        </div>

        {genie.isError && (
          <Problem>Couldn't list your Genie spaces: {message(genie.error)} You can still add one by id below.</Problem>
        )}
        {mcpLists.map((list, i) =>
          list.isError ? (
            <Problem key={schemas[i]}>
              Couldn't list the MCP services in <code>{schemas[i]}</code>: {message(list.error)}
            </Problem>
          ) : null,
        )}

        {shown.length > 0 ? (
          <ul className="mt-3 divide-y divide-line rounded-lg border border-line">
            {shown.slice(0, limit).map((c) => (
              <li key={c.key} className="px-3 py-2.5">
                <div className="flex items-start gap-3">
                  <SourceIcon source={c.source} />
                  <div className="min-w-0 flex-1 text-sm">
                    <p className="flex flex-wrap items-center gap-x-2 font-medium text-ink">
                      <span className={c.source === 'genie' ? '' : 'font-mono text-[0.8rem]'}>{c.title}</span>
                      <Kind source={c.source} />
                      {c.subtitle && <span className="text-[0.68rem] text-ink-muted">{c.subtitle}</span>}
                    </p>
                    {c.description && <p className="mt-0.5 line-clamp-2 text-xs text-ink-light">{c.description}</p>}
                  </div>
                  <button
                    type="button"
                    onClick={c.add}
                    disabled={!!c.blocked}
                    title={c.blocked}
                    className="flex shrink-0 items-center gap-1 rounded-lg border border-line px-2.5 py-1 text-xs font-medium text-ink hover:bg-canvas disabled:opacity-40"
                  >
                    <Plus className="h-3.5 w-3.5" aria-hidden="true" />
                    Add
                  </button>
                </div>
                {c.source === 'genie' && adding && `genie:${adding.space_id}` === c.key && (
                  <GenieSpaceForm
                    space={adding}
                    taken={takenNames}
                    onAdd={(space) => {
                      setSpaces((current) => [...current, space])
                      setAdding(null)
                    }}
                    onCancel={() => setAdding(null)}
                  />
                )}
              </li>
            ))}
          </ul>
        ) : (
          !loading && (
            <p className="mt-3 text-sm text-ink-light">
              {q ? <>Nothing you can add matches “{query.trim()}”.</> : 'Everything you can reach is already on.'}
              {hidden.length > 0 && ' Some sources are switched off above.'}
            </p>
          )
        )}
        {shown.length > limit && (
          <button type="button" className="mt-2 text-xs font-medium text-brand hover:underline" onClick={() => setShowAll(true)}>
            Show all {shown.length}
          </button>
        )}

        <SchemaList schemas={schemas} setSchemas={setSchemas} />

        {spaces.length < MAX_SPACES && (
          <details className="mt-3 text-xs text-ink-light">
            <summary className="cursor-pointer select-none">Can't find a Genie space? Add it by id</summary>
            <AddGenieSpaceById taken={takenNames} onAdd={(s) => setSpaces((current) => [...current, s])} />
          </details>
        )}
      </div>
    </div>
  )
}

function SectionLabel({ children }: { children: ReactNode }) {
  return <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-ink-muted">{children}</p>
}

function Problem({ children }: { children: ReactNode }) {
  return (
    <p role="alert" className="mt-2 rounded-lg border border-accent/40 bg-accent/5 px-3 py-2 text-xs text-ink">
      {children}
    </p>
  )
}

function SourceIcon({ source }: { source: Source }) {
  const Icon = ICONS[source]
  return <Icon className="mt-0.5 h-4 w-4 shrink-0 text-brand" aria-hidden="true" />
}

function Kind({ source }: { source: Source }) {
  return (
    <span className="rounded bg-canvas px-1.5 py-0.5 text-[0.65rem] font-semibold uppercase tracking-wide text-ink-muted">
      {KIND[source]}
    </span>
  )
}

function RemoveButton({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <button type="button" className="rounded p-1 text-ink-muted hover:bg-canvas hover:text-accent" aria-label={label} title={label} onClick={onClick}>
      <Trash2 className="h-4 w-4" aria-hidden="true" />
    </button>
  )
}

function AttachedRow(props: {
  source: Source
  title: ReactNode
  meta?: ReactNode
  description?: string
  onRemove: () => void
  removeLabel: string
}) {
  return (
    <li className="flex items-start gap-3 px-3 py-2.5">
      <SourceIcon source={props.source} />
      <div className="min-w-0 flex-1 text-sm">
        <p className="flex flex-wrap items-center gap-x-2 font-semibold text-ink">
          {props.title}
          <Kind source={props.source} />
          {props.meta}
        </p>
        {props.description && <p className="mt-0.5 line-clamp-2 text-xs text-ink-light">{props.description}</p>}
      </div>
      <RemoveButton label={props.removeLabel} onClick={props.onRemove} />
    </li>
  )
}

function summary(setting: McpServiceSetting) {
  const tools = setting.tools === null ? 'All tools' : plural(setting.tools.length, 'tool')
  const asks =
    setting.approve === null
      ? 'asks first unless read-only'
      : setting.approve.length === 0
        ? 'never asks first'
        : `asks first for ${setting.approve.length}`
  return `${tools} · ${asks}`
}

function McpServiceRow(props: {
  setting: McpServiceSetting
  comment?: string
  open: boolean
  onToggle: () => void
  onChange: (next: McpServiceSetting) => void
  onRemove: () => void
}) {
  const { setting, open } = props
  const Chevron = open ? ChevronDown : ChevronRight
  return (
    <li className="px-3 py-2.5">
      <div className="flex items-start gap-3">
        <SourceIcon source="mcp" />
        <div className="min-w-0 flex-1 text-sm">
          <p className="flex flex-wrap items-center gap-x-2 font-semibold text-ink">
            <span className="font-mono text-[0.8rem]">{setting.service}</span>
            <Kind source="mcp" />
            <span className="text-xs font-normal text-ink-muted">{summary(setting)}</span>
          </p>
          {props.comment && <p className="mt-0.5 line-clamp-2 text-xs text-ink-light">{props.comment}</p>}
        </div>
        <button
          type="button"
          onClick={props.onToggle}
          aria-expanded={open}
          className="flex shrink-0 items-center gap-1 rounded-lg px-2 py-1 text-xs font-medium text-brand hover:bg-canvas"
        >
          <Chevron className="h-3.5 w-3.5" aria-hidden="true" />
          Tools
        </button>
        <RemoveButton label={`Remove ${setting.service}`} onClick={props.onRemove} />
      </div>
      {open && <McpToolsEditor setting={setting} onChange={props.onChange} />}
    </li>
  )
}

/** Which of a service's tools the context offers, and which wait for the user's approval. */
function McpToolsEditor({ setting, onChange }: { setting: McpServiceSetting; onChange: (next: McpServiceSetting) => void }) {
  const queryClient = useQueryClient()
  const listing = useQuery({
    queryKey: toolsKey(setting.service),
    queryFn: () => listMcpServiceTools(setting.service),
    staleTime: LISTING_STALE_MS,
    retry: false,
  })
  const refresh = useMutation({
    mutationFn: () => listMcpServiceTools(setting.service, true),
    onSuccess: (data) => queryClient.setQueryData<McpServiceTools>(toolsKey(setting.service), data),
  })

  const tools = listing.data?.tools ?? []
  const offerable = tools.filter((t) => t.offerable).map((t) => t.name)
  const offered = (t: McpToolInfo) => t.offerable && (setting.tools === null || setting.tools.includes(t.name))
  const asksFirst = (t: McpToolInfo) => (setting.approve === null ? !t.read_only : setting.approve.includes(t.name))
  const toggle = (list: string[], name: string) => (list.includes(name) ? list.filter((n) => n !== name) : [...list, name])
  const problem = listing.data?.problem
  const error = refresh.error ?? listing.error

  return (
    <div className="ml-7 mt-3 rounded-lg bg-canvas p-3">
      <div className="mb-2 flex items-center justify-between gap-3">
        <p className="text-xs text-ink-light">
          Tools run as the person asking. <strong className="font-semibold text-ink">Ask first</strong> pauses for their
          approval in the assistant before the tool runs.
        </p>
        <button
          type="button"
          onClick={() => refresh.mutate()}
          disabled={refresh.isPending || listing.isPending}
          className="flex shrink-0 items-center gap-1 rounded-lg border border-line bg-white px-2 py-1 text-xs font-medium text-ink hover:bg-canvas disabled:opacity-40"
        >
          <RefreshCw className={`h-3.5 w-3.5 ${refresh.isPending ? 'animate-spin' : ''}`} aria-hidden="true" />
          Refresh
        </button>
      </div>

      {listing.isPending && (
        <p className="flex items-center gap-2 text-xs text-ink-muted">
          <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" /> Asking {setting.service} for its tools…
        </p>
      )}
      {error && <Problem>{message(error)}</Problem>}
      {problem &&
        (problem.sign_in ? (
          <Problem>
            You haven't connected <strong>{setting.service}</strong> yet, so its tools can't be listed. In Databricks, open{' '}
            <strong>AI Gateway → MCPs</strong>, choose it and sign in, then click Refresh. Everyone who asks the assistant
            connects their own account the same way; until they do, it answers without this service.
          </Problem>
        ) : (
          <Problem>
            {setting.service} didn't list its tools: {problem.detail}
          </Problem>
        ))}

      {tools.length > 0 && (
        <table className="w-full text-left text-xs">
          <thead>
            <tr className="text-ink-muted">
              <th className="w-14 pb-1 font-medium">Offer</th>
              <th className="pb-1 font-medium">Tool</th>
              <th className="w-20 pb-1 text-center font-medium">Ask first</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {tools.map((t) => (
              <tr key={t.name} className="align-top">
                <td className="py-2">
                  <input
                    type="checkbox"
                    className="accent-brand"
                    checked={offered(t)}
                    disabled={!t.offerable}
                    aria-label={`Offer ${t.name}`}
                    onChange={() => onChange({ ...setting, tools: toggle(setting.tools ?? offerable, t.name) })}
                  />
                </td>
                <td className="py-2 pr-3">
                  <p className="flex flex-wrap items-center gap-2">
                    <code className="font-medium text-ink">{t.name}</code>
                    {t.read_only && <span className="rounded bg-white px-1.5 py-0.5 text-[0.65rem] text-ink-muted">read-only</span>}
                    {!t.offerable && <span className="text-[0.65rem] text-accent">name the assistant can't use</span>}
                  </p>
                  {t.description && <p className="mt-0.5 line-clamp-3 text-ink-light">{t.description}</p>}
                </td>
                <td className="py-2 text-center">
                  <input
                    type="checkbox"
                    className="accent-brand"
                    checked={asksFirst(t)}
                    disabled={!offered(t)}
                    aria-label={`Ask before running ${t.name}`}
                    onChange={() =>
                      onChange({
                        ...setting,
                        approve: toggle(setting.approve ?? tools.filter((x) => !x.read_only).map((x) => x.name), t.name),
                      })
                    }
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {listing.isSuccess && !problem && tools.length === 0 && <p className="text-xs text-ink-light">This service has no tools.</p>}

      {(setting.tools !== null || setting.approve !== null) && (
        <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1">
          {setting.tools !== null && (
            <button type="button" className="text-xs font-medium text-brand hover:underline" onClick={() => onChange({ ...setting, tools: null })}>
              Offer every tool, including ones the service adds later
            </button>
          )}
          {setting.approve !== null && (
            <button type="button" className="text-xs font-medium text-brand hover:underline" onClick={() => onChange({ ...setting, approve: null })}>
              Ask first for everything not marked read-only (default)
            </button>
          )}
        </div>
      )}
    </div>
  )
}

/** Which Unity Catalog schemas the picker lists MCP services from. Not saved: it only widens the search. */
function SchemaList({ schemas, setSchemas }: { schemas: string[]; setSchemas: Dispatch<SetStateAction<string[]>> }) {
  const [draft, setDraft] = useState('')
  const value = draft.trim()
  const valid = SCHEMA_RE.test(value) && !schemas.includes(value)
  return (
    <div className="mt-3 flex flex-wrap items-center gap-1.5 text-xs text-ink-light">
      <span>MCP services from</span>
      {schemas.map((schema) => (
        <span key={schema} className="flex items-center gap-1 rounded-full bg-canvas px-2 py-0.5 font-mono text-[0.7rem] text-ink">
          {schema}
          {schemas.length > 1 && (
            <button
              type="button"
              aria-label={`Stop listing ${schema}`}
              className="text-ink-muted hover:text-accent"
              onClick={() => setSchemas((current) => current.filter((s) => s !== schema))}
            >
              <X className="h-3 w-3" aria-hidden="true" />
            </button>
          )}
        </span>
      ))}
      <form
        className="flex items-center gap-1"
        onSubmit={(e) => {
          e.preventDefault()
          if (valid) {
            setSchemas((current) => [...current, value])
            setDraft('')
          }
        }}
      >
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="catalog.schema"
          aria-label="Also list MCP services from this schema"
          className="w-36 rounded-md border border-line px-2 py-0.5 font-mono text-[0.7rem] text-ink focus:border-brand focus:outline-none"
        />
        <button type="submit" disabled={!valid} className="rounded-md px-1.5 py-0.5 font-medium text-brand hover:bg-canvas disabled:opacity-40">
          Add
        </button>
      </form>
    </div>
  )
}

/** Name a Genie space's tools and say what it covers, then add it. */
function GenieSpaceForm(props: {
  space: GenieSpaceInfo
  taken: string[]
  onAdd: (space: GenieSpaceSetting) => void
  onCancel?: () => void
}) {
  const { space, taken } = props
  const [name, setName] = useState(() => suggestGenieName(space.title, taken))
  const [description, setDescription] = useState(space.description.slice(0, 500))
  const nameError =
    name && !GENIE_NAME_RE.test(name)
      ? 'Lowercase letters, digits and underscores, starting with a letter; at most 24.'
      : taken.includes(name)
        ? 'Another space in this context uses that name.'
        : null

  return (
    <div className="ml-7 mt-3 space-y-2 rounded-lg bg-canvas p-3">
      <label className="block text-xs text-ink-light">
        Tool name
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          className="mt-1 block w-60 rounded-lg border border-line bg-white px-3 py-1.5 font-mono text-xs text-ink focus:border-brand focus:outline-none"
        />
        {nameError ? (
          <span className="mt-1 block text-accent">{nameError}</span>
        ) : (
          name && <span className="mt-1 block text-ink-muted">Tools: {name}_ask, {name}_poll, {name}_query_result</span>
        )}
      </label>
      <label className="block text-xs text-ink-light">
        What it covers (the assistant reads this to pick the right space)
        <textarea
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          rows={2}
          maxLength={500}
          className="mt-1 block w-full rounded-lg border border-line bg-white px-3 py-1.5 text-xs text-ink focus:border-brand focus:outline-none"
        />
      </label>
      <div className="flex gap-2">
        <button
          type="button"
          disabled={!name || !!nameError}
          onClick={() => props.onAdd({ name, space_id: space.space_id, title: space.title, description: description.trim() })}
          className="flex items-center gap-1.5 rounded-lg bg-brand px-3 py-1.5 text-sm font-medium text-white hover:bg-brand-bright disabled:opacity-40"
        >
          <Plus className="h-4 w-4" aria-hidden="true" />
          Add to this context
        </button>
        {props.onCancel && (
          <button type="button" onClick={props.onCancel} className="rounded-lg px-3 py-1.5 text-sm font-medium text-ink-light hover:bg-white">
            Cancel
          </button>
        )}
      </div>
    </div>
  )
}

/** For a space the list doesn't show: look it up by id, as the admin, then name it. */
function AddGenieSpaceById({ taken, onAdd }: { taken: string[]; onAdd: (space: GenieSpaceSetting) => void }) {
  const [spaceId, setSpaceId] = useState('')
  const lookup = useMutation({ mutationFn: () => lookupGenieSpace(spaceId.trim()) })
  const id = spaceId.trim()

  return (
    <div className="mt-2">
      <div className="flex gap-2">
        <input
          value={spaceId}
          onChange={(e) => setSpaceId(e.target.value)}
          placeholder="Space id (32 characters, from the space's URL)"
          aria-label="Genie space id"
          className="min-w-0 flex-1 rounded-lg border border-line px-3 py-1.5 font-mono text-xs focus:border-brand focus:outline-none"
        />
        <button
          type="button"
          disabled={!SPACE_ID_RE.test(id) || lookup.isPending}
          onClick={() => lookup.mutate()}
          className="rounded-lg border border-line px-3 py-1.5 text-sm font-medium text-ink hover:bg-canvas disabled:opacity-40"
        >
          {lookup.isPending ? 'Looking up…' : 'Look up'}
        </button>
      </div>
      {lookup.isError && <p className="mt-2 text-xs text-accent">{message(lookup.error)}</p>}
      {lookup.isSuccess && lookup.data.space_id === id && (
        <>
          <p className="mt-3 text-sm font-semibold text-ink">{lookup.data.title}</p>
          <GenieSpaceForm
            key={lookup.data.space_id}
            space={lookup.data}
            taken={taken}
            onAdd={(space) => {
              onAdd(space)
              setSpaceId('')
              lookup.reset()
            }}
          />
        </>
      )}
    </div>
  )
}
