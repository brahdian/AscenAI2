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
  Lock,
  Eye,
  EyeOff,
  Download,
} from 'lucide-react'

interface VariableForm {
  name: string
  description: string
  scope: string
  data_type: string
  default_value: string
  is_secret: boolean
}

const EMPTY_FORM: VariableForm = {
  name: '',
  description: '',
  scope: 'global',
  data_type: 'string',
  default_value: '',
  is_secret: false,
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
        default_value: initial.default_value
          ? JSON.stringify(initial.default_value)
          : '',
        is_secret: !!initial.is_secret,
      }
    }
    return EMPTY_FORM
  })

  const [showSecret, setShowSecret] = useState(false)

  const isReadOnly = initial?.scope === 'local'

  const saveMutation = useMutation({
    mutationFn: (data: Record<string, unknown>) => {
      const payload = { 
        ...data, 
        scope: initial?.scope || 'global' 
      }
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
    if (isReadOnly) return

    let parsedDefault = null
    // Sentinel Guard: If the value is '***', it means it's an existing secret
    // that hasn't been modified. We send 'undefined' to skip updating it.
    const isUnchangedSecret = form.is_secret && form.default_value === '***'

    if (form.default_value && !isUnchangedSecret) {
      try {
        parsedDefault = JSON.parse(form.default_value)
      } catch {
        parsedDefault = form.default_value
      }
    }

    saveMutation.mutate({
      name: form.name,
      description: form.description,
      scope: form.scope,
      data_type: form.data_type,
      default_value: isUnchangedSecret ? undefined : parsedDefault,
      is_secret: form.is_secret,
    })
  }

  const inputCls =
    'w-full px-3 py-2.5 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm focus:outline-none focus:ring-1 focus:ring-violet-500 transition-colors disabled:opacity-50'

  return (
    <div className="fixed inset-0 z-50 flex">
      <div
        className="flex-1 bg-black/40 backdrop-blur-sm"
        onClick={onClose}
      />
      <div className="w-full max-w-md bg-white dark:bg-gray-900 shadow-2xl flex flex-col h-full right-0 absolute animation-slide-in">
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200 dark:border-gray-800">
          <div className="flex items-center gap-2">
            <h2 className="text-base font-semibold text-gray-900 dark:text-white">
              {initial ? 'Edit Variable' : 'New Variable'}
            </h2>
            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider bg-blue-50 text-blue-600 dark:bg-blue-900/30 dark:text-blue-400">
              <Globe2 size={10} /> {form.scope}
            </span>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 text-gray-400 hover:text-gray-600 transition-colors"
          >
            <X size={18} />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="flex-1 overflow-y-auto p-6 space-y-4">
          {isReadOnly && (
            <div className="p-3 rounded-lg bg-orange-50 border border-orange-200 text-orange-800 text-sm">
              <span className="font-semibold block mb-1">Playbook-Local Variable</span>
              This variable is bound to a specific Playbook. You can only edit or
              delete it from within the Playbook editor.
            </div>
          )}

          <div>
            <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
              Variable Name * (Must start with a letter)
            </label>
            <input
              maxLength={100}
              required
              disabled={isReadOnly}
              value={form.name}
              onChange={(e) => {
                // Strip all illegal chars first, then enforce "must start with a letter"
                let val = e.target.value.replace(/[^a-zA-Z0-9_]/g, '')
                val = val.replace(/^[^a-zA-Z]+/, '')
                setForm((p) => ({ ...p, name: val }))
              }}
              placeholder="user_id, account_status..."
              className={inputCls}
            />
            <div className="flex justify-end pr-1.5">
              <span className="text-[9px] text-gray-400">{form.name.length}/100</span>
            </div>
          </div>

          <div>
            <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
              Description
            </label>
            <input
              maxLength={500}
              disabled={isReadOnly}
              value={form.description}
              onChange={(e) =>
                setForm((p) => ({ ...p, description: e.target.value }))
              }
              placeholder="What is this variable used for?"
              className={inputCls}
            />
          </div>

          <div>
            <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
              Data Type
            </label>
            <select
              disabled={isReadOnly}
              value={form.data_type}
              onChange={(e) =>
                setForm((p) => ({ ...p, data_type: e.target.value }))
              }
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
              maxLength={10000}
              disabled={initial?.scope === 'local'}
              value={form.is_secret && initial ? '***' : form.default_value}
              onChange={(e) => setForm((p) => ({ ...p, default_value: e.target.value }))}
              rows={3}
              placeholder={form.is_secret ? "Value is hidden" : 'e.g. "guest" or {"tier": "free"}'}
              className={`${inputCls} font-mono text-xs disabled:opacity-50`}
            />
            <div className="flex justify-between items-center mt-1 px-1">
              <div>
                {form.is_secret && initial && (
                  <p className="text-[10px] text-orange-500">Secret values cannot be viewed after saving. Updating this field will overwrite the secret.</p>
                )}
              </div>
              <span className={`text-[9px] ${form.default_value.length > 9000 ? 'text-orange-500 font-bold' : 'text-gray-400'}`}>
                {form.default_value.length}/10,000
              </span>
            </div>
          </div>

          <div className="pt-2">
            <label className="flex items-center gap-2 cursor-pointer group">
              <input
                type="checkbox"
                disabled={initial?.scope === 'local'}
                checked={form.is_secret}
                onChange={(e) => setForm((p) => ({ ...p, is_secret: e.target.checked }))}
                className="w-4 h-4 rounded border-gray-300 text-violet-600 focus:ring-violet-500"
              />
              <span className="text-sm font-medium text-gray-700 dark:text-gray-300 group-hover:text-gray-900 dark:group-hover:text-white transition-colors">
                Mark as Secret
              </span>
            </label>
            <p className="text-xs text-gray-400 mt-1 ml-6">
              Secrets are redacted in logs and API responses. Use for API keys, PII, or credentials.
            </p>
          </div>
        </form>

        <div className="px-6 py-4 border-t border-gray-200 dark:border-gray-800 flex items-center justify-end gap-3 bg-gray-50 dark:bg-gray-800/50">
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-2 rounded-lg border border-gray-200 dark:border-gray-700 text-sm text-gray-600 dark:text-gray-400 hover:bg-white dark:hover:bg-gray-800 transition-colors"
          >
            {isReadOnly ? 'Close' : 'Cancel'}
          </button>

          {!isReadOnly && (
            <button
              onClick={handleSubmit as unknown as React.MouseEventHandler}
              disabled={saveMutation.isPending}
              className="px-5 py-2 rounded-lg bg-gradient-to-r from-violet-600 to-blue-600 text-white text-sm font-medium hover:opacity-90 disabled:opacity-50 transition-opacity"
            >
              {saveMutation.isPending
                ? 'Saving…'
                : initial
                ? 'Update Variable'
                : 'Create Variable'}
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
  const [editing, setEditing] = useState<
    { id: string } & Record<string, unknown> | null
  >(null)
  
  // Zenith Pillar 2: Forensic Export State
  const [showExportModal, setShowExportModal] = useState(false)
  const [justification, setJustification] = useState('')
  const [isExporting, setIsExporting] = useState(false)

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
    onError: (err: any) => {
      const detail = err?.response?.data?.detail
      // Zenith Pillar 5: Expose Trace ID safely instead of raw errors if it's a 500
      toast.error(detail || 'An internal error occurred.')
    },
  })

  // Forensic Export Handler
  const handleExport = async () => {
    if (!justification.trim() || justification.length < 10) {
      toast.error('A detailed justification is required for forensic exports (min 10 chars).')
      return
    }
    try {
      setIsExporting(true)
      const url = variablesApi.exportUrl(agentId, justification)
      
      // Zenith Security: Creating an invisible iframe to trigger the download via browser,
      // which automatically sends the HttpOnly authentication cookies.
      const iframe = document.createElement('iframe')
      iframe.style.display = 'none'
      iframe.src = url
      document.body.appendChild(iframe)
      
      // Cleanup
      setTimeout(() => {
        document.body.removeChild(iframe)
        setIsExporting(false)
        setShowExportModal(false)
        setJustification('')
        toast.success('Audit export generated successfully.')
      }, 3000)
    } catch (err: any) {
      setIsExporting(false)
      toast.error('Export failed. Please check rate limits or try again later.')
    }
  }

  const items: any[] = Array.isArray(variables) ? variables : []
  const globalVars = items.filter((v) => v.scope === 'global')
  const localVars = items.filter((v) => v.scope === 'local')

  return (
    <div className="p-8 w-full">

      <div className="flex items-center justify-between mb-6">
        <div>
          <div className="flex items-center gap-3 mb-1">
            <Link
              href={`/dashboard/agents/${agentId}`}
              className="p-1.5 text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 transition-colors"
            >
              <ArrowLeft size={18} />
            </Link>
            <h1 className="text-2xl font-bold text-gray-900 dark:text-white">
              State Variables
            </h1>
          </div>
          <p className="text-gray-500 dark:text-gray-400 ml-9">
            Define named, typed placeholders injected into the agent context at runtime. 
            Local variables are managed from the Playbook editor.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={() => setShowExportModal(true)}
            className="inline-flex items-center gap-2 px-4 py-2.5 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-200 text-sm font-medium hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
          >
            <Download size={16} /> Audit Export
          </button>
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
      </div>

      {/* FIX-13: Scope info banner */}
      <div className="mb-5 p-3 rounded-lg bg-blue-50 dark:bg-blue-900/20 border border-blue-100 dark:border-blue-800 flex items-center gap-2 text-xs text-blue-700 dark:text-blue-300">
        <Globe2 size={13} className="shrink-0" />
        <span>
          <strong>Global variables</strong> persist across the entire session and all playbooks.
          &nbsp;<BoxSelect size={11} className="inline text-orange-500" /> <strong>Local variables</strong> are scoped to a specific playbook — create them in the Playbook editor.
        </span>
      </div>

      {/* Content */}
      {isLoading ? (
        <div className="space-y-3">
          {[1, 2, 3].map((i) => (
            <div
              key={i}
              className="h-20 rounded-xl bg-gray-100 dark:bg-gray-800 animate-pulse"
            />
          ))}
        </div>
      ) : items.length === 0 ? (
        <div className="text-center py-16 bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800">
          <Code2 size={40} className="mx-auto mb-3 text-gray-300 dark:text-gray-600" />
          <h3 className="text-base font-semibold text-gray-900 dark:text-white mb-1">
            No variables configured
          </h3>
          <p className="text-sm text-gray-500 mb-4">
            Variables let you store state dynamically and pass information into
            tools and playbooks via{' '}
            <code className="bg-gray-100 dark:bg-gray-800 px-1 rounded text-violet-600">
              $vars:name
            </code>{' '}
            placeholders.
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
        <div className="space-y-6">
          {/* Global variables */}
          {globalVars.length > 0 && (
            <section>
              <h2 className="text-xs font-bold uppercase tracking-wider text-gray-400 mb-3 flex items-center gap-1.5">
                <Globe2 size={12} className="text-blue-500" /> Global Variables
              </h2>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {globalVars.map((v: any) => (
                  <VariableCard
                    key={v.id}
                    v={v}
                    onEdit={() => {
                      setEditing(v)
                      setShowForm(true)
                    }}
                    onDelete={() =>
                      confirm('Delete variable?') &&
                      deleteMutation.mutate(v.id)
                    }
                  />
                ))}
              </div>
            </section>
          )}

          {/* Local (playbook-scoped) variables — read-only here */}
          {localVars.length > 0 && (
            <section>
              <h2 className="text-xs font-bold uppercase tracking-wider text-gray-400 mb-3 flex items-center gap-1.5">
                <BoxSelect size={12} className="text-orange-500" /> Playbook-Local Variables
                <span className="ml-1 text-gray-300 font-normal normal-case tracking-normal">
                  — edit from the Playbook editor
                </span>
              </h2>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {localVars.map((v: any) => (
                  <VariableCard
                    key={v.id}
                    v={v}
                    readOnly
                    onEdit={() => {
                      setEditing(v)
                      setShowForm(true)
                    }}
                  />
                ))}
              </div>
            </section>
          )}
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

      {/* Zenith Pillar 2: Export Justification Modal */}
      {showExportModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm p-4">
          <div className="bg-white dark:bg-gray-900 rounded-xl shadow-2xl w-full max-w-md p-6 animation-fade-in border border-gray-200 dark:border-gray-800">
            <h2 className="text-lg font-bold text-gray-900 dark:text-white mb-2 flex items-center gap-2">
              <Lock size={18} className="text-violet-500" /> Forensic Export Justification
            </h2>
            <p className="text-sm text-gray-600 dark:text-gray-400 mb-4">
              Exporting the variable registry generates a permanent audit trail.
              Please provide a business justification for this data extraction.
            </p>
            <textarea
              value={justification}
              onChange={(e) => setJustification(e.target.value)}
              placeholder="e.g., Routine compliance audit referencing ticket #1234"
              className="w-full px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 text-gray-900 dark:text-white text-sm mb-4 min-h-[80px]"
            />
            <div className="flex justify-end gap-3">
              <button
                onClick={() => {
                  setShowExportModal(false)
                  setJustification('')
                }}
                className="px-4 py-2 rounded-lg border border-gray-200 dark:border-gray-700 text-sm font-medium text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors"
                disabled={isExporting}
              >
                Cancel
              </button>
              <button
                onClick={handleExport}
                disabled={justification.length < 10 || isExporting}
                className="px-4 py-2 rounded-lg bg-violet-600 text-white text-sm font-medium hover:bg-violet-700 transition-colors disabled:opacity-50 flex items-center gap-2"
              >
                {isExporting ? 'Generating...' : 'Confirm Export'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

// ── VariableCard ────────────────────────────────────────────────────────────

function VariableCard({
  v,
  readOnly = false,
  onEdit,
  onDelete,
}: {
  v: any
  readOnly?: boolean
  onEdit: () => void
  onDelete?: () => void
}) {
  const isGlobal = v.scope === 'global'

  return (
    <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 p-5 flex flex-col justify-between hover:border-violet-200 dark:hover:border-violet-800 transition-colors">
      <div>
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-2">
            {isGlobal ? (
              <Globe2 size={15} className="text-blue-500 shrink-0" />
            ) : (
              <BoxSelect size={15} className="text-orange-500 shrink-0" />
            )}
            <h3 className="font-mono text-sm font-bold text-gray-900 dark:text-white flex items-center gap-1.5">
              {v.name}
              {/* FIX-04: Show lock icon for secret variables */}
              {v.is_secret && (
                <span title="Secret variable — value is redacted from the AI model and logs">
                  <Lock size={12} className="text-violet-500" />
                </span>
              )}
            </h3>
          </div>
          <div className="flex gap-1">
            {!readOnly ? (
              <>
                <button
                  onClick={onEdit}
                  className="p-1.5 text-gray-400 hover:text-violet-600 transition-colors"
                  title="Edit variable"
                >
                  <Edit2 size={14} />
                </button>
                {onDelete && (
                  <button
                    onClick={onDelete}
                    className="p-1.5 text-gray-400 hover:text-red-500 transition-colors"
                    title="Delete variable"
                  >
                    <Trash2 size={14} />
                  </button>
                )}
              </>
            ) : (
              <button
                onClick={onEdit}
                className="px-2 py-1 text-xs text-gray-400 border border-gray-200 dark:border-gray-800 rounded hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors"
              >
                View Details
              </button>
            )}
          </div>
        </div>
        <p className="text-xs text-gray-500 mb-4 line-clamp-2">
          {v.description || 'No description provided.'}
        </p>
      </div>

      <div className="flex items-center gap-2 flex-wrap">
        <span className="px-2 py-1 rounded bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-300 text-[10px] uppercase font-bold tracking-wider">
          {v.data_type}
        </span>
        <span
          className={`px-2 py-1 rounded text-[10px] uppercase font-bold tracking-wider ${
            isGlobal
              ? 'bg-blue-50 text-blue-600 dark:bg-blue-900/30 dark:text-blue-400'
              : 'bg-orange-50 text-orange-600 dark:bg-orange-900/30 dark:text-orange-400'
          }`}
        >
          {v.scope} Scope
        </span>
        {/* FIX-04: Secret badge */}
        {v.is_secret && (
          <span className="px-2 py-1 rounded text-[10px] uppercase font-bold tracking-wider bg-violet-50 text-violet-600 dark:bg-violet-900/30 dark:text-violet-400 flex items-center gap-1">
            <Lock size={9} /> Secret
          </span>
        )}
      </div>
    </div>
  )
}
