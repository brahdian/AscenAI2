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

const API_URL = typeof window !== 'undefined' ? (process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000') : (process.env.INTERNAL_API_URL || 'http://api-gateway:8000')

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
    withCredentials: true,
  })

  // The client relies strictly on HttpOnly cookies sent via withCredentials
  // No explicit Bearer tokens are attached from localStorage
  client.interceptors.request.use((config) => {
    // Zenith Pillar 1: Trace Continuity
    // Inject X-Trace-ID onto every API call so forensic logs correlate 1:1 with frontend actions
    if (!config.headers['X-Trace-ID'] && typeof window !== 'undefined' && window.crypto?.randomUUID) {
      config.headers['X-Trace-ID'] = window.crypto.randomUUID()
    }
    return config
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
        !original.url?.includes('/auth/') &&
        !original.url?.includes('/billing/plans')
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
          if (typeof window !== 'undefined') {
            const { useAuthStore } = await import('@/store/auth')
            useAuthStore.getState().logout()
            // POST /auth/logout so the server clears its cookies too
            try { await _refreshClient.post('/auth/logout') } catch { /* ignore */ }
            window.location.href = '/login'
          }
          // Return an unresolved promise to freeze the UI state instead of rejecting.
          // This prevents components from catching the error and displaying false
          // "failed to load" messages while the browser is redirecting to login.
          return new Promise(() => {})
        } finally {
          _isRefreshing = false
        }
      }

      // Handle 402 Payment Required (e.g. creating an agent without a slot)
      if (status === 402) {
        const detail = (error.response?.data as any)?.detail
        const paymentUrl = detail?.payment_url
        if (paymentUrl && typeof window !== 'undefined') {
          // Immediately redirect to Stripe for checkout
          window.location.href = paymentUrl
          return new Promise(() => {}) // Freeze UI until redirect
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
    plan?: string
  }) => api.post('/auth/register', data).then((r) => r.data),

  login: (data: { email: string; password: string }) =>
    api.post('/auth/login', data).then((r) => r.data),

  /** Trigger a refresh — the server reads the refresh_token cookie. */
  refresh: () => api.post('/auth/refresh').then((r) => r.data),

  logout: () => api.post('/auth/logout'),

  verifyEmail: (data: { email: string; otp: string }) =>
    api.post('/auth/verify-email', data).then((r) => r.data),

  resendOTP: (data: { email: string }) =>
    api.post('/auth/resend-otp', data).then((r) => r.data),

  me: () => api.get('/auth/me').then((r) => r.data),

  updateMe: (data: { full_name?: string }) =>
    api.patch('/auth/me', data).then((r) => r.data),

  changePassword: (data: { current_password: string; new_password: string }) =>
    api.post('/auth/change-password', data).then((r) => r.data),

  forgotPassword: (data: { email: string }) =>
    api.post('/auth/forgot-password', data).then((r) => r.data),

  resetPassword: (data: { token: string; new_password: string }) =>
    api.post('/auth/reset-password', data).then((r) => r.data),

  subscribe: (data: { email: string; plan: string }) =>
    api.post('/auth/subscribe', data).then((r) => r.data),

  // ── Profile Security ──────────────────────────────────────────────────────
  /** Upload a new avatar image (multipart/form-data). */
  uploadAvatar: (formData: FormData) =>
    api.post('/auth/avatar', formData, { headers: { 'Content-Type': 'multipart/form-data' } }),

  /** Soft-delete the current user's account. */
  deleteMe: () => api.delete('/auth/me'),

  /** Revoke all other sessions by incrementing session_version. */
  logoutOthers: () => api.post('/auth/logout-others').then((r) => r.data),

  /** Request an email change (sends OTP to new email). */
  requestEmailChange: (data: { new_email: string; password: string }) =>
    api.post('/auth/request-email-change', data).then((r) => r.data),

  /** Verify email change OTP and update the user's email. */
  verifyEmailChange: (data: { otp: string }) =>
    api.post('/auth/verify-email-change', data),

  /** Accept a team invitation and set up an account. */
  acceptInvite: (data: { token: string; full_name: string; password: string }) =>
    api.post('/auth/accept-invite', data).then((r) => r.data),
}

// ---------------------------------------------------------------------------
// Tenant
// ---------------------------------------------------------------------------

