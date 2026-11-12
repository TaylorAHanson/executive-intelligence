/**
 * Release notes parsed from ../RELEASE_NOTES.md (the single source of truth;
 * edit that file, not this one). Each `## <semver> — <YYYY-MM-DD>` heading starts
 * a release. Text above the first release heading is authoring guidance and is
 * not shown.
 */
import { useSyncExternalStore } from 'react'
import rawNotes from '../RELEASE_NOTES.md?raw'

export interface ReleaseNote {
  version: string
  date: string | null
  body: string
}

const HEADING = /^##\s+v?(\d+\.\d+\.\d+)\s*(?:[—–-]+\s*(\d{4}-\d{2}-\d{2}))?\s*$/

export function parseReleaseNotes(markdown: string): ReleaseNote[] {
  const releases: ReleaseNote[] = []
  let current: { version: string; date: string | null; lines: string[] } | null = null
  const flush = () => {
    if (current) releases.push({ version: current.version, date: current.date, body: current.lines.join('\n').trim() })
  }
  for (const line of markdown.replace(/<!--[\s\S]*?-->/g, '').split(/\r?\n/)) {
    const m = HEADING.exec(line)
    if (m) {
      flush()
      current = { version: m[1], date: m[2] ?? null, lines: [] }
    } else if (current) {
      current.lines.push(line)
    }
  }
  flush()
  return releases
}

export const RELEASES = parseReleaseNotes(rawNotes)
export const LATEST_VERSION = RELEASES[0]?.version ?? '0.0.0'

const SEEN_KEY = 'releaseNotes.seen'
const READ_EVENT = 'releaseNotes:read'

function hasUnreadRelease(): boolean {
  try {
    return localStorage.getItem(SEEN_KEY) !== LATEST_VERSION
  } catch {
    return false
  }
}

export function markReleasesRead(): void {
  try {
    localStorage.setItem(SEEN_KEY, LATEST_VERSION)
  } catch {
    // Private mode or storage disabled: the dot just stays.
  }
  window.dispatchEvent(new Event(READ_EVENT))
}

function subscribe(onChange: () => void): () => void {
  window.addEventListener(READ_EVENT, onChange)
  window.addEventListener('storage', onChange)
  return () => {
    window.removeEventListener(READ_EVENT, onChange)
    window.removeEventListener('storage', onChange)
  }
}

/** Whether this browser has opened the release notes since the latest release. */
export function useUnreadRelease(): boolean {
  return useSyncExternalStore(subscribe, hasUnreadRelease)
}
