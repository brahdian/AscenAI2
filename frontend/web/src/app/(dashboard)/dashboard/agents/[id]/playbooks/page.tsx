'use client'

import { useState } from 'react'
import { useParams } from 'next/navigation'
import Link from 'next/link'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { playbooksApi } from '@/lib/api'
import toast from 'react-hot-toast'
import {
  ArrowLeft,
  Plus,
  BookOpen,
  Trash2,
  Edit2,
  Star,
  X,
  ChevronDown,
  ChevronUp,
} from 'lucide-react'

interface Scenario {
  trigger: string
  response: string
}

interface PlaybookForm {
  name: string
  description: string
  intent_triggers: string
  is_default: boolean
  greeting_message: string
  instructions: string
  tone: string
  dos: string[]
  donts: string[]
  scenarios: Scenario[]
  out_of_scope_response: string
  fallback_response: string
  escalation_message: string
}

const EMPTY_FORM: PlaybookForm = {
  name: '',
  description: '',
  intent_triggers: '',
  is_default: false,
  greeting_message: '',
  instructions: '',
  tone: 'professional',
  dos: [],
  donts: [],
  scenarios: [],
  out_of_scope_response: '',
  fallback_response: '',
  escalation_message: '',
}

function TagInput({
  items,
  onChange,
  placeholder,
}: {
  items: string[]
  onChange: (items: string[]) => void
  placeholder?: string
}) {
  const [input, setInput] = useState('')

  const add = () => {
    const val = input.trim()
    if (val && !items.includes(val)) {
      onChange([...items, val])
    }
    setInput('')
  }

  return (
    <div>
      <div className="flex flex-wrap gap-1.5 mb-2">
        {items.map((item, i) => (
          <span
            key={i}
            className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full bg-violet-50 dark:bg-violet-900/20 text-violet-700 dark:text-violet-300 text-xs font-medium"
          >
            {item}
            <button
              type="button"
              onClick={() => onChange(items.filter((_, idx) => idx !== i))}
              className="text-violet-400 hover:text-violet-600 ml-0.5"
            >
              <X size={10} />
            </button>
          </span>
        ))}
      </div>
      <div className="flex gap-2">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ',') {
              e.preventDefault()
              add()
            }
          }}
          placeholder={placeholder || 'Type and press Enter'}
          className="flex-1 px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm focus:outline-none focus:ring-1 focus:ring-violet-500"
        />
        <button
          type="button"
          onClick={add}
          className="px-3 py-2 rounded-lg bg-violet-100 dark:bg-violet-900/30 text-violet-700 dark:text-violet-300 text-sm hover:bg-violet-200 transition-colors"
        >
          Add
        </button>
      </div>
    </div>
  )
}

function ScenarioEditor({
  scenarios,
  onChange,
}: {
  scenarios: Scenario[]
  onChange: (s: Scenario[]) => void
}) {
  const addScenario = () =>
    onChange([...scenarios, { trigger: '', response: '' }])

  const update = (i: number, field: keyof Scenario, val: string) => {
    const updated = scenarios.map((s, idx) =>
      idx === i ? { ...s, [field]: val } : s
    )
    onChange(updated)
  }

  return (
    <div className="space-y-3">
      {scenarios.map((s, i) => (
        <div
          key={i}
          className="p-3 rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800/50 space-y-2"
        >
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-gray-500">
              Scenario {i + 1}
            </span>
            <button
              type="button"
              onClick={() => onChange(scenarios.filter((_, idx) => idx !== i))}
              className="text-gray-400 hover:text-red-500"
            >
              <X size={14} />
            </button>
          </div>
          <input
            value={s.trigger}
            onChange={(e) => update(i, 'trigger', e.target.value)}
            placeholder="Trigger (e.g. user asks about refunds)"
            className="w-full px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm focus:outline-none focus:ring-1 focus:ring-violet-500"
          />
          <textarea
            value={s.response}
            onChange={(e) => update(i, 'response', e.target.value)}
            placeholder="Response to give in this scenario"
            rows={2}
            className="w-full px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm focus:outline-none focus:ring-1 focus:ring-violet-500 resize-none"
          />
        </div>
      ))}
      <button
        type="button"
        onClick={addScenario}
        className="inline-flex items-center gap-1.5 text-sm text-violet-600 dark:text-violet-400 hover:text-violet-800 transition-colors"
      >
        <Plus size={14} /> Add scenario
      </button>
    </div>
  )
}

