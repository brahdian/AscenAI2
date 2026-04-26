'use client'

import { useState, useMemo } from 'react'
import { useParams, useRouter } from 'next/navigation'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { toolsApi, agentsApi } from '@/lib/api'
import toast from 'react-hot-toast'
import {
  Wrench,
  Plus,
  ArrowLeft,
  Search,
  CheckCircle2,
  X,
  Eye,
  EyeOff,
  Play,
  CheckCircle,
  XCircle,
  Settings,
  Trash2,
  ChevronRight,
  ShieldCheck,
  Zap,
  ChevronLeft,
} from 'lucide-react'
import Link from 'next/link'

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

const PARAM_TYPES = ['string', 'number', 'boolean', 'object', 'array']

const AUTH_TYPES = [
  { value: 'none', label: 'None' },
  { value: 'api_key', label: 'API Key (X-API-Key header)' },
  { value: 'bearer', label: 'Bearer Token (Authorization header)' },
  { value: 'basic', label: 'Basic Auth (username + password)' },
  { value: 'oauth2_cc', label: 'OAuth2 Client Credentials' },
]

// ─── Helpers ──────────────────────────────────────────────────────────────────

function buildInputSchema(params: InputParam[]): Record<string, any> {
  if (params.length === 0) return {}
  const properties: Record<string, any> = {}
  const required: string[] = []
  for (const p of params) {
    if (!p.name) continue
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

// ─── Dynamic Tool Configuration Modal ───────────────────────────────────────

function ToolModal({
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
  const isCustom = entry.id === 'webhook'
  const existingMeta = tool?.tool_metadata || {}
  const existingAuth = tool?.auth_config || {}

  const [name, setName] = useState(tool?.name || entry.name.toLowerCase().replace(/\s+/g, '_'))
  const [description, setDescription] = useState(tool?.description || entry.description || '')
  
  // Custom Webhook state
  const [url, setUrl] = useState(tool?.endpoint_url || existingMeta.url || '')
  const [method, setMethod] = useState(existingMeta.method || 'POST')
  const [authType, setAuthType] = useState(existingAuth.type || 'none')
  const [params, setParams] = useState<InputParam[]>(schemaToParams(tool?.input_schema))

  // Auth fields (Unified)
  const [apiKey, setApiKey] = useState(existingAuth.value?.replace(/^Bearer /, '') || existingMeta.api_key || existingMeta.access_token || '')
  const [username, setUsername] = useState(existingAuth.username || existingMeta.username || '')
  const [password, setPassword] = useState(existingAuth.password || existingMeta.password || '')
  const [tokenUrl, setTokenUrl] = useState(existingAuth.token_url || existingMeta.token_url || '')
  const [clientId, setClientId] = useState(existingAuth.client_id || existingMeta.client_id || '')
  const [clientSecret, setClientSecret] = useState(existingAuth.client_secret || existingMeta.client_secret || '')

  const [showSecrets, setShowSecrets] = useState<Record<string, boolean>>({})
  const [saving, setSaving] = useState(false)

  const buildAuthConfig = (): Record<string, any> => {
    const auth: Record<string, any> = { type: authType }
    if (authType === 'api_key') {
      auth.header = 'X-API-Key'
      auth.value = apiKey
    } else if (authType === 'bearer') {
      auth.header = 'Authorization'
      auth.value = `Bearer ${apiKey}`
    } else if (authType === 'basic') {
      auth.username = username
      auth.password = password
    } else if (authType === 'oauth2_cc') {
      auth.token_url = tokenUrl
      auth.client_id = clientId
      auth.client_secret = clientSecret
    }
    return auth
  }

  const handleSave = async () => {
    if (!name.trim()) return toast.error('Name is required')
    if (isCustom && !url.trim()) return toast.error('Endpoint URL is required')

    try {
      setSaving(true)
      const payload: any = {
        name,
        description,
        category: entry.category,
        is_builtin: entry.is_builtin,
      }

      if (isCustom) {
        payload.endpoint_url = url
        payload.input_schema = buildInputSchema(params)
        payload.tool_metadata = { method }
        payload.auth_config = buildAuthConfig()
      } else {
        // Builtin integration
        const meta: any = {}
        // Map common fields from state
        if (apiKey) meta.api_key = apiKey
        if (username) meta.username = username
        if (password) meta.password = password
        if (clientId) meta.client_id = clientId
        if (clientSecret) meta.client_secret = clientSecret
        
        payload.tool_metadata = meta
        
        // Auto-generate auth_config based on detected fields
        if (apiKey) payload.auth_config = { type: 'api_key', value: apiKey, header: 'X-API-Key' }
        else if (username && password) payload.auth_config = { type: 'basic', username, password }
      }

      if (tool) {
        await toolsApi.update(tool.id, payload)
        toast.success('Tool updated')
      } else {
        await toolsApi.register(payload)
        toast.success('Tool installed')
      }
      onSaved()
      onClose()
    } catch (e: any) {
      toast.error(e.response?.data?.detail || 'Failed to save tool')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm p-4">
      <div className="bg-white dark:bg-gray-900 rounded-2xl shadow-xl w-full max-w-2xl max-h-[90vh] flex flex-col">
        <div className="px-6 py-4 border-b border-gray-200 dark:border-gray-800 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg bg-violet-100 dark:bg-violet-900/30 flex items-center justify-center text-violet-600 dark:text-violet-400">
              <Settings size={20} />
            </div>
            <div>
              <h2 className="text-lg font-bold text-gray-900 dark:text-white">
                {tool ? 'Edit' : 'Install'} {entry.name}
              </h2>
              <p className="text-sm text-gray-500">Configure your integration credentials</p>
            </div>
          </div>
          <button onClick={onClose} className="p-2 text-gray-400 hover:text-gray-600 dark:hover:text-gray-200">
            <X size={20} />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-6 space-y-6">
          {/* General */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1.5">Tool ID Name (Internal)</label>
              <input
                value={name}
                onChange={(e) => setName(e.target.value.toLowerCase().replace(/\s+/g, '_'))}
                placeholder="e.g. check_calendar"
                className="w-full px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-sm focus:ring-2 focus:ring-violet-500 outline-none"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1.5">Category</label>
              <input
                value={CATEGORY_LABELS[entry.category] || entry.category}
                disabled
                className="w-full px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800/50 text-sm opacity-60"
              />
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1.5">Description (for LLM context)</label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={2}
              className="w-full px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-sm focus:ring-2 focus:ring-violet-500 outline-none resize-none"
            />
          </div>

          {/* Config Fields */}
          {isCustom ? (
            <div className="space-y-4 pt-4 border-t border-gray-100 dark:border-gray-800">
              <h3 className="text-sm font-semibold text-gray-900 dark:text-white uppercase tracking-wider">Webhook Configuration</h3>
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1.5">Endpoint URL</label>
                <input
                  value={url}
                  onChange={(e) => setUrl(e.target.value)}
                  placeholder="https://api.yourservice.com/webhook"
                  className="w-full px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-sm outline-none focus:ring-2 focus:ring-violet-500"
                />
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1.5">Method</label>
                  <select
                    value={method}
                    onChange={(e) => setMethod(e.target.value)}
                    className="w-full px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-sm"
                  >
                    <option value="POST">POST (Default)</option>
                    <option value="GET">GET</option>
                    <option value="PUT">PUT</option>
                    <option value="PATCH">PATCH</option>
                  </select>
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1.5">Auth Type</label>
                  <select
                    value={authType}
                    onChange={(e) => setAuthType(e.target.value)}
                    className="w-full px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-sm"
                  >
                    {AUTH_TYPES.map(a => <option key={a.value} value={a.value}>{a.label}</option>)}
                  </select>
                </div>
              </div>

              {/* Dynamic Auth Inputs for Custom Webhook */}
              {authType !== 'none' && (
                <div className="p-4 rounded-xl bg-gray-50 dark:bg-gray-800/50 space-y-4 border border-gray-100 dark:border-gray-800">
                  {authType === 'api_key' || authType === 'bearer' ? (
                    <div>
                      <label className="block text-xs font-medium text-gray-500 uppercase tracking-wider mb-1.5">
                        {authType === 'api_key' ? 'API Key' : 'Bearer Token'}
                      </label>
                      <div className="relative">
                        <input
                          type={showSecrets.key ? 'text' : 'password'}
                          value={apiKey}
                          onChange={(e) => setApiKey(e.target.value)}
                          className="w-full px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-sm focus:outline-none focus:ring-1 focus:ring-violet-500 pr-10"
                        />
                        <button
                          type="button"
                          onClick={() => setShowSecrets(p => ({ ...p, key: !p.key }))}
                          className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
                        >
                          {showSecrets.key ? <EyeOff size={16} /> : <Eye size={16} />}
                        </button>
                      </div>
                    </div>
                  ) : authType === 'basic' ? (
                    <div className="grid grid-cols-2 gap-4">
                      <div>
                        <label className="block text-xs font-medium text-gray-500 uppercase tracking-wider mb-1.5">Username</label>
                        <input
                          value={username}
                          onChange={(e) => setUsername(e.target.value)}
                          className="w-full px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-sm"
                        />
                      </div>
                      <div>
                        <label className="block text-xs font-medium text-gray-500 uppercase tracking-wider mb-1.5">Password</label>
                        <input
                          type="password"
                          value={password}
                          onChange={(e) => setPassword(e.target.value)}
                          className="w-full px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-sm"
                        />
                      </div>
                    </div>
                  ) : authType === 'oauth2_cc' && (
                    <div className="space-y-4">
                      <div>
                        <label className="block text-xs font-medium text-gray-500 uppercase tracking-wider mb-1.5">Token URL</label>
                        <input
                          value={tokenUrl}
                          onChange={(e) => setTokenUrl(e.target.value)}
                          className="w-full px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-sm"
                        />
                      </div>
                      <div className="grid grid-cols-2 gap-4">
                        <div>
                          <label className="block text-xs font-medium text-gray-500 uppercase tracking-wider mb-1.5">Client ID</label>
                          <input
                            value={clientId}
                            onChange={(e) => setClientId(e.target.value)}
                            className="w-full px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-sm"
                          />
                        </div>
                        <div>
                          <label className="block text-xs font-medium text-gray-500 uppercase tracking-wider mb-1.5">Client Secret</label>
                          <input
                            type="password"
                            value={clientSecret}
                            onChange={(e) => setClientSecret(e.target.value)}
                            className="w-full px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-sm"
                          />
                        </div>
                      </div>
                    </div>
                  )}
                </div>
              )}

              {/* Input Parameters */}
              <div className="space-y-4">
                <div className="flex items-center justify-between">
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300">Input Parameters</label>
                  <button
                    onClick={() => setParams([...params, { name: '', type: 'string', description: '', required: false }])}
                    className="text-xs text-violet-600 hover:text-violet-700 font-bold flex items-center gap-1"
                  >
                    <Plus size={14} /> Add Parameter
                  </button>
                </div>
                {params.map((p, i) => (
                  <div key={i} className="flex gap-2 items-center bg-gray-50 dark:bg-gray-800/50 p-3 rounded-xl border border-gray-100 dark:border-gray-800">
                    <input
                      value={p.name}
                      onChange={(e) => setParams(params.map((x, idx) => idx === i ? { ...x, name: e.target.value } : x))}
                      placeholder="name"
                      className="w-1/4 px-2 py-1.5 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg text-xs"
                    />
                    <select
                      value={p.type}
                      onChange={(e) => setParams(params.map((x, idx) => idx === i ? { ...x, type: e.target.value } : x))}
                      className="w-1/4 px-2 py-1.5 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg text-xs"
                    >
                      {PARAM_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
                    </select>
                    <input
                      value={p.description}
                      onChange={(e) => setParams(params.map((x, idx) => idx === i ? { ...x, description: e.target.value } : x))}
                      placeholder="description"
                      className="flex-1 px-2 py-1.5 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg text-xs"
                    />
                    <button onClick={() => setParams(params.filter((_, idx) => idx !== i))} className="p-1.5 text-red-500 hover:bg-red-50 rounded-lg">
                      <Trash2 size={14} />
                    </button>
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <div className="space-y-4 pt-4 border-t border-gray-100 dark:border-gray-800">
              <h3 className="text-sm font-semibold text-gray-900 dark:text-white uppercase tracking-wider">Authentication</h3>
              <div className="grid gap-4">
                {entry.credentials.map((cred) => (
                  <div key={cred.field}>
                    <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1.5">{cred.label}</label>
                    <div className="relative">
                      <input
                        type={cred.type === 'password' && !showSecrets[cred.field] ? 'password' : 'text'}
                        value={
                          cred.field === 'api_key' ? apiKey :
                          cred.field === 'username' ? username :
                          cred.field === 'password' ? password :
                          cred.field === 'client_id' ? clientId :
                          cred.field === 'client_secret' ? clientSecret :
                          ''
                        }
                        onChange={(e) => {
                          const v = e.target.value
                          if (cred.field === 'api_key') setApiKey(v)
                          else if (cred.field === 'username') setUsername(v)
                          else if (cred.field === 'password') setPassword(v)
                          else if (cred.field === 'client_id') setClientId(v)
                          else if (cred.field === 'client_secret') setClientSecret(v)
                        }}
                        className="w-full px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-sm outline-none focus:ring-2 focus:ring-violet-500"
                        placeholder={`Enter ${cred.label.toLowerCase()}…`}
                      />
                      {cred.type === 'password' && (
                        <button
                          type="button"
                          onClick={() => setShowSecrets(p => ({ ...p, [cred.field]: !p[cred.field] }))}
                          className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
                        >
                          {showSecrets[cred.field] ? <EyeOff size={16} /> : <Eye size={16} />}
                        </button>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        <div className="px-6 py-4 bg-gray-50 dark:bg-gray-800/50 border-t border-gray-200 dark:border-gray-800 flex items-center justify-between rounded-b-2xl">
          <p className="text-xs text-gray-500 flex items-center gap-1.5">
            <ShieldCheck size={14} className="text-emerald-500" />
            Credentials are encrypted at rest.
          </p>
          <div className="flex items-center gap-3">
            <button
              onClick={onClose}
              className="px-4 py-2 text-sm font-medium text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white transition-colors"
            >
              Cancel
            </button>
            <button
              onClick={handleSave}
              disabled={saving}
              className="flex items-center gap-2 px-6 py-2 rounded-lg bg-violet-600 hover:bg-violet-700 text-white text-sm font-semibold shadow-lg shadow-violet-500/20 transition-all disabled:opacity-50"
            >
              {saving ? <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" /> : <Plus size={16} />}
              {tool ? 'Update Tool' : 'Install Tool'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

export default function MarketplacePage() {
  const params = useParams()
  const router = useRouter()
  const qc = useQueryClient()
  const agentId = params.id as string

  const [search, setSearch] = useState('')
  const [selectedCategory, setSelectedCategory] = useState<string | null>(null)
  const [showConfig, setShowConfig] = useState<{ entry: CatalogEntry; tool?: ToolRecord } | null>(null)

  const { data: catalog = [] } = useQuery({
    queryKey: ['tool-catalog'],
    queryFn: () => toolsApi.getCatalog(),
  })

  const { data: installedTools = [] } = useQuery({
    queryKey: ['tools', agentId],
    queryFn: () => toolsApi.list(agentId),
    enabled: !!agentId,
  })

  const filteredCatalog = useMemo(() => {
    return catalog.filter((entry: CatalogEntry) => {
      const matchesSearch = entry.name.toLowerCase().includes(search.toLowerCase()) ||
                          entry.description.toLowerCase().includes(search.toLowerCase())
      const matchesCat = !selectedCategory || entry.category === selectedCategory
      return matchesSearch && matchesCat
    })
  }, [catalog, search, selectedCategory])

  const categories = useMemo(() => {
    const cats = new Set(catalog.map((e: any) => e.category))
    return Array.from(cats).sort()
  }, [catalog])

  return (
    <div className="p-8 w-full max-w-7xl mx-auto">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-6 mb-10">
        <div className="space-y-1">
          <Link
            href={`/dashboard/agents/${agentId}/tools`}
            className="flex items-center gap-2 text-sm text-gray-500 hover:text-violet-600 transition-colors mb-2 w-fit"
          >
            <ArrowLeft size={16} />
            Back to Tools
          </Link>
          <h1 className="text-3xl font-bold text-gray-900 dark:text-white flex items-center gap-3">
            <Zap className="text-violet-600" />
            Tool Marketplace
          </h1>
          <p className="text-gray-500">Discover and install ready-made integrations for your AI Agent.</p>
        </div>

        <div className="flex items-center gap-3">
          <div className="relative group">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 group-focus-within:text-violet-500 transition-colors" size={18} />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search integrations…"
              className="pl-10 pr-4 py-2.5 w-full md:w-80 rounded-xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-950 text-sm focus:ring-2 focus:ring-violet-500/20 focus:border-violet-500 outline-none transition-all shadow-sm"
            />
          </div>
        </div>
      </div>

      <div className="flex flex-col lg:flex-row gap-8">
        {/* Sidebar Filters */}
        <div className="lg:w-64 flex-shrink-0 space-y-6">
          <div>
            <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-widest mb-4">Categories</h3>
            <div className="flex flex-wrap lg:flex-col gap-2">
              <button
                onClick={() => setSelectedCategory(null)}
                className={`px-4 py-2 rounded-lg text-sm font-medium transition-all text-left ${
                  !selectedCategory
                    ? 'bg-violet-600 text-white shadow-lg shadow-violet-500/30'
                    : 'text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800'
                }`}
              >
                All Categories
              </button>
              {categories.map((cat: any) => (
                <button
                  key={cat}
                  onClick={() => setSelectedCategory(cat)}
                  className={`px-4 py-2 rounded-lg text-sm font-medium transition-all text-left ${
                    selectedCategory === cat
                      ? 'bg-violet-600 text-white shadow-lg shadow-violet-500/30'
                      : 'text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800'
                  }`}
                >
                  {CATEGORY_LABELS[cat] || cat}
                </button>
              ))}
            </div>
          </div>

          <div className="p-5 rounded-2xl bg-gradient-to-br from-violet-600 to-indigo-700 text-white shadow-xl shadow-violet-500/20">
            <h4 className="font-bold mb-2 flex items-center gap-2">
              <Zap size={18} />
              Custom Tools?
            </h4>
            <p className="text-xs text-white/80 leading-relaxed mb-4">
              Can&apos;t find what you need? Create a custom webhook integration to connect any API.
            </p>
            <button
              onClick={() => {
                const webhookEntry = catalog.find((e: any) => e.id === 'webhook')
                if (webhookEntry) setShowConfig({ entry: webhookEntry })
              }}
              className="w-full py-2 bg-white/20 hover:bg-white/30 rounded-lg text-xs font-bold transition-colors border border-white/20"
            >
              Configure Webhook
            </button>
          </div>
        </div>

        {/* Results Grid */}
        <div className="flex-1">
          {filteredCatalog.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-20 bg-gray-50 dark:bg-gray-900/50 rounded-3xl border-2 border-dashed border-gray-200 dark:border-gray-800">
              <Search size={48} className="text-gray-300 mb-4" />
              <h3 className="text-lg font-medium text-gray-900 dark:text-white">No integrations found</h3>
              <p className="text-gray-500 text-sm">Try adjusting your search or filters.</p>
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6">
              {filteredCatalog.map((entry: CatalogEntry) => {
                const isInstalled = installedTools.some((t: any) => t.is_builtin && t.name.startsWith(entry.id))
                return (
                  <div
                    key={entry.id}
                    className="group flex flex-col bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-800 hover:border-violet-500/50 hover:shadow-2xl hover:shadow-violet-500/5 transition-all duration-300 overflow-hidden"
                  >
                    <div className="p-6 flex-1">
                      <div className="flex items-start justify-between mb-4">
                        <div className="w-12 h-12 rounded-xl bg-violet-50 dark:bg-violet-900/20 flex items-center justify-center group-hover:scale-110 transition-transform">
                          <Settings className="text-violet-600 dark:text-violet-400" size={24} />
                        </div>
                        {isInstalled && (
                          <span className="flex items-center gap-1 text-[10px] font-bold uppercase tracking-widest text-emerald-600 dark:text-emerald-400 bg-emerald-50 dark:bg-emerald-900/20 px-2 py-1 rounded-full">
                            <CheckCircle2 size={12} />
                            Installed
                          </span>
                        )}
                      </div>
                      <h3 className="text-lg font-bold text-gray-900 dark:text-white mb-2 group-hover:text-violet-600 transition-colors">
                        {entry.name}
                      </h3>
                      <p className="text-sm text-gray-500 line-clamp-3 leading-relaxed">
                        {entry.description}
                      </p>
                    </div>
                    <div className="px-6 py-4 bg-gray-50/50 dark:bg-gray-800/30 border-t border-gray-100 dark:border-gray-800 flex items-center justify-between">
                      <span className="text-[10px] font-bold text-gray-400 uppercase tracking-widest">
                        {CATEGORY_LABELS[entry.category] || entry.category}
                      </span>
                      <button
                        onClick={() => setShowConfig({ entry })}
                        className={`flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-bold transition-all ${
                          isInstalled
                            ? 'text-violet-600 hover:bg-violet-50 dark:hover:bg-violet-900/20'
                            : 'bg-gray-900 dark:bg-white text-white dark:text-gray-900 hover:scale-105 active:scale-95'
                        }`}
                      >
                        {isInstalled ? (
                          <>
                            <Settings size={16} />
                            Configure
                          </>
                        ) : (
                          <>
                            <Plus size={16} />
                            Install
                          </>
                        )}
                      </button>
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </div>
      </div>

      {showConfig && (
        <ToolModal
          entry={showConfig.entry}
          tool={showConfig.tool}
          onClose={() => setShowConfig(null)}
          onSaved={() => qc.invalidateQueries({ queryKey: ['tools', agentId] })}
        />
      )}
    </div>
  )
}
