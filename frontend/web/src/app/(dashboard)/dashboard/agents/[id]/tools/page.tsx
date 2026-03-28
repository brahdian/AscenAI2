'use client'

import { useState } from 'react'
import { useParams } from 'next/navigation'
import Link from 'next/link'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { agentsApi, toolsApi } from '@/lib/api'
import toast from 'react-hot-toast'
import {
  ArrowLeft,
  Wrench,
  ChevronRight,
  Settings,
  Check,
  X,
  Eye,
  EyeOff,
  ExternalLink,
} from 'lucide-react'

interface CatalogEntry {
  key: string
  name: string
  description: string
  category: string
  is_builtin: boolean
  credentials: { field: string; label: string; type: string }[]
}

interface ToolRecord {
  id: string
  name: string
  description: string
  category: string
  is_active: boolean
  is_builtin: boolean
  tool_metadata: Record<string, string>
}

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

export default function AgentToolsPage() {
  const params = useParams()
  const agentId = params.id as string
  const qc = useQueryClient()

  const [configuring, setConfiguring] = useState<CatalogEntry | null>(null)
  const [credentials, setCredentials] = useState<Record<string, string>>({})
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
  const registeredMap = Object.fromEntries(registeredTools.map((t) => [t.name, t]))

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
      toast.success(enabled ? 'Tool enabled for this agent' : 'Tool disabled')
    },
    onError: () => toast.error('Failed to update tool'),
  })

  const openConfig = (entry: CatalogEntry) => {
    const existing = registeredMap[entry.key]
    const existingMeta = existing?.tool_metadata || {}
    const initial: Record<string, string> = {}
    for (const cred of entry.credentials) {
      initial[cred.field] = existingMeta[cred.field] || ''
    }
    setCredentials(initial)
    setShowSecrets({})
    setConfiguring(entry)
  }

  const handleSaveCredentials = async () => {
    if (!configuring) return
    setSaving(true)
    try {
      const existing = registeredMap[configuring.key]
      if (existing) {
        await toolsApi.update(configuring.key, { tool_metadata: credentials })
      } else {
        // Register the tool with credentials
        const catalogEntry = catalog.find((c) => c.key === configuring.key)
        if (!catalogEntry) throw new Error('Catalog entry not found')
        await toolsApi.register({
          name: configuring.key,
          description: configuring.description,
          category: configuring.category,
          is_builtin: true,
          tool_metadata: credentials,
        })
      }
      qc.invalidateQueries({ queryKey: ['tools', agentId] })
      toast.success('Credentials saved')
      setConfiguring(null)
    } catch {
      toast.error('Failed to save credentials')
    } finally {
      setSaving(false)
    }
  }

  const grouped = catalog.reduce<Record<string, CatalogEntry[]>>((acc, entry) => {
    const cat = entry.category
    if (!acc[cat]) acc[cat] = []
    acc[cat].push(entry)
    return acc
  }, {})

  return (
    <div className="p-8 max-w-4xl mx-auto">
      {/* Breadcrumbs */}
      <div className="flex items-center gap-2 text-sm text-gray-500 dark:text-gray-400 mb-6">
        <Link href="/dashboard" className="hover:text-gray-900 dark:hover:text-white">Dashboard</Link>
        <ChevronRight size={14} />
        <Link href="/dashboard/agents" className="hover:text-gray-900 dark:hover:text-white">Agents</Link>
        <ChevronRight size={14} />
        <Link href={`/dashboard/agents/${agentId}`} className="hover:text-gray-900 dark:hover:text-white truncate max-w-[160px]">
          {agent?.name || agentId}
        </Link>
        <ChevronRight size={14} />
        <span className="text-gray-900 dark:text-white font-medium">Tools</span>
      </div>

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

      {/* Info banner */}
      <div className="mb-6 p-4 bg-violet-50 dark:bg-violet-900/20 border border-violet-100 dark:border-violet-800 rounded-xl text-sm text-violet-700 dark:text-violet-300">
        <strong>{agentTools.length}</strong> tool{agentTools.length !== 1 ? 's' : ''} enabled for this agent.
        {agentTools.length > 0 && (
          <span className="ml-1 font-mono text-xs">{agentTools.join(', ')}</span>
        )}
      </div>

      {/* Tool groups */}
      {Object.entries(grouped).map(([category, entries]) => (
        <div key={category} className="mb-6">
          <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">
            {CATEGORY_LABELS[category] || category}
          </h2>
          <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 divide-y divide-gray-100 dark:divide-gray-800">
            {entries.map((entry) => {
              const isEnabled = agentTools.includes(entry.key)
              const isRegistered = !!registeredMap[entry.key]
              const hasCredentials = entry.credentials.length === 0 || isRegistered
              const needsConfig = entry.credentials.length > 0

              return (
                <div
                  key={entry.key}
                  className="flex items-center gap-4 px-5 py-4"
                >
                  {/* Icon */}
                  <div className="w-9 h-9 rounded-lg bg-gradient-to-br from-violet-500/10 to-blue-500/10 flex items-center justify-center flex-shrink-0">
                    <Wrench size={16} className="text-violet-500" />
                  </div>

                  {/* Info */}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <p className="text-sm font-medium text-gray-900 dark:text-white">
                        {entry.name}
                      </p>
                      <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${CATEGORY_COLORS[category] || CATEGORY_COLORS.custom}`}>
                        {CATEGORY_LABELS[category] || category}
                      </span>
                      {entry.is_builtin && (
                        <span className="text-xs px-2 py-0.5 rounded-full bg-gray-100 dark:bg-gray-800 text-gray-500 font-medium">
                          Built-in
                        </span>
                      )}
                      {needsConfig && !isRegistered && (
                        <span className="text-xs px-2 py-0.5 rounded-full bg-amber-50 dark:bg-amber-900/20 text-amber-600 dark:text-amber-400 font-medium">
                          Needs setup
                        </span>
                      )}
                      {needsConfig && isRegistered && (
                        <span className="text-xs px-2 py-0.5 rounded-full bg-emerald-50 dark:bg-emerald-900/20 text-emerald-600 dark:text-emerald-400 font-medium">
                          Configured
                        </span>
                      )}
                    </div>
                    <p className="text-xs text-gray-500 mt-0.5 truncate">{entry.description}</p>
                  </div>

                  {/* Actions */}
                  <div className="flex items-center gap-2 flex-shrink-0">
                    {needsConfig && (
                      <button
                        onClick={() => openConfig(entry)}
                        className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-gray-200 dark:border-gray-700 text-xs text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors"
                      >
                        <Settings size={13} />
                        Configure
                      </button>
                    )}
                    <button
                      onClick={() => toggleMutation.mutate(entry.key)}
                      disabled={toggleMutation.isPending || (needsConfig && !isRegistered)}
                      title={needsConfig && !isRegistered ? 'Configure credentials first' : undefined}
                      className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors disabled:opacity-40 ${
                        isEnabled ? 'bg-violet-600' : 'bg-gray-200 dark:bg-gray-700'
                      }`}
                    >
                      <span
                        className={`inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform ${
                          isEnabled ? 'translate-x-6' : 'translate-x-1'
                        }`}
                      />
                    </button>
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      ))}

      {/* Config modal */}
      {configuring && (
        <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4">
          <div className="bg-white dark:bg-gray-900 rounded-2xl shadow-2xl w-full max-w-md">
            <div className="flex items-center justify-between px-6 py-5 border-b border-gray-100 dark:border-gray-800">
              <div>
                <h2 className="text-base font-semibold text-gray-900 dark:text-white">
                  Configure {configuring.name}
                </h2>
                <p className="text-xs text-gray-500 mt-0.5">
                  Credentials are stored securely and never exposed to end-users.
                </p>
              </div>
              <button
                onClick={() => setConfiguring(null)}
                className="p-1.5 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 text-gray-400"
              >
                <X size={16} />
              </button>
            </div>

            <div className="px-6 py-5 space-y-4">
              {configuring.credentials.map((cred) => (
                <div key={cred.field}>
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1.5">
                    {cred.label}
                  </label>
                  <div className="relative">
                    <input
                      type={cred.type === 'password' && !showSecrets[cred.field] ? 'password' : 'text'}
                      value={credentials[cred.field] || ''}
                      onChange={(e) =>
                        setCredentials((p) => ({ ...p, [cred.field]: e.target.value }))
                      }
                      placeholder={cred.type === 'password' ? '••••••••' : `Enter ${cred.label.toLowerCase()}`}
                      className="w-full px-3 py-2.5 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-sm text-gray-900 dark:text-white focus:outline-none focus:ring-1 focus:ring-violet-500 pr-10"
                    />
                    {cred.type === 'password' && (
                      <button
                        type="button"
                        onClick={() => setShowSecrets((p) => ({ ...p, [cred.field]: !p[cred.field] }))}
                        className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
                      >
                        {showSecrets[cred.field] ? <EyeOff size={14} /> : <Eye size={14} />}
                      </button>
                    )}
                  </div>
                </div>
              ))}
            </div>

            <div className="px-6 pb-5 flex justify-end gap-2">
              <button
                onClick={() => setConfiguring(null)}
                className="px-4 py-2 rounded-lg border border-gray-200 dark:border-gray-700 text-sm text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-800"
              >
                Cancel
              </button>
              <button
                onClick={handleSaveCredentials}
                disabled={saving}
                className="flex items-center gap-2 px-4 py-2 rounded-lg bg-violet-600 text-white text-sm font-medium hover:bg-violet-700 disabled:opacity-50 transition-colors"
              >
                {saving ? (
                  'Saving…'
                ) : (
                  <>
                    <Check size={14} />
                    Save credentials
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
