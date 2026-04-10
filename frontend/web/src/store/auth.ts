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
  syncAuth: () => Promise<void>
  setHasHydrated: (v: boolean) => void
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      user: null,
      tenantId: null,
      isAuthenticated: false,
      _hasHydrated: false,

      setHasHydrated: (v) => set({ _hasHydrated: v }),

      setUser: (user, tenantId) => set({
        user,
        tenantId,
        isAuthenticated: true,
      }),

      markAuthenticated: () => set({ isAuthenticated: true }),

      logout: () =>
        set({
          user: null,
          tenantId: null,
          isAuthenticated: false,
        }),

      syncAuth: async () => {
        const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'
        try {
          const axios = (await import('axios')).default
          const { data } = await axios.get(`${API_URL}/api/v1/auth/me`, {
            withCredentials: true,
          })
          if (data.user) {
            set({
              user: data.user,
              tenantId: data.tenant_id,
              isAuthenticated: true,
            })
          }
        } catch (error) {
          const axios = (await import('axios')).default
          if (axios.isAxiosError(error) && (error.response?.status === 401 || error.response?.status === 403)) {
            // Only clear auth state if we don't already have a user in local state.
            // This prevents wiping a fresh login when /auth/me can't be reached
            // (e.g. cookie SameSite mismatch on localhost vs lvh.me during dev).
            const current = get()
            if (!current.user) {
              set({ user: null, tenantId: null, isAuthenticated: false })
            }
          }
        }
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
