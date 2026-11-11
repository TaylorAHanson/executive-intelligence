import { createContext, useContext } from 'react'
import type { CurrentUser } from '../api'

export interface Session {
  /** null until /api/user/me answers, and if it fails. */
  user: CurrentUser | null
  /** `local`, `dev`, `prod`, ... from /api/health; null until it answers. */
  environment: string | null
  /** The dashboards show synthetic data. True until /api/health says otherwise. */
  syntheticData: boolean
}

export const SessionContext = createContext<Session | null>(null)

/** Who is signed in and which deployment this is. */
export function useSession(): Session {
  const session = useContext(SessionContext)
  if (!session) throw new Error('useSession must be used inside <SessionProvider>')
  return session
}
