import { useEffect, useState } from 'react'
import { formatValue } from '../../components/dashboard'
import { money, pct } from '../../components/story'

/**
 * "What changed since you last looked", kept in this browser.
 *
 * Each visit stores the briefing's headline figures under today's date. The
 * next day's visit compares itself with the newest earlier day. The figures
 * stay on this device, per signed-in browser profile; nothing goes to a server.
 * That is deliberate for now, because the insight records are overwritten on
 * every refresh, so there is no history server-side to compare with.
 */
export interface Snapshot {
  quarter: string | null
  plan: number | null
  commit: number | null
  attainment: number | null
  deviceShare: number | null
  atRisk: { id: string; name: string }[]
}

type Days = Record<string, Snapshot>

const KEY = (scope: string) => `customers.visit.v1.${scope}`
const KEEP_DAYS = 14

// Read once when the page loads, not on each render.
const TODAY = new Date().toLocaleDateString('en-CA')

function read(scope: string): Days {
  try {
    const parsed = JSON.parse(localStorage.getItem(KEY(scope)) ?? '{}')
    return parsed && typeof parsed === 'object' ? (parsed as Days) : {}
  } catch {
    return {}
  }
}

/** The newest snapshot from a day before today, with its date. */
function baseline(days: Days): { day: string; snapshot: Snapshot } | null {
  const day = Object.keys(days)
    .filter((d) => d < TODAY)
    .sort()
    .at(-1)
  return day ? { day, snapshot: days[day] } : null
}

const sentence = {
  commit(quarter: string, delta: number, now: number): string {
    return `${quarter} commit is ${money(Math.abs(delta))} ${delta > 0 ? 'higher' : 'lower'} than before, at ${money(now)}.`
  },
  attainment(delta: number, now: number): string {
    const pts = Math.round(Math.abs(delta) * 100)
    return `Revenue against plan is ${pct(now)}, ${delta > 0 ? 'up' : 'down'} ${pts} point${pts === 1 ? '' : 's'}.`
  },
  share(delta: number, now: number): string {
    const pts = Math.round(Math.abs(delta) * 100)
    return `Our share of their new devices is ${pct(now)}, ${delta > 0 ? 'up' : 'down'} ${pts} point${pts === 1 ? '' : 's'}.`
  },
}

/** What moved between two snapshots, as sentences. Empty when nothing did. */
export function changes(before: Snapshot, now: Snapshot): string[] {
  const out: string[] = []
  const names = (list: { name: string }[]) => list.map((a) => a.name).join(', ')

  const added = now.atRisk.filter((a) => !before.atRisk.some((b) => b.id === a.id))
  const cleared = before.atRisk.filter((b) => !now.atRisk.some((a) => a.id === b.id))
  if (added.length) out.push(`Newly at risk: ${names(added)}.`)
  if (cleared.length) out.push(`No longer at risk: ${names(cleared)}.`)

  // A commit is only comparable within the same quarter.
  if (now.quarter && now.quarter === before.quarter && now.commit != null && before.commit != null) {
    const delta = now.commit - before.commit
    const floor = Math.max(500_000, (now.plan ?? 0) * 0.005)
    if (Math.abs(delta) >= floor) out.push(sentence.commit(now.quarter, delta, now.commit))
  }
  if (now.attainment != null && before.attainment != null && Math.abs(now.attainment - before.attainment) >= 0.01) {
    out.push(sentence.attainment(now.attainment - before.attainment, now.attainment))
  }
  if (now.deviceShare != null && before.deviceShare != null && Math.abs(now.deviceShare - before.deviceShare) >= 0.01) {
    out.push(sentence.share(now.deviceShare - before.deviceShare, now.deviceShare))
  }
  return out
}

export interface SinceLastVisit {
  /** "Nov 10": the day compared against. */
  since: string
  changes: string[]
}

/**
 * Compares `snapshot` with the last earlier day this browser saw `scope`, and
 * stores today's snapshot. Null on a first visit or while `snapshot` is null.
 */
export function useSinceLastVisit(scope: string, snapshot: Snapshot | null): SinceLastVisit | null {
  // What an earlier day left behind, read once; today's write must not change the comparison.
  const [previous] = useState(() => baseline(read(scope)))

  const serialized = snapshot ? JSON.stringify(snapshot) : null
  useEffect(() => {
    if (!serialized) return
    const days = read(scope)
    days[TODAY] = JSON.parse(serialized) as Snapshot
    const newest = Object.keys(days).sort().slice(-KEEP_DAYS)
    const kept = Object.fromEntries(newest.map((d) => [d, days[d]]))
    try {
      localStorage.setItem(KEY(scope), JSON.stringify(kept))
    } catch {
      // Storage full or disabled: the comparison simply is not available next time.
    }
  }, [scope, serialized])

  if (!previous || !snapshot) return null
  return {
    since: formatValue(previous.day, 'date').replace(/, \d{4}$/, ''),
    changes: changes(previous.snapshot, snapshot),
  }
}
