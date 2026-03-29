'use client'

import { useParams, useRouter } from 'next/navigation'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { flowsApi } from '@/lib/api'
import toast from 'react-hot-toast'
import { GitBranch, Plus, Trash2, Play, Zap, Clock } from 'lucide-react'

export default function WorkflowsPage() {
  const { id: agentId } = useParams<{ id: string }>()
  const router = useRouter()
  const qc = useQueryClient()

  const { data: flows, isLoading } = useQuery({
    queryKey: ['flows', agentId],
    queryFn: () => flowsApi.list(agentId),
  })

  const createMutation = useMutation({
    mutationFn: () =>
      flowsApi.create(agentId, {
        name: 'Untitled Flow',
        steps: {
          start: {
            id: 'start',
            type: 'wait_input',
            prompt_to_user: 'Hello! How can I help you today?',
            variable_to_store: 'user_input',
            next_step_id: 'end',
          },
          end: {
            id: 'end',
            type: 'end',
            status: 'completed',
            final_message_template: 'Thank you! Is there anything else I can help you with?',
          },
        },
        ui_layout: {
          start: { x: 200, y: 100 },
          end: { x: 200, y: 300 },
        },
        initial_step_id: 'start',
      }),
    onSuccess: (flow: any) => {
      qc.invalidateQueries({ queryKey: ['flows', agentId] })
      router.push(`/dashboard/agents/${agentId}/workflows/${flow.id}`)
    },
    onError: () => toast.error('Failed to create flow'),
  })

  const deleteMutation = useMutation({
    mutationFn: (flowId: string) => flowsApi.delete(agentId, flowId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['flows', agentId] })
      toast.success('Flow deleted')
    },
    onError: () => toast.error('Failed to delete flow'),
  })

  const activateMutation = useMutation({
    mutationFn: (flowId: string) => flowsApi.activate(agentId, flowId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['flows', agentId] })
      toast.success('Flow activated')
    },
    onError: () => toast.error('Failed to activate flow'),
  })

  const stepCount = (flow: any) => Object.keys(flow.steps || {}).length

  return (
    <div className="p-8 max-w-4xl mx-auto">
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Workflows</h1>
          <p className="text-gray-500 dark:text-gray-400 mt-1">
            Build visual conversation flows with a drag-and-drop state machine editor.
          </p>
        </div>
        <button
          onClick={() => createMutation.mutate()}
          disabled={createMutation.isPending}
          className="inline-flex items-center gap-2 px-4 py-2.5 rounded-lg bg-violet-600 text-white text-sm font-medium hover:bg-violet-700 disabled:opacity-50 transition-colors"
        >
          <Plus size={16} /> New Flow
        </button>
      </div>

      {isLoading ? (
        <div className="space-y-3">
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-20 rounded-xl bg-gray-100 dark:bg-gray-800 animate-pulse" />
          ))}
        </div>
      ) : !flows?.length ? (
        <div className="text-center py-16 bg-white dark:bg-gray-900 rounded-xl border border-dashed border-gray-200 dark:border-gray-700">
          <GitBranch size={40} className="mx-auto mb-3 text-gray-300 dark:text-gray-600" />
          <p className="text-gray-500 dark:text-gray-400 font-medium">No workflows yet</p>
          <p className="text-sm text-gray-400 dark:text-gray-500 mt-1 mb-4">
            Create a flow to define multi-step conversation logic
          </p>
          <button
            onClick={() => createMutation.mutate()}
            disabled={createMutation.isPending}
            className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-violet-600 text-white text-sm font-medium hover:bg-violet-700 transition-colors"
          >
            <Plus size={15} /> Create first flow
          </button>
        </div>
      ) : (
        <div className="space-y-3">
          {flows.map((flow: any) => (
            <div
              key={flow.id}
              className="flex items-center justify-between bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 px-5 py-4 hover:border-violet-200 dark:hover:border-violet-800 transition-colors group"
            >
              <div
                className="flex items-center gap-4 flex-1 min-w-0 cursor-pointer"
                onClick={() => router.push(`/dashboard/agents/${agentId}/workflows/${flow.id}`)}
              >
                <div
                  className={`w-9 h-9 rounded-lg flex items-center justify-center flex-shrink-0 ${
                    flow.is_active
                      ? 'bg-emerald-100 dark:bg-emerald-900/30 text-emerald-600'
                      : 'bg-gray-100 dark:bg-gray-800 text-gray-500'
                  }`}
                >
                  <GitBranch size={17} />
                </div>
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <p className="text-sm font-medium text-gray-900 dark:text-white truncate">
                      {flow.name}
                    </p>
                    {flow.is_active && (
                      <span className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-300">
                        <Zap size={10} /> Active
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-3 mt-0.5">
                    <span className="text-xs text-gray-400">{stepCount(flow)} steps</span>
                    {flow.trigger_keywords?.length > 0 && (
                      <span className="text-xs text-gray-400">
                        Triggers: {flow.trigger_keywords.slice(0, 3).join(', ')}
                        {flow.trigger_keywords.length > 3 ? ` +${flow.trigger_keywords.length - 3}` : ''}
                      </span>
                    )}
                    <span className="text-xs text-gray-400 flex items-center gap-1">
                      <Clock size={10} />
                      v{flow.version}
                    </span>
                  </div>
                </div>
              </div>
              <div className="flex items-center gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
                {!flow.is_active && (
                  <button
                    onClick={() => activateMutation.mutate(flow.id)}
                    disabled={activateMutation.isPending}
                    className="px-3 py-1.5 rounded-lg text-xs font-medium bg-emerald-50 dark:bg-emerald-900/20 text-emerald-700 dark:text-emerald-300 hover:bg-emerald-100 transition-colors"
                  >
                    Activate
                  </button>
                )}
                <button
                  onClick={() => router.push(`/dashboard/agents/${agentId}/workflows/${flow.id}`)}
                  className="px-3 py-1.5 rounded-lg text-xs font-medium bg-violet-50 dark:bg-violet-900/20 text-violet-700 dark:text-violet-300 hover:bg-violet-100 transition-colors"
                >
                  Edit
                </button>
                <button
                  onClick={() => {
                    if (confirm('Delete this flow?')) deleteMutation.mutate(flow.id)
                  }}
                  className="p-1.5 text-gray-400 hover:text-red-500 transition-colors"
                >
                  <Trash2 size={14} />
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
