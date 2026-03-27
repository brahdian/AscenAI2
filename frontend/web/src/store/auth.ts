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
  accessToken: string | null
  refreshToken: string | null
  isAuthenticated: boolean
  _hasHydrated: boolean

  setTokens: (access: string, refresh: string) => void
  setUser: (user: UserInfo, tenantId: string) => void
  logout: () => void
  setHasHydrated: (v: boolean) => void
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      user: null,
      tenantId: null,
      accessToken: null,
      refreshToken: null,
      isAuthenticated: false,
      _hasHydrated: false,

      setHasHydrated: (v) => set({ _hasHydrated: v }),

      setTokens: (access, refresh) => {
        if (typeof window !== 'undefined') {
          localStorage.setItem('access_token', access)
          localStorage.setItem('refresh_token', refresh)
        }
        set({ accessToken: access, refreshToken: refresh, isAuthenticated: true })
      },

      setUser: (user, tenantId) => set({ user, tenantId }),

      logout: () => {
        if (typeof window !== 'undefined') {
          localStorage.removeItem('access_token')
          localStorage.removeItem('refresh_token')
        }
        set({
          user: null,
          tenantId: null,
          accessToken: null,
          refreshToken: null,
          isAuthenticated: false,
        })
      },
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
