import { useEffect, useRef, useState, type ReactNode } from 'react'
import { ChevronDown, RotateCcw, Search } from 'lucide-react'
import type { FiltersState } from '../../hooks/useFilters'
import { splitList, type FilterDef, type FilterOption } from './filters'

interface FilterBarProps {
  defs: FilterDef[]
  filters: FiltersState
}

const controlClass =
  'rounded-lg border border-line bg-white px-2.5 py-1.5 text-sm text-ink focus:border-brand focus:outline-none focus:ring-2 focus:ring-brand/20'

/** The controls for a dashboard's filters. State lives in the URL via `useFilters`. */
export default function FilterBar({ defs, filters }: FilterBarProps) {
  const { values, setFilters, reset, isDefault } = filters
  return (
    <div className="flex flex-wrap items-end gap-3">
      {defs.map((def) => {
        switch (def.type) {
          case 'daterange':
            return (
              <Field key={def.fromKey} label={def.label}>
                <div className="flex items-center gap-1.5">
                  <input
                    type="month"
                    className={controlClass}
                    value={values[def.fromKey] ?? ''}
                    max={values[def.toKey]}
                    onChange={(e) => e.target.value && setFilters({ [def.fromKey]: e.target.value })}
                    aria-label={`${def.label} from`}
                  />
                  <span className="text-xs text-ink-muted">to</span>
                  <input
                    type="month"
                    className={controlClass}
                    value={values[def.toKey] ?? ''}
                    min={values[def.fromKey]}
                    onChange={(e) => e.target.value && setFilters({ [def.toKey]: e.target.value })}
                    aria-label={`${def.label} to`}
                  />
                </div>
              </Field>
            )
          case 'select':
            return (
              <Field key={def.key} label={def.label}>
                <select
                  className={controlClass}
                  value={values[def.key] ?? ''}
                  onChange={(e) => setFilters({ [def.key]: e.target.value })}
                >
                  {def.options.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </Field>
            )
          case 'multiselect':
            return (
              <Field key={def.key} label={def.label}>
                <MultiSelect
                  options={def.options}
                  selected={splitList(values[def.key] ?? '')}
                  onChange={(selected) => setFilters({ [def.key]: selected.join(',') })}
                />
              </Field>
            )
          case 'search':
            return (
              <Field key={def.key} label={def.label}>
                <SearchInput
                  value={values[def.key] ?? ''}
                  placeholder={def.placeholder}
                  onChange={(value) => setFilters({ [def.key]: value })}
                />
              </Field>
            )
        }
      })}
      {!isDefault && (
        <button
          type="button"
          className="inline-flex items-center gap-1 rounded-lg px-2 py-1.5 text-sm font-medium text-ink-light hover:bg-canvas-dark hover:text-ink"
          onClick={reset}
        >
          <RotateCcw className="h-3.5 w-3.5" aria-hidden="true" /> Reset
        </button>
      )}
    </div>
  )
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-[0.7rem] font-semibold uppercase tracking-wide text-ink-muted">{label}</span>
      {children}
    </label>
  )
}

interface MultiSelectProps {
  options: FilterOption[]
  selected: string[]
  onChange: (selected: string[]) => void
}

function MultiSelect({ options, selected, onChange }: MultiSelectProps) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const close = (event: MouseEvent) => {
      if (!ref.current?.contains(event.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [open])

  const summary =
    selected.length === 0
      ? 'All'
      : selected.length === 1
        ? (options.find((o) => o.value === selected[0])?.label ?? selected[0])
        : `${selected.length} selected`

  const toggle = (value: string) =>
    onChange(selected.includes(value) ? selected.filter((v) => v !== value) : [...selected, value])

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        className={`${controlClass} flex min-w-[10rem] items-center justify-between gap-2`}
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        <span className="truncate">{summary}</span>
        <ChevronDown className="h-4 w-4 text-ink-muted" aria-hidden="true" />
      </button>
      {open && (
        <div className="absolute left-0 top-full z-20 mt-1 max-h-64 min-w-full overflow-y-auto rounded-lg border border-line bg-white py-1 shadow-tile">
          {options.map((option) => (
            <label key={option.value} className="flex cursor-pointer items-center gap-2 px-3 py-1.5 text-sm hover:bg-canvas">
              <input
                type="checkbox"
                className="accent-brand"
                checked={selected.includes(option.value)}
                onChange={() => toggle(option.value)}
              />
              {option.label}
            </label>
          ))}
          {selected.length > 0 && (
            <button
              type="button"
              className="w-full border-t border-line px-3 py-1.5 text-left text-xs font-medium text-brand hover:bg-canvas"
              onClick={() => onChange([])}
            >
              Clear
            </button>
          )}
        </div>
      )}
    </div>
  )
}

interface SearchInputProps {
  value: string
  placeholder?: string
  onChange: (value: string) => void
}

/** Commits after a pause in typing, so each keystroke is not a query. */
function SearchInput({ value, placeholder, onChange }: SearchInputProps) {
  const [draft, setDraft] = useState(value)
  const [committed, setCommitted] = useState(value)
  // Follow outside changes (reset, back button) without an effect.
  if (value !== committed) {
    setCommitted(value)
    setDraft(value)
  }

  useEffect(() => {
    if (draft === value) return
    const timer = setTimeout(() => onChange(draft.trim()), 400)
    return () => clearTimeout(timer)
  }, [draft, value, onChange])

  return (
    <div className="relative">
      <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-muted" aria-hidden="true" />
      <input
        type="search"
        className={`${controlClass} pl-8`}
        value={draft}
        placeholder={placeholder}
        onChange={(e) => setDraft(e.target.value)}
      />
    </div>
  )
}
