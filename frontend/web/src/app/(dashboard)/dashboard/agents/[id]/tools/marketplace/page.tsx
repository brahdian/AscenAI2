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

// ─── Advanced Webhook Modal ───────────────────────────────────────────────────

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

  const [name, setName] = useState(tool?.name || entry.name.toLowerCase().replace(/\s+/g, '_'))
  const [description, setDescription] = useState(tool?.description || entry.description || '')
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

  // Parameters
  const [params, setParams] = useState<InputParam[]>(schemaToParams(tool?.input_schema))
  
  // Testing
  const [isTesting, setIsTesting] = useState(false)
  const [testInput, setTestInput] = useState('{\n  \n}')
  const [testOutput, setTestOutput] = useState<any>(null)
  const [testError, setTestError] = useState<string | null>(null)

  const toggle = (field: string) => setShowSecrets((p) => ({ ...p, [field]: !p[field] }))
  const addParam = () => setParams((p) => [...p, { name: '', type: 'string', description: '', required: false }])
  const removeParam = (i: number) => setParams((p) => p.filter((_, idx) => idx !== i))
  const updateParam = (i: number, key: keyof InputParam, value: any) =>
    setParams((p) => p.map((row, idx) => (idx === i ? { ...row, [key]: value } : row)))

  const buildAuthConfig = (): Record<string, any> => {
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
    }
    return authConfig
  }

  const getPayload = () => ({
    name,
    description,
    category: entry.category,
    is_builtin: false,
    endpoint_url: url,
    input_schema: buildInputSchema(params),
    tool_metadata: { catalog_id: entry.id, method },
    auth_config: buildAuthConfig(),
  })

  const handleSave = async () => {
    if (!name) { toast.error('Tool name is required'); return }
    if (!url) { toast.error('Endpoint URL is required'); return }
    setSaving(true)
    try {
      const payload = getPayload()
      if (tool) await toolsApi.update(tool.name, payload)
      else await toolsApi.register(payload)
      toast.success('Integration saved')
      onSaved()
      onClose()
    } catch (e: any) {
      toast.error(e.response?.data?.detail || 'Save failed')
    } finally {
      setSaving(false)
    }
  }

  const handleTest = async () => {
    let parsedInput = {}
    try { if (testInput.trim()) parsedInput = JSON.parse(testInput) }
    catch { toast.error('Invalid JSON tool input'); return }
    
    setIsTesting(true)
    setTestError(null)
    setTestOutput(null)
    try {
      const res = await toolsApi.testExecute({ tool_config: getPayload(), parameters: parsedInput })
      if (res.status === 'failed' || res.status === 'timeout') setTestError(res.error || 'Execution failed')
      setTestOutput(res)
    } catch (e: any) {
      setTestError(e.response?.data?.detail || e.message || 'Test failed')
    } finally {
      setIsTesting(false)
    }
  }

  const inputCls = 'w-full px-4 py-3 rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-sm text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-violet-500/20 transition-all'
  const labelCls = 'block text-xs font-bold text-gray-400 uppercase tracking-widest mb-2'

  return (
    <div className="fixed inset-0 bg-black/60 z-50 flex items-center justify-center p-4 backdrop-blur-sm">
      <div className="bg-white dark:bg-gray-900 rounded-[2.5rem] shadow-2xl w-full max-w-4xl max-h-[90vh] flex flex-col overflow-hidden animate-in fade-in zoom-in duration-300">
        <div className="flex items-center justify-between px-10 py-8 border-b border-gray-100 dark:border-gray-800 flex-shrink-0">
          <div>
            <h2 className="text-2xl font-black text-gray-900 dark:text-white tracking-tight flex items-center gap-3">
              <Zap className="text-violet-600" />
              {tool ? 'Customize' : 'Configure'} {entry.name}
            </h2>
            <p className="text-sm text-gray-500 mt-1">Fine-tune your custom integration and test it live.</p>
          </div>
          <button onClick={onClose} className="p-3 rounded-2xl hover:bg-gray-100 dark:hover:bg-gray-800 text-gray-400 transition-colors">
            <X size={24} />
          </button>
        </div>

        <div className="overflow-y-auto flex-1 px-10 py-8 space-y-10 custom-scrollbar">
          {/* Section 1: Endpoint & Logic */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-10">
            <div className="space-y-6">
              <div>
                <label className={labelCls}>Unique Identifier</label>
                <input
                  type="text"
                  disabled={!!tool}
                  value={name}
                  onChange={(e) => setName(e.target.value.toLowerCase().replace(/[^a-z0-9_\-]/g, '_'))}
                  placeholder="my_webhook"
                  className={inputCls + (tool ? ' opacity-50 cursor-not-allowed' : '')}
                />
              </div>
              <div className="flex gap-4">
                <div className="w-32 shrink-0">
                  <label className={labelCls}>Method</label>
                  <select value={method} onChange={(e) => setMethod(e.target.value)} className={inputCls + ' appearance-none'}>
                    <option>POST</option><option>GET</option><option>PUT</option><option>PATCH</option>
                  </select>
                </div>
                <div className="flex-1">
                  <label className={labelCls}>Endpoint URL</label>
                  <input type="url" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://api.acme.com/hook" className={inputCls} />
                </div>
              </div>
              <div>
                <label className={labelCls}>Instructions (For AI LLM)</label>
                <textarea
                  rows={4}
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  placeholder="Tell the AI exactly when to trigger this tool..."
                  className={inputCls + ' resize-none'}
                />
              </div>
            </div>

            <div className="space-y-6">
              <label className={labelCls}>Authentication</label>
              <select value={authType} onChange={(e) => setAuthType(e.target.value)} className={inputCls}>
                {AUTH_TYPES.map((a) => <option key={a.value} value={a.value}>{a.label}</option>)}
              </select>

              {authType !== 'none' && (
                <div className="p-6 bg-gray-50/50 dark:bg-gray-800/50 rounded-2xl border border-gray-100 dark:border-gray-800 space-y-4">
                  {(authType === 'api_key' || authType === 'bearer') && (
                    <div>
                      <label className="text-[10px] font-bold text-gray-400 uppercase tracking-widest mb-1.5 block">Secret Token</label>
                      <div className="relative">
                        <input type={showSecrets.apiKey ? 'text' : 'password'} value={apiKey} onChange={(e) => setApiKey(e.target.value)} className={inputCls} />
                        <button type="button" onClick={() => toggle('apiKey')} className="absolute right-4 top-1/2 -translate-y-1/2 text-gray-400">
                          {showSecrets.apiKey ? <EyeOff size={16} /> : <Eye size={16} />}
                        </button>
                      </div>
                    </div>
                  )}
                  {authType === 'basic' && (
                    <div className="grid grid-cols-2 gap-4">
                      <div><label className="text-[10px] font-bold text-gray-400 uppercase tracking-widest mb-1.5 block">User</label><input type="text" value={username} onChange={(e) => setUsername(e.target.value)} className={inputCls} /></div>
                      <div><label className="text-[10px] font-bold text-gray-400 uppercase tracking-widest mb-1.5 block">Pass</label><input type="password" value={password} onChange={(e) => setPassword(e.target.value)} className={inputCls} /></div>
                    </div>
                  )}
                  {authType === 'oauth2_cc' && (
                    <div className="space-y-3">
                      <input type="url" placeholder="Token URL" value={tokenUrl} onChange={(e) => setTokenUrl(e.target.value)} className={inputCls} />
                      <input type="text" placeholder="Client ID" value={clientId} onChange={(e) => setClientId(e.target.value)} className={inputCls} />
                      <input type="password" placeholder="Client Secret" value={clientSecret} onChange={(e) => setClientSecret(e.target.value)} className={inputCls} />
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>

          {/* Section 2: Parameters */}
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <label className={labelCls}>Field Definitions</label>
              <button onClick={addParam} className="text-xs font-bold text-violet-600 hover:text-violet-700 flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-violet-50 dark:bg-violet-900/20 transition-all">
                <Plus size={14} /> Add Field
              </button>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {params.map((p, i) => (
                <div key={i} className="group flex items-center gap-3 bg-gray-50/50 dark:bg-gray-800/30 p-4 rounded-2xl border border-gray-100 dark:border-gray-800 hover:border-violet-200 transition-all">
                  <div className="flex-1 space-y-2">
                    <div className="flex gap-2">
                      <input type="text" value={p.name} onChange={(e) => updateParam(i, 'name', e.target.value)} placeholder="key" className="flex-1 bg-transparent text-sm font-bold border-none focus:ring-0 p-0" />
                      <select value={p.type} onChange={(e) => updateParam(i, 'type', e.target.value)} className="bg-transparent text-[10px] uppercase font-black text-gray-400 border-none focus:ring-0 p-0">
                        {PARAM_TYPES.map(t => <option key={t}>{t}</option>)}
                      </select>
                    </div>
                    <input type="text" value={p.description} onChange={(e) => updateParam(i, 'description', e.target.value)} placeholder="Usage instructions..." className="w-full bg-transparent text-xs text-gray-500 border-none focus:ring-0 p-0" />
                  </div>
                  <div className="flex flex-col items-center gap-2">
                    <input type="checkbox" checked={p.required} onChange={(e) => updateParam(i, 'required', e.target.checked)} className="h-4 w-4 bg-transparent border-gray-300 rounded accent-violet-600" />
                    <button onClick={() => removeParam(i)} className="text-gray-300 hover:text-red-500 transition-colors opacity-0 group-hover:opacity-100"><Trash2 size={14} /></button>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Section 3: Live Testing */}
          <div className="pt-10 border-t border-gray-100 dark:border-gray-800 space-y-6">
            <div className="flex items-center gap-2">
              <div className="w-8 h-8 rounded-full bg-emerald-50 dark:bg-emerald-900/20 flex items-center justify-center text-emerald-600">
                <ShieldCheck size={18} />
              </div>
              <h3 className="text-lg font-black text-gray-900 dark:text-white tracking-tight">Live Test Environment</h3>
            </div>
            
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
              <div className="space-y-3">
                <label className="text-[10px] font-black text-gray-400 tracking-[0.2em] uppercase">Test Payload (JSON)</label>
                <textarea
                  rows={6}
                  value={testInput}
                  onChange={(e) => setTestInput(e.target.value)}
                  className="w-full p-4 bg-gray-950 text-emerald-400 font-mono text-xs rounded-2xl border border-gray-800 focus:ring-2 focus:ring-emerald-500/20 outline-none transition-all resize-none"
                />
              </div>
              <div className="space-y-3">
                <label className="text-[10px] font-black text-gray-400 tracking-[0.2em] uppercase">Terminal Output</label>
                <div className="w-full h-[148px] p-4 bg-gray-900 rounded-2xl border border-gray-800 font-mono text-xs overflow-auto">
                  {isTesting && <div className="text-violet-400 animate-pulse flex items-center gap-2"><ArrowLeft size={12} className="animate-spin" /> Verifying connection...</div>}
                  {testError && <div className="text-red-400">Error: {testError}</div>}
                  {testOutput?.result && <pre className="text-gray-300">{JSON.stringify(testOutput.result, null, 2)}</pre>}
                  {!isTesting && !testError && !testOutput && <div className="text-gray-600 italic">No execution data...</div>}
                </div>
              </div>
            </div>
          </div>
        </div>

        <div className="px-10 py-6 bg-gray-50/50 dark:bg-gray-800/50 border-t border-gray-100 dark:border-gray-800 flex justify-between items-center flex-shrink-0">
          <button
            onClick={handleTest}
            disabled={isTesting || !url}
            className="flex items-center gap-2 px-6 py-3 border border-violet-200 dark:border-violet-800 rounded-2xl text-xs font-black text-violet-700 dark:text-violet-400 hover:bg-white dark:hover:bg-gray-900 transition-all disabled:opacity-50"
          >
            <Play size={14} fill="currentColor" /> Run Test Execution
          </button>
          <div className="flex gap-4">
            <button onClick={onClose} className="px-6 py-3 text-sm font-bold text-gray-500 hover:text-gray-900 transition-colors">Cancel</button>
            <button
              onClick={handleSave}
              disabled={saving || !name || !url}
              className="px-10 py-3 bg-violet-600 text-white rounded-2xl text-sm font-black hover:bg-violet-700 hover:shadow-xl hover:shadow-violet-500/20 transition-all active:scale-95 disabled:opacity-50"
            >
              {saving ? 'Syncing...' : tool ? 'Save Changes' : 'Connect Agent'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

// ─── Marketplace Page ──────────────────────────────────────────────────────────

export default function MarketplacePage() {
  const { id: agentId } = useParams<{ id: string }>()
  const router = useRouter()
  const qc = useQueryClient()
  
  const [search, setSearch] = useState('')
  const [webhookModal, setWebhookModal] = useState<{ entry: CatalogEntry; tool?: ToolRecord } | null>(null)

  const { data: catalog = [], isLoading: isLoadingCatalog } = useQuery<CatalogEntry[]>({
    queryKey: ['catalog'],
    queryFn: () => toolsApi.catalog(),
  })

  const { data: registeredTools = [] } = useQuery<ToolRecord[]>({
    queryKey: ['tools', agentId],
    queryFn: () => toolsApi.list(agentId),
    enabled: !!agentId,
  })

  const filteredCatalog = useMemo(() => {
    if (!search) return catalog
    const s = search.toLowerCase()
    return catalog.filter(c => 
      c.name.toLowerCase().includes(s) || 
      c.description.toLowerCase().includes(s) ||
      c.category.toLowerCase().includes(s)
    )
  }, [catalog, search])

  const grouped = useMemo(() => {
    return filteredCatalog.reduce((acc, entry) => {
      const cat = entry.category || 'other'
      if (!acc[cat]) acc[cat] = []
      acc[cat].push(entry)
      return acc
    }, {} as Record<string, CatalogEntry[]>)
  }, [filteredCatalog])

  const registeredInstances = useMemo(() => {
    return registeredTools.reduce((acc, t) => {
      const cid = t.tool_metadata?.catalog_id 
      if (cid) { if (!acc[cid]) acc[cid] = []; acc[cid].push(t) }
      return acc
    }, {} as Record<string, ToolRecord[]>)
  }, [registeredTools])

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-950 p-6">
      {/* Back nav */}
      <Link
        href={`/dashboard/agents/${agentId}/tools`}
        className="inline-flex items-center gap-2 text-sm text-gray-500 dark:text-gray-400 hover:text-violet-600 dark:hover:text-violet-400 mb-6"
      >
        <ChevronLeft size={16} /> Intelligence
      </Link>
      
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white flex items-center gap-2">
            <Wrench className="text-violet-500" size={24} /> Marketplace
          </h1>
          <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
            Expand your agent's capabilities with secure native integrations and webhooks
          </p>
        </div>
        
        <div className="relative w-full md:w-64 shrink-0">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" size={16} />
          <input
            type="text"
            placeholder="Search modules..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full pl-9 pr-4 py-2 rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-sm focus:outline-none focus:ring-2 focus:ring-violet-500 transition-all"
          />
        </div>
      </div>

      <div className="space-y-8">
        {Object.entries(grouped).map(([category, entries]) => (
          <div key={category}>
            <h3 className="text-sm font-semibold text-gray-900 dark:text-white mb-4">
              {CATEGORY_LABELS[category] || category}
            </h3>

            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
              {entries.map((entry) => {
                const instances = registeredInstances[entry.id] || []
                const isRegistered = instances.length > 0
                
                return (
                  <div key={entry.id} className="relative bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-800 hover:border-violet-300 dark:hover:border-violet-700 transition-colors p-5 flex flex-col gap-3">
                    <div className="flex items-start justify-between gap-3">
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 mb-1">
                          <Wrench size={16} className="text-violet-500 shrink-0" />
                          <span className="font-semibold text-gray-900 dark:text-white truncate">
                            {entry.name}
                          </span>
                        </div>
                        <p className="text-sm text-gray-500 dark:text-gray-400 line-clamp-2">
                          {entry.description}
                        </p>
                      </div>
                      
                      <div className="flex items-center gap-1.5 shrink-0">
                        {isRegistered && (
                          <span className="flex items-center gap-1 text-xs font-medium text-emerald-700 dark:text-emerald-400 bg-emerald-50 dark:bg-emerald-900/20 px-2 py-0.5 rounded-full">
                            <CheckCircle2 size={11} /> Connected
                          </span>
                        )}
                      </div>
                    </div>

                    <div className="flex items-center justify-between pt-3 border-t border-gray-100 dark:border-gray-800 mt-auto">
                      <div className="flex flex-wrap gap-1.5">
                        {isRegistered && instances.map(i => (
                          <button 
                            key={i.id} 
                            onClick={() => setWebhookModal({ entry, tool: i })}
                            className="px-2 py-1 bg-gray-100 dark:bg-gray-800 rounded-lg text-xs font-medium text-gray-600 dark:text-gray-300 hover:bg-violet-50 hover:text-violet-600 dark:hover:bg-violet-900/20 dark:hover:text-violet-400 transition-all truncate max-w-[120px]"
                          >
                            {i.name}
                          </button>
                        ))}
                      </div>

                      <button
                        onClick={() => setWebhookModal({ entry })}
                        className="flex items-center gap-1 px-3 py-1.5 rounded-xl bg-violet-50 text-violet-600 dark:bg-violet-900/20 dark:text-violet-400 hover:bg-violet-100 dark:hover:bg-violet-900/40 text-xs font-semibold transition-all ml-auto shrink-0"
                      >
                        <Plus size={14} />
                        {isRegistered && entry.allow_multiple ? 'Add' : isRegistered ? 'Configure' : 'Initialize'}
                      </button>
                    </div>
                  </div>
                )
              })}
            </div>
          </div>
        ))}
      </div>

      {webhookModal && (
        <WebhookModal
          entry={webhookModal.entry}
          tool={webhookModal.tool}
          onClose={() => setWebhookModal(null)}
          onSaved={() => qc.invalidateQueries({ queryKey: ['tools', agentId] })}
        />
      )}
    </div>
  )
}
