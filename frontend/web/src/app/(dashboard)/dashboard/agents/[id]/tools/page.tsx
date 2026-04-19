'use client'

import { useState } from 'react'
import { useParams, useRouter } from 'next/navigation'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { agentsApi, toolsApi, workflowsApi } from '@/lib/api'
import toast from 'react-hot-toast'
import {
  Wrench,
  Settings,
  X,
  Eye,
  EyeOff,
  Plus,
  Trash2,
  CheckCircle,
  XCircle,
  Play,
  CheckCircle2,
  Bot,
  GitBranch,
  Zap,
  ChevronRight,
  ShieldCheck,
  ArrowRight,
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

interface AgentRecord {
  id: string
  name: string
  description?: string
  is_available_as_tool: boolean
}

interface WorkflowRecord {
  id: string
  name: string
  description: string
  is_active: boolean
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

// ─── Shared Configuration Components ───────────────────────────────────────────

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
  
  const [apiKey, setApiKey] = useState(existingAuth.value?.replace(/^Bearer /, '') || '')
  const [username, setUsername] = useState(existingAuth.username || '')
  const [password, setPassword] = useState(existingAuth.password || '')
  const [tokenUrl, setTokenUrl] = useState(existingAuth.token_url || '')
  const [clientId, setClientId] = useState(existingAuth.client_id || '')
  const [clientSecret, setClientSecret] = useState(existingAuth.client_secret || '')

  const [params, setParams] = useState<InputParam[]>(schemaToParams(tool?.input_schema))
  
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
    if (!name || !url) { toast.error('Name and URL required'); return }
    setSaving(true)
    try {
      const payload = getPayload()
      if (tool) await toolsApi.update(tool.name, payload)
      else await toolsApi.register(payload)
      toast.success('Integration updated')
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
    setIsTesting(true); setTestError(null); setTestOutput(null)
    try {
      const res = await toolsApi.testExecute({ tool_config: getPayload(), parameters: parsedInput })
      if (res.status === 'failed' || res.status === 'timeout') setTestError(res.error || 'Execution failed')
      setTestOutput(res)
    } catch (e: any) { setTestError(e.response?.data?.detail || e.message || 'Test failed') }
    finally { setIsTesting(false) }
  }

  const inputCls = 'w-full px-4 py-3 rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-sm focus:outline-none focus:ring-2 focus:ring-violet-500/20 transition-all'
  const labelCls = 'block text-[10px] font-black text-gray-400 uppercase tracking-widest mb-2'

  return (
    <div className="fixed inset-0 bg-black/60 z-50 flex items-center justify-center p-4 backdrop-blur-sm">
      <div className="bg-white dark:bg-gray-900 rounded-[2.5rem] shadow-2xl w-full max-w-4xl max-h-[90vh] flex flex-col overflow-hidden animate-in fade-in zoom-in duration-300">
        <div className="flex items-center justify-between px-10 py-8 border-b border-gray-100 dark:border-gray-800">
          <div>
            <h2 className="text-2xl font-black tracking-tight flex items-center gap-3">
              <Zap className="text-violet-600" />
              Configure {entry.name}
            </h2>
            <p className="text-sm text-gray-500 mt-1">Manage integration logic and perform live execution tests.</p>
          </div>
          <button onClick={onClose} className="p-3 rounded-2xl hover:bg-gray-100 text-gray-400"><X size={24} /></button>
        </div>

        <div className="overflow-y-auto flex-1 px-10 py-8 space-y-10">
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-10">
            <div className="space-y-6">
              <div><label className={labelCls}>Name</label><input type="text" disabled value={name} className={inputCls + ' opacity-50'} /></div>
              <div className="flex gap-4">
                <div className="w-32"><label className={labelCls}>Method</label><select value={method} onChange={(e) => setMethod(e.target.value)} className={inputCls}><option>POST</option><option>GET</option><option>PUT</option></select></div>
                <div className="flex-1"><label className={labelCls}>URL</label><input type="url" value={url} onChange={(e) => setUrl(e.target.value)} className={inputCls} /></div>
              </div>
              <div><label className={labelCls}>Logic Instructions</label><textarea rows={3} value={description} onChange={(e) => setDescription(e.target.value)} className={inputCls + ' resize-none'} /></div>
            </div>
            <div className="space-y-6">
              <label className={labelCls}>Authentication</label>
              <select value={authType} onChange={(e) => setAuthType(e.target.value)} className={inputCls}>
                {AUTH_TYPES.map((a) => <option key={a.value} value={a.value}>{a.label}</option>)}
              </select>
              {authType !== 'none' && (
                <div className="p-6 bg-gray-50 dark:bg-gray-800/50 rounded-2xl space-y-4">
                   {(authType === 'api_key' || authType === 'bearer') && (
                    <div className="relative">
                      <input type={showSecrets.apiKey ? 'text' : 'password'} value={apiKey} onChange={(e) => setApiKey(e.target.value)} placeholder="Secret Token" className={inputCls} />
                      <button type="button" onClick={() => toggle('apiKey')} className="absolute right-4 top-1/2 -translate-y-1/2 text-gray-400">
                        {showSecrets.apiKey ? <EyeOff size={16} /> : <Eye size={16} />}
                      </button>
                    </div>
                  )}
                  {authType === 'basic' && (
                    <div className="flex gap-4">
                      <input type="text" placeholder="User" value={username} onChange={(e) => setUsername(e.target.value)} className={inputCls} />
                      <input type="password" placeholder="Pass" value={password} onChange={(e) => setPassword(e.target.value)} className={inputCls} />
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>

          <div className="space-y-4">
            <div className="flex items-center justify-between"><label className={labelCls}>Fields</label><button onClick={addParam} className="text-[10px] font-black uppercase text-violet-600 px-3 py-1.5 bg-violet-50 rounded-lg tracking-widest">+ Add Field</button></div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {params.map((p, i) => (
                <div key={i} className="flex items-center gap-3 p-4 bg-gray-50 dark:bg-gray-800/30 rounded-2xl border border-gray-100 dark:border-gray-800">
                  <div className="flex-1 min-w-0">
                    <input type="text" value={p.name} onChange={(e) => updateParam(i, 'name', e.target.value)} className="w-full bg-transparent font-bold text-sm outline-none" placeholder="key-name" />
                    <input type="text" value={p.description} onChange={(e) => updateParam(i, 'description', e.target.value)} className="w-full bg-transparent text-xs text-gray-500 outline-none" placeholder="Purpose..." />
                  </div>
                  <button onClick={() => removeParam(i)} className="text-gray-300 hover:text-red-500"><Trash2 size={14} /></button>
                </div>
              ))}
            </div>
          </div>

          <div className="pt-10 border-t border-gray-100 space-y-6">
            <h3 className="text-sm font-black uppercase tracking-widest flex items-center gap-2"><ShieldCheck size={18} /> Test Environment</h3>
            <div className="grid grid-cols-2 gap-8">
              <textarea rows={4} value={testInput} onChange={(e) => setTestInput(e.target.value)} className="w-full p-4 bg-gray-950 text-emerald-400 font-mono text-xs rounded-2xl" placeholder="{}" />
              <div className="w-full h-28 p-4 bg-gray-900 rounded-2xl font-mono text-xs overflow-auto text-gray-300">
                {isTesting && <div className="animate-pulse">Running test...</div>}
                {testError && <div className="text-red-400">{testError}</div>}
                {testOutput?.result && <pre>{JSON.stringify(testOutput.result, null, 2)}</pre>}
              </div>
            </div>
          </div>
        </div>

        <div className="px-10 py-6 bg-gray-50/50 border-t flex justify-between items-center">
          <button onClick={handleTest} className="flex items-center gap-2 px-6 py-3 border border-violet-200 rounded-2xl text-[10px] font-black uppercase text-violet-700 tracking-widest hover:bg-white"><Play size={12} fill="currentColor" /> Run Execution</button>
          <div className="flex gap-4">
            <button onClick={onClose} className="text-sm font-bold text-gray-400">Cancel</button>
            <button onClick={handleSave} className="px-10 py-3 bg-violet-600 text-white rounded-2xl text-sm font-black hover:bg-violet-700">Update Module</button>
          </div>
        </div>
      </div>
    </div>
  )
}

// ─── Management Page ─────────────────────────────────────────────────────────

export default function AgentToolsPage() {
  const router = useRouter()
  const params = useParams()
  const agentId = params.id as string
  const qc = useQueryClient()

  const [webhookModal, setWebhookModal] = useState<{ entry: CatalogEntry; tool?: ToolRecord } | null>(null)

  const { data: agent } = useQuery({ queryKey: ['agent', agentId], queryFn: () => agentsApi.get(agentId), enabled: !!agentId })
  const { data: catalog = [] } = useQuery<CatalogEntry[]>({ queryKey: ['tools-catalog'], queryFn: toolsApi.catalog })
  const { data: registeredTools = [] } = useQuery<ToolRecord[]>({ queryKey: ['tools', agentId], queryFn: () => toolsApi.list(agentId), enabled: !!agentId })
  const { data: peerAgents = [] } = useQuery<AgentRecord[]>({ queryKey: ['agents-as-tools', agentId], queryFn: () => agentsApi.listAvailableAsTools(agentId), enabled: !!agentId })
  const { data: workflows = [] } = useQuery<WorkflowRecord[]>({ queryKey: ['workflows', agentId], queryFn: () => workflowsApi.list(agentId), enabled: !!agentId })

  const agentTools: string[] = agent?.tools || []

  const toggleMutation = useMutation({
    mutationFn: (toolName: string) => agentTools.includes(toolName) ? toolsApi.disableForAgent(agentId, toolName, agentTools) : toolsApi.enableForAgent(agentId, toolName, agentTools),
    onSuccess: (_, name) => { qc.invalidateQueries({ queryKey: ['agent', agentId] }); toast.success(agentTools.includes(name) ? 'Tool disabled' : 'Tool enabled') },
  })

  const handleDeleteTool = async (n: string) => { if (confirm(`Delete '${n}'?`)) { await toolsApi.delete(n); qc.invalidateQueries({ queryKey: ['tools', agentId] }); toast.success('Tool deleted') } }

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-950 p-6">
      
      {/* Back nav */}
      <Link
        href={`/dashboard/agents/${agentId}`}
        className="inline-flex items-center gap-2 text-sm text-gray-500 dark:text-gray-400 hover:text-violet-600 dark:hover:text-violet-400 mb-6"
      >
        <ChevronLeft size={16} /> {agent?.name ?? 'Agent'}
      </Link>

      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white flex items-center gap-2">
            <Wrench className="text-violet-500" size={24} /> Intelligence
          </h1>
          <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
            Manage active skills and connect new intelligence modules
          </p>
        </div>
        <button
          onClick={() => router.push(`/dashboard/agents/${agentId}/tools/marketplace`)}
          className="flex items-center gap-2 px-4 py-2 bg-violet-600 text-white rounded-xl text-sm font-medium hover:bg-violet-700 transition-colors"
        >
          <Plus size={16} /> Marketplace
        </button>
      </div>

      <div className="space-y-8">
        {/* Section: Configured Integrations */}
        {registeredTools.length > 0 && (
          <div>
            <h3 className="text-sm font-semibold text-gray-900 dark:text-white mb-4">Active Integrations</h3>
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
              {registeredTools.map((tool) => {
                const isEnabled = agentTools.includes(tool.name)
                const entry = catalog.find(c => c.id === tool.tool_metadata?.catalog_id) || { name: tool.name, description: tool.description, category: tool.category, credentials: [] } as any
                return (
                  <div key={tool.id} className="relative bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-800 hover:border-violet-300 dark:hover:border-violet-700 transition-colors p-5 flex flex-col gap-3">
                    <div className="flex items-start justify-between gap-3">
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 mb-1">
                          <Zap size={16} className="text-violet-500" />
                          <span className="font-semibold text-gray-900 dark:text-white truncate">
                            {tool.name}
                          </span>
                        </div>
                        {tool.description && (
                          <p className="text-sm text-gray-500 dark:text-gray-400 line-clamp-2">{tool.description}</p>
                        )}
                      </div>
                      <div className="flex items-center gap-1.5 shrink-0">
                        {isEnabled ? (
                          <span className="flex items-center gap-1 text-xs font-medium text-emerald-700 dark:text-emerald-400 bg-emerald-50 dark:bg-emerald-900/20 px-2 py-0.5 rounded-full">
                            <CheckCircle2 size={11} /> Ready
                          </span>
                        ) : (
                          <span className="flex items-center gap-1 text-xs font-medium text-gray-500 dark:text-gray-400 bg-gray-100 dark:bg-gray-800 px-2 py-0.5 rounded-full">
                            <XCircle size={11} /> Disabled
                          </span>
                        )}
                      </div>
                    </div>
                    
                    <div className="flex items-center justify-between pt-3 border-t border-gray-100 dark:border-gray-800 mt-auto">
                      <button onClick={() => toggleMutation.mutate(tool.name)} className={`h-5 w-9 rounded-full transition-all relative ${isEnabled ? 'bg-violet-600' : 'bg-gray-200 dark:bg-gray-700'}`}>
                        <span className={`absolute top-[2px] h-4 w-4 rounded-full bg-white transition-all shadow-sm ${isEnabled ? 'translate-x-[16px]' : 'translate-x-[2px]'}`} />
                      </button>
                      <div className="flex items-center gap-1.5">
                        <button onClick={() => setWebhookModal({ entry, tool })} title="Edit configuration" className="p-1.5 rounded-lg text-gray-400 hover:text-gray-600 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"><Settings size={14} /></button>
                        <button onClick={() => handleDeleteTool(tool.name)} title="Delete integration" className="p-1.5 rounded-lg text-gray-400 hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-900/20 transition-colors"><Trash2 size={14} /></button>
                      </div>
                    </div>
                  </div>
                )
              })}
            </div>
          </div>
        )}

        {/* Section: Sub-Agents & Workflows */}
        {(peerAgents.length > 0 || workflows.length > 0) && (
          <div>
            <h3 className="text-sm font-semibold text-gray-900 dark:text-white mb-4">Internal Assets</h3>
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
              {peerAgents.map((peer) => {
                const toolName = `agent:${peer.id}`
                const isEnabled = agentTools.includes(toolName)
                return (
                  <div key={peer.id} className="relative bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-800 hover:border-emerald-300 dark:hover:border-emerald-700 transition-colors p-5 flex flex-col gap-3">
                    <div className="flex items-start justify-between gap-3">
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 mb-1">
                          <Bot size={16} className="text-emerald-500" />
                          <span className="font-semibold text-gray-900 dark:text-white truncate">
                            {peer.name}
                          </span>
                        </div>
                        <p className="text-sm text-gray-500 dark:text-gray-400 line-clamp-2">Peer Agent skill.</p>
                      </div>
                      <div className="flex items-center gap-1.5 shrink-0">
                        {isEnabled ? (
                          <span className="flex items-center gap-1 text-xs font-medium text-emerald-700 dark:text-emerald-400 bg-emerald-50 dark:bg-emerald-900/20 px-2 py-0.5 rounded-full">
                            <CheckCircle2 size={11} /> Ready
                          </span>
                        ) : (
                          <span className="flex items-center gap-1 text-xs font-medium text-gray-500 dark:text-gray-400 bg-gray-100 dark:bg-gray-800 px-2 py-0.5 rounded-full">
                            <XCircle size={11} /> Disabled
                          </span>
                        )}
                      </div>
                    </div>
                    
                    <div className="flex items-center justify-between pt-3 border-t border-gray-100 dark:border-gray-800 mt-auto">
                      <button onClick={() => toggleMutation.mutate(toolName)} className={`h-5 w-9 rounded-full transition-all relative ${isEnabled ? 'bg-emerald-600' : 'bg-gray-200 dark:bg-gray-700'}`}>
                        <span className={`absolute top-[2px] h-4 w-4 rounded-full bg-white transition-all shadow-sm ${isEnabled ? 'translate-x-[16px]' : 'translate-x-[2px]'}`} />
                      </button>
                    </div>
                  </div>
                )
              })}
              {workflows.filter(wf => wf.is_active).map((wf) => {
                const toolName = `wf:${wf.id}`
                const isEnabled = agentTools.includes(toolName)
                return (
                  <div key={wf.id} className="relative bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-800 hover:border-violet-300 dark:hover:border-violet-700 transition-colors p-5 flex flex-col gap-3">
                    <div className="flex items-start justify-between gap-3">
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 mb-1">
                          <GitBranch size={16} className="text-violet-500" />
                          <span className="font-semibold text-gray-900 dark:text-white truncate">
                            {wf.name}
                          </span>
                        </div>
                        <p className="text-sm text-gray-500 dark:text-gray-400 line-clamp-2">Active business workflow.</p>
                      </div>
                      <div className="flex items-center gap-1.5 shrink-0">
                        {isEnabled ? (
                          <span className="flex items-center gap-1 text-xs font-medium text-emerald-700 dark:text-emerald-400 bg-emerald-50 dark:bg-emerald-900/20 px-2 py-0.5 rounded-full">
                            <CheckCircle2 size={11} /> Ready
                          </span>
                        ) : (
                          <span className="flex items-center gap-1 text-xs font-medium text-gray-500 dark:text-gray-400 bg-gray-100 dark:bg-gray-800 px-2 py-0.5 rounded-full">
                            <XCircle size={11} /> Disabled
                          </span>
                        )}
                      </div>
                    </div>
                    
                    <div className="flex items-center justify-between pt-3 border-t border-gray-100 dark:border-gray-800 mt-auto">
                      <button onClick={() => toggleMutation.mutate(toolName)} className={`h-5 w-9 rounded-full transition-all relative ${isEnabled ? 'bg-violet-600' : 'bg-gray-200 dark:bg-gray-700'}`}>
                        <span className={`absolute top-[2px] h-4 w-4 rounded-full bg-white transition-all shadow-sm ${isEnabled ? 'translate-x-[16px]' : 'translate-x-[2px]'}`} />
                      </button>
                    </div>
                  </div>
                )
              })}
            </div>
          </div>
        )}
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
