'use client'

import { useState, useEffect } from 'react'
import { useParams, useRouter } from 'next/navigation'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { guardrailsApi, agentsApi, platformApi, GlobalGuardrail } from '@/lib/api'
import toast from 'react-hot-toast'
import Link from 'next/link'
import {
  Shield, ChevronLeft, Plus, X, AlertTriangle, CheckCircle2, Save, Trash2, Info,
  Lock, Send, Pencil, Globe, UserCheck, Eye, EyeOff, MessageSquareWarning,
} from 'lucide-react'

// ─── Fetch global guardrails from platform settings (admin-controlled) ──

async function fetchPlatformGlobalGuardrails(): Promise<GlobalGuardrail[]> {
  try {
    const data = await platformApi.getGlobalGuardrails()
    return data.guardrails || []
  } catch {
    return []
  }
}

const CATEGORY_COLORS: Record<string, string> = {
  Security: 'bg-red-50 text-red-700 dark:bg-red-900/20 dark:text-red-300',
  Safety: 'bg-amber-50 text-amber-700 dark:bg-amber-900/20 dark:text-amber-300',
  Confirmation: 'bg-blue-50 text-blue-700 dark:bg-blue-900/20 dark:text-blue-300',
  Concurrency: 'bg-violet-50 text-violet-700 dark:bg-violet-900/20 dark:text-violet-300',
  'Voice UX': 'bg-emerald-50 text-emerald-700 dark:bg-emerald-900/20 dark:text-emerald-300',
  Privacy: 'bg-pink-50 text-pink-700 dark:bg-pink-900/20 dark:text-pink-300',
}

// ─── Tag input ───────────────────────────────────────────────────────────────

function TagInput({
  tags,
  onChange,
  placeholder,
}: {
  tags: string[]
  onChange: (v: string[]) => void
  placeholder: string
}) {
  const [input, setInput] = useState('')

  const add = () => {
    const v = input.trim()
    if (v && !tags.includes(v)) {
      onChange([...tags, v])
    }
    setInput('')
  }

  return (
    <div className="flex flex-wrap gap-1.5 p-2 min-h-[44px] rounded-xl border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 focus-within:ring-1 focus-within:ring-violet-500">
      {tags.map((tag) => (
        <span
          key={tag}
          className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full bg-violet-100 dark:bg-violet-900/40 text-violet-700 dark:text-violet-300 text-xs font-medium"
        >
          {tag}
          <button
            type="button"
            onClick={() => onChange(tags.filter((t) => t !== tag))}
            className="hover:text-violet-900 dark:hover:text-violet-100"
          >
            <X size={10} />
          </button>
        </span>
      ))}
      <input
        value={input}
        onChange={(e) => setInput(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ',') {
            e.preventDefault()
            add()
          }
          if (e.key === 'Backspace' && !input && tags.length) {
            onChange(tags.slice(0, -1))
          }
        }}
        onBlur={add}
        placeholder={tags.length === 0 ? placeholder : ''}
        className="flex-1 min-w-[120px] bg-transparent text-sm text-gray-900 dark:text-white outline-none placeholder-gray-400"
      />
    </div>
  )
}

// ─── Section wrapper ──────────────────────────────────────────────────────────

function Section({
  title,
  description,
  children,
  icon,
}: {
  title: string
  description?: string
  children: React.ReactNode
  icon?: React.ReactNode
}) {
  return (
    <div className="bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-800 p-6">
      <div className="mb-5 flex items-start gap-3">
        {icon && <div className="mt-0.5">{icon}</div>}
        <div>
          <h2 className="text-base font-semibold text-gray-900 dark:text-white">{title}</h2>
          {description && (
            <p className="text-sm text-gray-500 dark:text-gray-400 mt-0.5">{description}</p>
          )}
        </div>
      </div>
      {children}
    </div>
  )
}

// ─── Toggle ───────────────────────────────────────────────────────────────────

function Toggle({
  checked,
  onChange,
  label,
  description,
}: {
  checked: boolean
  onChange: (v: boolean) => void
  label: string
  description?: string
}) {
  return (
    <label className="flex items-start gap-3 cursor-pointer">
      <div className="relative mt-0.5">
        <input
          type="checkbox"
          checked={checked}
          onChange={(e) => onChange(e.target.checked)}
          className="sr-only"
        />
        <div
          className={`w-10 h-5 rounded-full transition-colors ${
            checked ? 'bg-violet-600' : 'bg-gray-200 dark:bg-gray-700'
          }`}
        />
        <div
          className={`absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform ${
            checked ? 'translate-x-5' : ''
          }`}
        />
      </div>
      <div>
        <p className="text-sm font-medium text-gray-900 dark:text-white">{label}</p>
        {description && (
          <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">{description}</p>
        )}
      </div>
    </label>
  )
}

