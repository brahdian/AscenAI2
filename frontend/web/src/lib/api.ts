import axios, { AxiosInstance, AxiosError } from 'axios'

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

function createApiClient(): AxiosInstance {
  const client = axios.create({
    baseURL: `${API_URL}/api/v1`,
    headers: { 'Content-Type': 'application/json' },
  })

  // Attach JWT token from localStorage
  client.interceptors.request.use((config) => {
    if (typeof window !== 'undefined') {
      const token = localStorage.getItem('access_token')
      if (token) {
        config.headers.Authorization = `Bearer ${token}`
      }
    }
    return config
  })

  // Handle 401 — redirect to login
  client.interceptors.response.use(
    (res) => res,
    async (error: AxiosError) => {
      if (error.response?.status === 401 && typeof window !== 'undefined') {
        localStorage.removeItem('access_token')
        localStorage.removeItem('refresh_token')
        window.location.href = '/login'
      }
      return Promise.reject(error)
    }
  )

  return client
}

export const api = createApiClient()

// ---------------------------------------------------------------------------
// Auth
// ---------------------------------------------------------------------------

export const authApi = {
  register: (data: {
    email: string
    password: string
    full_name: string
    business_name: string
    business_type?: string
  }) => api.post('/auth/register', data).then((r) => r.data),

  login: (data: { email: string; password: string }) =>
    api.post('/auth/login', data).then((r) => r.data),

  refresh: (refresh_token: string) =>
    api.post('/auth/refresh', { refresh_token }).then((r) => r.data),
}

// ---------------------------------------------------------------------------
// Tenant
// ---------------------------------------------------------------------------

export const tenantApi = {
  getMe: () => api.get('/tenants/me').then((r) => r.data),
  updateMe: (data: Record<string, unknown>) =>
    api.patch('/tenants/me', data).then((r) => r.data),
  getUsage: () => api.get('/tenants/me/usage').then((r) => r.data),
}

// ---------------------------------------------------------------------------
// Agents (via proxy)
// ---------------------------------------------------------------------------

export const agentsApi = {
  list: () => api.get('/proxy/agents').then((r) => r.data),
  get: (id: string) => api.get(`/proxy/agents/${id}`).then((r) => r.data),
  create: (data: Record<string, unknown>) =>
    api.post('/proxy/agents', data).then((r) => r.data),
  update: (id: string, data: Record<string, unknown>) =>
    api.patch(`/proxy/agents/${id}`, data).then((r) => r.data),
  delete: (id: string) => api.delete(`/proxy/agents/${id}`),
  test: (id: string, message: string) =>
    api.post(`/proxy/agents/${id}/test`, { message }).then((r) => r.data),
}

// ---------------------------------------------------------------------------
// Chat (via proxy)
// ---------------------------------------------------------------------------

export const chatApi = {
  send: (data: {
    agent_id: string
    message: string
    session_id?: string
    channel?: string
  }) => api.post('/proxy/chat', data).then((r) => r.data),
}

// ---------------------------------------------------------------------------
// Sessions (via proxy)
// ---------------------------------------------------------------------------

export const sessionsApi = {
  list: (params?: { agent_id?: string; status?: string; limit?: number }) =>
    api.get('/proxy/sessions', { params }).then((r) => r.data),
  get: (id: string, include_messages?: boolean) =>
    api
      .get(`/proxy/sessions/${id}`, {
        params: include_messages ? { include_messages: true } : undefined,
      })
      .then((r) => r.data),
}

// ---------------------------------------------------------------------------
// API Keys
// ---------------------------------------------------------------------------

export const apiKeysApi = {
  list: () => api.get('/api-keys').then((r) => r.data),
  create: (data: { name: string; scopes?: string[] }) =>
    api.post('/api-keys', data).then((r) => r.data),
  revoke: (id: string) => api.delete(`/api-keys/${id}`),
}
