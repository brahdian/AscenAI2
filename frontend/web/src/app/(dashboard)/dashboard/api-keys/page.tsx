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
  const [createdKey, setCreatedKey] = useState<string | null>(null)
  const [showCreated, setShowCreated] = useState(true)

  const { data: keys, isLoading } = useQuery({
    queryKey: ['api-keys'],
    queryFn: apiKeysApi.list,
  })

  const { data: agents } = useQuery({
    queryKey: ['agents'],
    queryFn: agentsApi.list,
  })

  const createMutation = useMutation({
    mutationFn: (payload: { name: string; agent_id?: string }) => apiKeysApi.create(payload),
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ['api-keys'] })
      setCreatedKey(data.raw_key)
      setNewKeyName('')
      setSelectedAgentId('')
      toast.success('API key created!')
    },
    onError: () => toast.error('Failed to create key'),
  })

  const revokeMutation = useMutation({
    mutationFn: (id: string) => apiKeysApi.revoke(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['api-keys'] })
      toast.success('Key revoked')
    },
  })

  const agentName = (agentId: string) =>
    (agents as any[])?.find((a: any) => a.id === agentId)?.name ?? agentId

  return (
    <div className="p-8 max-w-3xl">
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-gray-900 dark:text-white">API Keys</h1>
        <p className="text-gray-500 dark:text-gray-400 mt-1">
          Create and manage API keys. Optionally scope a key to a single agent.
        </p>
      </div>

      {/* Create new key */}
      <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 p-5 mb-6">
        <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-3">
          Create new API key
        </h2>
        <div className="space-y-3">
          <div className="flex gap-2">
            <input
              value={newKeyName}
              onChange={(e) => setNewKeyName(e.target.value)}
              placeholder="Key name e.g. Production"
              className="flex-1 px-3 py-2.5 rounded-lg text-sm border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white focus:outline-none focus:ring-1 focus:ring-violet-500"
            />
          </div>
          <div className="flex gap-2 items-center">
            <select
              value={selectedAgentId}
              onChange={(e) => setSelectedAgentId(e.target.value)}
              className="flex-1 px-3 py-2.5 rounded-lg text-sm border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white focus:outline-none focus:ring-1 focus:ring-violet-500"
            >
              <option value="">All agents (unrestricted)</option>
              {(agents as any[])?.map((agent: any) => (
                <option key={agent.id} value={agent.id}>
                  {agent.name}
                </option>
              ))}
            </select>
            <button
              onClick={() => {
                if (!newKeyName.trim()) return
                createMutation.mutate({
                  name: newKeyName.trim(),
                  ...(selectedAgentId ? { agent_id: selectedAgentId } : {}),
                })
              }}
              disabled={!newKeyName.trim() || createMutation.isPending}
              className="inline-flex items-center gap-2 px-4 py-2.5 rounded-lg bg-violet-600 text-white text-sm font-medium hover:bg-violet-700 disabled:opacity-50 transition-colors whitespace-nowrap"
            >
              <Plus size={16} /> Create
            </button>
          </div>
          {selectedAgentId && (
            <p className="text-xs text-amber-600 dark:text-amber-400 flex items-center gap-1">
              <Lock size={12} /> This key will only work for agent &quot;{agentName(selectedAgentId)}&quot;
            </p>
          )}
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
                      <span className="inline-flex items-center gap-1 text-xs px-1.5 py-0.5 rounded bg-violet-100 dark:bg-violet-900/30 text-violet-700 dark:text-violet-300">
                        <Lock size={10} /> {agentName(key.agent_id)}
                      </span>
                    )}
                  </div>
                  <p className="text-xs text-gray-500 font-mono">{key.key_prefix}…</p>
                </div>
              </div>
              <button
                onClick={() => confirm('Revoke this key?') && revokeMutation.mutate(key.id)}
                className="p-2 text-gray-400 hover:text-red-500 transition-colors"
              >
                <Trash2 size={15} />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
