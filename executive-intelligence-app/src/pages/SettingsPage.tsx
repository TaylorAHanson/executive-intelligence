import { useState, type ReactNode } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Loader2, RotateCcw } from 'lucide-react'
import {
  ApiError,
  getAgentSettings,
  resetAgentSettings,
  saveAgentSettings,
  type AgentSettings,
  type ContextAgentSettings,
  type GenieSpaceSetting,
  type McpServiceSetting,
} from '../api'
import ToolPicker from './settings/ToolPicker'

const SETTINGS_KEY = ['agentSettings']

const sameSet = (a: string[], b: string[]) => a.length === b.length && a.every((x) => b.includes(x))
const isCustomized = (c: ContextAgentSettings) =>
  c.prompt !== null || c.builtin_tools !== null || c.genie_spaces !== null || c.mcp_services !== null
const spaceKey = (spaces: GenieSpaceSetting[]) => JSON.stringify(spaces.map(({ name, space_id, description }) => [name, space_id, description]))
const serviceKey = (services: McpServiceSetting[]) => JSON.stringify(services.map(({ service, tools, approve }) => [service, tools, approve]))
const message = (error: unknown) => (error instanceof Error ? error.message : 'Something went wrong.')

/** Admins edit each app context's agent prompt and tools. Saved to the app's database; the backend checks the admin group. */
export default function SettingsPage() {
  const settings = useQuery({ queryKey: SETTINGS_KEY, queryFn: getAgentSettings, retry: false })
  const [params, setParams] = useSearchParams()

  if (settings.isPending) {
    return (
      <div className="flex h-full items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-brand" aria-label="Loading" />
      </div>
    )
  }
  if (settings.isError) {
    const forbidden = settings.error instanceof ApiError && settings.error.status === 403
    return (
      <div className="flex h-full flex-col items-center justify-center gap-2 bg-canvas px-8 text-center">
        <h2 className="text-xl font-bold text-ink">{forbidden ? 'Settings are for admins' : 'Could not load settings'}</h2>
        <p className="max-w-lg text-sm text-ink-light">{message(settings.error)}</p>
      </div>
    )
  }

  const contexts = settings.data.contexts
  const selected = contexts.find((c) => c.id === params.get('context')) ?? contexts[0]

  return (
    <div className="min-h-full bg-canvas px-8 py-10">
      <div className="mx-auto max-w-[1080px]">
        <h2 className="mb-1 text-2xl font-bold text-ink">Settings</h2>
        <p className="mb-8 max-w-3xl text-sm text-ink-light">
          Each part of the app has its own assistant context: the instructions it follows there and the tools it
          may use. Changes apply to everyone from their next question. Data tools always run as the person asking,
          so they only ever see data they could query themselves.
        </p>

        <div className="flex gap-6">
          <nav aria-label="Assistant contexts" className="w-56 shrink-0">
            <ul className="space-y-1">
              {contexts.map((c) => (
                <li key={c.id}>
                  <button
                    type="button"
                    onClick={() => setParams({ context: c.id })}
                    aria-current={c.id === selected?.id ? 'page' : undefined}
                    className={`flex w-full items-center justify-between gap-2 rounded-lg px-3 py-2 text-left text-sm ${
                      c.id === selected?.id ? 'bg-brand/10 font-semibold text-brand' : 'text-ink hover:bg-white'
                    }`}
                  >
                    {c.label}
                    {isCustomized(c) && <span className="h-1.5 w-1.5 rounded-full bg-brand" title="Customized" />}
                  </button>
                </li>
              ))}
            </ul>
          </nav>

          {selected && (
            <ContextEditor
              // Remount on save so the form starts from what was stored.
              key={`${selected.id}:${selected.updated_at ?? 'default'}`}
              context={selected}
              settings={settings.data}
            />
          )}
        </div>
      </div>
    </div>
  )
}

