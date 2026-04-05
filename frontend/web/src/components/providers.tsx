'use client'

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Toaster } from 'react-hot-toast'
import { useState, useEffect } from 'react'
import { useAuthStore } from '@/store/auth'

export function Providers({ children }: { children: React.ReactNode }) {
  const syncAuth = useAuthStore((state) => state.syncAuth)
  const isHydrated = useAuthStore((state) => state._hasHydrated)

  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 60 * 1000,
            retry: 1,
          },
        },
      })
  )

  useEffect(() => {
    if (isHydrated) {
      syncAuth()
    }
  }, [isHydrated, syncAuth])

  return (
    <QueryClientProvider client={queryClient}>
      {children}
      <Toaster
        position="top-right"
        toastOptions={{
          duration: 4000,
          style: {
            background: '#1e1b4b',
            color: '#e0e7ff',
            border: '1px solid rgba(124,58,237,0.3)',
          },
        }}
      />
    </QueryClientProvider>
  )
}
