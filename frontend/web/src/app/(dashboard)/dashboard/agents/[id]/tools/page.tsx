'use client'

import { useState } from 'react'
import { useParams } from 'next/navigation'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { agentsApi, toolsApi } from '@/lib/api'
import toast from 'react-hot-toast'
import {
  Wrench,
  Settings,
  X,
  Eye,
  EyeOff,
  Plus,
  Trash2,
} from 'lucide-react'

// ─── Types ───────────────────────────────────────────────────────────────────

interface CatalogEntry {
  id: string
  name: string
  description: string
  category: string
  is_builtin: boolean
  allow_multiple?: boolean
  voice_capable?: boolean
  pci_compliant?: boolean
  channel_support?: string[]
  credentials: {
    field: string
    label: string
    type: string
    options?: string[]
    condition?: Record<string, string[]>
  }[]
}

interface ToolRecord {
  id: string
  name: string
  description: string
  category: string
  is_active: boolean
  is_builtin: boolean
  tool_metadata: Record<string, any>
  endpoint_url?: string
  input_schema?: Record<string, any>
  auth_config?: Record<string, any>
}

interface InputParam {
  name: string
  type: string
  description: string
  required: boolean
}

// ─── Constants ────────────────────────────────────────────────────────────────

const CATEGORY_LABELS: Record<string, string> = {
  booking: 'Booking',
  calendar: 'Calendar',
  crm: 'CRM',
  payments: 'Payments',
  messaging: 'Messaging',
  data: 'Data',
  custom: 'Custom',
  ordering: 'Ordering',
}

const CATEGORY_COLORS: Record<string, string> = {
  booking: 'bg-blue-50 text-blue-700 dark:bg-blue-900/20 dark:text-blue-300',
  calendar: 'bg-violet-50 text-violet-700 dark:bg-violet-900/20 dark:text-violet-300',
  crm: 'bg-amber-50 text-amber-700 dark:bg-amber-900/20 dark:text-amber-300',
  payments: 'bg-emerald-50 text-emerald-700 dark:bg-emerald-900/20 dark:text-emerald-300',
  messaging: 'bg-pink-50 text-pink-700 dark:bg-pink-900/20 dark:text-pink-300',
  data: 'bg-cyan-50 text-cyan-700 dark:bg-cyan-900/20 dark:text-cyan-300',
  custom: 'bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300',
  ordering: 'bg-orange-50 text-orange-700 dark:bg-orange-900/20 dark:text-orange-300',
}

const PARAM_TYPES = ['string', 'number', 'boolean', 'object', 'array']

const AUTH_TYPES = [
  { value: 'none', label: 'None' },
  { value: 'api_key', label: 'API Key  (X-API-Key header)' },
  { value: 'bearer', label: 'Bearer Token  (Authorization header)' },
  { value: 'basic', label: 'Basic Auth  (username + password)' },
  { value: 'oauth2_cc', label: 'OAuth2 Client Credentials  (server-to-server)' },
]

// ─── Helpers ──────────────────────────────────────────────────────────────────

function buildInputSchema(params: InputParam[]): Record<string, any> {
  if (params.length === 0) return {}
  const properties: Record<string, any> = {}
  const required: string[] = []
  for (const p of params) {
    properties[p.name] = { type: p.type, description: p.description }
    if (p.required) required.push(p.name)
  }
  return { type: 'object', properties, required }
}

function schemaToParams(schema: Record<string, any> | undefined): InputParam[] {
  if (!schema?.properties) return []
  return Object.entries(schema.properties).map(([name, def]: [string, any]) => ({
    name,
    type: def.type || 'string',
    description: def.description || '',
    required: schema.required?.includes(name) ?? false,
  }))
}

// ─── Webhook Config Modal ─────────────────────────────────────────────────────

