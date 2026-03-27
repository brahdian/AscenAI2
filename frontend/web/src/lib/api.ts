/**
 * API client — cookie-based authentication.
 *
 * Tokens (access_token, refresh_token) are stored as HttpOnly cookies by the
 * server and are never accessible from JavaScript. The browser sends them
 * automatically with every same-origin (or credentialed cross-origin) request
 * because we set `withCredentials: true`.
 *
 * On a 401 response the client silently calls POST /auth/refresh (which also
 * uses the HttpOnly refresh_token cookie). If the refresh succeeds, the
 * original request is retried once. If it fails, the user is redirected to
 * /login and the auth store is cleared.
 */
import axios, { AxiosInstance, AxiosError } from 'axios'

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

// Separate "bare" instance used only for the refresh call so the response
// interceptor does not trigger recursively.
const _refreshClient = axios.create({
  baseURL: `${API_URL}/api/v1`,
  withCredentials: true,
  headers: { 'Content-Type': 'application/json' },
})

let _isRefreshing = false
let _pendingQueue: Array<{ resolve: () => void; reject: (e: unknown) => void }> = []

function _drainQueue(error?: unknown) {
  _pendingQueue.forEach((p) => (error ? p.reject(error) : p.resolve()))
  _pendingQueue = []
}

function createApiClient(): AxiosInstance {
  const client = axios.create({
    baseURL: `${API_URL}/api/v1`,
    headers: { 'Content-Type': 'application/json' },
    // Send HttpOnly auth cookies automatically on every request
    withCredentials: true,
  })

  // 401 → try a silent token refresh, then retry the original request once
  client.interceptors.response.use(
    (res) => res,
    async (error: AxiosError) => {
      const original = error.config as (typeof error.config & { _retry?: boolean }) | undefined
      const status = error.response?.status

      // Only attempt refresh for 401s on non-auth endpoints (avoid loops)
      if (
        status === 401 &&
        original &&
        !original._retry &&
        !original.url?.includes('/auth/')
      ) {
        if (_isRefreshing) {
          // Queue the retry until the in-flight refresh completes
          return new Promise<unknown>((resolve, reject) => {
            _pendingQueue.push({
              resolve: () => resolve(client(original)),
              reject,
            })
          })
        }

        original._retry = true
        _isRefreshing = true

        try {
          // POST /auth/refresh — sends the refresh_token HttpOnly cookie automatically
          await _refreshClient.post('/auth/refresh')
          _drainQueue()
          return client(original)
        } catch (refreshError) {
          _drainQueue(refreshError)
          // Refresh failed — clear client-side state and send to login
          if (typeof window !== 'undefined') {
            const { useAuthStore } = await import('@/store/auth')
            useAuthStore.getState().logout()
            // POST /auth/logout so the server clears its cookies too
            try { await _refreshClient.post('/auth/logout') } catch { /* ignore */ }
            window.location.href = '/login'
          }
          return Promise.reject(refreshError)
        } finally {
          _isRefreshing = false
        }
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

  /** Trigger a refresh — the server reads the refresh_token cookie. */
  refresh: () => api.post('/auth/refresh').then((r) => r.data),

  logout: () => api.post('/auth/logout'),
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
  uploadVoiceGreeting: (id: string, blob: Blob, ext: string) => {
    const form = new FormData()
    form.append('audio', blob, `greeting.${ext}`)
    return api
      .post(`/proxy/agents/${id}/voice-greeting`, form, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      .then((r) => r.data as { url: string })
  },
  deleteVoiceGreeting: (id: string) =>
    api.delete(`/proxy/agents/${id}/voice-greeting`).then((r) => r.data),
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
  create: (data: { name: string; scopes?: string[]; agent_id?: string }) =>
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
    playbook_correction?: { correct_playbook_id: string; correct_playbook_name: string } | null
    tool_corrections?: Array<{ tool_name: string; was_correct: boolean; correct_tool?: string; reason?: string }>
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

  /**
   * Returns a URL for the export endpoint. The browser will send the auth
   * cookie automatically when navigating to this URL (same-origin).
   */
  exportUrl: (params?: { format?: string; agent_id?: string; rating?: string }) => {
    const qs = new URLSearchParams({ ...(params as Record<string, string>) }).toString()
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
// Multi-playbook API
// ---------------------------------------------------------------------------

export const playbooksApi = {
  list: (agentId: string) =>
    api.get(`/proxy/agents/${agentId}/playbooks`).then((r) => r.data),
  create: (agentId: string, data: Record<string, unknown>) =>
    api.post(`/proxy/agents/${agentId}/playbooks`, data).then((r) => r.data),
  get: (agentId: string, playbookId: string) =>
    api.get(`/proxy/agents/${agentId}/playbooks/${playbookId}`).then((r) => r.data),
  update: (agentId: string, playbookId: string, data: Record<string, unknown>) =>
    api.put(`/proxy/agents/${agentId}/playbooks/${playbookId}`, data).then((r) => r.data),
  delete: (agentId: string, playbookId: string) =>
    api.delete(`/proxy/agents/${agentId}/playbooks/${playbookId}`),
  setDefault: (agentId: string, playbookId: string) =>
    api.post(`/proxy/agents/${agentId}/playbooks/${playbookId}/set-default`).then((r) => r.data),
}

// ---------------------------------------------------------------------------
// Documents / RAG API
// ---------------------------------------------------------------------------

export const documentsApi = {
  list: (agentId: string) =>
    api.get(`/proxy/agents/${agentId}/documents`).then((r) => r.data),
  upload: (agentId: string, file: File) => {
    const form = new FormData()
    form.append('file', file)
    return api.post(`/proxy/agents/${agentId}/documents`, form).then((r) => r.data)
  },
  delete: (agentId: string, docId: string) =>
    api.delete(`/proxy/agents/${agentId}/documents/${docId}`),
}

// ---------------------------------------------------------------------------
// Team management API
// ---------------------------------------------------------------------------

export const teamApi = {
  list: () => api.get('/team').then((r) => r.data),
  invite: (data: { email: string; full_name: string; role: string }) =>
    api.post('/team/invite', data).then((r) => r.data),
  updateRole: (userId: string, role: string) =>
    api.patch(`/team/${userId}/role`, { role }).then((r) => r.data),
  remove: (userId: string) => api.delete(`/team/${userId}`),
}

// ---------------------------------------------------------------------------
// Billing API
// ---------------------------------------------------------------------------

export const billingApi = {
  overview: () => api.get('/billing/overview').then((r) => r.data),
  agents: () => api.get('/billing/agents').then((r) => r.data),
}

// ---------------------------------------------------------------------------
// Tools / Integrations API (via proxy → mcp-server)
// ---------------------------------------------------------------------------

export const toolsApi = {
  catalog: () => api.get('/proxy/tools/catalog').then((r) => r.data),
  list: () => api.get('/proxy/tools').then((r) => r.data),
  get: (name: string) => api.get(`/proxy/tools/${name}`).then((r) => r.data),
  register: (data: {
    name: string
    description: string
    category: string
    input_schema?: Record<string, unknown>
    output_schema?: Record<string, unknown>
    is_builtin?: boolean
    tool_metadata?: Record<string, unknown>
    rate_limit_per_minute?: number
    timeout_seconds?: number
  }) => api.post('/proxy/tools', data).then((r) => r.data),
  update: (name: string, data: Record<string, unknown>) =>
    api.patch(`/proxy/tools/${name}`, data).then((r) => r.data),
  delete: (name: string) => api.delete(`/proxy/tools/${name}`),
  enableForAgent: (agentId: string, toolName: string, currentTools: string[]) => {
    if (currentTools.includes(toolName)) return Promise.resolve()
    return api.patch(`/proxy/agents/${agentId}`, { tools: [...currentTools, toolName] }).then((r) => r.data)
  },
  disableForAgent: (agentId: string, toolName: string, currentTools: string[]) =>
    api
      .patch(`/proxy/agents/${agentId}`, { tools: currentTools.filter((t) => t !== toolName) })
      .then((r) => r.data),
}

// ---------------------------------------------------------------------------
// PIPEDA / Compliance API
// ---------------------------------------------------------------------------

export const complianceApi = {
  getSettings: () => api.get('/compliance/settings').then((r) => r.data),
  updateSettings: (data: Record<string, unknown>) =>
    api.patch('/compliance/settings', data).then((r) => r.data),
  requestErasure: (data: { contact_identifier: string; reason?: string; requester_name?: string }) =>
    api.post('/compliance/erasure', data).then((r) => r.data),
  getErasureLog: () => api.get('/compliance/erasure-log').then((r) => r.data),
}

// ---------------------------------------------------------------------------
// Embed / Widget
// ---------------------------------------------------------------------------

export const embedApi = {
  getSnippet: (agentId: string, apiKey: string, apiUrl: string) => ({
    scriptTag: `<script>\n  window.AscenAI = {\n    agentId: '${agentId}',\n    apiKey: '${apiKey}',\n    apiUrl: '${apiUrl}',\n  };\n</script>\n<script src="${apiUrl}/widget/widget.js" defer></script>`,
    npmInstall: `npm install @ascenai/sdk`,
    sdkUsage: `import { AscenAIClient } from '@ascenai/sdk';\n\nconst client = new AscenAIClient({\n  apiKey: '${apiKey}',\n  apiUrl: '${apiUrl}',\n  agentId: '${agentId}',\n});\n\nconst response = await client.chat('Hello!');\nconsole.log(response.message);`,
  }),
}
