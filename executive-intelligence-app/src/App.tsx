import { Suspense } from 'react'
import { Route, Routes } from 'react-router-dom'
import { Loader2 } from 'lucide-react'
import Layout from './components/Layout'
import LandingPage from './pages/LandingPage'
import NotFoundPage from './pages/NotFoundPage'
import ReleaseNotesPage from './pages/ReleaseNotesPage'
import SettingsPage from './pages/SettingsPage'
import { APP_TITLE } from './brand'
import { SECTIONS } from './sections'

export default function App() {
  return (
    <Layout title={APP_TITLE}>
      <Suspense fallback={<PageLoading />}>
        <Routes>
          <Route index element={<LandingPage />} />
          {SECTIONS.map(({ id, path, component: Page }) => (
            <Route key={id} path={`${path}/*`} element={<Page />} />
          ))}
          <Route path="release-notes" element={<ReleaseNotesPage />} />
          <Route path="settings" element={<SettingsPage />} />
          <Route path="*" element={<NotFoundPage />} />
        </Routes>
      </Suspense>
    </Layout>
  )
}

function PageLoading() {
  return (
    <div className="flex h-full items-center justify-center text-ink-muted">
      <Loader2 className="h-6 w-6 animate-spin text-brand" aria-label="Loading" />
    </div>
  )
}
