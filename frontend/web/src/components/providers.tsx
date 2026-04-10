'use client'

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Toaster } from 'react-hot-toast'
import { useState, useEffect } from 'react'
import { usePathname } from 'next/navigation'
import { useAuthStore } from '@/store/auth'

const AUTH_PAGES = new Set(['/login', '/register', '/forgot-password', '/reset-password'])

export function Providers({ children }: { children: React.ReactNode }) {
  const syncAuth = useAuthStore((state) => state.syncAuth)
  const isHydrated = useAuthStore((state) => state._hasHydrated)
  const pathname = usePathname()

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
    // Only sync once when the store finishes hydrating from localStorage.
    // Do NOT include `pathname` in deps — that would fire /auth/me on every
    // navigation, causing a 401 → clear-state → redirect loop when the
    // cookie isn't available (e.g. cross-origin in dev).
    if (isHydrated && !AUTH_PAGES.has(pathname)) {
      syncAuth()
    }
  }, [isHydrated, pathname, syncAuth])

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