// ─── Change Request Modal ────────────────────────────────────────────────────

function ChangeRequestModal({
  guardrail,
  onClose,
  onSubmit,
}: {
  guardrail: { id: string; category: string; rule: string }
  onClose: () => void
  onSubmit: (proposedRule: string, reason: string) => void
}) {
  const [proposedRule, setProposedRule] = useState(guardrail.rule)
  const [reason, setReason] = useState('')
  const [submitting, setSubmitting] = useState(false)

  const handleSubmit = async () => {
    if (!reason.trim()) {
      toast.error('Please provide a reason for the change')
      return
    }
    setSubmitting(true)
    try {
      await onSubmit(proposedRule, reason)
      onClose()
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/60 z-50 flex items-center justify-center p-4">
      <div className="bg-white dark:bg-gray-900 rounded-2xl shadow-2xl w-full max-w-lg overflow-hidden">
        <div className="flex items-center justify-between px-6 py-5 border-b border-gray-100 dark:border-gray-800">
          <div>
            <h2 className="text-base font-semibold text-gray-900 dark:text-white">
              Request Guardrail Change
            </h2>
            <p className="text-xs text-gray-500 mt-0.5">
              {guardrail.id} — {guardrail.category}
            </p>
          </div>
          <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 text-gray-400">
            <X size={16} />
          </button>
        </div>

        <div className="px-6 py-5 space-y-4">
          <div>
            <label className="block text-xs font-medium text-gray-500 uppercase tracking-wider mb-1.5">
              Current Rule (read-only)
            </label>
            <div className="p-3 rounded-lg bg-gray-50 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 text-sm text-gray-600 dark:text-gray-400">
              {guardrail.rule}
            </div>
          </div>

          <div>
            <label className="block text-xs font-medium text-gray-500 uppercase tracking-wider mb-1.5">
              Proposed Rule
            </label>
            <textarea
              value={proposedRule}
              onChange={(e) => setProposedRule(e.target.value)}
              rows={3}
              className="w-full px-3 py-2 text-sm rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white focus:outline-none focus:ring-1 focus:ring-violet-500 resize-none"
            />
          </div>

          <div>
            <label className="block text-xs font-medium text-gray-500 uppercase tracking-wider mb-1.5">
              Reason for Change <span className="text-red-500">*</span>
            </label>
            <textarea
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              rows={3}
              placeholder="Explain why this guardrail should be modified..."
              className="w-full px-3 py-2 text-sm rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white focus:outline-none focus:ring-1 focus:ring-violet-500 resize-none"
            />
          </div>
        </div>

        <div className="px-6 py-4 border-t border-gray-100 dark:border-gray-800 flex justify-end gap-2 bg-gray-50/50 dark:bg-gray-800/50">
          <button
            onClick={onClose}
            className="px-4 py-2 rounded-lg border border-gray-200 dark:border-gray-700 text-sm text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-800"
          >
            Cancel
          </button>
          <button
            onClick={handleSubmit}
            disabled={submitting || !reason.trim()}
            className="flex items-center gap-2 px-5 py-2 rounded-lg bg-violet-600 text-white text-sm font-medium hover:bg-violet-700 disabled:opacity-50 transition-colors"
          >
            <Send size={14} />
            {submitting ? 'Submitting…' : 'Submit Request'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ─── Custom Guardrail Row ────────────────────────────────────────────────────

function CustomGuardrailRow({
  guardrail,
  onEdit,
  onDelete,
  onToggle,
}: {
  guardrail: { id: string; rule: string; category: string; is_active: boolean }
  onEdit: () => void
  onDelete: () => void
  onToggle: () => void
}) {
  return (
    <div className="flex items-start gap-3 p-4 rounded-xl border border-gray-200 dark:border-gray-700 bg-gray-50/50 dark:bg-gray-800/30 group">
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-1">
          <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${
            guardrail.is_active
              ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-900/20 dark:text-emerald-400'
              : 'bg-gray-100 text-gray-500 dark:bg-gray-800 dark:text-gray-400'
          }`}>
            {guardrail.is_active ? 'Active' : 'Inactive'}
          </span>
          {guardrail.category && (
            <span className="text-xs text-gray-400">{guardrail.category}</span>
          )}
        </div>
        <p className="text-sm text-gray-700 dark:text-gray-300">{guardrail.rule}</p>
      </div>
      <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
        <button
          onClick={onToggle}
          className="p-1.5 rounded-lg hover:bg-gray-200 dark:hover:bg-gray-700 text-gray-400 hover:text-gray-600 dark:hover:text-gray-300"
          title={guardrail.is_active ? 'Deactivate' : 'Activate'}
        >
          {guardrail.is_active ? <EyeOff size={14} /> : <Eye size={14} />}
        </button>
        <button
          onClick={onEdit}
          className="p-1.5 rounded-lg hover:bg-gray-200 dark:hover:bg-gray-700 text-gray-400 hover:text-gray-600 dark:hover:text-gray-300"
          title="Edit"
        >
          <Pencil size={14} />
        </button>
        <button
          onClick={onDelete}
          className="p-1.5 rounded-lg hover:bg-red-50 dark:hover:bg-red-900/20 text-gray-400 hover:text-red-500"
          title="Delete"
        >
          <Trash2 size={14} />
        </button>
      </div>
    </div>
  )
}

// ─── Custom Guardrail Form Modal ─────────────────────────────────────────────

function CustomGuardrailFormModal({
  guardrail,
  onClose,
  onSave,
}: {
  guardrail?: { id: string; rule: string; category: string; is_active: boolean } | null
  onClose: () => void
  onSave: (data: { rule: string; category: string }) => void
}) {
  const [rule, setRule] = useState(guardrail?.rule || '')
  const [category, setCategory] = useState(guardrail?.category || 'Custom')
  const [saving, setSaving] = useState(false)

  const handleSave = async () => {
    if (!rule.trim()) {
      toast.error('Rule description is required')
      return
    }
    setSaving(true)
    try {
      await onSave({ rule: rule.trim(), category })
      onClose()
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/60 z-50 flex items-center justify-center p-4">
      <div className="bg-white dark:bg-gray-900 rounded-2xl shadow-2xl w-full max-w-lg overflow-hidden">
        <div className="flex items-center justify-between px-6 py-5 border-b border-gray-100 dark:border-gray-800">
          <div>
            <h2 className="text-base font-semibold text-gray-900 dark:text-white">
              {guardrail ? 'Edit' : 'Add'} Custom Guardrail
            </h2>
            <p className="text-xs text-gray-500 mt-0.5">
              Agent-specific rules that supplement the global guardrails.
            </p>
          </div>
          <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 text-gray-400">
            <X size={16} />
          </button>
        </div>

        <div className="px-6 py-5 space-y-4">
          <div>
            <label className="block text-xs font-medium text-gray-500 uppercase tracking-wider mb-1.5">
              Category
            </label>
            <select
              value={category}
              onChange={(e) => setCategory(e.target.value)}
              className="w-full px-3 py-2.5 text-sm rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white focus:outline-none focus:ring-1 focus:ring-violet-500"
            >
              <option value="Custom">Custom</option>
              <option value="Security">Security</option>
              <option value="Safety">Safety</option>
              <option value="Compliance">Compliance</option>
              <option value="Tone">Tone</option>
              <option value="Scope">Scope</option>
              <option value="Data Handling">Data Handling</option>
            </select>
          </div>

          <div>
            <label className="block text-xs font-medium text-gray-500 uppercase tracking-wider mb-1.5">
              Rule Description <span className="text-red-500">*</span>
            </label>
            <textarea
              value={rule}
              onChange={(e) => setRule(e.target.value)}
              rows={4}
              placeholder="Describe the guardrail rule the agent must follow..."
              className="w-full px-3 py-2 text-sm rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white focus:outline-none focus:ring-1 focus:ring-violet-500 resize-none"
            />
            <p className="text-[10px] text-gray-400 mt-1">
              This rule will be injected into the agent system prompt alongside global guardrails.
            </p>
          </div>
        </div>

        <div className="px-6 py-4 border-t border-gray-100 dark:border-gray-800 flex justify-end gap-2 bg-gray-50/50 dark:bg-gray-800/50">
          <button
            onClick={onClose}
            className="px-4 py-2 rounded-lg border border-gray-200 dark:border-gray-700 text-sm text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-800"
          >
            Cancel
          </button>
          <button
            onClick={handleSave}
            disabled={saving || !rule.trim()}
            className="flex items-center gap-2 px-5 py-2 rounded-lg bg-violet-600 text-white text-sm font-medium hover:bg-violet-700 disabled:opacity-50 transition-colors"
          >
            <Save size={14} />
            {saving ? 'Saving…' : guardrail ? 'Update' : 'Add Guardrail'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ─── Main page ────────────────────────────────────────────────────────────────

const FILTER_LEVELS = [
  { value: 'none', label: 'None', description: 'No content filtering. Agent can discuss any topic.', color: 'gray' },
  { value: 'low', label: 'Low', description: 'Block explicit profanity only.', color: 'green' },
  { value: 'medium', label: 'Medium', description: 'Profanity filter + blocked topics/keywords enforced.', color: 'yellow' },
  { value: 'strict', label: 'Strict', description: 'All filters active. Agent refuses anything ambiguous.', color: 'red' },
]

export default function GuardrailsPage() {
  const { id } = useParams<{ id: string }>()
  const router = useRouter()
  const qc = useQueryClient()

  const { data: agent } = useQuery({
    queryKey: ['agents', id],
    queryFn: () => agentsApi.get(id),
  })

  const { data: existing, isLoading } = useQuery({
    queryKey: ['guardrails', id],
    queryFn: () => guardrailsApi.get(id).catch(() => null),
  })

  // Custom guardrails
  const { data: customGuardrails = [], isLoading: loadingCustom } = useQuery({
    queryKey: ['guardrails-custom', id],
    queryFn: () => guardrailsApi.listCustom(id).catch(() => []),
  })

  // Form state for content filters
  const [filterLevel, setFilterLevel] = useState('medium')
  const [blockedKeywords, setBlockedKeywords] = useState<string[]>([])
  const [blockedTopics, setBlockedTopics] = useState<string[]>([])
  const [allowedTopics, setAllowedTopics] = useState<string[]>([])
  const [profanityFilter, setProfanityFilter] = useState(true)
  const [piiRedaction, setPiiRedaction] = useState(false)
  const [piiPseudonymization, setPiiPseudonymization] = useState(false)
  const [maxLength, setMaxLength] = useState(0)
  const [requireDisclaimer, setRequireDisclaimer] = useState('')
  const [blockedMessage, setBlockedMessage] = useState("I'm sorry, I can't help with that.")
  const [offTopicMessage, setOffTopicMessage] = useState("I'm only able to help with topics related to our service.")
  const [isActive, setIsActive] = useState(true)
  const [dirty, setDirty] = useState(false)

  // Modal state
  const [changeRequestGuardrail, setChangeRequestGuardrail] = useState<GlobalGuardrail | null>(null)
  const [customFormModal, setCustomFormModal] = useState<{ guardrail?: typeof customGuardrails[0] } | null>(null)
  const [expandedCategory, setExpandedCategory] = useState<string | null>(null)

  useEffect(() => {
    if (!existing) return
    const cfg = (existing.config || {}) as Record<string, unknown>
    setFilterLevel((cfg.content_filter_level as string) || (existing.content_filter_level as string) || 'medium')
    setBlockedKeywords((cfg.blocked_keywords as string[]) || (existing.blocked_keywords as string[]) || [])
    setBlockedTopics((cfg.blocked_topics as string[]) || (existing.blocked_topics as string[]) || [])
    setAllowedTopics((cfg.allowed_topics as string[]) || (existing.allowed_topics as string[]) || [])
    setProfanityFilter((cfg.profanity_filter as boolean) ?? (existing.profanity_filter as boolean) ?? true)
    setPiiRedaction((cfg.pii_redaction as boolean) ?? (existing.pii_redaction as boolean) ?? false)
    setPiiPseudonymization((cfg.pii_pseudonymization as boolean) ?? (existing.pii_pseudonymization as boolean) ?? false)
    setMaxLength((cfg.max_response_length as number) || (existing.max_response_length as number) || 0)
    setRequireDisclaimer((cfg.require_disclaimer as string) || (existing.require_disclaimer as string) || '')
    setBlockedMessage((cfg.blocked_message as string) || (existing.blocked_message as string) || "I'm sorry, I can't help with that.")
    setOffTopicMessage((cfg.off_topic_message as string) || (existing.off_topic_message as string) || "I'm only able to help with topics related to our service.")
    setIsActive(existing.is_active ?? true)
    setDirty(false)
  }, [existing])

  // Mutations
  const saveMutation = useMutation({
    mutationFn: () =>
      guardrailsApi.upsert(id, {
        content_filter_level: filterLevel,
        blocked_keywords: blockedKeywords,
        blocked_topics: blockedTopics,
        allowed_topics: allowedTopics,
        profanity_filter: profanityFilter,
        pii_redaction: piiRedaction,
        max_response_length: maxLength,
        require_disclaimer: requireDisclaimer || undefined,
        blocked_message: blockedMessage,
        off_topic_message: offTopicMessage,
        is_active: isActive,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['guardrails', id] })
      toast.success('Guardrails saved')
      setDirty(false)
    },
    onError: () => toast.error('Failed to save guardrails'),
  })

  const deleteMutation = useMutation({
    mutationFn: () => guardrailsApi.delete(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['guardrails', id] })
      toast.success('Guardrails removed')
      router.push(`/dashboard/agents/${id}`)
    },
    onError: () => toast.error('Failed to remove guardrails'),
  })

  const changeRequestMutation = useMutation({
    mutationFn: (data: { guardrail_id: string; proposed_rule: string; reason: string }) =>
      guardrailsApi.requestChange(data),
    onSuccess: () => {
      toast.success('Change request submitted for admin review')
    },
    onError: () => toast.error('Failed to submit change request'),
  })

  const createCustomMutation = useMutation({
    mutationFn: (data: { rule: string; category: string }) =>
      guardrailsApi.createCustom(id, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['guardrails-custom', id] })
      toast.success('Custom guardrail added')
    },
    onError: () => toast.error('Failed to add custom guardrail'),
  })

  const updateCustomMutation = useMutation({
    mutationFn: (data: { customId: string; updates: { rule?: string; category?: string; is_active?: boolean } }) =>
      guardrailsApi.updateCustom(id, data.customId, data.updates),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['guardrails-custom', id] })
      toast.success('Custom guardrail updated')
    },
    onError: () => toast.error('Failed to update custom guardrail'),
  })

  const deleteCustomMutation = useMutation({
    mutationFn: (customId: string) =>
      guardrailsApi.deleteCustom(id, customId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['guardrails-custom', id] })
      toast.success('Custom guardrail removed')
    },
    onError: () => toast.error('Failed to remove custom guardrail'),
  })

  const mark = () => setDirty(true)

  // Fetch global guardrails from platform settings (admin-controlled)
  const { data: platformData } = useQuery({
    queryKey: ['platform', 'global-guardrails'],
    queryFn: () => fetch('/api/v1/proxy/agents/platform/global-guardrails').then(r => r.json()),
    staleTime: 5 * 60 * 1000, // 5 minutes
  })
  const globalGuardrails = (platformData?.guardrails || []) as GlobalGuardrail[]

  // Group global guardrails by category
  const groupedGlobal = globalGuardrails.reduce<Record<string, GlobalGuardrail[]>>((acc, g) => {
    if (!acc[g.category]) acc[g.category] = []
    acc[g.category].push(g)
    return acc
  }, {})

  return (
    <div className="p-8 w-full">
      {/* Header */}
      <div className="flex items-center gap-3 mb-2">
        <Link
          href={`/dashboard/agents/${id}`}
          className="p-1.5 text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
        >
          <ChevronLeft size={18} />
        </Link>
        <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-orange-500/20 to-red-500/20 flex items-center justify-center">
          <Shield size={18} className="text-orange-600 dark:text-orange-400" />
        </div>
        <div>
          <h1 className="text-xl font-bold text-gray-900 dark:text-white">
            Guardrails
            {agent ? ` — ${agent.name}` : ''}
          </h1>
          <p className="text-sm text-gray-500 dark:text-gray-400">
            System-wide safety rules &amp; agent-specific guardrail configuration
          </p>
        </div>
      </div>

      {dirty && (
        <div className="mt-4 mb-2 flex items-center gap-2 text-amber-600 dark:text-amber-400 text-sm">
          <AlertTriangle size={14} />
          Unsaved changes
        </div>
      )}

      <div className="mt-6 space-y-5">
        {/* ───────────────────────────────────────────────────────────────────── */}
        {/* 1. GLOBAL GUARDRAILS (Read-Only)                                     */}
        {/* ───────────────────────────────────────────────────────────────────── */}
        <Section
          title="Global Guardrails"
          description="System-enforced safety rules applied to all agents. These cannot be edited — submit a change request for admin review."
          icon={<Globe size={18} className="text-blue-500 dark:text-blue-400" />}
        >
          <div className="flex items-center gap-2 mb-4 p-3 rounded-lg bg-blue-50 dark:bg-blue-900/20 border border-blue-100 dark:border-blue-800">
            <Lock size={14} className="text-blue-500 flex-shrink-0" />
            <p className="text-xs text-blue-700 dark:text-blue-300">
              These rules are enforced at the code level in the orchestrator and proxy. Changes require admin approval.
            </p>
          </div>

          <div className="space-y-2">
            {Object.entries(groupedGlobal).map(([category, rules]) => {
              const isExpanded = expandedCategory === category || expandedCategory === null
              return (
                <div key={category}>
                  <button
                    onClick={() => setExpandedCategory(expandedCategory === category ? null : category)}
                    className="flex items-center gap-2 w-full text-left px-3 py-2 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors"
                  >
                    <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${CATEGORY_COLORS[category] || 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-300'}`}>
                      {category}
                    </span>
                    <span className="text-xs text-gray-400">{rules.length} rule{rules.length !== 1 ? 's' : ''}</span>
                    <ChevronLeft size={14} className={`text-gray-400 ml-auto transition-transform ${expandedCategory === category ? '-rotate-90' : '-rotate-0'}`} />
                  </button>
                  {expandedCategory === category && (
                    <div className="ml-3 mt-1 space-y-1.5 border-l-2 border-gray-100 dark:border-gray-800 pl-4">
                      {rules.map((g) => (
                        <div
                          key={g.id}
                          className="flex items-start gap-3 p-3 rounded-xl border border-gray-100 dark:border-gray-800 bg-gray-50/50 dark:bg-gray-800/20 group"
                        >
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2 mb-1">
                              <span className="text-xs font-mono font-semibold text-gray-500 dark:text-gray-400">
                                {g.id}
                              </span>
                              <span className="text-[10px] text-gray-400 font-mono">
                                ref: {g.fix_ref}
                              </span>
                            </div>
                            <p className="text-sm text-gray-700 dark:text-gray-300 leading-relaxed">
                              {g.rule}
                            </p>
                          </div>
                          <button
                            onClick={() => setChangeRequestGuardrail(g)}
                            className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-xs font-medium text-gray-400 hover:text-violet-600 dark:hover:text-violet-400 hover:bg-violet-50 dark:hover:bg-violet-900/20 opacity-0 group-hover:opacity-100 transition-all"
                            title="Request change"
                          >
                            <MessageSquareWarning size={12} />
                            Request Change
                          </button>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        </Section>

        {/* ───────────────────────────────────────────────────────────────────── */}
        {/* 2. AGENT-SPECIFIC CUSTOM GUARDRAILS (Editable)                       */}
        {/* ───────────────────────────────────────────────────────────────────── */}
        <Section
          title="Agent Guardrails"
          description="Custom rules specific to this agent. These are injected into the system prompt alongside global guardrails."
          icon={<UserCheck size={18} className="text-violet-500 dark:text-violet-400" />}
        >
          <div className="flex items-center justify-between mb-4">
            <p className="text-xs text-gray-500">
              {customGuardrails.length} custom rule{customGuardrails.length !== 1 ? 's' : ''} configured
            </p>
            <button
              onClick={() => setCustomFormModal({})}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-violet-600 text-white text-xs font-medium hover:bg-violet-700 transition-colors"
            >
              <Plus size={12} />
              Add Guardrail
            </button>
          </div>

          {loadingCustom ? (
            <div className="space-y-2">
              {[1, 2].map((i) => (
                <div key={i} className="h-16 rounded-xl bg-gray-100 dark:bg-gray-800 animate-pulse" />
              ))}
            </div>
          ) : customGuardrails.length === 0 ? (
            <div className="text-center py-8 border border-dashed border-gray-200 dark:border-gray-700 rounded-xl">
              <Shield size={24} className="mx-auto text-gray-300 dark:text-gray-600 mb-2" />
              <p className="text-sm text-gray-500 dark:text-gray-400">No custom guardrails yet.</p>
              <p className="text-xs text-gray-400 mt-1">
                Add agent-specific rules to supplement the global guardrails.
              </p>
            </div>
          ) : (
            <div className="space-y-2">
              {customGuardrails.map((g: any) => (
                <CustomGuardrailRow
                  key={g.id}
                  guardrail={g}
                  onEdit={() => setCustomFormModal({ guardrail: g })}
                  onDelete={() => {
                    if (confirm('Remove this custom guardrail?')) {
                      deleteCustomMutation.mutate(g.id)
                    }
                  }}
                  onToggle={() =>
                    updateCustomMutation.mutate({
                      customId: g.id,
                      updates: { is_active: !g.is_active },
                    })
                  }
                />
              ))}
            </div>
          )}
        </Section>

        {/* ───────────────────────────────────────────────────────────────────── */}
        {/* 3. CONTENT FILTER SETTINGS (Existing)                                */}
        {/* ───────────────────────────────────────────────────────────────────── */}
        <Section
          title="Content Filters"
          description="Content policy, keyword blocking & output safety settings."
          icon={<AlertTriangle size={18} className="text-amber-500 dark:text-amber-400" />}
        >
          {/* Content filter level */}
          <div className="mb-6">
            <label className="text-xs font-medium text-gray-500 uppercase tracking-wider block mb-3">
              Filter Level
            </label>
            <div className="grid grid-cols-2 gap-3">
              {FILTER_LEVELS.map((lvl) => (
                <button
                  key={lvl.value}
                  type="button"
                  onClick={() => { setFilterLevel(lvl.value); mark() }}
                  className={`text-left p-3 rounded-xl border-2 transition-all ${
                    filterLevel === lvl.value
                      ? 'border-violet-500 bg-violet-50 dark:bg-violet-900/20'
                      : 'border-gray-200 dark:border-gray-700 hover:border-gray-300'
                  }`}
                >
                  <div className="flex items-center gap-2 mb-1">
                    <span className={`w-2 h-2 rounded-full ${
                      { none: 'bg-gray-400', low: 'bg-green-500', medium: 'bg-yellow-500', strict: 'bg-red-500' }[lvl.value]
                    }`} />
                    <span className="text-sm font-semibold text-gray-900 dark:text-white">{lvl.label}</span>
                    {filterLevel === lvl.value && (
                      <CheckCircle2 size={14} className="ml-auto text-violet-600" />
                    )}
                  </div>
                  <p className="text-xs text-gray-500 dark:text-gray-400">{lvl.description}</p>
                </button>
              ))}
            </div>
          </div>

          {/* Blocked keywords */}
          <div className="mb-6">
            <label className="text-xs font-medium text-gray-500 uppercase tracking-wider block mb-2">
              Blocked Keywords
            </label>
            <TagInput
              tags={blockedKeywords}
              onChange={(v) => { setBlockedKeywords(v); mark() }}
              placeholder="Type a keyword and press Enter…"
            />
            <p className="mt-1.5 text-xs text-gray-400">Case-insensitive substring match.</p>
          </div>

          {/* Blocked topics */}
          <div className="mb-6">
            <label className="text-xs font-medium text-gray-500 uppercase tracking-wider block mb-2">
              Blocked Topics
            </label>
            <TagInput
              tags={blockedTopics}
              onChange={(v) => { setBlockedTopics(v); mark() }}
              placeholder="e.g. competitors, pricing, medical advice…"
            />
          </div>

          {/* Allowed topics */}
          <div className="mb-6">
            <label className="text-xs font-medium text-gray-500 uppercase tracking-wider block mb-2">
              Allowed Topics (Whitelist)
            </label>
            <TagInput
              tags={allowedTopics}
              onChange={(v) => { setAllowedTopics(v); mark() }}
              placeholder="e.g. pizza orders, store hours, delivery…"
            />
            {allowedTopics.length > 0 && (
              <div className="mt-2 flex items-center gap-2 text-xs text-amber-600 dark:text-amber-400 bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 rounded-lg px-3 py-2">
                <Info size={12} />
                Whitelist mode active — agent will deflect all other topics.
              </div>
            )}
          </div>

          {/* Safety toggles */}
          <div className="mb-6 space-y-4">
            <Toggle
              checked={profanityFilter}
              onChange={(v) => { setProfanityFilter(v); mark() }}
              label="Profanity Filter"
              description="Block messages containing common profanity and offensive language."
            />
            <Toggle
              checked={piiRedaction}
              onChange={(v) => { setPiiRedaction(v); mark() }}
              label="Redact PII in Chat History"
              description="Automatically redact sensitive information (PII) from the saved chat history to protect user privacy."
            />
          </div>

          {/* Response constraints */}
          <div className="mb-6 space-y-4">
            <div>
              <label className="text-xs font-medium text-gray-500 uppercase tracking-wider block mb-1.5">
                Max Response Length
                <span className="ml-2 normal-case text-gray-400 font-normal">
                  {maxLength > 0 ? `${maxLength} characters` : 'Unlimited'}
                </span>
              </label>
              <input
                type="range"
                min={0}
                max={2000}
                step={50}
                value={maxLength}
                onChange={(e) => { setMaxLength(Number(e.target.value)); mark() }}
                className="w-full accent-violet-600"
              />
            </div>
            <div>
              <label className="text-xs font-medium text-gray-500 uppercase tracking-wider block mb-1.5">
                Require Disclaimer
              </label>
              <input
                value={requireDisclaimer}
                onChange={(e) => { setRequireDisclaimer(e.target.value); mark() }}
                placeholder="e.g. This is not professional medical/legal advice."
                className="w-full px-3 py-2 text-sm rounded-xl border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 text-gray-900 dark:text-white focus:outline-none focus:ring-1 focus:ring-violet-500"
              />
            </div>
          </div>

          {/* Block messages */}
          <div className="mb-6 space-y-4">
            <div>
              <label className="text-xs font-medium text-gray-500 uppercase tracking-wider block mb-1.5">
                Blocked Keyword Response
              </label>
              <textarea
                value={blockedMessage}
                onChange={(e) => { setBlockedMessage(e.target.value); mark() }}
                rows={2}
                className="w-full px-3 py-2 text-sm rounded-xl border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 text-gray-900 dark:text-white focus:outline-none focus:ring-1 focus:ring-violet-500 resize-none"
              />
            </div>
            <div>
              <label className="text-xs font-medium text-gray-500 uppercase tracking-wider block mb-1.5">
                Off-Topic Response
              </label>
              <textarea
                value={offTopicMessage}
                onChange={(e) => { setOffTopicMessage(e.target.value); mark() }}
                rows={2}
                className="w-full px-3 py-2 text-sm rounded-xl border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 text-gray-900 dark:text-white focus:outline-none focus:ring-1 focus:ring-violet-500 resize-none"
              />
            </div>
          </div>

          {/* Status toggle */}
          <Toggle
            checked={isActive}
            onChange={(v) => { setIsActive(v); mark() }}
            label="Guardrails Active"
            description="Disable to turn off all guardrail enforcement for this agent."
          />
        </Section>

        {/* ── Actions ── */}
        <div className="flex items-center justify-between pt-2">
          <button
            onClick={() => {
              if (confirm('Remove all guardrails for this agent?')) {
                deleteMutation.mutate()
              }
            }}
            disabled={deleteMutation.isPending || !existing}
            className="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm text-red-500 hover:bg-red-50 dark:hover:bg-red-900/20 disabled:opacity-40 transition-colors"
          >
            <Trash2 size={14} />
            Remove guardrails
          </button>

          <button
            onClick={() => saveMutation.mutate()}
            disabled={saveMutation.isPending}
            className="inline-flex items-center gap-2 px-5 py-2.5 rounded-lg bg-gradient-to-r from-violet-600 to-blue-600 text-white text-sm font-medium hover:opacity-90 disabled:opacity-50 transition-opacity"
          >
            <Save size={15} />
            {saveMutation.isPending ? 'Saving…' : 'Save guardrails'}
          </button>
        </div>
      </div>

      {/* Modals */}
      {changeRequestGuardrail && (
        <ChangeRequestModal
          guardrail={changeRequestGuardrail}
          onClose={() => setChangeRequestGuardrail(null)}
          onSubmit={(proposedRule, reason) =>
            changeRequestMutation.mutateAsync({
              guardrail_id: changeRequestGuardrail.id,
              proposed_rule: proposedRule,
              reason,
            })
          }
        />
      )}

      {customFormModal && (
        <CustomGuardrailFormModal
          guardrail={customFormModal.guardrail}
          onClose={() => setCustomFormModal(null)}
          onSave={(data) => {
            if (customFormModal.guardrail) {
              return updateCustomMutation.mutateAsync({
                customId: customFormModal.guardrail.id,
                updates: data,
              })
            }
            return createCustomMutation.mutateAsync(data)
          }}
        />
      )}
    </div>
  )
}