function WebhookModal({
  entry,
  tool,
  onClose,
  onSaved,
}: {
  entry: CatalogEntry
  tool?: ToolRecord
  onClose: () => void
  onSaved: () => void
}) {
  const existingMeta = tool?.tool_metadata || {}
  const existingAuth = tool?.auth_config || {}

  const [name, setName] = useState(tool?.name || '')
  const [description, setDescription] = useState(tool?.description || '')
  const [url, setUrl] = useState(tool?.endpoint_url || existingMeta.url || '')
  const [method, setMethod] = useState(existingMeta.method || 'POST')
  const [authType, setAuthType] = useState(existingAuth.type || 'none')
  const [showSecrets, setShowSecrets] = useState<Record<string, boolean>>({})
  const [saving, setSaving] = useState(false)

  // Auth fields
  const [apiKey, setApiKey] = useState(existingAuth.value?.replace(/^Bearer /, '') || '')
  const [username, setUsername] = useState(existingAuth.username || '')
  const [password, setPassword] = useState(existingAuth.password || '')
  const [tokenUrl, setTokenUrl] = useState(existingAuth.token_url || '')
  const [clientId, setClientId] = useState(existingAuth.client_id || '')
  const [clientSecret, setClientSecret] = useState(existingAuth.client_secret || '')
  const [scope, setScope] = useState(existingAuth.scope || '')
  const [audience, setAudience] = useState(existingAuth.audience || '')

  // Input params
  const [params, setParams] = useState<InputParam[]>(
    schemaToParams(tool?.input_schema)
  )

  const toggle = (field: string) =>
    setShowSecrets((p) => ({ ...p, [field]: !p[field] }))

  const addParam = () =>
    setParams((p) => [...p, { name: '', type: 'string', description: '', required: false }])

  const removeParam = (i: number) =>
    setParams((p) => p.filter((_, idx) => idx !== i))

  const updateParam = (i: number, key: keyof InputParam, value: any) =>
    setParams((p) => p.map((row, idx) => (idx === i ? { ...row, [key]: value } : row)))

  const handleSave = async () => {
    if (!name) { toast.error('Tool name is required'); return }
    if (!url) { toast.error('Endpoint URL is required'); return }
    setSaving(true)
    try {
      // Build auth_config
      const authConfig: Record<string, any> = { type: authType }
      if (authType === 'api_key') {
        authConfig.header = 'X-API-Key'
        authConfig.value = apiKey
      } else if (authType === 'bearer') {
        authConfig.header = 'Authorization'
        authConfig.value = `Bearer ${apiKey}`
      } else if (authType === 'basic') {
        authConfig.username = username
        authConfig.password = password
      } else if (authType === 'oauth2_cc') {
        authConfig.token_url = tokenUrl
        authConfig.client_id = clientId
        authConfig.client_secret = clientSecret
        if (scope) authConfig.scope = scope
        if (audience) authConfig.audience = audience
      }

      const payload = {
        name,
        description,
        category: entry.category,
        is_builtin: false,
        endpoint_url: url,
        input_schema: buildInputSchema(params),
        tool_metadata: { catalog_id: entry.id, method },
        auth_config: authConfig,
      }

      if (tool) {
        await toolsApi.update(tool.name, payload)
      } else {
        await toolsApi.register(payload)
      }
      toast.success('Webhook saved')
      onSaved()
      onClose()
    } catch (e: any) {
      toast.error(e.response?.data?.detail || 'Save failed')
    } finally {
      setSaving(false)
    }
  }

  const inputCls = 'w-full px-3 py-2.5 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-sm text-gray-900 dark:text-white focus:outline-none focus:ring-1 focus:ring-violet-500'
  const labelCls = 'block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1'
  const sectionCls = 'pt-4 border-t border-gray-100 dark:border-gray-800 space-y-3'

  return (
    <div className="fixed inset-0 bg-black/60 z-50 flex items-center justify-center p-4">
      <div className="bg-white dark:bg-gray-900 rounded-2xl shadow-2xl w-full max-w-2xl max-h-[90vh] flex flex-col overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-5 border-b border-gray-100 dark:border-gray-800 flex-shrink-0">
          <div>
            <h2 className="text-base font-semibold text-gray-900 dark:text-white">
              {tool ? 'Edit' : 'New'} Custom Webhook
            </h2>
            <p className="text-xs text-gray-500 mt-0.5">Configure endpoint, parameters, and authentication.</p>
          </div>
          <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 text-gray-400">
            <X size={16} />
          </button>
        </div>

        {/* Scrollable body */}
        <div className="overflow-y-auto flex-1 px-6 py-5 space-y-5">

          {/* ── Section 1: Basic Info ── */}
          <div className="space-y-3">
            <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide">Basic Info</p>

            <div className="grid grid-cols-2 gap-3">
              <div className="col-span-2 sm:col-span-1">
                <label className={labelCls}>Tool Name <span className="text-red-500">*</span></label>
                <input
                  type="text"
                  disabled={!!tool}
                  value={name}
                  onChange={(e) => setName(e.target.value.toLowerCase().replace(/[^a-z0-9_\-]/g, '_'))}
                  placeholder="my_crm_webhook"
                  className={inputCls + (tool ? ' opacity-60' : '')}
                />
                {!tool && <p className="text-[10px] text-gray-400 mt-1">Lowercase, underscores/hyphens only. Unique per tenant.</p>}
              </div>
              <div className="col-span-2 sm:col-span-1">
                <label className={labelCls}>HTTP Method</label>
                <select value={method} onChange={(e) => setMethod(e.target.value)} className={inputCls}>
                  <option>POST</option>
                  <option>GET</option>
                  <option>PUT</option>
                  <option>PATCH</option>
                </select>
              </div>
            </div>

            <div>
              <label className={labelCls}>Endpoint URL <span className="text-red-500">*</span></label>
              <input type="url" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://api.example.com/v1/action" className={inputCls} />
            </div>

            <div>
              <label className={labelCls}>Description <span className="text-red-500">*</span></label>
              <textarea
                rows={3}
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="Describe when the AI should call this webhook. E.g. 'Call this when the user wants to submit a support ticket. Requires ticket_title and message.'"
                className={inputCls + ' resize-none'}
              />
              <p className="text-[10px] text-gray-400 mt-1">The AI uses this to decide when to invoke the tool. Be specific about the trigger and required context.</p>
            </div>
          </div>

          {/* ── Section 2: Authentication ── */}
          <div className={sectionCls}>
            <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide">Authentication</p>

            <div>
              <label className={labelCls}>Auth Type</label>
              <select
                value={authType}
                onChange={(e) => { setAuthType(e.target.value); setApiKey(''); setUsername(''); setPassword('') }}
                className={inputCls}
              >
                {AUTH_TYPES.map((a) => (
                  <option key={a.value} value={a.value}>{a.label}</option>
                ))}
              </select>
            </div>

            {/* API Key / Bearer */}
            {(authType === 'api_key' || authType === 'bearer') && (
              <div>
                <label className={labelCls}>{authType === 'bearer' ? 'Bearer Token' : 'API Key'}</label>
                <div className="relative">
                  <input
                    type={showSecrets.apiKey ? 'text' : 'password'}
                    value={apiKey}
                    onChange={(e) => setApiKey(e.target.value)}
                    placeholder="••••••••"
                    className={inputCls + ' pr-10'}
                  />
                  <button type="button" onClick={() => toggle('apiKey')} className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600">
                    {showSecrets.apiKey ? <EyeOff size={14} /> : <Eye size={14} />}
                  </button>
                </div>
              </div>
            )}

            {/* Basic Auth */}
            {authType === 'basic' && (
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className={labelCls}>Username</label>
                  <input type="text" value={username} onChange={(e) => setUsername(e.target.value)} placeholder="user" className={inputCls} />
                </div>
                <div>
                  <label className={labelCls}>Password</label>
                  <div className="relative">
                    <input type={showSecrets.password ? 'text' : 'password'} value={password} onChange={(e) => setPassword(e.target.value)} placeholder="••••••••" className={inputCls + ' pr-10'} />
                    <button type="button" onClick={() => toggle('password')} className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600">
                      {showSecrets.password ? <EyeOff size={14} /> : <Eye size={14} />}
                    </button>
                  </div>
                </div>
              </div>
            )}

            {/* OAuth2 Client Credentials */}
            {authType === 'oauth2_cc' && (
              <div className="space-y-3">
                <div className="p-3 bg-blue-50 dark:bg-blue-900/20 rounded-lg text-xs text-blue-700 dark:text-blue-300">
                  The server will automatically obtain a Bearer token from your token endpoint before each call. Your client secret is stored encrypted.
                </div>
                <div>
                  <label className={labelCls}>Token URL <span className="text-red-500">*</span></label>
                  <input type="url" value={tokenUrl} onChange={(e) => setTokenUrl(e.target.value)} placeholder="https://auth.example.com/oauth/token" className={inputCls} />
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className={labelCls}>Client ID <span className="text-red-500">*</span></label>
                    <input type="text" value={clientId} onChange={(e) => setClientId(e.target.value)} placeholder="client_id" className={inputCls} />
                  </div>
                  <div>
                    <label className={labelCls}>Client Secret <span className="text-red-500">*</span></label>
                    <div className="relative">
                      <input type={showSecrets.secret ? 'text' : 'password'} value={clientSecret} onChange={(e) => setClientSecret(e.target.value)} placeholder="••••••••" className={inputCls + ' pr-10'} />
                      <button type="button" onClick={() => toggle('secret')} className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600">
                        {showSecrets.secret ? <EyeOff size={14} /> : <Eye size={14} />}
                      </button>
                    </div>
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className={labelCls}>Scope <span className="text-gray-400 font-normal">(optional)</span></label>
                    <input type="text" value={scope} onChange={(e) => setScope(e.target.value)} placeholder="read write" className={inputCls} />
                  </div>
                  <div>
                    <label className={labelCls}>Audience <span className="text-gray-400 font-normal">(optional, Auth0)</span></label>
                    <input type="text" value={audience} onChange={(e) => setAudience(e.target.value)} placeholder="https://api.example.com" className={inputCls} />
                  </div>
                </div>
              </div>
            )}
          </div>

          {/* ── Section 3: Input Parameters ── */}
          <div className={sectionCls}>
            <div className="flex items-center justify-between">
              <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide">Input Parameters</p>
              <button
                onClick={addParam}
                className="flex items-center gap-1 text-xs text-violet-600 dark:text-violet-400 hover:text-violet-700 font-medium"
              >
                <Plus size={12} /> Add parameter
              </button>
            </div>
            <p className="text-[10px] text-gray-400">
              Define what data the AI should collect and pass to this webhook. The AI will read the description to know what each field means.
            </p>

            {params.length === 0 && (
              <div className="text-center py-6 border border-dashed border-gray-200 dark:border-gray-700 rounded-lg text-xs text-gray-400">
                No parameters yet. Add parameters the AI should pass in the request body.
              </div>
            )}

            {params.map((p, i) => (
              <div key={i} className="grid grid-cols-12 gap-2 items-start bg-gray-50 dark:bg-gray-800/50 p-3 rounded-lg">
                <div className="col-span-3">
                  {i === 0 && <label className={labelCls}>Name</label>}
                  <input
                    type="text"
                    value={p.name}
                    onChange={(e) => updateParam(i, 'name', e.target.value.replace(/\s/g, '_'))}
                    placeholder="field_name"
                    className={inputCls + ' text-xs'}
                  />
                </div>
                <div className="col-span-2">
                  {i === 0 && <label className={labelCls}>Type</label>}
                  <select value={p.type} onChange={(e) => updateParam(i, 'type', e.target.value)} className={inputCls + ' text-xs'}>
                    {PARAM_TYPES.map((t) => <option key={t}>{t}</option>)}
                  </select>
                </div>
                <div className="col-span-5">
                  {i === 0 && <label className={labelCls}>Description (AI reads this)</label>}
                  <input
                    type="text"
                    value={p.description}
                    onChange={(e) => updateParam(i, 'description', e.target.value)}
                    placeholder="e.g. Customer's email address"
                    className={inputCls + ' text-xs'}
                  />
                </div>
                <div className="col-span-1 flex flex-col items-center">
                  {i === 0 && <label className={labelCls}>Req.</label>}
                  <input
                    type="checkbox"
                    checked={p.required}
                    onChange={(e) => updateParam(i, 'required', e.target.checked)}
                    className="mt-2.5 h-4 w-4 accent-violet-600 rounded"
                  />
                </div>
                <div className="col-span-1 flex flex-col items-center">
                  {i === 0 && <label className={labelCls}>&nbsp;</label>}
                  <button onClick={() => removeParam(i)} className="mt-2 text-gray-400 hover:text-red-500 transition-colors">
                    <Trash2 size={13} />
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Footer */}
        <div className="px-6 py-4 border-t border-gray-100 dark:border-gray-800 flex justify-end gap-2 flex-shrink-0 bg-gray-50/50 dark:bg-gray-800/50">
          <button onClick={onClose} className="px-4 py-2 rounded-lg border border-gray-200 dark:border-gray-700 text-sm text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-800">
            Cancel
          </button>
          <button
            onClick={handleSave}
            disabled={saving || !name || !url || !description}
            className="px-6 py-2 rounded-lg bg-violet-600 text-white text-sm font-semibold hover:bg-violet-700 disabled:opacity-50 transition-colors"
          >
            {saving ? 'Saving…' : tool ? 'Update webhook' : 'Create webhook'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function AgentToolsPage() {
  const params = useParams()
  const agentId = params.id as string
  const qc = useQueryClient()

  const [webhookModal, setWebhookModal] = useState<{
    entry: CatalogEntry
    tool?: ToolRecord
  } | null>(null)
  const [configuring, setConfiguring] = useState<{
    entry: CatalogEntry
    tool?: ToolRecord
  } | null>(null)
  const [credentials, setCredentials] = useState<Record<string, any>>({})
  const [showSecrets, setShowSecrets] = useState<Record<string, boolean>>({})
  const [saving, setSaving] = useState(false)

  const { data: agent } = useQuery({
    queryKey: ['agent', agentId],
    queryFn: () => agentsApi.get(agentId),
    enabled: !!agentId,
  })

  const { data: catalog = [] } = useQuery<CatalogEntry[]>({
    queryKey: ['tools-catalog'],
    queryFn: toolsApi.catalog,
  })

  const { data: registeredTools = [] } = useQuery<ToolRecord[]>({
    queryKey: ['tools', agentId],
    queryFn: toolsApi.list,
    enabled: !!agentId,
  })

  const agentTools: string[] = agent?.tools || []

  const registeredInstances = registeredTools.reduce<Record<string, ToolRecord[]>>((acc, t) => {
    const catalogId = t.tool_metadata?.catalog_id || t.name
    if (!acc[catalogId]) acc[catalogId] = []
    acc[catalogId].push(t)
    return acc
  }, {})

  const toggleMutation = useMutation({
    mutationFn: async (toolName: string) => {
      if (agentTools.includes(toolName)) {
        return toolsApi.disableForAgent(agentId, toolName, agentTools)
      } else {
        return toolsApi.enableForAgent(agentId, toolName, agentTools)
      }
    },
    onSuccess: (_, toolName) => {
      qc.invalidateQueries({ queryKey: ['agent', agentId] })
      const enabled = !agentTools.includes(toolName)
      toast.success(enabled ? 'Tool enabled' : 'Tool disabled')
    },
    onError: () => toast.error('Failed to update tool'),
  })

  const openConfig = (entry: CatalogEntry, tool?: ToolRecord) => {
    const existingMeta = tool?.tool_metadata || {}
    const initial: Record<string, any> = {
      name: tool?.name || entry.name.toLowerCase().replace(/\s+/g, '_'),
    }
    for (const cred of entry.credentials.filter((c) => !['auth_type', 'api_key', 'username', 'password'].includes(c.field))) {
      initial[cred.field] = existingMeta[cred.field] || ''
    }
    if (tool?.endpoint_url) initial.url = tool.endpoint_url
    setCredentials(initial)
    setShowSecrets({})
    setConfiguring({ entry, tool })
  }

  const handleSaveCredentials = async () => {
    if (!configuring) return
    setSaving(true)
    try {
      const { entry, tool } = configuring
      const toolName = credentials.name || entry.id
      const metadata: Record<string, any> = { ...credentials, catalog_id: entry.id }
      delete metadata.name
      delete metadata.url

      const authConfig: Record<string, any> = { type: credentials.auth_type || 'none' }
      if (authConfig.type === 'api_key') {
        authConfig.value = credentials.api_key
        authConfig.header = 'X-API-Key'
      } else if (authConfig.type === 'bearer') {
        authConfig.header = 'Authorization'
        authConfig.value = `Bearer ${credentials.api_key}`
      } else if (authConfig.type === 'basic') {
        authConfig.username = credentials.username
        authConfig.password = credentials.password
      }

      const payload = {
        name: toolName,
        description: entry.description,
        category: entry.category,
        is_builtin: !entry.allow_multiple,
        endpoint_url: credentials.url || null,
        tool_metadata: metadata,
        auth_config: authConfig,
      }

      if (tool) {
        await toolsApi.update(tool.name, payload)
      } else {
        await toolsApi.register(payload)
      }

      qc.invalidateQueries({ queryKey: ['tools', agentId] })
      toast.success('Tool configured')
      setConfiguring(null)
    } catch (error: any) {
      toast.error(error.response?.data?.detail || 'Failed to save configuration')
    } finally {
      setSaving(false)
    }
  }

  const handleDeleteTool = async (toolName: string) => {
    if (!confirm(`Delete '${toolName}'?`)) return
    try {
      await toolsApi.delete(toolName)
      qc.invalidateQueries({ queryKey: ['tools', agentId] })
      toast.success('Tool deleted')
    } catch {
      toast.error('Failed to delete tool')
    }
  }

  const grouped = catalog.reduce<Record<string, CatalogEntry[]>>((acc, entry) => {
    const cat = entry.category
    if (!acc[cat]) acc[cat] = []
    acc[cat].push(entry)
    return acc
  }, {})

  return (
    <div className="p-8 w-full">
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-gray-900 dark:text-white flex items-center gap-2">
          <Wrench size={22} className="text-violet-500" />
          Tools & Integrations
        </h1>
        <p className="text-gray-500 mt-1">
          Connect external services to <strong>{agent?.name || 'this agent'}</strong>. Enable a tool to let
          the agent call it during conversations.
        </p>
      </div>

      <div className="mb-6 p-4 bg-violet-50 dark:bg-violet-900/20 border border-violet-100 dark:border-violet-800 rounded-xl text-sm text-violet-700 dark:text-violet-300">
        <strong>{agentTools.length}</strong> tool{agentTools.length !== 1 ? 's' : ''} enabled for this agent.
      </div>

      {Object.entries(grouped).map(([category, entries]) => (
        <div key={category} className="mb-6">
          <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">
            {CATEGORY_LABELS[category] || category}
          </h2>
          <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 divide-y divide-gray-100 dark:divide-gray-800">
            {entries.map((entry) => {
              const instances = registeredInstances[entry.id] || []
              const allowsMultiple = entry.allow_multiple
              const needsConfig = entry.credentials.length > 0

              return (
                <div key={entry.id} className="flex flex-col">
                  {/* Catalog row */}
                  <div className="flex items-center gap-4 px-5 py-4">
                    <div className="w-9 h-9 rounded-lg bg-gradient-to-br from-violet-500/10 to-blue-500/10 flex items-center justify-center flex-shrink-0">
                      <Wrench size={16} className="text-violet-500" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <p className="text-sm font-medium text-gray-900 dark:text-white">{entry.name}</p>
                        <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${CATEGORY_COLORS[category] || CATEGORY_COLORS.custom}`}>
                          {CATEGORY_LABELS[category] || category}
                        </span>
                        {entry.channel_support && entry.channel_support.length > 0 && !entry.channel_support.includes('voice') && (
                          <span className="text-xs px-2 py-0.5 rounded-full font-medium bg-orange-50 text-orange-700 dark:bg-orange-900/20 dark:text-orange-300">
                            Chat Only
                          </span>
                        )}
                        {category === 'payments' && entry.pci_compliant === false && (
                          <span className="text-xs px-2 py-0.5 rounded-full font-medium bg-red-50 text-red-700 dark:bg-red-900/20 dark:text-red-300" title="Not PCI-DSS compliant">
                            PCI Warning
                          </span>
                        )}
                      </div>
                      <p className="text-xs text-gray-500 mt-0.5">{entry.description}</p>
                    </div>
                    <div className="flex items-center gap-2">
                      {allowsMultiple ? (
                        <button
                          onClick={() => setWebhookModal({ entry })}
                          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-gray-200 dark:border-gray-700 text-xs text-violet-600 dark:text-violet-400 hover:bg-violet-50 dark:hover:bg-violet-900/20 transition-colors"
                        >
                          <Plus size={12} /> Add New
                        </button>
                      ) : !instances.length && needsConfig ? (
                        <button
                          onClick={() => openConfig(entry)}
                          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-gray-200 dark:border-gray-700 text-xs text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors"
                        >
                          <Settings size={13} /> Configure
                        </button>
                      ) : null}
                    </div>
                  </div>

                  {/* Tool instances */}
                  {instances.map((tool) => {
                    const isEnabled = agentTools.includes(tool.name)
                    const paramCount = Object.keys(tool.input_schema?.properties || {}).length
                    return (
                      <div
                        key={tool.id}
                        className="flex items-center gap-4 px-5 py-3 bg-gray-50/50 dark:bg-gray-800/30 border-t border-gray-100 dark:border-gray-800 ml-12"
                      >
                        <div className="flex-1 min-w-0">
                          <p className="text-xs font-semibold text-gray-700 dark:text-gray-300">{tool.name}</p>
                          {tool.description && (
                            <p className="text-[10px] text-gray-400 truncate mt-0.5">{tool.description}</p>
                          )}
                          {tool.endpoint_url && (
                            <p className="text-[10px] text-gray-400 font-mono truncate">{tool.endpoint_url}</p>
                          )}
                          {paramCount > 0 && (
                            <p className="text-[10px] text-violet-500 mt-0.5">{paramCount} input param{paramCount !== 1 ? 's' : ''}</p>
                          )}
                        </div>
                        <div className="flex items-center gap-3">
                          <button
                            onClick={() => allowsMultiple
                              ? setWebhookModal({ entry, tool })
                              : openConfig(entry, tool)
                            }
                            className="p-1.5 text-gray-400 hover:text-gray-600 dark:hover:text-gray-300"
                            title="Edit"
                          >
                            <Settings size={12} />
                          </button>
                          {allowsMultiple && (
                            <button
                              onClick={() => handleDeleteTool(tool.name)}
                              className="p-1.5 text-gray-400 hover:text-red-500"
                              title="Delete"
                            >
                              <X size={12} />
                            </button>
                          )}
                          <button
                            onClick={() => toggleMutation.mutate(tool.name)}
                            disabled={toggleMutation.isPending}
                            className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${
                              isEnabled ? 'bg-violet-600' : 'bg-gray-300 dark:bg-gray-700'
                            }`}
                          >
                            <span className={`inline-block h-3 w-3 transform rounded-full bg-white shadow transition-transform ${
                              isEnabled ? 'translate-x-5' : 'translate-x-1'
                            }`} />
                          </button>
                        </div>
                      </div>
                    )
                  })}
                </div>
              )
            })}
          </div>
        </div>
      ))}

      {/* Webhook modal */}
      {webhookModal && (
        <WebhookModal
          entry={webhookModal.entry}
          tool={webhookModal.tool}
          onClose={() => setWebhookModal(null)}
          onSaved={() => qc.invalidateQueries({ queryKey: ['tools', agentId] })}
        />
      )}

      {/* Generic credential modal for non-webhook tools */}
      {configuring && (
        <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4">
          <div className="bg-white dark:bg-gray-900 rounded-2xl shadow-2xl w-full max-w-md overflow-hidden">
            <div className="flex items-center justify-between px-6 py-5 border-b border-gray-100 dark:border-gray-800">
              <div>
                <h2 className="text-base font-semibold text-gray-900 dark:text-white line-clamp-1">
                  Configure {configuring.entry.name}
                </h2>
                <p className="text-xs text-gray-500 mt-0.5">Credentials are stored encrypted and never exposed to users.</p>
              </div>
              <button onClick={() => setConfiguring(null)} className="p-1.5 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 text-gray-400">
                <X size={16} />
              </button>
            </div>

            <div className="px-6 py-5 space-y-4 max-h-[60vh] overflow-y-auto">
              {configuring.entry.credentials
                .filter((c) => !['auth_type', 'api_key', 'username', 'password'].includes(c.field))
                .map((cred) => (
                  <div key={cred.field}>
                    <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1.5">
                      {cred.label}
                    </label>
                    <div className="relative">
                      <input
                        type={cred.type === 'password' && !showSecrets[cred.field] ? 'password' : 'text'}
                        value={credentials[cred.field] || ''}
                        onChange={(e) => setCredentials((p) => ({ ...p, [cred.field]: e.target.value }))}
                        placeholder={cred.type === 'password' ? '••••••••' : `Enter ${cred.label.toLowerCase()}`}
                        className="w-full px-3 py-2.5 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-sm text-gray-900 dark:text-white focus:outline-none focus:ring-1 focus:ring-violet-500 pr-10"
                      />
                      {cred.type === 'password' && (
                        <button type="button" onClick={() => setShowSecrets((p) => ({ ...p, [cred.field]: !p[cred.field] }))} className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600">
                          {showSecrets[cred.field] ? <EyeOff size={14} /> : <Eye size={14} />}
                        </button>
                      )}
                    </div>
                  </div>
                ))}
            </div>

            <div className="px-6 pb-5 pt-2 flex justify-end gap-2 bg-gray-50/50 dark:bg-gray-800/50 border-t border-gray-100 dark:border-gray-800">
              <button onClick={() => setConfiguring(null)} className="px-4 py-2 rounded-lg border border-gray-200 dark:border-gray-700 text-sm text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-800">
                Cancel
              </button>
              <button
                onClick={handleSaveCredentials}
                disabled={saving || !credentials.name}
                className="flex items-center gap-2 px-6 py-2 rounded-lg bg-violet-600 text-white text-sm font-medium hover:bg-violet-700 disabled:opacity-50 transition-colors"
              >
                {saving ? 'Saving…' : 'Save'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
