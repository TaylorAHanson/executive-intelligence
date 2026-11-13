import { formatValue, monthsAgo } from '../../components/dashboard'

/** "Last 12 complete months (Nov 2025 to Oct 2026)", matching the backend's windows. */
export function periodText(): string {
  return `Last 12 complete months (${formatValue(monthsAgo(12), 'month')} to ${formatValue(monthsAgo(1), 'month')})`
}

/** At the foot of the page: who wrote the narrative, so nobody mistakes templates for analysis. */
export function provenance(generatedBy: string | null, generatedAt: string | null): string | null {
  if (!generatedBy) return null
  const when = generatedAt ? ` on ${formatValue(generatedAt.slice(0, 10), 'date')}` : ''
  if (generatedBy.startsWith('template:')) {
    return `The narrative was filled in from fixed templates${when} (${generatedBy.slice('template:'.length)}), not written by the signal-finding loop or reviewed by a person. Every figure in it comes from the same data as the numbers beside it.`
  }
  return `Narrative written by ${generatedBy}${when}.`
}

/** Starter questions for the assistant, as chips under the headline. */
export const PORTFOLIO_QUESTIONS = [
  'Which accounts explain the gap to plan?',
  'Which renewals are most at risk, and why?',
  'Where is our share of new devices falling?',
]

/** "Orion Electronics'" and "Helix Networks'", as data/insights.py writes them; otherwise "Atlas's". */
const possessive = (name: string) => (name.endsWith('s') ? `${name}'` : `${name}'s`)

export function accountQuestions(name: string): string[] {
  return [
    `What is driving the change in ${possessive(name)} device share?`,
    `What would it take to win ${possessive(name)} next renewal?`,
    `Which deals matter most for ${name} this quarter?`,
  ]
}
