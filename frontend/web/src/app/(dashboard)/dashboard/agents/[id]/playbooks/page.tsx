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
  BoxSelect,
  Save,
} from 'lucide-react'
import { variablesApi, toolsApi, documentsApi } from '@/lib/api'
import { PlaybookMentionsEditor } from '@/components/PlaybookMentionsEditor'

interface Scenario {
  trigger: string
  response: string
}

interface PlaybookForm {
  name: string
  description: string
  intent_triggers: string
  instructions: string
  tone: string
  dos: string[]
  donts: string[]
  scenarios: Scenario[]
  out_of_scope_response: string
  fallback_response: string
  escalation_message: string
  tools: string[]
  input_schema: string
  output_schema: string
}

const EMPTY_FORM: PlaybookForm = {
  name: '',
  description: '',
  intent_triggers: '',
  instructions: '',
  tone: 'professional',
  dos: [],
  donts: [],
  scenarios: [],
  out_of_scope_response: '',
  fallback_response: '',
  escalation_message: '',
  tools: [],
  input_schema: '',
  output_schema: '',
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
  tools,
  variables,
  documents,
}: {
  scenarios: Scenario[]
  onChange: (s: Scenario[]) => void
  tools: any[]
  variables: any[]
  documents: any[]
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
          <PlaybookMentionsEditor
            value={s.response}
            onChange={(val) => update(i, 'response', val)}
            placeholder="Response to give in this scenario"
            tools={tools}
            variables={variables}
            documents={documents}
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

function LocalVariablesSection({ agentId, playbookId }: { agentId: string; playbookId: string }) {
  const qc = useQueryClient()
  const { data: variables, isLoading } = useQuery({
    queryKey: ['variables', agentId],
    queryFn: () => variablesApi.list(agentId),
    enabled: !!agentId,
  })

  const [form, setForm] = useState({ id: '', name: '', data_type: 'string', default_value: '' })
  const [editing, setEditing] = useState(false)

  const saveMutation = useMutation({
    mutationFn: (data: Record<string, unknown>) => {
      if (form.id) {
        return variablesApi.update(agentId, form.id, data)
      }
      return variablesApi.create(agentId, data)
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['variables', agentId] })
      toast.success(form.id ? 'Local variable updated' : 'Local variable created')
      setEditing(false)
      setForm({ id: '', name: '', data_type: 'string', default_value: '' })
    },
    onError: (e: any) => toast.error(e?.response?.data?.detail || 'Failed to save variable'),
  })

  const deleteMutation = useMutation({
    mutationFn: (vId: string) => variablesApi.delete(agentId, vId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['variables', agentId] })
      toast.success('Local variable deleted')
    },
  })

  const locals = Array.isArray(variables) 
    ? variables.filter((v: any) => v.playbook_id === playbookId && v.scope === 'local') 
    : []

  if (isLoading) return <div className="animate-pulse bg-gray-100 dark:bg-gray-800 h-10 rounded" />

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
          Playbook-Local Variables
        </label>
        {!editing && (
          <button
            type="button"
            onClick={() => {
              setForm({ id: '', name: '', data_type: 'string', default_value: '' })
              setEditing(true)
            }}
            className="text-xs flex items-center gap-1 text-violet-600 hover:text-violet-700 dark:text-violet-400 font-medium"
          >
            <Plus size={14} /> New Variable
          </button>
        )}
      </div>

      {locals.length === 0 && !editing ? (
        <div className="text-xs text-center py-4 bg-gray-50 dark:bg-gray-800/50 rounded-lg text-gray-500 border border-dashed border-gray-300 dark:border-gray-700">
          No local variables yet. These variables only exist while this playbook is active.
        </div>
      ) : (
        <div className="space-y-2">
          {locals.map((v: any) => (
            <div key={v.id} className="flex items-center justify-between p-2.5 bg-gray-50 dark:bg-gray-800/50 rounded-lg border border-gray-200 dark:border-gray-700">
              <div className="flex flex-col">
                <div className="flex items-center gap-2">
                  <BoxSelect size={14} className="text-orange-500" />
                  <span className="text-sm font-bold font-mono text-gray-900 dark:text-white">{v.name}</span>
                  <span className="text-[10px] px-1.5 py-0.5 rounded bg-gray-200 dark:bg-gray-700 text-gray-600 dark:text-gray-300 uppercase font-bold tracking-wider">{v.data_type}</span>
                </div>
                {v.default_value && (
                  <span className="text-xs text-gray-500 mt-1 pl-6">Default: {JSON.stringify(v.default_value)}</span>
                )}
              </div>
              <div className="flex items-center gap-1">
                <button
                  type="button"
                  onClick={() => {
                    setForm({
                      id: v.id,
                      name: v.name,
                      data_type: v.data_type,
                      default_value: v.default_value ? JSON.stringify(v.default_value) : ''
                    })
                    setEditing(true)
                  }}
                  className="p-1 text-gray-400 hover:text-violet-500 transition-colors"
                >
                  <Edit2 size={14} />
                </button>
                <button
                  type="button"
                  onClick={() => confirm('Delete local variable?') && deleteMutation.mutate(v.id)}
                  className="p-1 text-gray-400 hover:text-red-500 transition-colors"
                >
                  <Trash2 size={14} />
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {editing && (
        <div className="p-3 bg-white dark:bg-gray-900 border border-violet-200 dark:border-violet-900/50 rounded-lg shadow-sm space-y-3">
          <div className="flex gap-2">
            <input
              autoFocus
              value={form.name}
              onChange={(e) => setForm((p) => ({ ...p, name: e.target.value.replace(/[^a-zA-Z0-9_]/g, '') }))}
              placeholder="Variable Name"
              className="flex-1 px-3 py-1.5 rounded-md border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-sm focus:outline-none focus:ring-1 focus:ring-violet-500"
            />
            <select
              value={form.data_type}
              onChange={(e) => setForm((p) => ({ ...p, data_type: e.target.value }))}
              className="w-28 px-2 py-1.5 rounded-md border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-sm focus:outline-none focus:ring-1 focus:ring-violet-500"
            >
              <option value="string">String</option>
              <option value="number">Number</option>
              <option value="boolean">Boolean</option>
              <option value="object">JSON</option>
            </select>
          </div>
          <input
            value={form.default_value}
            onChange={(e) => setForm((p) => ({ ...p, default_value: e.target.value }))}
            placeholder="Default value (optional)"
            className="w-full px-3 py-1.5 font-mono text-xs rounded-md border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 focus:outline-none focus:ring-1 focus:ring-violet-500"
          />
          <div className="flex gap-2 justify-end">
            <button
              type="button"
              onClick={() => {
                setEditing(false)
                setForm({ id: '', name: '', data_type: 'string', default_value: '' })
              }}
              className="text-xs px-3 py-1.5 text-gray-500 hover:text-gray-700 transition-colors"
            >
              Cancel
            </button>
            <button
              type="button"
              disabled={!form.name || saveMutation.isPending}
              onClick={() => {
                let parsedDefault = null
                if (form.default_value) {
                  try { parsedDefault = JSON.parse(form.default_value) }
                  catch { parsedDefault = form.default_value }
                }
                saveMutation.mutate({
                  name: form.name,
                  scope: 'local',
                  playbook_id: playbookId,
                  data_type: form.data_type,
                  default_value: parsedDefault,
                })
              }}
              className="text-xs px-3 py-1.5 bg-violet-600 hover:bg-violet-700 text-white font-medium rounded transition-colors disabled:opacity-50"
            >
              <span className="flex items-center gap-1"><Save size={12} /> Save</span>
            </button>
          </div>
        </div>
      )}
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
      const cfg = (initial.config || {}) as Record<string, any>
      return {
        name: (initial.name as string) || '',
        description: (initial.description as string) || '',
        intent_triggers: Array.isArray(initial.intent_triggers)
          ? (initial.intent_triggers as string[]).join(', ')
          : (initial.intent_triggers as string) || '',
        instructions: (cfg.instructions as string) || (initial.instructions as string) || '',
        tone: (cfg.tone as string) || (initial.tone as string) || 'professional',
        dos: Array.isArray(cfg.dos) ? (cfg.dos as string[]) : Array.isArray(initial.dos) ? (initial.dos as string[]) : [],
        donts: Array.isArray(cfg.donts) ? (cfg.donts as string[]) : Array.isArray(initial.donts) ? (initial.donts as string[]) : [],
        scenarios: Array.isArray(cfg.scenarios) ? (cfg.scenarios as Scenario[]) : Array.isArray(initial.scenarios) ? (initial.scenarios as Scenario[]) : [],
        out_of_scope_response: (cfg.out_of_scope_response as string) || (initial.out_of_scope_response as string) || '',
        fallback_response: (cfg.fallback_response as string) || (initial.fallback_response as string) || '',
        escalation_message: (cfg.custom_escalation_message as string) || (initial.custom_escalation_message as string) || (initial.escalation_message as string) || '',
        tools: Array.isArray(cfg.tools) ? (cfg.tools as string[]) : Array.isArray(initial.tools) ? (initial.tools as string[]) : [],
        input_schema: cfg.input_schema ? JSON.stringify(cfg.input_schema, null, 2) : initial.input_schema ? JSON.stringify(initial.input_schema as object, null, 2) : '',
        output_schema: cfg.output_schema ? JSON.stringify(cfg.output_schema, null, 2) : initial.output_schema ? JSON.stringify(initial.output_schema as object, null, 2) : '',
      }
    }
    return EMPTY_FORM
  })

  const [expanded, setExpanded] = useState<Record<string, boolean>>({
    basic: true,
    content: false,
    tools: false,
    advanced: false,
  })

  const toggle = (section: string) =>
    setExpanded((p) => ({ ...p, [section]: !p[section] }))

  const { data: variables = [] } = useQuery({
    queryKey: ['variables', agentId],
    queryFn: () => variablesApi.list(agentId),
  })

  const { data: tools = [] } = useQuery({
    queryKey: ['tools', agentId],
    queryFn: () => toolsApi.list(agentId),
  })

  const { data: documents = [] } = useQuery({
    queryKey: ['documents', agentId],
    queryFn: () => documentsApi.list(agentId),
  })

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
      
    let parsedInput = null
    let parsedOutput = null
    try {
      if (form.input_schema?.trim()) parsedInput = JSON.parse(form.input_schema.trim())
      if (form.output_schema?.trim()) parsedOutput = JSON.parse(form.output_schema.trim())
    } catch (e) {
      toast.error("Invalid JSON inside Input or Output Schema")
      return
    }

    // B7 FIX: Backend PlaybookUpsert reads content fields exclusively from the
    // nested `config` object. Sending them flat causes silent data loss.
    const config: Record<string, unknown> = {
      instructions: form.instructions,
      tone: form.tone,
      dos: form.dos,
      donts: form.donts,
      scenarios: form.scenarios,
      out_of_scope_response: form.out_of_scope_response,
      fallback_response: form.fallback_response,
      custom_escalation_message: form.escalation_message,
      tools: form.tools,
    }
    if (parsedInput !== null) config.input_schema = parsedInput
    if (parsedOutput !== null) config.output_schema = parsedOutput

    saveMutation.mutate({
      name: form.name,
      description: form.description,
      intent_triggers: triggers,
      is_active: true,
      config,
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
                  <PlaybookMentionsEditor
                    value={form.instructions}
                    onChange={(val) => setForm((p) => ({ ...p, instructions: val }))}
                    tools={tools}
                    variables={variables}
                    documents={documents}
                    placeholder="Detailed instructions... Use $tools:, $vars:, or $rag: to reference context."
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
                    tools={tools}
                    variables={variables}
                    documents={documents}
                  />
                </div>
              </div>
            )}
          </div>

          <hr className="border-gray-100 dark:border-gray-800" />

          {/* Tools & Data section */}
          <div>
            <button
              type="button"
              onClick={() => toggle('tools')}
              className="flex items-center justify-between w-full text-sm font-semibold text-gray-700 dark:text-gray-300 mb-3"
            >
              Tools & Variables
              {expanded.tools ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
            </button>
            {expanded.tools && (
              <div className="space-y-4">
                <div>
                  <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-2">
                    Available Tools
                  </label>
                  <TagInput
                    items={form.tools}
                    onChange={(items) => setForm((p) => ({ ...p, tools: items }))}
                    placeholder="E.g. cancel_order, get_shipping_status"
                  />
                  <p className="text-xs text-gray-400 mt-1">Specify tool names the agent can call while in this playbook.</p>
                </div>
                
                <div>
                  <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
                    Input Schema (JSON)
                  </label>
                  <textarea
                    value={form.input_schema}
                    onChange={(e) => setForm((p) => ({ ...p, input_schema: e.target.value }))}
                    rows={4}
                    placeholder={'{\n  "type": "object",\n  "properties": {}\n}'}
                    className={`${inputCls} font-mono text-xs resize-none`}
                  />
                </div>

                <div>
                  <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
                    Output Schema (JSON)
                  </label>
                  <textarea
                    value={form.output_schema}
                    onChange={(e) => setForm((p) => ({ ...p, output_schema: e.target.value }))}
                    rows={4}
                    placeholder={'{\n  "type": "object",\n  "properties": {}\n}'}
                    className={`${inputCls} font-mono text-xs resize-none`}
                  />
                </div>

                {initial?.id ? (
                  <LocalVariablesSection agentId={agentId} playbookId={initial.id as string} />
                ) : (
                  <div className="text-xs text-gray-400 italic p-3 bg-gray-50 dark:bg-gray-800/50 rounded text-center">
                    Save the playbook to add Playbook-Local Variables.
                  </div>
                )}
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
                  <PlaybookMentionsEditor
                    value={form.out_of_scope_response}
                    onChange={(val) => setForm((p) => ({ ...p, out_of_scope_response: val }))}
                    tools={tools}
                    variables={variables}
                    documents={documents}
                    placeholder="I'm sorry, that's outside the scope of what I can help with..."
                  />
                </div>

                <div>
                  <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
                    Fallback Response
                  </label>
                  <PlaybookMentionsEditor
                    value={form.fallback_response}
                    onChange={(val) => setForm((p) => ({ ...p, fallback_response: val }))}
                    tools={tools}
                    variables={variables}
                    documents={documents}
                    placeholder="I didn't quite understand that. Could you rephrase?"
                  />
                </div>

                <div>
                  <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
                    Escalation Message
                  </label>
                  <PlaybookMentionsEditor
                    value={form.escalation_message}
                    onChange={(val) => setForm((p) => ({ ...p, escalation_message: val }))}
                    tools={tools}
                    variables={variables}
                    documents={documents}
                    placeholder="I'll connect you with a human agent now..."
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
  const [editing, setEditing] = useState<{ id: string } & Record<string, unknown> | null>(null)

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



  const items: any[] = Array.isArray(playbooks)
    ? playbooks
    : (playbooks as any)?.items || []

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
                    </div>
                    {pb.description && (
                      <p className="text-xs text-gray-500 mb-2 italic">{pb.description}</p>
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
