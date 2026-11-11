import { useState, type ReactNode } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ApiError } from '../api'
import AgentTrayProvider from './AgentTrayProvider'
import SessionProvider from './SessionProvider'

const MAX_RETRIES = 2

function shouldRetry(failureCount: number, error: Error) {
  if (error instanceof ApiError) {
    // A lapsed sign-in needs a reload, and a 4xx (bad filter, missing grant,
    // missing table) fails the same way every time.
    if (error.sessionExpired || (error.status >= 400 && error.status < 500)) return false
  }
  return failureCount < MAX_RETRIES
}

function createQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        // Dashboard data changes on pipeline schedules, not per second. Five
        // minutes keeps switching between dashboards from re-running queries.
        staleTime: 5 * 60 * 1000,
        refetchOnWindowFocus: false,
        retry: shouldRetry,
      },
    },
  })
}

/** Everything every page can rely on. Render inside the router. */
export default function AppProviders({ children }: { children: ReactNode }) {
  const [queryClient] = useState(createQueryClient)
  return (
    <QueryClientProvider client={queryClient}>
      <SessionProvider>
        <AgentTrayProvider>{children}</AgentTrayProvider>
      </SessionProvider>
    </QueryClientProvider>
  )
}
