import { useEffect, useState, type ReactNode } from 'react'
import { getCurrentUser, getHealth, type CurrentUser } from '../api'
import { APP_TITLE } from '../brand'
import { SessionContext } from './session'

export default function SessionProvider({ children }: { children: ReactNode }) {
  const [environment, setEnvironment] = useState<string | null>(null)
  const [syntheticData, setSyntheticData] = useState(true)
  const [user, setUser] = useState<CurrentUser | null>(null)

  useEffect(() => {
    // Both are best-effort: the app should still render if either fails, rather
    // than showing a blank screen because a label could not be fetched.
    getHealth()
      .then((health) => {
        setEnvironment(health.environment)
        setSyntheticData(health.synthetic_data !== false)
      })
      .catch(() => setEnvironment(null))

    getCurrentUser()
      .then(setUser)
      .catch(() => setUser(null))
  }, [])

  useEffect(() => {
    // The environment comes from the server rather than a build-time constant
    // because the same built assets are promoted from dev to prod.
    document.title = environment && environment !== 'prod' ? `${APP_TITLE} - ${environment}` : APP_TITLE
  }, [environment])

  return <SessionContext.Provider value={{ user, environment, syntheticData }}>{children}</SessionContext.Provider>
}