export const tenantApi = {
  getMe: () => api.get('/tenants/me').then((r) => r.data),
  updateMe: (data: Record<string, unknown>) =>
    api.patch('/tenants/me', data).then((r) => r.data),
  getUsage: () => api.get('/tenants/me/usage').then((r) => r.data),
  selfDestruct: () => api.post('/tenants/me/self-destruct').then((r) => r.data),
}

// ---------------------------------------------------------------------------
// Agents (via proxy)
// ---------------------------------------------------------------------------

export const agentsApi = {
  list: (params?: { agent_id?: string; status?: string; limit?: number }) =>
    api.get('/proxy/agents', { params }).then((r) => r.data),
  get: (id: string) => api.get(`/proxy/agents/${id}`).then((r) => r.data),
  create: (data: Record<string, unknown> & {
    template_context?: {
      template_id: string
      template_version_id: string
      variable_values?: Record<string, any>
      tool_configs?: Record<string, any>
    }
  }) => api.post('/proxy/agents', data).then((r) => r.data),
  update: (id: string, data: Record<string, unknown>) => {
    const {
      auto_detect_language,
      supported_languages,
      greeting_message,
      ivr_language_prompt,
      voice_system_prompt,
      escalation_config,
      tone,
      ...rest
    } = data as Record<string, unknown>
    const payload: Record<string, unknown> = { ...rest }
    const agentConfig: Record<string, unknown> = {}
    if (auto_detect_language !== undefined) agentConfig.auto_detect_language = auto_detect_language
    if (supported_languages !== undefined) agentConfig.supported_languages = supported_languages
    if (greeting_message !== undefined) agentConfig.greeting_message = greeting_message
    if (ivr_language_prompt !== undefined) agentConfig.ivr_language_prompt = ivr_language_prompt
    if (voice_system_prompt !== undefined) agentConfig.voice_system_prompt = voice_system_prompt
    if (escalation_config !== undefined) agentConfig.escalation_config = escalation_config
    if (tone !== undefined) agentConfig.tone = tone
    if (Object.keys(agentConfig).length > 0) {
      payload.agent_config = agentConfig
    }
    return api.patch(`/proxy/agents/${id}`, payload).then((r) => r.data)
  },
  delete: (id: string) => api.delete(`/proxy/agents/${id}`),
  restore: (id: string) => api.post(`/proxy/agents/${id}/restore`).then((r) => r.data),
  test: (id: string, message: string) =>
    api.post(`/proxy/agents/${id}/test`, { message }).then((r) => r.data),
  getOpeningPreview: (id: string, language?: string, supportedLanguages?: string[], greeting?: string, ivrPrompt?: string) => {
    const params = new URLSearchParams()
    if (language) params.append('language', language)
    if (supportedLanguages !== undefined) params.append('supported_languages', supportedLanguages.join(','))
    if (greeting) params.append('greeting', greeting)
    if (ivrPrompt !== undefined) params.append('ivr_prompt', ivrPrompt)
    return api.get(`/proxy/agents/${id}/opening-preview?${params.toString()}`).then((r) => r.data as { text: string })
  },
  
  // IVR DTMF Menu
  getIvrDtmfMenu: (id: string) => api.get(`/proxy/agents/${id}/ivr-dtmf-menu`).then((r) => r.data),
  updateIvrDtmfMenu: (id: string, menu: any) =>
    api.patch(`/proxy/agents/${id}/ivr-dtmf-menu`, { ivr_dtmf_menu: menu }).then((r) => r.data),
  generateDtmfEntryAudio: (id: string, digit: string) =>
    api.post(`/proxy/agents/${id}/ivr-dtmf-menu/${digit}/generate-audio`).then((r) => r.data),

  uploadVoiceGreeting: (id: string, blob: Blob, ext: string) => {
    const form = new FormData()
    form.append('audio', blob, `greeting.${ext}`)
    return api
      .post(`/proxy/agents/${id}/voice-greeting`, form, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      .then((r) => r.data)
  },
  deleteVoiceGreeting: (id: string) =>
    api.delete(`/proxy/agents/${id}/voice-greeting`).then((r) => r.data),
  generateGreetingAudio: (id: string) =>
    api.post(`/proxy/agents/${id}/generate-greeting-audio`).then((r) => r.data),
  generateIvrAudio: (id: string) =>
    api.post(`/proxy/agents/${id}/generate-ivr-audio`).then((r) => r.data),
  testEscalationConnector: (id: string) =>
    api.post(`/proxy/agents/${id}/escalation/test`).then((r) => r.data as {
      success: boolean
      connector_type: string
      message: string
      latency_ms: number
    }),
  /** Activate/revive an agent (subject to slot capacity check at gateway). */
  slotActivate: (id: string, body?: { stripe_subscription_id?: string; expires_at?: string }) =>
    api.post(`/proxy/agents/${id}/slot-activate`, body ?? {}).then((r) => r.data),
  /** Archive an agent to free its slot for reuse. */
  slotArchive: (id: string) =>
    api.post(`/proxy/agents/${id}/slot-archive`).then((r) => r.data),
  /** Atomic archive and activate. */
  slotSwap: (archiveId: string, activateId: string) =>
    api.post("/proxy/agents/slot-swap", { archive_id: archiveId, activate_id: activateId }).then((r) => r.data),
  /** List all active agents in the same tenant that are marked is_available_as_tool=true. */
  listAvailableAsTools: (excludeId?: string) =>
    api.get('/proxy/agents/available-as-tools', { params: excludeId ? { exclude_id: excludeId } : {} })
      .then((r) => r.data as any[]),
}


// ---------------------------------------------------------------------------
// Templates (via proxy)
// ---------------------------------------------------------------------------

export const templatesApi = {
  list: () => api.get('/proxy/templates').then((r) => r.data),
  get: (id: string) => api.get(`/proxy/templates/${id}`).then((r) => r.data),
  instantiate: (id: string, data: Record<string, unknown>) =>
    api.post(`/proxy/templates/${id}/instantiate`, data).then((r) => r.data),
  getInstanceByAgent: (agentId: string) =>
    api.get(`/proxy/templates/instances/by-agent/${agentId}`).then((r) => r.data),
  updateInstance: (instanceId: string, data: { variable_values: Record<string, any> }) =>
    api.patch(`/proxy/templates/instances/${instanceId}`, data).then((r) => r.data),
}


// ---------------------------------------------------------------------------
// Chat (via proxy)
// ---------------------------------------------------------------------------

export const chatApi = {
  init: (data: {
    agent_id: string
    channel: 'chat' | 'voice'
    customer_identifier?: string
    test_mode?: boolean
  }) => api.post('/proxy/chat/init', data).then((r) => r.data as {
    session_id: string
    chat_greeting: string
    voice_greeting: string
    language: string
    supported_languages: string[]
    auto_detect_language: boolean
  }),

  send: (data: {
    agent_id: string
    message: string
    session_id?: string
    channel?: string
    test_mode?: boolean
  }) => api.post('/proxy/chat', data).then((r) => r.data),

  agentCall: (data: {
    agent_id: string
    message: string
    context?: string
    tenant_id?: string
  }) => api.post('/proxy/chat/agent-call', data).then((r) => r.data),

  stream: async (data: {
    agent_id: string
    message: string
    session_id?: string
    channel?: string
    test_mode?: boolean
  }, onChunk: (chunk: string, meta?: Record<string, any>) => void, onSession?: (sessionId: string) => void) => {
    const response = await fetch(`${API_URL}/api/v1/proxy/chat/stream`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      credentials: 'include',
      body: JSON.stringify(data),
    })

    if (!response.ok) throw new Error(`HTTP ${response.status}`)
    const reader = response.body?.getReader()
    if (!reader) return

    const decoder = new TextDecoder()
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      
      const chunk = decoder.decode(value, { stream: true })
      const lines = chunk.split('\n')
      
      for (const line of lines) {
        if (line.startsWith('data: ')) {
          try {
            const parsed = JSON.parse(line.substring(6))
            if (parsed.type === 'text_delta' && parsed.data) {
              const meta: Record<string, any> = {}
              if (parsed.session_status) meta.session_status = parsed.session_status
              if (parsed.minutes_until_expiry != null) meta.minutes_until_expiry = parsed.minutes_until_expiry
              if (parsed.expiry_warning != null) meta.expiry_warning = parsed.expiry_warning
              onChunk(parsed.data, Object.keys(meta).length > 0 ? meta : undefined)
            } else if (parsed.type === 'done' && parsed.data) {
              const d = typeof parsed.data === 'string' ? JSON.parse(parsed.data) : parsed.data
              if (d.session_status) onChunk('', { session_status: d.session_status })
              if (onSession && d.session_id) onSession(d.session_id)
            } else if (parsed.type === 'session' || parsed.session_id) {
              if (onSession) onSession(parsed.session_id || parsed.data)
            }
          } catch (e) {
            // Ignore partial/invalid SSE lines
          }
        }
      }
    }
  }
}

