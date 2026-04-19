'use client'

import { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useSearchParams, useRouter } from 'next/navigation'
import { agentsApi, billingApi } from '@/lib/api'
import Link from 'next/link'
import toast from 'react-hot-toast'
import {
  Bot, Plus, Trash2, Edit2, Mic, MicOff, TestTube, BookOpen, Shield,
  ToggleLeft, ToggleRight, ArchiveIcon, RefreshCw, Layers, AlertTriangle
} from 'lucide-react'

// ── Swap Modal ───────────────────────────────────────────────────────────────
interface SwapModalProps {
  targetAgent: any
  activeAgents: Array<{ id: string; name: string }>
  onConfirm: (archiveAgentId: string) => void
  onCancel: () => void
  isPending: boolean
}

function SwapModal({ targetAgent, activeAgents, onConfirm, onCancel, isPending }: SwapModalProps) {
  const [selected, setSelected] = useState<string>(activeAgents[0]?.id ?? '')

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
      <div className="bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-700 shadow-2xl w-full max-w-md mx-4 p-6">
        <div className="flex items-center gap-3 mb-4">
          <div className="w-10 h-10 rounded-xl bg-amber-100 dark:bg-amber-900/30 flex items-center justify-center">
            <AlertTriangle size={20} className="text-amber-600 dark:text-amber-400" />
          </div>
          <div>
            <h2 className="text-base font-bold text-gray-900 dark:text-white">All Slots In Use</h2>
            <p className="text-xs text-gray-500 dark:text-gray-400">Archive an agent to free a slot</p>
          </div>
        </div>

        <p className="text-sm text-gray-600 dark:text-gray-300 mb-4">
          You want to activate <strong className="text-gray-900 dark:text-white">{targetAgent.name}</strong>, but all your
          slots are occupied. Select an active agent to archive (it will keep all its configuration and
          can be reactivated later).
        </p>

        <div className="space-y-2 mb-6">
          {activeAgents.map((a) => (
            <label
              key={a.id}
              className={`flex items-center gap-3 p-3 rounded-xl border cursor-pointer transition-all ${
                selected === a.id
                  ? 'border-violet-500 bg-violet-50 dark:bg-violet-900/20'
                  : 'border-gray-200 dark:border-gray-700 hover:border-violet-300'
              }`}
            >
              <input
                type="radio"
                name="archiveAgent"
                value={a.id}
                checked={selected === a.id}
                onChange={() => setSelected(a.id)}
                className="accent-violet-600"
              />
              <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-violet-500/20 to-blue-500/20 flex items-center justify-center">
                <Bot size={14} className="text-violet-600" />
              </div>
              <span className="text-sm font-medium text-gray-900 dark:text-white">{a.name}</span>
            </label>
          ))}
        </div>

        <div className="flex gap-3">
          <button
            onClick={onCancel}
            className="flex-1 px-4 py-2.5 rounded-xl border border-gray-200 dark:border-gray-700 text-sm text-gray-600 dark:text-gray-300 font-medium hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={() => selected && onConfirm(selected)}
            disabled={!selected || isPending}
            className="flex-1 px-4 py-2.5 rounded-xl bg-gradient-to-r from-violet-600 to-blue-600 text-white text-sm font-bold hover:opacity-90 disabled:opacity-50 transition-all"
          >
            {isPending ? 'Swapping…' : 'Archive & Activate'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Main Page ────────────────────────────────────────────────────────────────
export default function AgentsPage() {
  const qc = useQueryClient()
  const searchParams = useSearchParams()
  const router = useRouter()

  const [testingId, setTestingId] = useState<string | null>(null)
  const [testMsg, setTestMsg] = useState('')
  const [testResult, setTestResult] = useState<string | null>(null)
  const [showAll, setShowAll] = useState(false)

  // Swap modal state
  const [swapModal, setSwapModal] = useState<{ targetAgent: any; activeAgents: Array<{ id: string; name: string }> } | null>(null)

  // Handle Stripe return after reactivation checkout
  useEffect(() => {
    if (searchParams.get('reactivated') === 'true') {
      toast.success('Agent reactivated — your subscription is now active!')
      qc.invalidateQueries({ queryKey: ['agents'] })
      router.replace('/dashboard/agents')
    }
  }, [searchParams, qc, router])

  const { data: agents, isLoading } = useQuery({
    queryKey: ['agents', showAll],
    queryFn: () => agentsApi.list({ status: showAll ? 'all' : 'active' }),
    staleTime: 30000,
  })

  // Slot capacity derived from agent list + billing info
  const { data: billingInfo } = useQuery({
    queryKey: ['billing-info'],
    queryFn: () => billingApi.getInfo(),
    staleTime: 60000,
  })

  const activeCount = (agents ?? []).filter((a: any) => a.status === 'ACTIVE').length
  const totalSlots: number = billingInfo?.agent_slots ?? billingInfo?.purchased_slots ?? 0

  // ── Mutations ──────────────────────────────────────────────────────────────

  const deleteMutation = useMutation({
    mutationFn: (id: string) => agentsApi.delete(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['agents'] })
      toast.success('Agent removed from directory')
    },
    onError: (err: any) => {
      const detail = err?.response?.data?.detail
      if (err?.response?.status === 403 && typeof detail === 'string') {
        toast.error(detail, { duration: 6000 })
      } else {
        toast.error('Failed to remove agent')
      }
    },
  })

  // Archive an agent (free its slot)
  const archiveMutation = useMutation({
    mutationFn: (id: string) => agentsApi.slotArchive(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['agents'] })
      toast.success('Agent archived — slot freed')
    },
    onError: () => toast.error('Failed to archive agent'),
  })

  // Activate/revive an agent (requires free slot)
  const activateMutation = useMutation({
    mutationFn: async (agent: any) => {
      try {
        return await agentsApi.slotActivate(agent.id)
      } catch (err: any) {
        if (err?.response?.status === 409) {
          const detail = err.response.data?.detail ?? {}
          return { _atCapacity: true, activeAgents: detail.active_agents ?? [], agent }
        }
        throw err
      }
    },
    onSuccess: (data: any, agent: any) => {
      if (data?._atCapacity) {
        // Show swap modal
        setSwapModal({ targetAgent: data.agent, activeAgents: data.activeAgents })
        return
      }
      qc.invalidateQueries({ queryKey: ['agents'] })
      toast.success(`${agent.name} is now active`)
    },
    onError: () => toast.error('Failed to activate agent'),
  })

  // Swap: atomic archive and activate
  const swapMutation = useMutation({
    mutationFn: async ({ archiveId, activateId }: { archiveId: string; activateId: string }) => {
      return agentsApi.slotSwap(archiveId, activateId)
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['agents'] })
      setSwapModal(null)
      toast.success('Agent swapped successfully')
    },
    onError: () => toast.error('Swap failed — please try again'),
  })

  const testMutation = useMutation({
    mutationFn: ({ id, message }: { id: string; message: string }) => agentsApi.test(id, message),
    onSuccess: (data) => setTestResult(data.message),
    onError: (err: any) => toast.error(err?.response?.data?.detail || 'Test failed'),
  })

  const handleDelete = (agent: any) => {
    toast((t) => (
      <div className="flex items-center gap-3">
        <span className="text-sm">Delete <b>{agent.name}</b>?</span>
        <button
          onClick={() => { deleteMutation.mutate(agent.id); toast.dismiss(t.id) }}
          className="px-3 py-1 bg-red-600 text-white text-xs font-bold rounded hover:bg-red-700 transition-colors"
        >CONFIRM</button>
        <button
          onClick={() => toast.dismiss(t.id)}
          className="px-3 py-1 bg-gray-200 dark:bg-gray-800 text-gray-600 dark:text-gray-400 text-xs font-bold rounded hover:bg-gray-300 dark:hover:bg-gray-700 transition-colors"
        >CANCEL</button>
      </div>
    ), { duration: 5000, position: 'top-center' })
  }

  const handleSyncStatus = async () => {
    const loading = toast.loading('Running deep sync with Stripe…')
    try {
      const result = await billingApi.syncSubscription()
      qc.invalidateQueries({ queryKey: ['agents'] })
      if (result?.status === 'no_customer') {
        toast.error('No Stripe account linked. Please make a payment first.', { id: loading })
      } else if (result?.status === 'no_active_subscription') {
        toast.error('No active subscriptions found in Stripe.', { id: loading })
      } else if (result?.agents_activated > 0) {
        toast.success(
          `Synced! ${result.agents_activated} agent${result.agents_activated !== 1 ? 's' : ''} activated.`,
          { id: loading }
        )
      } else {
        toast.success('All agent statuses are up to date.', { id: loading })
      }
    } catch {
      toast.error('Failed to sync agent status', { id: loading })
    }
  }

  const getStatusBadge = (agent: any) => {
    const s = agent.status
    if (s === 'ACTIVE') {
      return (
        <span className="px-2 py-0.5 rounded-full bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400 text-[10px] font-bold uppercase tracking-wider border border-green-200 dark:border-green-800">
          Active
        </span>
      )
    }
    if (s === 'ARCHIVED') {
      return (
        <span className="px-2 py-0.5 rounded-full bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-400 text-[10px] font-bold uppercase tracking-wider border border-gray-200 dark:border-gray-700">
          Archived
        </span>
      )
    }
    if (s === 'PENDING_PAYMENT') {
      return (
        <span className="px-2 py-0.5 rounded-full bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-400 text-[10px] font-bold uppercase tracking-wider border border-amber-200 dark:border-amber-800">
          Payment Required
        </span>
      )
    }
    if (s === 'DRAFT') {
      return (
        <span className="px-2 py-0.5 rounded-full bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-400 text-[10px] font-bold uppercase tracking-wider border border-blue-200 dark:border-blue-800">
          Draft
        </span>
      )
    }
    return null
  }

  return (
    <>
      {/* Swap Modal */}
      {swapModal && (
        <SwapModal
          targetAgent={swapModal.targetAgent}
          activeAgents={swapModal.activeAgents}
          isPending={swapMutation.isPending}
          onCancel={() => setSwapModal(null)}
          onConfirm={(archiveId) =>
            swapMutation.mutate({ archiveId, activateId: swapModal.targetAgent.id })
          }
        />
      )}

      <div className="p-8">
        {/* ── Header ── */}
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Agents</h1>
            <p className="text-gray-500 dark:text-gray-400 mt-1">
              Manage your AI agents and their configurations.
            </p>
          </div>
          <div className="flex items-center gap-3">
            {/* View toggle */}
            <div className="flex items-center gap-1 bg-gray-100 dark:bg-gray-800 p-1 rounded-lg border border-gray-200 dark:border-gray-700">
              <button
                onClick={() => setShowAll(false)}
                className={`px-3 py-1 rounded-md text-xs font-bold transition-all ${!showAll ? 'bg-white dark:bg-gray-700 text-gray-900 dark:text-white shadow-sm ring-1 ring-gray-200 dark:ring-gray-600' : 'text-gray-400 hover:text-gray-900'}`}
              >Active</button>
              <button
                onClick={() => setShowAll(true)}
                className={`px-3 py-1 rounded-md text-xs font-bold transition-all ${showAll ? 'bg-white dark:bg-gray-700 text-gray-900 dark:text-white shadow-sm ring-1 ring-gray-200 dark:ring-gray-600' : 'text-gray-400 hover:text-gray-900'}`}
              >All</button>
            </div>

            {/* Deep sync */}
            <button
              onClick={handleSyncStatus}
              className="inline-flex items-center gap-2 px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-700 text-gray-700 dark:text-gray-300 text-sm font-medium hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors"
            >
              <RefreshCw size={14} />
              Sync Status
            </button>

            {/* New agent */}
            <Link
              href="/dashboard/agents/new"
              className="inline-flex items-center gap-2 px-4 py-2.5 rounded-lg bg-gradient-to-r from-violet-600 to-blue-600 text-white text-sm font-medium hover:opacity-90 transition-opacity"
            >
              <Plus size={16} />
              New Agent
            </Link>
          </div>
        </div>

        {/* ── Slot Capacity Indicator ── */}
        {totalSlots > 0 && (
          <div className="mb-6 flex items-center gap-4 p-4 bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800">
            <div className="w-9 h-9 rounded-lg bg-gradient-to-br from-violet-500/20 to-blue-500/20 flex items-center justify-center">
              <Layers size={18} className="text-violet-600 dark:text-violet-400" />
            </div>
            <div className="flex-1">
              <p className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider">Agent Slots</p>
              <div className="flex items-center gap-3 mt-1">
                <div className="flex-1 bg-gray-100 dark:bg-gray-800 rounded-full h-2">
                  <div
                    className={`h-2 rounded-full transition-all ${activeCount >= totalSlots ? 'bg-amber-500' : 'bg-gradient-to-r from-violet-500 to-blue-500'}`}
                    style={{ width: `${Math.min(100, (activeCount / totalSlots) * 100)}%` }}
                  />
                </div>
                <span className="text-xs font-bold text-gray-900 dark:text-white whitespace-nowrap">
                  {activeCount} / {totalSlots} used
                </span>
              </div>
            </div>
            {activeCount >= totalSlots && (
              <span className="text-xs text-amber-600 dark:text-amber-400 font-bold bg-amber-50 dark:bg-amber-900/20 px-2 py-1 rounded-lg border border-amber-200 dark:border-amber-800">
                At Capacity
              </span>
            )}
          </div>
        )}

        {/* ── Agent List ── */}
        {isLoading ? (
          <div className="space-y-3">
            {[1, 2, 3].map((i) => (
              <div key={i} className="h-24 rounded-xl bg-gray-100 dark:bg-gray-800 animate-pulse" />
            ))}
          </div>
        ) : agents?.length === 0 ? (
          <div className="text-center py-16 bg-white dark:bg-gray-900 rounded-xl border border-dashed border-gray-200 dark:border-gray-700">
            <Bot size={40} className="mx-auto text-gray-300 dark:text-gray-600 mb-3" />
            <h3 className="text-gray-900 dark:text-white font-medium">No agents yet</h3>
            <p className="text-gray-500 text-sm mt-1 mb-6">Create your first AI agent to get started.</p>
            <Link
              href="/dashboard/agents/new"
              className="inline-flex items-center gap-2 px-4 py-2.5 rounded-lg bg-violet-600 text-white text-sm font-medium hover:bg-violet-700 transition-colors"
            >
              <Plus size={16} /> Create agent
            </Link>
          </div>
        ) : (
          <div className="space-y-3">
            {agents?.map((agent: any) => (
              <div
                key={agent.id}
                className={`bg-white dark:bg-gray-900 rounded-xl border p-5 transition-all ${
                  agent.status === 'ACTIVE'
                    ? 'border-gray-200 dark:border-gray-800'
                    : 'border-gray-100 dark:border-gray-800/50 opacity-75'
                }`}
              >
                <div className="flex items-start justify-between">
                  <div className="flex items-center gap-3">
                    <div className={`w-10 h-10 rounded-lg flex items-center justify-center ${
                      agent.status === 'ACTIVE'
                        ? 'bg-gradient-to-br from-violet-500/20 to-blue-500/20'
                        : 'bg-gray-100 dark:bg-gray-800'
                    }`}>
                      <Bot size={20} className={agent.status === 'ACTIVE' ? 'text-violet-600 dark:text-violet-400' : 'text-gray-400'} />
                    </div>
                    <div>
                      <div className="flex items-center gap-2">
                        <h3 className={`font-semibold ${agent.status === 'ACTIVE' ? 'text-gray-900 dark:text-white' : 'text-gray-500 dark:text-gray-400'}`}>
                          {agent.name}
                        </h3>
                        {getStatusBadge(agent)}
                      </div>
                      <p className="text-xs mt-0.5 text-gray-500">
                        {agent.business_type} • {agent.language}
                        {agent.voice_enabled ? (
                          <span className="ml-2 inline-flex items-center gap-1 text-green-600">
                            <Mic size={10} /> Voice
                          </span>
                        ) : (
                          <span className="ml-2 inline-flex items-center gap-1 text-gray-400">
                            <MicOff size={10} /> Text only
                          </span>
                        )}
                      </p>
                    </div>
                  </div>

                  {/* Right-side actions */}
                  <div className="flex items-center gap-1">
                    {/* Activate / Archive toggle */}
                    {agent.status !== 'PENDING_PAYMENT' && (
                      <>
                        {agent.status === 'ACTIVE' ? (
                          <button
                            onClick={() => {
                              toast((t) => (
                                <div className="flex items-center gap-3">
                                  <span className="text-sm">Archive <b>{agent.name}</b>?</span>
                                  <button
                                    onClick={() => { archiveMutation.mutate(agent.id); toast.dismiss(t.id) }}
                                    className="px-3 py-1 bg-amber-600 text-white text-xs font-bold rounded"
                                  >Archive</button>
                                  <button onClick={() => toast.dismiss(t.id)} className="px-3 py-1 bg-gray-200 text-gray-600 text-xs font-bold rounded">Cancel</button>
                                </div>
                              ), { duration: 6000, position: 'top-center' })
                            }}
                            title="Archive agent (frees slot)"
                            className="p-2 text-green-500 hover:text-amber-500 transition-colors"
                          >
                            <ToggleRight size={20} />
                          </button>
                        ) : agent.status === 'ARCHIVED' || agent.status === 'DRAFT' ? (
                          <button
                            onClick={() => activateMutation.mutate(agent)}
                            disabled={activateMutation.isPending}
                            title="Activate agent (uses a slot)"
                            className="p-2 text-gray-400 hover:text-green-500 transition-colors disabled:opacity-40"
                          >
                            <ToggleLeft size={20} />
                          </button>
                        ) : null}
                      </>
                    )}

                    {agent.status === 'ACTIVE' && (
                      <>
                        <button
                          onClick={() => {
                            setTestingId(testingId === agent.id ? null : agent.id)
                            setTestResult(null)
                            setTestMsg('')
                          }}
                          className="p-2 text-gray-400 hover:text-violet-600 transition-colors"
                          title="Test agent"
                        >
                          <TestTube size={16} />
                        </button>
                        <Link href={`/dashboard/agents/${agent.id}/playbooks`} className="p-2 text-gray-400 hover:text-violet-600 transition-colors" title="Edit Playbook">
                          <BookOpen size={16} />
                        </Link>
                        <Link href={`/dashboard/agents/${agent.id}/guardrails`} className="p-2 text-gray-400 hover:text-orange-500 transition-colors" title="Edit Guardrails">
                          <Shield size={16} />
                        </Link>
                        <Link href={`/dashboard/agents/${agent.id}`} className="p-2 text-gray-400 hover:text-blue-600 transition-colors" title="Edit agent">
                          <Edit2 size={16} />
                        </Link>
                      </>
                    )}

                    {agent.status === 'ARCHIVED' && (
                      <Link href={`/dashboard/agents/${agent.id}`} className="p-2 text-gray-400 hover:text-blue-600 transition-colors" title="Edit agent">
                        <Edit2 size={16} />
                      </Link>
                    )}

                    <button
                      onClick={() => handleDelete(agent)}
                      className="p-2 text-gray-400 hover:text-red-500 transition-colors"
                      title="Delete agent"
                    >
                      <Trash2 size={16} />
                    </button>
                  </div>
                </div>

                {/* Test panel */}
                {testingId === agent.id && (
                  <div className="mt-4 pt-4 border-t border-gray-100 dark:border-gray-800">
                    <div className="flex gap-2">
                      <input
                        value={testMsg}
                        onChange={(e) => setTestMsg(e.target.value)}
                        placeholder="Send a test message…"
                        className="flex-1 px-3 py-2 rounded-lg text-sm bg-gray-50 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 text-gray-900 dark:text-white focus:outline-none focus:ring-1 focus:ring-violet-500"
                        onKeyDown={(e) => {
                          if (e.key === 'Enter' && testMsg.trim()) {
                            testMutation.mutate({ id: agent.id, message: testMsg })
                          }
                        }}
                      />
                      <button
                        onClick={() => testMsg.trim() && testMutation.mutate({ id: agent.id, message: testMsg })}
                        disabled={testMutation.isPending}
                        className="px-3 py-2 rounded-lg bg-violet-600 text-white text-sm font-medium hover:bg-violet-700 disabled:opacity-50"
                      >
                        {testMutation.isPending ? '…' : 'Send'}
                      </button>
                    </div>
                    {testResult && (
                      <div className="mt-3 p-3 rounded-lg bg-gray-50 dark:bg-gray-800 text-sm text-gray-700 dark:text-gray-300">
                        <strong className="text-violet-600 dark:text-violet-400">Agent:</strong>{' '}
                        {testResult}
                      </div>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </>
  )
}
