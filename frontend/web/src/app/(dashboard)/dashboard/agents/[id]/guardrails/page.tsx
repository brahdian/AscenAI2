'use client'

import { useState, useEffect } from 'react'
import { useParams, useRouter } from 'next/navigation'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { guardrailsApi, agentsApi } from '@/lib/api'
import toast from 'react-hot-toast'
import Link from 'next/link'
import {
  Shield, ChevronLeft, ChevronRight, Plus, X, AlertTriangle, Eye, EyeOff,
  CheckCircle2, Save, Trash2, Info,
} from 'lucide-react'

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
}: {
  title: string
  description?: string
  children: React.ReactNode
}) {
  return (
    <div className="bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-800 p-6">
      <div className="mb-5">
        <h2 className="text-base font-semibold text-gray-900 dark:text-white">{title}</h2>
        {description && (
          <p className="text-sm text-gray-500 dark:text-gray-400 mt-0.5">{description}</p>
        )}
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

// ─── Main page ────────────────────────────────────────────────────────────────

const FILTER_LEVELS = [
  {
    value: 'none',
    label: 'None',
    description: 'No content filtering. Agent can discuss any topic.',
    color: 'gray',
  },
  {
    value: 'low',
    label: 'Low',
    description: 'Block explicit profanity only.',
    color: 'green',
  },
  {
    value: 'medium',
    label: 'Medium',
    description: 'Profanity filter + blocked topics/keywords enforced.',
    color: 'yellow',
  },
  {
    value: 'strict',
    label: 'Strict',
    description: 'All filters active. Agent refuses anything ambiguous.',
    color: 'red',
  },
]

const LEVEL_COLORS: Record<string, string> = {
  gray: 'border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800/50',
  green: 'border-green-200 dark:border-green-800/60 bg-green-50 dark:bg-green-900/10',
  yellow: 'border-yellow-200 dark:border-yellow-700/60 bg-yellow-50 dark:bg-yellow-900/10',
  red: 'border-red-200 dark:border-red-800/60 bg-red-50 dark:bg-red-900/10',
}

const LEVEL_TEXT: Record<string, string> = {
  gray: 'text-gray-700 dark:text-gray-300',
  green: 'text-green-700 dark:text-green-400',
  yellow: 'text-yellow-700 dark:text-yellow-400',
  red: 'text-red-700 dark:text-red-400',
}

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

  // Form state
  const [filterLevel, setFilterLevel] = useState('medium')
  const [blockedKeywords, setBlockedKeywords] = useState<string[]>([])
  const [blockedTopics, setBlockedTopics] = useState<string[]>([])
  const [allowedTopics, setAllowedTopics] = useState<string[]>([])
  const [profanityFilter, setProfanityFilter] = useState(true)
  const [piiRedaction, setPiiRedaction] = useState(false)
  const [maxLength, setMaxLength] = useState(0)
  const [requireDisclaimer, setRequireDisclaimer] = useState('')
  const [blockedMessage, setBlockedMessage] = useState(
    "I'm sorry, I can't help with that."
  )
  const [offTopicMessage, setOffTopicMessage] = useState(
    "I'm only able to help with topics related to our service."
  )
  const [isActive, setIsActive] = useState(true)
  const [dirty, setDirty] = useState(false)

  useEffect(() => {
    if (!existing) return
    setFilterLevel(existing.content_filter_level ?? 'medium')
    setBlockedKeywords(existing.blocked_keywords ?? [])
    setBlockedTopics(existing.blocked_topics ?? [])
    setAllowedTopics(existing.allowed_topics ?? [])
    setProfanityFilter(existing.profanity_filter ?? true)
    setPiiRedaction(existing.pii_redaction ?? false)
    setMaxLength(existing.max_response_length ?? 0)
    setRequireDisclaimer(existing.require_disclaimer ?? '')
    setBlockedMessage(existing.blocked_message ?? "I'm sorry, I can't help with that.")
    setOffTopicMessage(
      existing.off_topic_message ?? "I'm only able to help with topics related to our service."
    )
    setIsActive(existing.is_active ?? true)
    setDirty(false)
  }, [existing])

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

  const mark = () => setDirty(true)

  return (
    <div className="p-8 max-w-3xl mx-auto">
      {/* Breadcrumbs */}
      <nav className="flex items-center gap-1.5 text-sm text-gray-400 mb-5">
        <Link href="/dashboard" className="hover:text-gray-600 dark:hover:text-gray-200 transition-colors">Dashboard</Link>
        <ChevronRight size={13} />
        <Link href="/dashboard/agents" className="hover:text-gray-600 dark:hover:text-gray-200 transition-colors">Agents</Link>
        <ChevronRight size={13} />
        <Link href={`/dashboard/agents/${id}`} className="hover:text-gray-600 dark:hover:text-gray-200 transition-colors">{agent?.name || '…'}</Link>
        <ChevronRight size={13} />
        <span className="text-gray-600 dark:text-gray-300">Guardrails</span>
      </nav>

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
            Content policy, keyword blocking & output safety
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
        {/* Content filter level */}
        <Section
          title="Content Filter Level"
          description="Sets the overall strictness. Higher levels enforce more aggressive filtering."
        >
          <div className="grid grid-cols-2 gap-3">
            {FILTER_LEVELS.map((lvl) => (
              <button
                key={lvl.value}
                type="button"
                onClick={() => { setFilterLevel(lvl.value); mark() }}
                className={`text-left p-3 rounded-xl border-2 transition-all ${
                  filterLevel === lvl.value
                    ? 'border-violet-500 bg-violet-50 dark:bg-violet-900/20'
                    : `border-gray-200 dark:border-gray-700 hover:border-gray-300`
                }`}
              >
                <div className="flex items-center gap-2 mb-1">
                  <span
                    className={`w-2 h-2 rounded-full ${
                      { none: 'bg-gray-400', low: 'bg-green-500', medium: 'bg-yellow-500', strict: 'bg-red-500' }[lvl.value]
                    }`}
                  />
                  <span className="text-sm font-semibold text-gray-900 dark:text-white">
                    {lvl.label}
                  </span>
                  {filterLevel === lvl.value && (
                    <CheckCircle2 size={14} className="ml-auto text-violet-600" />
                  )}
                </div>
                <p className="text-xs text-gray-500 dark:text-gray-400">{lvl.description}</p>
              </button>
            ))}
          </div>
        </Section>

        {/* Blocked keywords */}
        <Section
          title="Blocked Keywords"
          description="Any user message containing these words is instantly blocked — no LLM call made."
        >
          <TagInput
            tags={blockedKeywords}
            onChange={(v) => { setBlockedKeywords(v); mark() }}
            placeholder="Type a keyword and press Enter…"
          />
          <p className="mt-2 text-xs text-gray-400">Case-insensitive substring match.</p>
        </Section>

        {/* Blocked topics */}
        <Section
          title="Blocked Topics"
          description="Topics the agent should refuse to discuss. Injected into the system prompt — LLM-enforced."
        >
          <TagInput
            tags={blockedTopics}
            onChange={(v) => { setBlockedTopics(v); mark() }}
            placeholder="e.g. competitors, pricing, medical advice…"
          />
        </Section>

        {/* Allowed topics (whitelist mode) */}
        <Section
          title="Allowed Topics (Whitelist)"
          description="If set, the agent will ONLY discuss these topics and politely decline everything else."
        >
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
        </Section>

        {/* Filters */}
        <Section title="Safety Filters">
          <div className="space-y-4">
            <Toggle
              checked={profanityFilter}
              onChange={(v) => { setProfanityFilter(v); mark() }}
              label="Profanity Filter"
              description="Block messages containing common profanity and offensive language."
            />
            <Toggle
              checked={piiRedaction}
              onChange={(v) => { setPiiRedaction(v); mark() }}
              label="PII Redaction in Responses"
              description="Automatically redact email addresses, phone numbers, and credit card numbers from agent responses."
            />
          </div>
        </Section>

        {/* Response constraints */}
        <Section
          title="Response Constraints"
          description="Control the shape and content of agent responses."
        >
          <div className="space-y-4">
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
              <div className="flex justify-between text-xs text-gray-400 mt-1">
                <span>Unlimited</span>
                <span>2000 chars</span>
              </div>
            </div>
            <div>
              <label className="text-xs font-medium text-gray-500 uppercase tracking-wider block mb-1.5">
                Require Disclaimer (appended to every response)
              </label>
              <input
                value={requireDisclaimer}
                onChange={(e) => { setRequireDisclaimer(e.target.value); mark() }}
                placeholder="e.g. This is not professional medical/legal advice."
                className="w-full px-3 py-2 text-sm rounded-xl border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 text-gray-900 dark:text-white focus:outline-none focus:ring-1 focus:ring-violet-500"
              />
            </div>
          </div>
        </Section>

        {/* Custom block messages */}
        <Section
          title="Custom Block Responses"
          description="What the agent says when a message is blocked."
        >
          <div className="space-y-4">
            <div>
              <label className="text-xs font-medium text-gray-500 uppercase tracking-wider block mb-1.5">
                Blocked Keyword / Profanity Response
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
                Off-Topic / Not-Allowed Response
              </label>
              <textarea
                value={offTopicMessage}
                onChange={(e) => { setOffTopicMessage(e.target.value); mark() }}
                rows={2}
                className="w-full px-3 py-2 text-sm rounded-xl border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 text-gray-900 dark:text-white focus:outline-none focus:ring-1 focus:ring-violet-500 resize-none"
              />
            </div>
          </div>
        </Section>

        {/* Active toggle */}
        <Section title="Status">
          <Toggle
            checked={isActive}
            onChange={(v) => { setIsActive(v); mark() }}
            label="Guardrails Active"
            description="Disable to turn off all guardrail enforcement for this agent."
          />
        </Section>

        {/* Actions */}
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
    </div>
  )
}
