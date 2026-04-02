'use client'

import { useState } from 'react'
import { useParams } from 'next/navigation'
import Link from 'next/link'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { variablesApi } from '@/lib/api'
import toast from 'react-hot-toast'
import {
  ArrowLeft,
  Plus,
  Code2,
  Trash2,
  Edit2,
  X,
  Globe2,
  BoxSelect,
} from 'lucide-react'

interface VariableForm {
  name: string
  description: string
  scope: string
  data_type: string
  default_value: string
}

const EMPTY_FORM: VariableForm = {
  name: '',
  description: '',
  scope: 'global',
  data_type: 'string',
  default_value: '',
}

function VariableFormPanel({
  agentId,
  initial,
  onClose,
}: {
  agentId: string
  initial?: { id: string } & Record<string, unknown>
  onClose: () => void
}) {
  const qc = useQueryClient()
  const [form, setForm] = useState<VariableForm>(() => {
    if (initial) {
      return {
        name: (initial.name as string) || '',
        description: (initial.description as string) || '',
        scope: (initial.scope as string) || 'global',
        data_type: (initial.data_type as string) || 'string',
        default_value: initial.default_value ? JSON.stringify(initial.default_value) : '',
      }
    }
    return EMPTY_FORM
  })

  const saveMutation = useMutation({
    mutationFn: (data: Record<string, unknown>) => {
      // Force global scope on this generic Variables page
      const payload = { ...data, scope: 'global' }
      if (initial?.id) {
        return variablesApi.update(agentId, initial.id as string, payload)
      }
      return variablesApi.create(agentId, payload)
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['variables', agentId] })
      toast.success(initial ? 'Variable updated!' : 'Variable created!')
      onClose()
    },
    onError: (e: any) =>
      toast.error(e?.response?.data?.detail || 'Failed to save variable'),
  })

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    let parsedDefault = null
    if (form.default_value) {
      try {
        parsedDefault = JSON.parse(form.default_value)
      } catch {
        parsedDefault = form.default_value // Fallback to string
      }
    }

    saveMutation.mutate({
      name: form.name,
      description: form.description,
      scope: form.scope,
      data_type: form.data_type,
      default_value: parsedDefault,
    })
  }

  const inputCls =
    'w-full px-3 py-2.5 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm focus:outline-none focus:ring-1 focus:ring-violet-500'

  return (
    <div className="fixed inset-0 z-50 flex">
      <div
        className="flex-1 bg-black/40 backdrop-blur-sm"
        onClick={onClose}
      />
      <div className="w-full max-w-md bg-white dark:bg-gray-900 shadow-2xl flex flex-col h-full right-0 absolute animation-slide-in">
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200 dark:border-gray-800">
          <h2 className="text-base font-semibold text-gray-900 dark:text-white">
            {initial ? 'Edit Variable' : 'New Variable'}
          </h2>
          <button
            onClick={onClose}
            className="p-1.5 text-gray-400 hover:text-gray-600 transition-colors"
          >
            <X size={18} />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="flex-1 overflow-y-auto p-6 space-y-4">
          <div>
            <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
              Variable Name *
            </label>
            <input
              required
              disabled={initial?.scope === 'local'}
              value={form.name}
              onChange={(e) => setForm((p) => ({ ...p, name: e.target.value.replace(/[^a-zA-Z0-9_]/g, '') }))}
              placeholder="user_id, account_status..."
              className={inputCls}
            />
            <p className="text-xs text-gray-400 mt-1">Must be alphanumeric with underscores.</p>
          </div>

          <div>
            <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
              Description
            </label>
            <input
              disabled={initial?.scope === 'local'}
              value={form.description}
              onChange={(e) => setForm((p) => ({ ...p, description: e.target.value }))}
              placeholder="What is this variable used for?"
              className={inputCls}
            />
          </div>

          {initial?.scope === 'local' && (
            <div className="p-3 rounded-lg bg-orange-50 border border-orange-200 text-orange-800 text-sm">
              <span className="font-semibold block mb-1">Playbook-Local Variable</span>
              This variable is bound to a specific Playbook. You can only edit or delete it from within the Playbook editor.
            </div>
          )}

          <div>
            <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
              Data Type
            </label>
            <select
              disabled={initial?.scope === 'local'}
              value={form.data_type}
              onChange={(e) => setForm((p) => ({ ...p, data_type: e.target.value }))}
              className={inputCls}
            >
              <option value="string">String</option>
              <option value="number">Number</option>
              <option value="boolean">Boolean</option>
              <option value="object">JSON Object</option>
            </select>
          </div>

          <div>
            <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
              Default Value (Optional, overrides Session injection if empty)
            </label>
            <textarea
              disabled={initial?.scope === 'local'}
              value={form.default_value}
              onChange={(e) => setForm((p) => ({ ...p, default_value: e.target.value }))}
              rows={3}
              placeholder='e.g. "guest" or {"tier": "free"}'
              className={`${inputCls} font-mono text-xs disabled:opacity-50`}
            />
          </div>
        </form>

        <div className="px-6 py-4 border-t border-gray-200 dark:border-gray-800 flex items-center justify-end gap-3 bg-gray-50 dark:bg-gray-800/50">
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-2 rounded-lg border border-gray-200 dark:border-gray-700 text-sm text-gray-600 dark:text-gray-400 hover:bg-white dark:hover:bg-gray-800 transition-colors"
          >
            {initial?.scope === 'local' ? 'Close' : 'Cancel'}
          </button>
          
          {initial?.scope !== 'local' && (
            <button
              onClick={handleSubmit as unknown as React.MouseEventHandler}
              disabled={saveMutation.isPending}
              className="px-5 py-2 rounded-lg bg-gradient-to-r from-violet-600 to-blue-600 text-white text-sm font-medium hover:opacity-90 disabled:opacity-50 transition-opacity"
            >
              {saveMutation.isPending ? 'Saving…' : initial ? 'Update Variable' : 'Create Variable'}
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

export default function VariablesPage() {
  const params = useParams()
  const agentId = params.id as string
  const qc = useQueryClient()

  const [showForm, setShowForm] = useState(false)
  const [editing, setEditing] = useState<{ id: string } & Record<string, unknown> | null>(null)

  const { data: variables, isLoading } = useQuery({
    queryKey: ['variables', agentId],
    queryFn: () => variablesApi.list(agentId),
    enabled: !!agentId,
  })

  const deleteMutation = useMutation({
    mutationFn: (vId: string) => variablesApi.delete(agentId, vId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['variables', agentId] })
      toast.success('Variable deleted')
    },
    onError: () => toast.error('Failed to delete variable'),
  })

  const items: any[] = Array.isArray(variables) ? variables : []

  return (
    <div className="p-8 w-full">

      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <div className="flex items-center gap-3 mb-1">
            <Link
              href={`/dashboard/agents/${agentId}`}
              className="p-1.5 text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 transition-colors"
            >
              <ArrowLeft size={18} />
            </Link>
            <h1 className="text-2xl font-bold text-gray-900 dark:text-white">State Variables</h1>
          </div>
          <p className="text-gray-500 dark:text-gray-400 ml-9">
            Define global or local variables that can be injected into the agent's context or passed to tools. 
          </p>
        </div>
        <button
          onClick={() => {
            setEditing(null)
            setShowForm(true)
          }}
          className="inline-flex items-center gap-2 px-4 py-2.5 rounded-lg bg-gradient-to-r from-violet-600 to-blue-600 text-white text-sm font-medium hover:opacity-90 transition-opacity"
        >
          <Plus size={16} /> New Variable
        </button>
      </div>

      {/* Content */}
      {isLoading ? (
        <div className="space-y-3">
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-20 rounded-xl bg-gray-100 dark:bg-gray-800 animate-pulse" />
          ))}
        </div>
      ) : items.length === 0 ? (
        <div className="text-center py-16 bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800">
          <Code2 size={40} className="mx-auto mb-3 text-gray-300 dark:text-gray-600" />
          <h3 className="text-base font-semibold text-gray-900 dark:text-white mb-1">
            No variables configured
          </h3>
          <p className="text-sm text-gray-500 mb-4">
            Variables let you store state dynamically and pass information into tools.
          </p>
          <button
            onClick={() => {
              setEditing(null)
              setShowForm(true)
            }}
            className="inline-flex items-center gap-2 px-4 py-2.5 rounded-lg bg-violet-600 text-white text-sm font-medium hover:bg-violet-700 transition-colors"
          >
            <Plus size={16} /> Create Variable
          </button>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {items.map((v: any) => (
            <div
              key={v.id}
              className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 p-5 flex flex-col justify-between"
            >
              <div>
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2">
                    {v.scope === 'global' ? (
                      <Globe2 size={16} className="text-blue-500" />
                    ) : (
                      <BoxSelect size={16} className="text-orange-500" />
                    )}
                    <h3 className="font-mono text-sm font-bold text-gray-900 dark:text-white">
                      {v.name}
                    </h3>
                  </div>
                  <div className="flex gap-1">
                    {v.scope === 'global' ? (
                      <>
                        <button
                          onClick={() => {
                            setEditing(v)
                            setShowForm(true)
                          }}
                          className="p-1.5 text-gray-400 hover:text-violet-600 transition-colors"
                        >
                          <Edit2 size={14} />
                        </button>
                        <button
                          onClick={() => confirm('Delete variable?') && deleteMutation.mutate(v.id)}
                          className="p-1.5 text-gray-400 hover:text-red-500 transition-colors"
                        >
                          <Trash2 size={14} />
                        </button>
                      </>
                    ) : (
                      <button
                        onClick={() => {
                          setEditing(v)
                          setShowForm(true)
                        }}
                        className="px-2 py-1 text-xs text-gray-400 border border-gray-200 dark:border-gray-800 rounded hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors"
                      >
                        View Details
                      </button>
                    )}
                  </div>
                </div>
                <p className="text-xs text-gray-500 mb-4">{v.description || 'No description provided.'}</p>
              </div>

              <div className="flex items-center gap-2">
                <span className="px-2 py-1 rounded bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-300 text-[10px] uppercase font-bold tracking-wider">
                  {v.data_type}
                </span>
                <span className={`px-2 py-1 rounded text-[10px] uppercase font-bold tracking-wider ${
                  v.scope === 'global' ? 'bg-blue-50 text-blue-600 dark:bg-blue-900/30 dark:text-blue-400' : 'bg-orange-50 text-orange-600 dark:bg-orange-900/30 dark:text-orange-400'
                }`}>
                  {v.scope} Scope
                </span>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Slide-in panel */}
      {showForm && (
        <VariableFormPanel
          agentId={agentId}
          initial={editing || undefined}
          onClose={() => {
            setShowForm(false)
            setEditing(null)
          }}
        />
      )}
    </div>
  )
}
