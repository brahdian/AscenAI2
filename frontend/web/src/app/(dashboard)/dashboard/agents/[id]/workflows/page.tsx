'use client'

import { useState } from 'react'
import { useParams, useRouter } from 'next/navigation'
import Link from 'next/link'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { workflowsApi, agentsApi } from '@/lib/api'
import toast from 'react-hot-toast'
import {
  ChevronLeft,
  Plus,
  Zap,
  Trash2,
  Copy,
  Play,
  Pause,
  Clock,
  Webhook,
  Radio,
  GitBranch,
  Loader2,
  MoreHorizontal,
  CheckCircle2,
  XCircle,
  AlertCircle,
  Calendar,
  RefreshCw,
} from 'lucide-react'

// ─── Types ───────────────────────────────────────────────────────────────────

interface Flow {
  id: string
  name: string
  description: string
  is_active: boolean
  is_archived: boolean
  trigger_type: 'none' | 'cron' | 'webhook' | 'event'
  trigger_config: Record<string, unknown>
  tags: string[]
  version: number
  created_at: string
  updated_at: string
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

const TRIGGER_ICONS: Record<string, React.ElementType> = {
  none: GitBranch,
  cron: Clock,
  webhook: Webhook,
  event: Radio,
}

const TRIGGER_LABELS: Record<string, string> = {
  none: 'Manual / LLM',
  cron: 'Scheduled',
  webhook: 'Webhook',
  event: 'Event',
}

const TRIGGER_COLORS: Record<string, string> = {
  none: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400',
  cron: 'bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300',
  webhook: 'bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300',
  event: 'bg-violet-100 text-violet-700 dark:bg-violet-900/40 dark:text-violet-300',
}

function formatDate(iso: string) {
  return new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
}

// ─── Create Flow Modal ────────────────────────────────────────────────────────

function CreateFlowModal({
  agentId,
  onClose,
  onCreated,
}: {
  agentId: string
  onClose: () => void
  onCreated: (flow: Flow) => void
}) {
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [triggerType, setTriggerType] = useState<'none' | 'cron' | 'webhook' | 'event'>('none')

  const mutation = useMutation({
    mutationFn: (data: Record<string, unknown>) => workflowsApi.create(agentId, data),
    onSuccess: (flow) => {
      toast.success('Workflow created')
      onCreated(flow)
    },
    onError: (e: any) => {
      toast.error(e?.response?.data?.detail || 'Failed to create workflow')
    },
  })

  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!name.trim()) return
    mutation.mutate({
      name: name.trim(),
      description: description.trim(),
      trigger_type: triggerType,
      trigger_config: {},
      definition: {
        nodes: [{ id: 'end_1', type: 'END', label: 'End', config: { final_message: 'Done.' } }],
        edges: [],
        entry_node_id: 'end_1',
        variables: {},
      },
      input_schema: {},
      output_schema: {},
      tags: [],
    })
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
      <div className="w-full max-w-md bg-white dark:bg-gray-900 rounded-2xl shadow-2xl p-6">
        <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">New Workflow</h2>
        <form onSubmit={submit} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Name</label>
            <input
              autoFocus
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Appointment reminder"
              className="w-full px-3 py-2 rounded-xl border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 text-sm focus:outline-none focus:ring-2 focus:ring-violet-500"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Description</label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={2}
              placeholder="Optional"
              className="w-full px-3 py-2 rounded-xl border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 text-sm resize-none focus:outline-none focus:ring-2 focus:ring-violet-500"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Trigger</label>
            <select
              value={triggerType}
              onChange={(e) => setTriggerType(e.target.value as any)}
              className="w-full px-3 py-2 rounded-xl border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 text-sm focus:outline-none focus:ring-2 focus:ring-violet-500"
            >
              <option value="none">Manual / LLM tool call</option>
              <option value="cron">Scheduled (cron)</option>
              <option value="webhook">Webhook</option>
              <option value="event">Internal event</option>
            </select>
          </div>
          <div className="flex gap-3 justify-end pt-2">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 text-sm rounded-xl border border-gray-200 dark:border-gray-700 text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-800"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={!name.trim() || mutation.isPending}
              className="px-4 py-2 text-sm rounded-xl bg-violet-600 text-white font-medium disabled:opacity-50 hover:bg-violet-700 flex items-center gap-2"
            >
              {mutation.isPending && <Loader2 size={14} className="animate-spin" />}
              Create Workflow
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

// ─── Flow Card ────────────────────────────────────────────────────────────────

function FlowCard({
  flow,
  agentId,
  onDelete,
  onArchive,
  onRestore,
  onClone,
  onToggle,
}: {
  flow: Flow
  agentId: string
  onDelete: () => void
  onArchive: () => void
  onRestore: () => void
  onClone: () => void
  onToggle: () => void
}) {
  const [menuOpen, setMenuOpen] = useState(false)
  const TriggerIcon = TRIGGER_ICONS[flow.trigger_type] ?? GitBranch

  return (
    <div className="relative bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-800 hover:border-violet-300 dark:hover:border-violet-700 transition-colors p-5 flex flex-col gap-3">
      {/* Header */}
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <Link
            href={`/dashboard/agents/${agentId}/workflows/${flow.id}`}
            className="block font-semibold text-gray-900 dark:text-white hover:text-violet-600 dark:hover:text-violet-400 truncate"
          >
            {flow.name}
          </Link>
          {flow.description && (
            <p className="text-sm text-gray-500 dark:text-gray-400 mt-0.5 line-clamp-2">{flow.description}</p>
          )}
        </div>

        {/* Status badge */}
        <div className="flex items-center gap-1.5 shrink-0">
          {flow.is_active ? (
            <span className="flex items-center gap-1 text-xs font-medium text-emerald-700 dark:text-emerald-400 bg-emerald-50 dark:bg-emerald-900/20 px-2 py-0.5 rounded-full">
              <CheckCircle2 size={11} /> Active
            </span>
          ) : (
            <span className="flex items-center gap-1 text-xs font-medium text-gray-500 dark:text-gray-400 bg-gray-100 dark:bg-gray-800 px-2 py-0.5 rounded-full">
              <XCircle size={11} /> Inactive
            </span>
          )}
        </div>
      </div>

      {/* Trigger + tags row */}
      <div className="flex items-center gap-2 flex-wrap">
        <span className={`inline-flex items-center gap-1 text-xs font-medium px-2 py-0.5 rounded-full ${TRIGGER_COLORS[flow.trigger_type]}`}>
          <TriggerIcon size={11} />
          {TRIGGER_LABELS[flow.trigger_type]}
        </span>
        {flow.tags.slice(0, 3).map((tag) => (
          <span key={tag} className="text-xs px-2 py-0.5 rounded-full bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-400">
            {tag}
          </span>
        ))}
      </div>

      {/* Footer */}
      <div className="flex items-center justify-between pt-1 border-t border-gray-100 dark:border-gray-800">
        <span className="text-xs text-gray-400 dark:text-gray-500 flex items-center gap-1">
          <Calendar size={11} /> {formatDate(flow.updated_at)} · v{flow.version}
        </span>

        <div className="flex items-center gap-1">
          {/* Toggle active */}
          <button
            onClick={onToggle}
            title={flow.is_active ? 'Deactivate' : 'Activate'}
            className="p-1.5 rounded-lg text-gray-400 hover:text-violet-600 hover:bg-violet-50 dark:hover:bg-violet-900/20 transition-colors"
          >
            {flow.is_active ? <Pause size={14} /> : <Play size={14} />}
          </button>

          {/* More menu */}
          <div className="relative">
            <button
              onClick={() => setMenuOpen(!menuOpen)}
              className="p-1.5 rounded-lg text-gray-400 hover:text-gray-600 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
            >
              <MoreHorizontal size={14} />
            </button>
            {menuOpen && (
              <>
                <div className="fixed inset-0 z-10" onClick={() => setMenuOpen(false)} />
                <div className="absolute right-0 bottom-8 z-20 w-40 bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-700 shadow-lg py-1">
                  <Link
                    href={`/dashboard/agents/${agentId}/workflows/${flow.id}`}
                    className="flex items-center gap-2 px-3 py-2 text-sm text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800"
                    onClick={() => setMenuOpen(false)}
                  >
                    <GitBranch size={13} /> Edit
                  </Link>
                  <button
                    onClick={() => { onClone(); setMenuOpen(false) }}
                    className="w-full flex items-center gap-2 px-3 py-2 text-sm text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800"
                  >
                    <Copy size={13} /> Clone
                  </button>
                  {flow.is_archived ? (
                    <button
                      onClick={() => { onRestore(); setMenuOpen(false) }}
                      className="w-full flex items-center gap-2 px-3 py-2 text-sm text-emerald-600 dark:text-emerald-400 hover:bg-emerald-50 dark:hover:bg-emerald-900/20"
                    >
                      <RefreshCw size={13} /> Restore
                    </button>
                  ) : (
                    <button
                      onClick={() => { onArchive(); setMenuOpen(false) }}
                      className="w-full flex items-center gap-2 px-3 py-2 text-sm text-amber-600 dark:text-amber-400 hover:bg-amber-50 dark:hover:bg-amber-900/20"
                    >
                      <XCircle size={13} /> Archive
                    </button>
                  )}
                  <button
                    onClick={() => { onDelete(); setMenuOpen(false) }}
                    className="w-full flex items-center gap-2 px-3 py-2 text-sm text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20"
                  >
                    <Trash2 size={13} /> Hard Delete
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function FlowsPage() {
  const { id } = useParams<{ id: string }>()
  const router = useRouter()
  const qc = useQueryClient()
  const [showCreate, setShowCreate] = useState(false)
  const [activeTab, setActiveTab] = useState<'active' | 'archived'>('active')

  const { data: agent } = useQuery({
    queryKey: ['agent', id],
    queryFn: () => agentsApi.get(id),
  })

  const { data: flows = [], isLoading } = useQuery<Flow[]>({
    queryKey: ['workflows', id, activeTab],
    queryFn: () => workflowsApi.list(id, { include_archived: activeTab === 'archived' }),
  })

  // Filter based on activeTab (just in case the API doesn't filter strictly)
  const filteredFlows = flows.filter(f => activeTab === 'archived' ? f.is_archived : !f.is_archived)

  const deleteMutation = useMutation({
    mutationFn: (flowId: string) => workflowsApi.delete(id, flowId),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['workflows', id] }); toast.success('Workflow permanently deleted') },
    onError: () => toast.error('Failed to delete workflow'),
  })

  const archiveMutation = useMutation({
    mutationFn: (flowId: string) => workflowsApi.archive(id, flowId),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['workflows', id] }); toast.success('Workflow archived') },
    onError: () => toast.error('Failed to archive workflow'),
  })

  const restoreMutation = useMutation({
    mutationFn: (flowId: string) => workflowsApi.restore(id, flowId),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['workflows', id] }); toast.success('Workflow restored') },
    onError: () => toast.error('Failed to restore workflow'),
  })

  const cloneMutation = useMutation({
    mutationFn: (flowId: string) => workflowsApi.clone(id, flowId),
    onSuccess: (cloned: Flow) => {
      qc.invalidateQueries({ queryKey: ['workflows', id] })
      toast.success(`Cloned as "${cloned.name}"`)
    },
    onError: () => toast.error('Failed to clone workflow'),
  })

  const toggleMutation = useMutation({
    mutationFn: (flow: Flow) =>
      flow.is_active ? workflowsApi.deactivate(id, flow.id) : workflowsApi.activate(id, flow.id),
    onSuccess: (_data, flow) => {
      qc.invalidateQueries({ queryKey: ['workflows', id] })
      toast.success(flow.is_active ? 'Workflow deactivated' : 'Workflow activated')
    },
    onError: () => toast.error('Failed to toggle workflow'),
  })

  const confirmDelete = (flow: Flow) => {
    if (confirm(`PERMANENTLY delete "${flow.name}"? This will erase all history and cannot be undone.`)) {
      deleteMutation.mutate(flow.id)
    }
  }

  const handleArchive = (flow: Flow) => {
    archiveMutation.mutate(flow.id)
  }

  const handleRestore = (flow: Flow) => {
    restoreMutation.mutate(flow.id)
  }

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-950 p-6">
      {/* Back nav */}
      <Link
        href={`/dashboard/agents/${id}`}
        className="inline-flex items-center gap-2 text-sm text-gray-500 dark:text-gray-400 hover:text-violet-600 dark:hover:text-violet-400 mb-6"
      >
        <ChevronLeft size={16} /> {agent?.name ?? 'Agent'}
      </Link>

      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white flex items-center gap-2">
            <Zap className="text-violet-500" size={24} /> Workflows
          </h1>
          <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
            Automated workflows triggered by schedule, webhook, event, or LLM tool call
          </p>
        </div>
        <div className="flex items-center gap-3">
          <div className="bg-gray-100 dark:bg-gray-800 p-1 rounded-xl flex gap-1">
            <button
              onClick={() => setActiveTab('active')}
              className={`px-4 py-1.5 rounded-lg text-xs font-bold transition-all ${activeTab === 'active' ? 'bg-white dark:bg-gray-700 text-gray-900 dark:text-white shadow-sm' : 'text-gray-500'}`}
            >
              Active
            </button>
            <button
              onClick={() => setActiveTab('archived')}
              className={`px-4 py-1.5 rounded-lg text-xs font-bold transition-all ${activeTab === 'archived' ? 'bg-white dark:bg-gray-700 text-gray-900 dark:text-white shadow-sm' : 'text-gray-500'}`}
            >
              Archived
            </button>
          </div>
          <button
            onClick={() => setShowCreate(true)}
            className="flex items-center gap-2 px-4 py-2 bg-violet-600 text-white rounded-xl text-sm font-medium hover:bg-violet-700 transition-colors shadow-lg shadow-violet-500/20"
          >
            <Plus size={16} /> New Workflow
          </button>
        </div>
      </div>

      {/* Content */}
      {isLoading ? (
        <div className="flex justify-center py-20">
          <Loader2 size={28} className="animate-spin text-violet-500" />
        </div>
      ) : filteredFlows.length === 0 ? (
        <div className="text-center py-20 bg-white dark:bg-gray-900/50 rounded-2xl border-2 border-dashed border-gray-100 dark:border-gray-800">
          <Zap size={40} className="text-gray-200 dark:text-gray-700 mx-auto mb-4" />
          <p className="text-gray-500 dark:text-gray-400 font-medium mb-2">
            {activeTab === 'active' ? 'No workflows yet' : 'No archived workflows'}
          </p>
          <p className="text-sm text-gray-400 dark:text-gray-500 mb-6">
            {activeTab === 'active' 
              ? 'Create a workflow to automate actions — send SMS, call tools, run logic, and more.'
              : 'Workflows you archive will appear here.'}
          </p>
          {activeTab === 'active' && (
            <button
              onClick={() => setShowCreate(true)}
              className="inline-flex items-center gap-2 px-4 py-2 bg-violet-600 text-white rounded-xl text-sm font-medium hover:bg-violet-700"
            >
              <Plus size={16} /> Create your first workflow
            </button>
          )}
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {filteredFlows.map((flow) => (
            <FlowCard
              key={flow.id}
              flow={flow}
              agentId={id}
              onDelete={() => confirmDelete(flow)}
              onArchive={() => handleArchive(flow)}
              onRestore={() => handleRestore(flow)}
              onClone={() => cloneMutation.mutate(flow.id)}
              onToggle={() => toggleMutation.mutate(flow)}
            />
          ))}
        </div>
      )}

      {/* Create modal */}
      {showCreate && (
        <CreateFlowModal
          agentId={id}
          onClose={() => setShowCreate(false)}
          onCreated={(flow) => {
            qc.invalidateQueries({ queryKey: ['workflows', id] })
            setShowCreate(false)
            router.push(`/dashboard/agents/${id}/workflows/${flow.id}`)
          }}
        />
      )}
    </div>
  )
}
