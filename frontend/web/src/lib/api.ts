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

// ---------------------------------------------------------------------------
// Feedback (via proxy)
// ---------------------------------------------------------------------------

export const feedbackApi = {
  submit: (data: {
    message_id: string
    session_id: string
    agent_id: string
    rating: 'positive' | 'negative'
    labels?: string[]
    comment?: string
    ideal_response?: string
    correction_reason?: string
    feedback_source?: string
  }) => api.post('/proxy/feedback', data).then((r) => r.data),

  list: (params?: {
    agent_id?: string
    rating?: string
    session_id?: string
    limit?: number
    offset?: number
  }) => api.get('/proxy/feedback', { params }).then((r) => r.data),

  summary: (params?: { agent_id?: string }) =>
    api.get('/proxy/feedback/summary', { params }).then((r) => r.data),

  exportUrl: (params?: { format?: string; agent_id?: string; rating?: string }) => {
    const token = typeof window !== 'undefined' ? localStorage.getItem('access_token') : ''
    const qs = new URLSearchParams({ ...(params as any) }).toString()
    return `${API_URL}/api/v1/proxy/feedback/export${qs ? `?${qs}` : ''}`
  },
}

// ---------------------------------------------------------------------------
// Analytics (via proxy)
// ---------------------------------------------------------------------------

export const analyticsApi = {
  overview: (params?: { days?: number; agent_id?: string }) =>
    api.get('/proxy/analytics/overview', { params }).then((r) => r.data),
}

// ---------------------------------------------------------------------------
// Playbook (via proxy)
// ---------------------------------------------------------------------------

export const playbookApi = {
  get: (agentId: string) =>
    api.get(`/proxy/agents/${agentId}/playbook`).then((r) => r.data),

  upsert: (agentId: string, data: {
    greeting_message?: string
    instructions?: string
    tone?: string
    dos?: string[]
    donts?: string[]
    scenarios?: { trigger: string; response: string }[]
    out_of_scope_response?: string
    fallback_response?: string
    custom_escalation_message?: string
    is_active?: boolean
  }) => api.put(`/proxy/agents/${agentId}/playbook`, data).then((r) => r.data),

  delete: (agentId: string) =>
    api.delete(`/proxy/agents/${agentId}/playbook`),
}

// ---------------------------------------------------------------------------
// Guardrails (via proxy)
// ---------------------------------------------------------------------------

export const guardrailsApi = {
  get: (agentId: string) =>
    api.get(`/proxy/agents/${agentId}/guardrails`).then((r) => r.data),

  upsert: (agentId: string, data: {
    blocked_keywords?: string[]
    blocked_topics?: string[]
    allowed_topics?: string[]
    profanity_filter?: boolean
    pii_redaction?: boolean
    max_response_length?: number
    require_disclaimer?: string
    blocked_message?: string
    off_topic_message?: string
    content_filter_level?: string
    is_active?: boolean
  }) => api.put(`/proxy/agents/${agentId}/guardrails`, data).then((r) => r.data),

  delete: (agentId: string) =>
    api.delete(`/proxy/agents/${agentId}/guardrails`),
}

// ---------------------------------------------------------------------------
// Learning (via proxy)
// ---------------------------------------------------------------------------

export const learningApi = {
  getInsights: (agentId: string, limit?: number) =>
    api.get(`/proxy/agents/${agentId}/learning`, { params: limit ? { limit } : undefined }).then((r) => r.data),
}

// ---------------------------------------------------------------------------
// Embed / Widget public token (future: api-keys with widget scope)
// ---------------------------------------------------------------------------

export const embedApi = {
  // Returns the snippet and SDK info for the current agent
  getSnippet: (agentId: string, apiKey: string, apiUrl: string) => ({
    scriptTag: `<script>\n  window.AscenAI = {\n    agentId: '${agentId}',\n    apiKey: '${apiKey}',\n    apiUrl: '${apiUrl}',\n  };\n</script>\n<script src="${apiUrl}/widget/widget.js" defer></script>`,
    npmInstall: `npm install @ascenai/sdk`,
    sdkUsage: `import { AscenAIClient } from '@ascenai/sdk';\n\nconst client = new AscenAIClient({\n  apiKey: '${apiKey}',\n  apiUrl: '${apiUrl}',\n  agentId: '${agentId}',\n});\n\nconst response = await client.chat('Hello!');\nconsole.log(response.message);`,
  }),
}
