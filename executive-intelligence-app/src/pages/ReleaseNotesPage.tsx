import { useEffect } from 'react'
import Markdown from '../components/Markdown'
import { RELEASES, markReleasesRead } from '../releaseNotes'

const formatDate = (iso: string) =>
  new Date(`${iso}T00:00:00`).toLocaleDateString(undefined, { year: 'numeric', month: 'long', day: 'numeric' })

export default function ReleaseNotesPage() {
  useEffect(markReleasesRead, [])

  return (
    <div className="min-h-full bg-canvas px-8 py-10">
      <div className="mx-auto max-w-[760px]">
        <h2 className="mb-1 text-2xl font-bold text-ink">Release notes</h2>
        <p className="mb-8 text-sm text-ink-light">What changed in this app, newest first.</p>

        <ol className="space-y-5">
          {RELEASES.map((release, i) => (
            <li
              key={release.version}
              id={`v${release.version}`}
              className="scroll-mt-6 rounded-[14px] border border-line bg-white px-6 py-5 shadow-tile"
            >
              <div className="mb-2 flex items-baseline gap-3">
                <h3 className="text-lg font-bold text-ink">{release.version}</h3>
                {release.date && <span className="text-sm text-ink-muted">{formatDate(release.date)}</span>}
                {i === 0 && (
                  <span className="rounded-full bg-brand/10 px-2 py-0.5 text-xs font-semibold text-brand">Latest</span>
                )}
              </div>
              <div className="text-[0.92rem] leading-relaxed text-ink">
                <Markdown>{release.body}</Markdown>
              </div>
            </li>
          ))}
        </ol>
      </div>
    </div>
  )
}