function PlaybookFormPanel({
  agentId,
  initial,
  onClose,
}: {
  agentId: string
  initial?: { id: string } & Record<string, unknown>
  onClose: () => void
}) {
  const qc = useQueryClient()
  const [form, setForm] = useState<PlaybookForm>(() => {
    if (initial) {
      return {
        name: (initial.name as string) || '',
        description: (initial.description as string) || '',
        intent_triggers: Array.isArray(initial.intent_triggers)
          ? (initial.intent_triggers as string[]).join(', ')
          : (initial.intent_triggers as string) || '',
        is_default: !!(initial.is_default),
        greeting_message: (initial.greeting_message as string) || '',
        instructions: (initial.instructions as string) || '',
        tone: (initial.tone as string) || 'professional',
        dos: Array.isArray(initial.dos) ? (initial.dos as string[]) : [],
        donts: Array.isArray(initial.donts) ? (initial.donts as string[]) : [],
        scenarios: Array.isArray(initial.scenarios)
          ? (initial.scenarios as Scenario[])
          : [],
        out_of_scope_response: (initial.out_of_scope_response as string) || '',
        fallback_response: (initial.fallback_response as string) || '',
        escalation_message:
          (initial.custom_escalation_message as string) ||
          (initial.escalation_message as string) ||
          '',
      }
    }
    return EMPTY_FORM
  })

  const [expanded, setExpanded] = useState<Record<string, boolean>>({
    basic: true,
    content: false,
    advanced: false,
  })

  const toggle = (section: string) =>
    setExpanded((p) => ({ ...p, [section]: !p[section] }))

  const saveMutation = useMutation({
    mutationFn: (data: Record<string, unknown>) => {
      if (initial?.id) {
        return playbooksApi.update(agentId, initial.id as string, data)
      }
      return playbooksApi.create(agentId, data)
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['playbooks', agentId] })
      toast.success(initial ? 'Playbook updated!' : 'Playbook created!')
      onClose()
    },
    onError: (e: any) =>
      toast.error(e?.response?.data?.detail || 'Failed to save playbook'),
  })

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    const triggers = form.intent_triggers
      .split(',')
      .map((t) => t.trim())
      .filter(Boolean)
    saveMutation.mutate({
      ...form,
      intent_triggers: triggers,
      custom_escalation_message: form.escalation_message,
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
      <div className="w-full max-w-xl bg-white dark:bg-gray-900 shadow-2xl flex flex-col overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200 dark:border-gray-800">
          <h2 className="text-base font-semibold text-gray-900 dark:text-white">
            {initial ? 'Edit Playbook' : 'New Playbook'}
          </h2>
          <button
            onClick={onClose}
            className="p-1.5 text-gray-400 hover:text-gray-600 transition-colors"
          >
            <X size={18} />
          </button>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} className="flex-1 overflow-y-auto p-6 space-y-5">
          {/* Basic section */}
          <div>
            <button
              type="button"
              onClick={() => toggle('basic')}
              className="flex items-center justify-between w-full text-sm font-semibold text-gray-700 dark:text-gray-300 mb-3"
            >
              Basic Information
              {expanded.basic ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
            </button>
            {expanded.basic && (
              <div className="space-y-4">
                <div>
                  <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
                    Name *
                  </label>
                  <input
                    required
                    value={form.name}
                    onChange={(e) => setForm((p) => ({ ...p, name: e.target.value }))}
                    placeholder="e.g. Order Support Playbook"
                    className={inputCls}
                  />
                </div>

                <div>
                  <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
                    Description — when is this playbook used?
                  </label>
                  <input
                    value={form.description}
                    onChange={(e) => setForm((p) => ({ ...p, description: e.target.value }))}
                    placeholder="Used when customers ask about orders..."
                    className={inputCls}
                  />
                </div>

                <div>
                  <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
                    Intent Triggers (comma-separated keywords)
                  </label>
                  <input
                    value={form.intent_triggers}
                    onChange={(e) => setForm((p) => ({ ...p, intent_triggers: e.target.value }))}
                    placeholder="order, tracking, delivery, shipment"
                    className={inputCls}
                  />
                </div>

                <div className="flex items-center gap-3">
                  <input
                    type="checkbox"
                    id="is_default"
                    checked={form.is_default}
                    onChange={(e) => setForm((p) => ({ ...p, is_default: e.target.checked }))}
                    className="w-4 h-4 accent-violet-600"
                  />
                  <label htmlFor="is_default" className="text-sm text-gray-700 dark:text-gray-300">
                    Set as default playbook
                  </label>
                </div>

                <div>
                  <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
                    Tone
                  </label>
                  <select
                    value={form.tone}
                    onChange={(e) => setForm((p) => ({ ...p, tone: e.target.value }))}
                    className={inputCls}
                  >
                    <option value="professional">Professional</option>
                    <option value="friendly">Friendly</option>
                    <option value="casual">Casual</option>
                    <option value="empathetic">Empathetic</option>
                  </select>
                </div>

                <div>
                  <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
                    Greeting Message
                  </label>
                  <input
                    value={form.greeting_message}
                    onChange={(e) => setForm((p) => ({ ...p, greeting_message: e.target.value }))}
                    placeholder="Hello! How can I help you today?"
                    className={inputCls}
                  />
                </div>
              </div>
            )}
          </div>

          <hr className="border-gray-100 dark:border-gray-800" />

          {/* Content section */}
          <div>
            <button
              type="button"
              onClick={() => toggle('content')}
              className="flex items-center justify-between w-full text-sm font-semibold text-gray-700 dark:text-gray-300 mb-3"
            >
              Instructions & Content
              {expanded.content ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
            </button>
            {expanded.content && (
              <div className="space-y-4">
                <div>
                  <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
                    Instructions
                  </label>
                  <textarea
                    value={form.instructions}
                    onChange={(e) => setForm((p) => ({ ...p, instructions: e.target.value }))}
                    rows={5}
                    placeholder="Detailed instructions for how the agent should behave..."
                    className={`${inputCls} resize-none`}
                  />
                </div>

                <div>
                  <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-2">
                    Do&apos;s
                  </label>
                  <TagInput
                    items={form.dos}
                    onChange={(items) => setForm((p) => ({ ...p, dos: items }))}
                    placeholder="Add a guideline and press Enter"
                  />
                </div>

                <div>
                  <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-2">
                    Don&apos;ts
                  </label>
                  <TagInput
                    items={form.donts}
                    onChange={(items) => setForm((p) => ({ ...p, donts: items }))}
                    placeholder="Add a restriction and press Enter"
                  />
                </div>

                <div>
                  <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-2">
                    Scenarios
                  </label>
                  <ScenarioEditor
                    scenarios={form.scenarios}
                    onChange={(s) => setForm((p) => ({ ...p, scenarios: s }))}
                  />
                </div>
              </div>
            )}
          </div>

          <hr className="border-gray-100 dark:border-gray-800" />

          {/* Advanced section */}
          <div>
            <button
              type="button"
              onClick={() => toggle('advanced')}
              className="flex items-center justify-between w-full text-sm font-semibold text-gray-700 dark:text-gray-300 mb-3"
            >
              Fallbacks & Escalation
              {expanded.advanced ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
            </button>
            {expanded.advanced && (
              <div className="space-y-4">
                <div>
                  <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
                    Out of Scope Response
                  </label>
                  <textarea
                    value={form.out_of_scope_response}
                    onChange={(e) => setForm((p) => ({ ...p, out_of_scope_response: e.target.value }))}
                    rows={2}
                    placeholder="I'm sorry, that's outside the scope of what I can help with..."
                    className={`${inputCls} resize-none`}
                  />
                </div>

                <div>
                  <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
                    Fallback Response
                  </label>
                  <textarea
                    value={form.fallback_response}
                    onChange={(e) => setForm((p) => ({ ...p, fallback_response: e.target.value }))}
                    rows={2}
                    placeholder="I didn't quite understand that. Could you rephrase?"
                    className={`${inputCls} resize-none`}
                  />
                </div>

                <div>
                  <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
                    Escalation Message
                  </label>
                  <textarea
                    value={form.escalation_message}
                    onChange={(e) => setForm((p) => ({ ...p, escalation_message: e.target.value }))}
                    rows={2}
                    placeholder="I'll connect you with a human agent now..."
                    className={`${inputCls} resize-none`}
                  />
                </div>
              </div>
            )}
          </div>
        </form>

        {/* Footer */}
        <div className="px-6 py-4 border-t border-gray-200 dark:border-gray-800 flex items-center justify-end gap-3">
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-2 rounded-lg border border-gray-200 dark:border-gray-700 text-sm text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={handleSubmit as unknown as React.MouseEventHandler}
            disabled={saveMutation.isPending}
            className="px-5 py-2 rounded-lg bg-gradient-to-r from-violet-600 to-blue-600 text-white text-sm font-medium hover:opacity-90 disabled:opacity-50 transition-opacity"
          >
            {saveMutation.isPending ? 'Saving…' : initial ? 'Update Playbook' : 'Create Playbook'}
          </button>
        </div>
      </div>
    </div>
  )
}

export default function PlaybooksPage() {
  const params = useParams()
  const agentId = params.id as string
  const qc = useQueryClient()

  const [showForm, setShowForm] = useState(false)
  const [editing, setEditing] = useState<Record<string, unknown> | null>(null)

  const { data: playbooks, isLoading } = useQuery({
    queryKey: ['playbooks', agentId],
    queryFn: () => playbooksApi.list(agentId),
    enabled: !!agentId,
  })

  const deleteMutation = useMutation({
    mutationFn: (pbId: string) => playbooksApi.delete(agentId, pbId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['playbooks', agentId] })
      toast.success('Playbook deleted')
    },
    onError: () => toast.error('Failed to delete playbook'),
  })

  const setDefaultMutation = useMutation({
    mutationFn: (pbId: string) => playbooksApi.setDefault(agentId, pbId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['playbooks', agentId] })
      toast.success('Default playbook updated')
    },
    onError: () => toast.error('Failed to set default'),
  })

  const items: any[] = Array.isArray(playbooks)
    ? playbooks
    : (playbooks as any)?.items || []

  return (
    <div className="p-8 max-w-4xl">
      {/* Breadcrumbs */}
      <div className="flex items-center gap-2 text-sm text-gray-500 dark:text-gray-400 mb-6">
        <Link href="/dashboard/agents" className="hover:text-gray-900 dark:hover:text-white transition-colors">
          Agents
        </Link>
        <span>/</span>
        <Link href={`/dashboard/agents/${agentId}`} className="hover:text-gray-900 dark:hover:text-white transition-colors">
          Agent
        </Link>
        <span>/</span>
        <span className="text-gray-900 dark:text-white font-medium">Playbooks</span>
      </div>

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
            <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Playbooks</h1>
          </div>
          <p className="text-gray-500 dark:text-gray-400 ml-9">
            Define conversation playbooks for different intents and scenarios.
          </p>
        </div>
        <button
          onClick={() => {
            setEditing(null)
            setShowForm(true)
          }}
          className="inline-flex items-center gap-2 px-4 py-2.5 rounded-lg bg-gradient-to-r from-violet-600 to-blue-600 text-white text-sm font-medium hover:opacity-90 transition-opacity"
        >
          <Plus size={16} /> New Playbook
        </button>
      </div>

      {/* Content */}
      {isLoading ? (
        <div className="space-y-3">
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-24 rounded-xl bg-gray-100 dark:bg-gray-800 animate-pulse" />
          ))}
        </div>
      ) : items.length === 0 ? (
        <div className="text-center py-16 bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800">
          <BookOpen size={40} className="mx-auto mb-3 text-gray-300 dark:text-gray-600" />
          <h3 className="text-base font-semibold text-gray-900 dark:text-white mb-1">
            No playbooks yet
          </h3>
          <p className="text-sm text-gray-500 mb-4">
            Create playbooks to define how your agent responds in specific situations.
          </p>
          <button
            onClick={() => {
              setEditing(null)
              setShowForm(true)
            }}
            className="inline-flex items-center gap-2 px-4 py-2.5 rounded-lg bg-violet-600 text-white text-sm font-medium hover:bg-violet-700 transition-colors"
          >
            <Plus size={16} /> Create first playbook
          </button>
        </div>
      ) : (
        <div className="space-y-3">
          {items.map((pb: any) => {
            const triggers: string[] = Array.isArray(pb.intent_triggers)
              ? pb.intent_triggers
              : typeof pb.intent_triggers === 'string' && pb.intent_triggers
              ? pb.intent_triggers.split(',').map((t: string) => t.trim()).filter(Boolean)
              : []

            return (
              <div
                key={pb.id}
                className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 p-5"
              >
                <div className="flex items-start justify-between gap-4">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1">
                      <h3 className="text-sm font-semibold text-gray-900 dark:text-white">
                        {pb.name}
                      </h3>
                      {pb.is_default && (
                        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-amber-50 dark:bg-amber-900/20 text-amber-700 dark:text-amber-300 text-xs font-medium">
                          <Star size={10} fill="currentColor" /> Default
                        </span>
                      )}
                    </div>
                    {pb.description && (
                      <p className="text-sm text-gray-500 mb-2">{pb.description}</p>
                    )}
                    {triggers.length > 0 && (
                      <div className="flex flex-wrap gap-1.5">
                        {triggers.map((t: string, i: number) => (
                          <span
                            key={i}
                            className="px-2 py-0.5 rounded-full bg-violet-50 dark:bg-violet-900/20 text-violet-700 dark:text-violet-300 text-xs"
                          >
                            {t}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                  <div className="flex items-center gap-2 flex-shrink-0">
                    {!pb.is_default && (
                      <button
                        onClick={() => setDefaultMutation.mutate(pb.id)}
                        disabled={setDefaultMutation.isPending}
                        className="px-3 py-1.5 rounded-lg border border-gray-200 dark:border-gray-700 text-xs text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors disabled:opacity-50"
                        title="Set as default"
                      >
                        Set default
                      </button>
                    )}
                    <button
                      onClick={() => {
                        setEditing(pb)
                        setShowForm(true)
                      }}
                      className="p-2 text-gray-400 hover:text-violet-600 transition-colors"
                      title="Edit"
                    >
                      <Edit2 size={15} />
                    </button>
                    <button
                      onClick={() =>
                        confirm('Delete this playbook?') && deleteMutation.mutate(pb.id)
                      }
                      className="p-2 text-gray-400 hover:text-red-500 transition-colors"
                      title="Delete"
                    >
                      <Trash2 size={15} />
                    </button>
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      )}

      {/* Slide-in panel */}
      {showForm && (
        <PlaybookFormPanel
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