function ContextEditor({ context, settings }: { context: ContextAgentSettings; settings: AgentSettings }) {
  const queryClient = useQueryClient()
  const [prompt, setPrompt] = useState(context.prompt ?? context.default_prompt)
  const [builtin, setBuiltin] = useState(context.builtin_tools ?? context.default_builtin_tools)
  const [spaces, setSpaces] = useState<GenieSpaceSetting[]>(context.genie_spaces ?? context.default_genie_spaces)
  const [services, setServices] = useState<McpServiceSetting[]>(context.mcp_services ?? context.default_mcp_services)

  const promptIsDefault = prompt.trim() === context.default_prompt.trim()
  const builtinIsDefault = sameSet(builtin, context.default_builtin_tools)
  const spacesAreDefault = spaceKey(spaces) === spaceKey(context.default_genie_spaces)
  const servicesAreDefault = serviceKey(services) === serviceKey(context.default_mcp_services)
  const toolsAreDefault = builtinIsDefault && spacesAreDefault && servicesAreDefault
  const dirty =
    prompt.trim() !== (context.prompt ?? context.default_prompt).trim() ||
    !sameSet(builtin, context.builtin_tools ?? context.default_builtin_tools) ||
    spaceKey(spaces) !== spaceKey(context.genie_spaces ?? context.default_genie_spaces) ||
    serviceKey(services) !== serviceKey(context.mcp_services ?? context.default_mcp_services)

  const done = () => queryClient.invalidateQueries({ queryKey: SETTINGS_KEY })
  const save = useMutation({
    mutationFn: () =>
      saveAgentSettings(context.id, {
        prompt: promptIsDefault ? null : prompt.trim(),
        builtin_tools: builtinIsDefault ? null : builtin,
        genie_spaces: spacesAreDefault ? null : spaces.map(({ name, space_id, description }) => ({ name, space_id, description })),
        mcp_services: servicesAreDefault ? null : services,
      }),
    onSuccess: done,
  })
  const reset = useMutation({ mutationFn: () => resetAgentSettings(context.id), onSuccess: done })

  return (
    <section className="min-w-0 flex-1 space-y-5" aria-label={`${context.label} settings`}>
      <div className="rounded-[14px] border border-line bg-white px-6 py-5 shadow-tile">
        <div className="mb-1 flex items-baseline justify-between gap-4">
          <h3 className="text-lg font-bold text-ink">{context.label}</h3>
          <code className="text-xs text-ink-muted">{context.id}</code>
        </div>
        <p className="text-xs text-ink-muted">
          {context.updated_by
            ? `Last changed by ${context.updated_by}${context.updated_at ? ` on ${context.updated_at.slice(0, 16).replace('T', ' ')}` : ''}.`
            : "Using the assistant's defaults."}
        </p>
      </div>

      <Card
        title="Instructions"
        badge={promptIsDefault ? 'Default' : 'Customized'}
        action={
          !promptIsDefault && (
            <button type="button" className="text-xs font-medium text-brand hover:underline" onClick={() => setPrompt(context.default_prompt)}>
              Restore default
            </button>
          )
        }
      >
        <textarea
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          rows={8}
          maxLength={8000}
          aria-label={`Instructions for ${context.label}`}
          className="w-full rounded-lg border border-line px-3 py-2 text-sm leading-relaxed text-ink focus:border-brand focus:outline-none"
        />
        <details className="mt-2 text-xs text-ink-light">
          <summary className="cursor-pointer select-none">Always included before these instructions</summary>
          <p className="mt-2 whitespace-pre-wrap rounded-lg bg-canvas p-3">{settings.base_prompt}</p>
        </details>
      </Card>

      <Card
        title="Tools"
        badge={toolsAreDefault ? 'Default' : 'Customized'}
        action={
          !toolsAreDefault && (
            <button
              type="button"
              className="text-xs font-medium text-brand hover:underline"
              onClick={() => {
                setBuiltin(context.default_builtin_tools)
                setSpaces(context.default_genie_spaces)
                setServices(context.default_mcp_services)
              }}
            >
              Restore default
            </button>
          )
        }
      >
        <ToolPicker
          builtinTools={settings.builtin_tools}
          builtin={builtin}
          setBuiltin={setBuiltin}
          spaces={spaces}
          setSpaces={setSpaces}
          services={services}
          setServices={setServices}
        />
      </Card>

      {(save.isError || reset.isError) && (
        <p role="alert" className="rounded-lg border border-accent/40 bg-white px-4 py-3 text-sm text-accent">
          {message(save.error ?? reset.error)}
        </p>
      )}

      <div className="flex items-center justify-between gap-3">
        <button
          type="button"
          disabled={!isCustomized(context) || reset.isPending}
          onClick={() => {
            if (window.confirm(`Return ${context.label} to its default instructions and tools?`)) reset.mutate()
          }}
          className="flex items-center gap-1.5 rounded-lg px-3 py-2 text-sm font-medium text-ink-light hover:bg-white disabled:opacity-40"
        >
          <RotateCcw className="h-4 w-4" aria-hidden="true" />
          Reset to defaults
        </button>
        <div className="flex items-center gap-2">
          {dirty && <span className="text-xs text-ink-muted">Unsaved changes</span>}
          <button
            type="button"
            disabled={!dirty || save.isPending}
            onClick={() => save.mutate()}
            className="flex items-center gap-1.5 rounded-lg bg-brand px-4 py-2 text-sm font-medium text-white hover:bg-brand-bright disabled:opacity-40"
          >
            {save.isPending && <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />}
            Save
          </button>
        </div>
      </div>
    </section>
  )
}

function Card({ title, badge, action, children }: { title: string; badge?: string; action?: ReactNode; children: ReactNode }) {
  return (
    <div className="rounded-[14px] border border-line bg-white px-6 py-5 shadow-tile">
      <div className="mb-3 flex items-center gap-2">
        <h4 className="text-sm font-bold text-ink">{title}</h4>
        {badge && (
          <span
            className={`rounded-full px-2 py-0.5 text-[0.68rem] font-semibold ${
              badge === 'Default' ? 'bg-canvas text-ink-muted' : 'bg-brand/10 text-brand'
            }`}
          >
            {badge}
          </span>
        )}
        <span className="ml-auto">{action}</span>
      </div>
      {children}
    </div>
  )
}
