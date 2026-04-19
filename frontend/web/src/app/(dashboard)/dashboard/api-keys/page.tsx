'use client'

import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { apiKeysApi, agentsApi } from '@/lib/api'
import toast from 'react-hot-toast'
import { Key, Plus, Trash2, Copy, Eye, EyeOff, Lock } from 'lucide-react'

export default function ApiKeysPage() {
  const qc = useQueryClient()
  const [newKeyName, setNewKeyName] = useState('')
  const [selectedAgentId, setSelectedAgentId] = useState<string>('')
  const [selectedScopes, setSelectedScopes] = useState<string[]>(['chat', 'agents:read'])
  const [expiration, setExpiration] = useState<string>('never')
  const [createdKey, setCreatedKey] = useState<string | null>(null)
  const [showCreated, setShowCreated] = useState(true)

  const { data: keys, isLoading } = useQuery({
    queryKey: ['api-keys'],
    queryFn: apiKeysApi.list,
  })

  const { data: agents } = useQuery({
    queryKey: ['agents'],
    queryFn: () => agentsApi.list(),
  })

  const createMutation = useMutation({
    mutationFn: (payload: { 
      name: string; 
      agent_id?: string; 
      scopes: string[]; 
      expires_at?: string 
    }) => apiKeysApi.create(payload),
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ['api-keys'] })
      setCreatedKey(data.raw_key)
      setNewKeyName('')
      setSelectedAgentId('')
      setSelectedScopes(['chat', 'agents:read'])
      setExpiration('never')
      toast.success('API key created!')
    },
    onError: () => toast.error('Failed to create key'),
  })

  const agentName = (agentId: string) =>
    (agents as any[])?.find((a: any) => a.id === agentId)?.name ?? agentId

  const ALL_SCOPE_OPTIONS = [
    { id: 'chat', label: 'Chat & Interactive', description: 'Interact with agents via widgets or API' },
    { id: 'agents:read', label: 'View Agents', description: 'Read agent configuration and state' },
    { id: 'agents:write', label: 'Modify Agents', description: 'Create and update agents' },
    { id: 'analytics', label: 'Analytics', description: 'Access usage and performance data' },
    { id: 'admin', label: 'Full Admin', description: 'Unrestricted access (Owner/Admin roles only)' },
  ]

  const EXPIRATION_OPTIONS = [
    { value: 'never', label: 'Never' },
    { value: '7d', label: '7 days' },
    { value: '30d', label: '30 days' },
    { value: '90d', label: '90 days' },
  ]

  const getExpirationDate = (opt: string) => {
    if (opt === 'never') return undefined
    const days = parseInt(opt)
    const date = new Date()
    date.setDate(date.getDate() + days)
    return date.toISOString()
  }

  const toggleScope = (id: string) => {
    setSelectedScopes(prev => 
      prev.includes(id) ? prev.filter(s => s !== id) : [...prev, id]
    )
  }

  const revokeMutation = useMutation({
    mutationFn: (id: string) => apiKeysApi.revoke(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['api-keys'] })
      toast.success('Key revoked')
    },
  })

  return (
    <div className="p-8 w-full max-w-5xl mx-auto">
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-gray-900 dark:text-white">API Keys</h1>
        <p className="text-gray-500 dark:text-gray-400 mt-1">
          Create and manage API keys for programmatic access.
        </p>
      </div>

      {/* Create new key */}
      <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 overflow-hidden mb-8 shadow-sm">
        <div className="p-5 border-b border-gray-100 dark:border-gray-800">
          <h2 className="text-sm font-semibold text-gray-900 dark:text-white">
            Create new API key
          </h2>
        </div>
        <div className="p-5 space-y-6">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <div className="space-y-4">
              <div>
                <label className="block text-xs font-medium text-gray-500 dark:text-gray-400 mb-1.5 uppercase tracking-wider">
                  Key Name
                </label>
                <input
                  value={newKeyName}
                  onChange={(e) => setNewKeyName(e.target.value)}
                  placeholder="e.g. Production Mobile App"
                  className="w-full px-3 py-2.5 rounded-lg text-sm border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-violet-500/20 focus:border-violet-500 transition-all"
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-gray-500 dark:text-gray-400 mb-1.5 uppercase tracking-wider">
                  Agent Restriction
                </label>
                <select
                  value={selectedAgentId}
                  onChange={(e) => setSelectedAgentId(e.target.value)}
                  className="w-full px-3 py-2.5 rounded-lg text-sm border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-violet-500/20 focus:border-violet-500 transition-all"
                >
                  <option value="">All agents (unrestricted)</option>
                  {(agents as any[])?.map((agent: any) => (
                    <option key={agent.id} value={agent.id}>
                      {agent.name}
                    </option>
                  ))}
                </select>
                {selectedAgentId && (
                  <p className="mt-1.5 text-xs text-amber-600 dark:text-amber-400 flex items-center gap-1 font-medium">
                    <Lock size={12} /> Restricted to &quot;{agentName(selectedAgentId)}&quot;
                  </p>
                )}
              </div>

              <div>
                <label className="block text-xs font-medium text-gray-500 dark:text-gray-400 mb-1.5 uppercase tracking-wider">
                  Expiration
                </label>
                <select
                  value={expiration}
                  onChange={(e) => setExpiration(e.target.value)}
                  className="w-full px-3 py-2.5 rounded-lg text-sm border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-violet-500/20 focus:border-violet-500 transition-all"
                >
                  {EXPIRATION_OPTIONS.map(opt => (
                    <option key={opt.value} value={opt.value}>{opt.label}</option>
                  ))}
                </select>
              </div>
            </div>

            <div className="space-y-4">
              <label className="block text-xs font-medium text-gray-500 dark:text-gray-400 mb-1.5 uppercase tracking-wider">
                Permissions (Scopes)
              </label>
              <div className="space-y-2 max-h-[220px] overflow-y-auto pr-2 custom-scrollbar">
                {ALL_SCOPE_OPTIONS.map(scope => (
                  <div 
                    key={scope.id}
                    onClick={() => toggleScope(scope.id)}
                    className={`flex items-start gap-3 p-2.5 rounded-lg border cursor-pointer transition-all ${
                      selectedScopes.includes(scope.id)
                        ? 'bg-violet-50 dark:bg-violet-900/10 border-violet-200 dark:border-violet-700'
                        : 'bg-white dark:bg-gray-800/50 border-gray-100 dark:border-gray-800 hover:border-gray-200 dark:hover:border-gray-700'
                    }`}
                  >
                    <input 
                      type="checkbox"
                      checked={selectedScopes.includes(scope.id)}
                      onChange={() => {}}
                      className="mt-1 h-4 w-4 text-violet-600 focus:ring-violet-500 border-gray-300 rounded"
                    />
                    <div>
                      <p className="text-xs font-semibold text-gray-900 dark:text-white">{scope.label}</p>
                      <p className="text-[10px] text-gray-500 dark:text-gray-400 leading-tight mt-0.5">{scope.description}</p>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>

          <div className="flex items-center justify-between pt-4 border-t border-gray-100 dark:border-gray-800">
            <p className="text-xs text-gray-500">
              Only {selectedScopes.length} permission(s) selected
            </p>
            <button
              onClick={() => {
                if (!newKeyName.trim() || selectedScopes.length === 0) return
                createMutation.mutate({
                  name: newKeyName.trim(),
                  scopes: selectedScopes,
                  expires_at: getExpirationDate(expiration),
                  ...(selectedAgentId ? { agent_id: selectedAgentId } : {}),
                })
              }}
              disabled={!newKeyName.trim() || selectedScopes.length === 0 || createMutation.isPending}
              className="inline-flex items-center gap-2 px-6 py-2.5 rounded-lg bg-violet-600 text-white text-sm font-semibold hover:bg-violet-700 disabled:opacity-50 shadow-sm shadow-violet-200 dark:shadow-none transition-all"
            >
              {createMutation.isPending ? 'Creating...' : (
                <><Plus size={16} /> Create API Key</>
              )}
            </button>
          </div>
        </div>
      </div>

      {/* Newly created key — show once */}
      {createdKey && (
        <div className="bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800 rounded-xl p-4 mb-6">
          <p className="text-sm font-medium text-green-800 dark:text-green-300 mb-2">
            ✓ Copy this key now — it won&apos;t be shown again.
          </p>
          <div className="flex items-center gap-2">
            <code className="flex-1 text-xs font-mono bg-white dark:bg-gray-900 p-2.5 rounded-lg border border-green-200 dark:border-green-700 text-gray-900 dark:text-white break-all">
              {showCreated ? createdKey : '•'.repeat(40)}
            </code>
            <button
              onClick={() => setShowCreated(!showCreated)}
              className="p-2 text-gray-400 hover:text-gray-600"
            >
              {showCreated ? <EyeOff size={16} /> : <Eye size={16} />}
            </button>
            <button
              onClick={() => {
                navigator.clipboard.writeText(createdKey)
                toast.success('Copied!')
              }}
              className="p-2 text-gray-400 hover:text-violet-600"
            >
              <Copy size={16} />
            </button>
          </div>
        </div>
      )}

      {/* Key list */}
      {isLoading ? (
        <div className="space-y-2">
          {[1, 2].map((i) => (
            <div key={i} className="h-16 rounded-xl bg-gray-100 dark:bg-gray-800 animate-pulse" />
          ))}
        </div>
      ) : keys?.length === 0 && !createdKey ? (
        <div className="text-center py-12 text-gray-400">
          <Key size={32} className="mx-auto mb-2" />
          <p>No API keys yet</p>
        </div>
      ) : (
        <div className="space-y-2">
          {keys?.map((key: any) => (
            <div
              key={key.id}
              className="flex items-center justify-between bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 px-4 py-3"
            >
              <div className="flex items-center gap-3">
                <Key size={16} className="text-gray-400" />
                <div>
                  <div className="flex items-center gap-2">
                    <p className="text-sm font-medium text-gray-900 dark:text-white">{key.name}</p>
                    {key.agent_id && (
                      <span className="inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded bg-violet-100 dark:bg-violet-900/30 text-violet-700 dark:text-violet-300 font-medium">
                        <Lock size={10} /> {agentName(key.agent_id)}
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-3 mt-1">
                    <p className="text-xs text-gray-500 font-mono">{key.key_prefix}…</p>
                    <div className="flex gap-1.5">
                      {key.scopes?.slice(0, 3).map((s: string) => (
                        <span key={s} className="text-[9px] text-gray-400 dark:text-gray-500 border border-gray-100 dark:border-gray-800 px-1 rounded uppercase">
                          {s.replace(':', ' ')}
                        </span>
                      ))}
                      {key.scopes?.length > 3 && (
                        <span className="text-[9px] text-gray-400 dark:text-gray-500">+{key.scopes.length - 3}</span>
                      )}
                    </div>
                  </div>
                </div>
              </div>
              <div className="flex items-center gap-6">
                <div className="text-right hidden sm:block">
                  <p className="text-[10px] text-gray-400 uppercase tracking-wider font-semibold">Expires</p>
                  <p className="text-xs text-gray-600 dark:text-gray-400">
                    {key.expires_at ? new Date(key.expires_at).toLocaleDateString() : 'Never'}
                  </p>
                </div>
                <button
                  onClick={() => confirm('Revoke this key?') && revokeMutation.mutate(key.id)}
                  className="p-2 text-gray-400 hover:text-red-500 transition-colors"
                >
                  <Trash2 size={15} />
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
