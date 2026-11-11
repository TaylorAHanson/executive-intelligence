import { Link } from 'react-router-dom'

export default function NotFoundPage() {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-3 bg-canvas px-8 text-center">
      <p className="text-sm font-semibold uppercase tracking-wide text-brand">Not found</p>
      <h2 className="text-2xl font-bold text-ink">There is no dashboard at this address.</h2>
      <Link to="/" className="rounded-lg bg-brand px-4 py-2 text-sm font-medium text-white hover:bg-brand-bright">
        Back to home
      </Link>
    </div>
  )
}
