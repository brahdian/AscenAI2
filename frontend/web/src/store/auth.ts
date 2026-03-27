import { create } from 'zustand'
import { persist } from 'zustand/middleware'

interface UserInfo {
  id: string
  email: string
  full_name: string
  role: string
  tenant_id: string
}

interface AuthState {
  user: UserInfo | null
  tenantId: string | null
  isAuthenticated: boolean
  _hasHydrated: boolean

  setUser: (user: UserInfo, tenantId: string) => void
  markAuthenticated: () => void
  logout: () => void
  setHasHydrated: (v: boolean) => void
}

/**
 * Auth state store — tokens are NOT stored here or in localStorage.
 * They live exclusively in HttpOnly cookies (set by the API server) so they are
 * invisible to JavaScript and immune to XSS token theft.
 *
 * Persisted to localStorage: user profile + isAuthenticated flag only.
 * The flag is a UI hint; the server is the authority (a stale flag just
 * causes an extra 401 that the interceptor handles gracefully).
 */
export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      user: null,
      tenantId: null,
      isAuthenticated: false,
      _hasHydrated: false,

      setHasHydrated: (v) => set({ _hasHydrated: v }),

      setUser: (user, tenantId) => set({ user, tenantId, isAuthenticated: true }),

      markAuthenticated: () => set({ isAuthenticated: true }),

      logout: () =>
        set({
          user: null,
          tenantId: null,
          isAuthenticated: false,
        }),
    }),
    {
      name: 'ascenai-auth',
      partialize: (state) => ({
        user: state.user,
        tenantId: state.tenantId,
        isAuthenticated: state.isAuthenticated,
      }),
      onRehydrateStorage: () => (state) => {
        state?.setHasHydrated(true)
      },
    }
  )
)