// ---------------------------------------------------------------------------
// Voice / TTS (via proxy)
// ---------------------------------------------------------------------------

export const voiceApi = {
  /**
   * Stream TTS audio for a text response.
   * Returns a ReadableStream of MP3 audio bytes for immediate playback.
   */
  streamTts: async (text: string, voiceId?: string): Promise<ReadableStream<Uint8Array> | null> => {
    if (!text.trim()) return null
    const response = await fetch(`${API_URL}/api/v1/proxy/voice/tts/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ text, voice_id: voiceId || 'alloy' }),
    })
    if (!response.ok) return null
    return response.body
  },

  /**
   * Play streamed TTS audio using the Web Audio API.
   * Accumulates chunks and plays as they arrive for low-latency voice preview.
   * Returns a function to stop playback.
   */
  playStreamedAudio: async (
    stream: ReadableStream<Uint8Array>,
    onChunk?: (bytesReceived: number) => void
  ): Promise<() => void> => {
    const audioCtx = new (window.AudioContext || (window as any).webkitAudioContext)()
    const reader = stream.getReader()
    const chunks: Uint8Array[] = []
    let cancelled = false

    const decodeAndPlay = async () => {
      let totalBytes = 0
      try {
        while (!cancelled) {
          const { done, value } = await reader.read()
          if (done) break
          if (value) {
            chunks.push(value)
            totalBytes += value.length
            onChunk?.(totalBytes)
          }
        }
      } catch {
        // Stream interrupted
      }

      if (chunks.length === 0 || cancelled) return

      // Concatenate all chunks into a single ArrayBuffer
      const totalLength = chunks.reduce((acc, c) => acc + c.length, 0)
      const combined = new Uint8Array(totalLength)
      let offset = 0
      for (const chunk of chunks) {
        combined.set(chunk, offset)
        offset += chunk.length
      }

      try {
        const audioBuffer = await audioCtx.decodeAudioData(combined.buffer)
        const source = audioCtx.createBufferSource()
        source.buffer = audioBuffer
        source.connect(audioCtx.destination)
        source.start(0)
      } catch (e) {
        // Decoding failed — audio data may be incomplete
      }
    }

    // Start accumulating and playing
    decodeAndPlay()

    return () => {
      cancelled = true
      reader.cancel().catch(() => {})
      audioCtx.close().catch(() => {})
    }
  },
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
  end: (id: string) => api.post(`/proxy/sessions/${id}/end`).then((r) => r.data),
  analytics: (id: string) => api.get(`/proxy/sessions/${id}/analytics`).then((r) => r.data),
}

// ---------------------------------------------------------------------------
// API Keys
// ---------------------------------------------------------------------------

export const apiKeysApi = {
  list: () => api.get('/api-keys').then((r) => r.data),
  create: (data: { name: string; scopes?: string[]; agent_id?: string }) =>
    api.post('/api-keys', data).then((r) => r.data),
  revoke: (id: string) => api.delete(`/api-keys/${id}`),
  patch: (id: string, data: { name?: string; allowed_origins?: string[]; is_active?: boolean }) =>
    api.patch(`/api-keys/${id}`, data).then((r) => r.data),
}

// ---------------------------------------------------------------------------
// Feedback (via proxy)
// ---------------------------------------------------------------------------

export const feedbackApi = {
  submit: (data: {
    message_id: string
    session_id: string
    agent_id: string
    rating?: 'positive' | 'negative'
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
    has_correction?: boolean
    include_messages?: boolean
    limit?: number
    offset?: number
  }) => api.get('/proxy/feedback', { params }).then((r) => r.data),

  delete: (id: string) => api.delete(`/proxy/feedback/${id}`),

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

export interface AgentAnalyticsSummary {
  agent_id: string
  agent_name: string
  total_sessions: number
  total_messages: number
  total_chats: number
  total_tokens: number
  estimated_cost_usd: number
  avg_latency_ms: number
  total_voice_minutes: number
  positive_feedback_pct: number | null
}

export interface DailyAnalytics {
  date: string
  total_sessions: number
  total_messages: number
  total_chats: number
  total_tokens: number
  estimated_cost_usd: number
  avg_latency_ms: number
  tool_executions: number
  escalations: number
  successful_completions: number
  total_voice_minutes: number
}

export interface AnalyticsOverview {
  period_days: number
  total_sessions: number
  total_messages: number
  total_chats: number
  total_tokens: number
  /** Total estimated LLM token cost for the period (USD). */
  total_cost_usd: number
  avg_latency_ms: number
  total_tool_executions: number
  total_escalations: number
  /** Total voice session minutes for the period. */
  total_voice_minutes: number
  feedback_positive_pct: number | null
  daily: DailyAnalytics[]
  by_agent: AgentAnalyticsSummary[]
}

export const analyticsApi = {
  overview: (params?: { days?: number; agent_id?: string }) =>
    api.get<AnalyticsOverview>('/proxy/analytics/overview', { params }).then((r) => r.data),
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
    pii_pseudonymization?: boolean
    max_response_length?: number
    require_disclaimer?: string
    blocked_message?: string
    off_topic_message?: string
    content_filter_level?: string
    is_active?: boolean
  }) => {
    const payload = {
      config: {
        blocked_keywords: data.blocked_keywords,
        blocked_topics: data.blocked_topics,
        allowed_topics: data.allowed_topics,
        profanity_filter: data.profanity_filter,
        pii_redaction: data.pii_redaction,
        pii_pseudonymization: data.pii_pseudonymization,
        max_response_length: data.max_response_length,
        require_disclaimer: data.require_disclaimer,
        blocked_message: data.blocked_message,
        off_topic_message: data.off_topic_message,
        content_filter_level: data.content_filter_level,
      },
      is_active: data.is_active,
    }
    return api.put(`/proxy/agents/${agentId}/guardrails`, payload).then((r) => r.data)
  },

  delete: (agentId: string) =>
    api.delete(`/proxy/agents/${agentId}/guardrails`),

  // Agent-specific custom guardrails
  listCustom: (agentId: string) =>
    api.get(`/proxy/agents/${agentId}/guardrails/custom`).then((r) => r.data),

  createCustom: (agentId: string, data: { rule: string; category?: string }) =>
    api.post(`/proxy/agents/${agentId}/guardrails/custom`, data).then((r) => r.data),

  updateCustom: (agentId: string, customId: string, data: { rule?: string; category?: string; is_active?: boolean }) =>
    api.patch(`/proxy/agents/${agentId}/guardrails/custom/${customId}`, data).then((r) => r.data),

  deleteCustom: (agentId: string, customId: string) =>
    api.delete(`/proxy/agents/${agentId}/guardrails/custom/${customId}`),

  // Global guardrails change requests
  requestChange: (data: { guardrail_id: string; proposed_rule: string; reason: string }) =>
    api.post('/proxy/guardrails/change-requests', data).then((r) => r.data),

  listChangeRequests: () =>
    api.get('/proxy/guardrails/change-requests').then((r) => r.data),
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
  list: (agentId: string) => api.get(`/proxy/agents/${agentId}/playbooks`).then((r) => r.data),
  validateSafety: (text: string) => api.post('/proxy/playbooks/validate-safety', { text }).then((r) => r.data),
  create: (agentId: string, data: Record<string, unknown>) => {
    const payload = {
      name: data.name,
      description: data.description,
      intent_triggers: data.intent_triggers,
      config: {
        instructions: data.instructions,
        tone: data.tone || 'professional',
        dos: data.dos || [],
        donts: data.donts || [],
        scenarios: data.scenarios || [],
        out_of_scope_response: data.out_of_scope_response,
        fallback_response: data.fallback_response,
        custom_escalation_message: data.custom_escalation_message,
      },
      is_active: data.is_active ?? true,
    }
    return api.post(`/proxy/agents/${agentId}/playbooks`, payload).then((r) => r.data)
  },
  get: (agentId: string, playbookId: string) =>
    api.get(`/proxy/agents/${agentId}/playbooks/${playbookId}`).then((r) => r.data),
  update: (agentId: string, playbookId: string, data: Record<string, unknown>) => {
    const payload = {
      name: data.name,
      description: data.description,
      intent_triggers: data.intent_triggers,
      config: {
        instructions: data.instructions,
        tone: data.tone || 'professional',
        dos: data.dos || [],
        donts: data.donts || [],
        scenarios: data.scenarios || [],
        out_of_scope_response: data.out_of_scope_response,
        fallback_response: data.fallback_response,
        custom_escalation_message: data.custom_escalation_message,
      },
      is_active: data.is_active,
    }
    return api.put(`/proxy/agents/${agentId}/playbooks/${playbookId}`, payload).then((r) => r.data)
  },
  delete: (agentId: string, playbookId: string) =>
    api.delete(`/proxy/agents/${agentId}/playbooks/${playbookId}`),
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
    // Do NOT set Content-Type manually — axios/browser sets it automatically
    // with the correct multipart boundary when given FormData
    return api.post(`/proxy/agents/${agentId}/documents`, form).then((r) => r.data)
  },
  createText: (agentId: string, data: { name: string; content: string; status?: 'draft' | 'published' }) =>
    api.post(`/proxy/agents/${agentId}/documents/text`, data).then((r) => r.data),
  updateText: (agentId: string, docId: string, data: { name?: string; content?: string; status?: 'draft' | 'published' }) =>
    api.put(`/proxy/agents/${agentId}/documents/${docId}`, data).then((r) => r.data),
  retryIndexing: (agentId: string, docId: string) =>
    api.post(`/proxy/agents/${agentId}/documents/${docId}/retry`).then((r) => r.data),
  delete: (agentId: string, docId: string) =>
    api.delete(`/proxy/agents/${agentId}/documents/${docId}`),
}

// ---------------------------------------------------------------------------
// Variables API
// ---------------------------------------------------------------------------

export const variablesApi = {
  list: (agentId: string) => api.get(`/proxy/agents/${agentId}/variables`).then((r) => r.data),
  create: (agentId: string, data: Record<string, unknown>) =>
    api.post(`/proxy/agents/${agentId}/variables`, data).then((r) => r.data),
  update: (agentId: string, varId: string, data: Record<string, unknown>) =>
    api.put(`/proxy/agents/${agentId}/variables/${varId}`, data).then((r) => r.data),
  delete: (agentId: string, varId: string) =>
    api.delete(`/proxy/agents/${agentId}/variables/${varId}`).then((r) => r.data),
  exportUrl: (agentId: string, justificationId: string) => {
    const qs = new URLSearchParams({ justification_id: justificationId }).toString()
    return `${API_URL}/api/v1/proxy/agents/${agentId}/variables/export?${qs}`
  },
}

// ---------------------------------------------------------------------------
// Team management API
// ---------------------------------------------------------------------------

export const teamApi = {
  list: () => api.get('/team').then((r) => r.data),
  listInvites: () => api.get('/team/invites').then((r) => r.data),
  invite: (data: { email: string; full_name: string; role: string }) =>
    api.post('/team/invite', data).then((r) => r.data),
  updateRole: (userId: string, role: string) =>
    api.patch(`/team/${userId}/role`, { role }).then((r) => r.data),
  remove: (userId: string) => api.delete(`/team/${userId}`),
  reactivate: (userId: string) => api.post(`/team/${userId}/reactivate`).then((r) => r.data),
  hardRemove: (userId: string) => api.delete(`/team/${userId}/hard`),
}

// ---------------------------------------------------------------------------
// Billing API
// ---------------------------------------------------------------------------

export const billingApi = {
  overview: () => api.get('/billing/overview').then((r) => r.data),
  listPlans: () => api.get('/billing/plans').then((r) => r.data as Record<string, any>),
  agents: () => api.get('/billing/agents').then((r) => r.data),
  createCheckoutSession: (data: { plan: string; billing_cycle?: string }) =>
    api.post('/billing/create-checkout-session', data).then((r) => r.data),
  createPortalSession: () =>
    api.post('/billing/portal-session').then((r) => r.data as { portal_url: string }),
  createAgentSlotSession: (agentConfig?: any, returnPath?: string, plan?: string) =>
    api.post('/billing/create-agent-slot-session', { agent_config: agentConfig, return_path: returnPath, plan }).then((r) => r.data as { checkout_url: string }),
  getInvoices: () =>
    api.get('/billing/invoices').then((r) => r.data as { invoices: any[] }),
  cancel: () => api.post('/billing/cancel').then((r) => r.data),
  toggleVoiceAddon: (enabled: boolean) =>
    api.post('/billing/voice-addon', { enabled }).then((r) => r.data),
  syncSubscription: () => api.post('/billing/sync-subscription').then((r) => r.data),
  /** Alias for overview — includes purchased_slots / agent_slots for capacity indicator. */
  getInfo: () => api.get('/billing/overview').then((r) => r.data),
}

// ---------------------------------------------------------------------------
// Tools / Integrations API (via proxy → mcp-server)
// ---------------------------------------------------------------------------

export const toolsApi = {
  getCatalog: () => api.get('/proxy/tools/catalog').then((r) => r.data),
  list: (agentId?: string) => api.get('/proxy/tools', { params: { agent_id: agentId } }).then((r) => r.data),
  get: (name: string) => api.get(`/proxy/tools/${name}`).then((r) => r.data),
  register: (data: {
    name: string
    description: string
    category: string
    endpoint_url?: string
    input_schema?: Record<string, unknown>
    output_schema?: Record<string, unknown>
    is_builtin?: boolean
    tool_metadata?: Record<string, unknown>
    rate_limit_per_minute?: number
    timeout_seconds?: number
  }) => api.post('/proxy/tools', data).then((r) => r.data),
  update: (name: string, data: Record<string, unknown>) =>
    api.patch(`/proxy/tools/${name}`, data).then((r) => r.data),
  testExecute: (data: { tool_config: Record<string, unknown>, parameters: Record<string, unknown> }) =>
    api.post('/proxy/tools/test-execute', data).then((r) => r.data),
  delete: (name: string) => api.delete(`/proxy/tools/${name}`),
  /**
   * Verify tool credentials before saving.
   * For known providers (stripe, twilio, google_calendar …) this calls the
   * provider's lightest read-only endpoint.
   * For generic HTTP tools pass endpoint_url + config to test reachability.
   */
  verify: (payload: {
    provider: string
    config: Record<string, unknown>
    endpoint_url?: string
  }): Promise<{
    ok: boolean
    latency_ms: number
    error?: string
    details?: Record<string, unknown>
  }> => api.post('/proxy/tools/verify', payload).then((r) => r.data),
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
// Workflows (visual DAG workflow builder)
// ---------------------------------------------------------------------------

export const workflowsApi = {
  list: (agentId: string, params?: { include_archived?: boolean }) =>
    api.get(`/proxy/agents/${agentId}/workflows`, { params }).then((r) => r.data),
  create: (agentId: string, data: Record<string, unknown>) =>
    api.post(`/proxy/agents/${agentId}/workflows`, data).then((r) => r.data),
  get: (agentId: string, flowId: string) =>
    api.get(`/proxy/agents/${agentId}/workflows/${flowId}`).then((r) => r.data),
  update: (agentId: string, flowId: string, data: Record<string, unknown>) =>
    api.put(`/proxy/agents/${agentId}/workflows/${flowId}`, data).then((r) => r.data),
  patch: (agentId: string, flowId: string, data: Record<string, unknown>) =>
    api.patch(`/proxy/agents/${agentId}/workflows/${flowId}`, data).then((r) => r.data),
  delete: (agentId: string, flowId: string) =>
    api.delete(`/proxy/agents/${agentId}/workflows/${flowId}`),
  archive: (agentId: string, flowId: string) =>
    api.post(`/proxy/agents/${agentId}/workflows/${flowId}/archive`).then((r) => r.data),
  restore: (agentId: string, flowId: string) =>
    api.post(`/proxy/agents/${agentId}/workflows/${flowId}/restore`).then((r) => r.data),
  activate: (agentId: string, flowId: string) =>
    api.post(`/proxy/agents/${agentId}/workflows/${flowId}/activate`).then((r) => r.data),
  deactivate: (agentId: string, flowId: string) =>
    api.post(`/proxy/agents/${agentId}/workflows/${flowId}/deactivate`).then((r) => r.data),
  clone: (agentId: string, flowId: string) =>
    api.post(`/proxy/agents/${agentId}/workflows/${flowId}/clone`).then((r) => r.data),
  listExecutions: (agentId: string, flowId: string, status?: string) =>
    api
      .get(`/proxy/agents/${agentId}/workflows/${flowId}/executions`, { params: status ? { status } : {} })
      .then((r) => r.data),
  getExecution: (agentId: string, flowId: string, sessionId: string) =>
    api
      .get(`/proxy/agents/${agentId}/workflows/${flowId}/executions/${sessionId}`)
      .then((r) => r.data),
  advance: (agentId: string, flowId: string, data: Record<string, unknown>) =>
    api.post(`/proxy/agents/${agentId}/workflows/${flowId}/advance`, data).then((r) => r.data),
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

// ---------------------------------------------------------------------------
// Platform Settings (Admin)
// ---------------------------------------------------------------------------

export const platformSettingsApi = {
  list: () => api.get('/admin/settings').then((r) => r.data),
  update: (key: string, value: any) =>
    api.put(`/admin/settings/${key}`, { value }).then((r) => r.data),
}

// ---------------------------------------------------------------------------
// Admin API
// ---------------------------------------------------------------------------

export const adminApi = {
  // Tenants
  listTenants: (params?: { page?: number; per_page?: number; status?: string }) =>
    api.get('/admin/tenants', { params }).then((r) => r.data),

  getTenant: (tenantId: string) =>
    api.get(`/admin/tenants/${tenantId}`).then((r) => r.data),

  suspendTenant: (tenantId: string, reason: string) =>
    api.post(`/admin/tenants/${tenantId}/suspend`, { reason }).then((r) => r.data),

  reactivateTenant: (tenantId: string) =>
    api.post(`/admin/tenants/${tenantId}/reactivate`).then((r) => r.data),

  deleteTenant: (tenantId: string, hard_delete?: boolean) =>
    api.delete(`/admin/tenants/${tenantId}`, { params: { hard_delete: hard_delete ?? false } }).then((r) => r.data),

  // Users
  listUsers: (params?: { tenant_id?: string; page?: number; per_page?: number }) =>
    api.get('/admin/users', { params }).then((r) => r.data),

  updateUserRole: (userId: string, role: string) =>
    api.put(`/admin/users/${userId}/role`, { role }).then((r) => r.data),

  // Prompts
  getPrompts: (agentId?: string) =>
    api.get('/admin/prompts', { params: agentId ? { agent_id: agentId } : undefined }).then((r) => r.data),

  updatePrompt: (agentId: string, systemPrompt: string) =>
    api.put(`/admin/prompts/${agentId}`, { system_prompt: systemPrompt }).then((r) => r.data),

  // Traces
  getTraces: (params?: { session_id?: string; tenant_id?: string; limit?: number }) =>
    api.get('/admin/traces', { params }).then((r) => r.data),

  // Metrics
  getMetrics: () => api.get('/admin/metrics').then((r) => r.data),

  // Roles
  listRoles: () => api.get('/admin/roles').then((r) => r.data),

  // Settings
  getSettings: () => api.get('/admin/settings').then((r) => r.data),

  updateSetting: (key: string, value: any) =>
    api.put(`/admin/settings/${key}`, { value }).then((r) => r.data),

  // Trial tenant creation (bypasses payment)
  createTrialTenant: (data: {
    name: string
    business_name: string
    plan: string
    admin_email: string
    admin_password: string
  }) => api.post('/admin/trial-tenants', data).then((r) => r.data),

  // Tenant usage
  getTenantsUsage: () => api.get('/admin/tenants/usage').then((r) => r.data),

  // Platform Guardrails
  listGuardrails: () => api.get('/admin/guardrails').then((r) => r.data),
  updateGuardrail: (guardrailId: string, enabled: boolean) =>
    api.patch(`/admin/guardrails/${guardrailId}`, { enabled }).then((r) => r.data),
}
// ---------------------------------------------------------------------------
// Platform Configuration
// ---------------------------------------------------------------------------

export interface GlobalGuardrail {
  id: string
  category: string
  rule: string
  fix_ref: string
}

export const platformApi = {
  getLanguageConfig: (): Promise<{
    languages: Array<{ code: string; label: string }>
    greetings: Record<string, string>
    assist_prefixes: Record<string, string>
    phrases: Record<string, string>
  }> => api.get('/proxy/platform/language-config').then((r) => r.data),
  getVoiceProtocols: (): Promise<Array<{ id: string; label: string; template: string }>> =>
    api.get('/proxy/platform/voice-protocols').then((r) => r.data),
  getGlobalGuardrails: (): Promise<{ guardrails: GlobalGuardrail[] }> =>
    api.get('/proxy/platform/global-guardrails').then((r) => r.data),
}
