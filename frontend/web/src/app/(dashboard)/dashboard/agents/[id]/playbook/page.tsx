'use client'

import { useState, useEffect } from 'react'
import { useParams, useRouter } from 'next/navigation'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { playbookApi, agentsApi } from '@/lib/api'
import toast from 'react-hot-toast'
import {
  BookOpen,
  Plus,
  Trash2,
  ChevronLeft,
  Save,
  MessageSquare,
  List,
  Zap,
  AlertCircle,
  CheckCircle2,
  Info,
} from 'lucide-react'

const TONES = [
  { value: 'professional', label: 'Professional', desc: 'Formal, precise, complete sentences' },
  { value: 'friendly', label: 'Friendly', desc: 'Warm, approachable, conversational' },
  { value: 'casual', label: 'Casual', desc: 'Relaxed, informal, short replies' },
  { value: 'empathetic', label: 'Empathetic', desc: 'Acknowledges feelings, patient tone' },
]

function SectionTitle({ icon: Icon, title, desc }: { icon: any; title: string; desc: string }) {
  return (
    <div className="flex items-start gap-3 mb-4">
      <div className="w-8 h-8 rounded-lg bg-violet-100 dark:bg-violet-900/30 flex items-center justify-center flex-shrink-0 mt-0.5">
        <Icon size={15} className="text-violet-600 dark:text-violet-400" />
      </div>
      <div>
        <h3 className="text-sm font-semibold text-gray-900 dark:text-white">{title}</h3>
        <p className="text-xs text-gray-500 mt-0.5">{desc}</p>
      </div>
    </div>
  )
}

function ListEditor({
  items,
  onChange,
  placeholder,
  addLabel,
}: {
  items: string[]
  onChange: (v: string[]) => void
  placeholder: string
  addLabel: string
}) {
  const [draft, setDraft] = useState('')

  function add() {
    const v = draft.trim()
    if (!v) return
    onChange([...items, v])
    setDraft('')
  }

  return (
    <div className="space-y-2">
      {items.map((item, i) => (
        <div key={i} className="flex items-center gap-2 group">
          <span className="flex-1 text-sm text-gray-700 dark:text-gray-300 bg-gray-50 dark:bg-gray-800 rounded-lg px-3 py-1.5 border border-gray-200 dark:border-gray-700">
            {item}
          </span>
          <button
            onClick={() => onChange(items.filter((_, j) => j !== i))}
            className="opacity-0 group-hover:opacity-100 text-gray-400 hover:text-red-500 transition-all"
          >
            <Trash2 size={14} />
          </button>
        </div>
      ))}
      <div className="flex gap-2">
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && add()}
          placeholder={placeholder}
          className="flex-1 text-sm rounded-lg border border-gray-200 dark:border-gray-700 bg-transparent px-3 py-1.5 text-gray-900 dark:text-white placeholder-gray-400 focus:outline-none focus:ring-1 focus:ring-violet-500"
        />
        <button
          onClick={add}
          className="px-3 py-1.5 rounded-lg bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-300 hover:bg-violet-100 dark:hover:bg-violet-900/30 hover:text-violet-700 text-sm transition-colors flex items-center gap-1"
        >
          <Plus size={13} />
          {addLabel}
        </button>
      </div>
    </div>
  )
}

function ScenarioEditor({
  scenarios,
  onChange,
}: {
  scenarios: { trigger: string; response: string }[]
  onChange: (v: { trigger: string; response: string }[]) => void
}) {
  const [draftTrigger, setDraftTrigger] = useState('')
  const [draftResponse, setDraftResponse] = useState('')

  function add() {
    if (!draftTrigger.trim() || !draftResponse.trim()) return
    onChange([...scenarios, { trigger: draftTrigger.trim(), response: draftResponse.trim() }])
    setDraftTrigger('')
    setDraftResponse('')
  }

  return (
    <div className="space-y-3">
      {scenarios.map((s, i) => (
        <div key={i} className="bg-gray-50 dark:bg-gray-800 rounded-xl p-4 border border-gray-200 dark:border-gray-700 group relative">
          <button
            onClick={() => onChange(scenarios.filter((_, j) => j !== i))}
            className="absolute top-3 right-3 opacity-0 group-hover:opacity-100 text-gray-400 hover:text-red-500 transition-all"
          >
            <Trash2 size={14} />
          </button>
          <p className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-1">Trigger</p>
          <p className="text-sm text-gray-900 dark:text-white mb-2">"{s.trigger}"</p>
          <p className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-1">Response</p>
          <p className="text-sm text-gray-600 dark:text-gray-400">{s.response}</p>
        </div>
      ))}

      <div className="bg-violet-50/50 dark:bg-violet-900/10 rounded-xl p-4 border border-violet-100 dark:border-violet-800/50 space-y-3">
        <p className="text-xs font-medium text-violet-600 dark:text-violet-400 uppercase tracking-wide">
          Add scenario
        </p>
        <input
          value={draftTrigger}
          onChange={(e) => setDraftTrigger(e.target.value)}
          placeholder='If user asks about… e.g. "refund policy"'
          className="w-full text-sm rounded-lg border border-violet-200 dark:border-violet-700 bg-white dark:bg-gray-900 px-3 py-2 text-gray-900 dark:text-white placeholder-gray-400 focus:outline-none focus:ring-1 focus:ring-violet-500"
        />
        <textarea
          value={draftResponse}
          onChange={(e) => setDraftResponse(e.target.value)}
          placeholder="Respond with… e.g. 'Our refund policy allows returns within 30 days…'"
          rows={2}
          className="w-full text-sm rounded-lg border border-violet-200 dark:border-violet-700 bg-white dark:bg-gray-900 px-3 py-2 text-gray-900 dark:text-white placeholder-gray-400 focus:outline-none focus:ring-1 focus:ring-violet-500 resize-none"
        />
        <button
          onClick={add}
          disabled={!draftTrigger.trim() || !draftResponse.trim()}
          className="flex items-center gap-2 px-4 py-2 rounded-lg bg-violet-600 hover:bg-violet-700 disabled:opacity-40 text-white text-sm font-medium transition-colors"
        >
          <Plus size={14} />
          Add Scenario
        </button>
      </div>
    </div>
  )
}

export default function PlaybookEditorPage() {
  const params = useParams()
  const router = useRouter()
  const agentId = params.id as string
  const qc = useQueryClient()

  // Form state
  const [greetingMessage, setGreetingMessage] = useState('')
  const [instructions, setInstructions] = useState('')
  const [tone, setTone] = useState('professional')
  const [dos, setDos] = useState<string[]>([])
  const [donts, setDonts] = useState<string[]>([])
  const [scenarios, setScenarios] = useState<{ trigger: string; response: string }[]>([])
  const [outOfScope, setOutOfScope] = useState('')
  const [fallback, setFallback] = useState('')
  const [escalationMessage, setEscalationMessage] = useState('')
  const [isActive, setIsActive] = useState(true)
  const [isDirty, setIsDirty] = useState(false)

  const { data: agent } = useQuery({
    queryKey: ['agent', agentId],
    queryFn: () => agentsApi.get(agentId),
  })

  const { data: existing, isLoading } = useQuery({
    queryKey: ['playbook', agentId],
    queryFn: () => playbookApi.get(agentId),
    retry: false, // 404 is fine — no playbook yet
  })

  // Hydrate form from existing playbook
  useEffect(() => {
    if (existing) {
      setGreetingMessage(existing.greeting_message ?? '')
      setInstructions(existing.instructions ?? '')
      setTone(existing.tone ?? 'professional')
      setDos(existing.dos ?? [])
      setDonts(existing.donts ?? [])
      setScenarios(existing.scenarios ?? [])
      setOutOfScope(existing.out_of_scope_response ?? '')
      setFallback(existing.fallback_response ?? '')
      setEscalationMessage(existing.custom_escalation_message ?? '')
      setIsActive(existing.is_active ?? true)
      setIsDirty(false)
    }
  }, [existing])

  const save = useMutation({
    mutationFn: () =>
      playbookApi.upsert(agentId, {
        greeting_message: greetingMessage || undefined,
        instructions: instructions || undefined,
        tone,
        dos,
        donts,
        scenarios,
        out_of_scope_response: outOfScope || undefined,
        fallback_response: fallback || undefined,
        custom_escalation_message: escalationMessage || undefined,
        is_active: isActive,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['playbook', agentId] })
      setIsDirty(false)
      toast.success('Playbook saved')
    },
    onError: () => toast.error('Failed to save playbook'),
  })

  function mark() { setIsDirty(true) }

  return (
    <div className="p-8 max-w-3xl mx-auto">
      {/* Header */}
      <div className="flex items-center gap-4 mb-8">
        <button
          onClick={() => router.push('/dashboard/agents')}
          className="p-2 rounded-lg text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
        >
          <ChevronLeft size={18} />
        </button>
        <div className="flex-1">
          <div className="flex items-center gap-2">
            <BookOpen size={20} className="text-violet-600" />
            <h1 className="text-xl font-bold text-gray-900 dark:text-white">Playbook Editor</h1>
            {isDirty && (
              <span className="text-xs bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400 px-2 py-0.5 rounded-full">
                Unsaved changes
              </span>
            )}
          </div>
          <p className="text-sm text-gray-500 mt-0.5">
            {agent?.name ?? 'Loading…'} — configure greeting, tone, instructions &amp; scenarios
          </p>
        </div>
        <div className="flex items-center gap-3">
          <label className="flex items-center gap-2 text-sm text-gray-600 dark:text-gray-400 cursor-pointer">
            <div
              onClick={() => { setIsActive((v) => !v); mark() }}
              className={`w-9 h-5 rounded-full transition-colors relative ${isActive ? 'bg-violet-600' : 'bg-gray-300 dark:bg-gray-600'}`}
            >
              <span className={`absolute top-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform ${isActive ? 'translate-x-4' : 'translate-x-0.5'}`} />
            </div>
            Active
          </label>
          <button
            onClick={() => save.mutate()}
            disabled={save.isPending || !isDirty}
            className="flex items-center gap-2 px-4 py-2 rounded-xl bg-violet-600 hover:bg-violet-700 disabled:opacity-40 text-white text-sm font-medium transition-colors"
          >
            <Save size={15} />
            {save.isPending ? 'Saving…' : 'Save Playbook'}
          </button>
        </div>
      </div>

      {isLoading ? (
        <div className="space-y-4">
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-32 rounded-2xl bg-gray-100 dark:bg-gray-800 animate-pulse" />
          ))}
        </div>
      ) : (
        <div className="space-y-6">

          {/* Greeting */}
          <section className="bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-800 p-6">
            <SectionTitle
              icon={MessageSquare}
              title="Greeting Message"
              desc="Sent automatically as the first message when a new conversation starts. Leave blank for no auto-greeting."
            />
            <textarea
              value={greetingMessage}
              onChange={(e) => { setGreetingMessage(e.target.value); mark() }}
              rows={3}
              placeholder="Hi! I'm your assistant at Bella Pizza. How can I help you today? 🍕"
              className="w-full text-sm rounded-xl border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 px-4 py-3 text-gray-900 dark:text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-violet-400 resize-none"
            />
            {greetingMessage && (
              <div className="mt-3 bg-violet-50 dark:bg-violet-900/20 rounded-xl p-4 border border-violet-100 dark:border-violet-800/40">
                <p className="text-xs text-violet-500 font-medium mb-1">Preview</p>
                <div className="flex items-start gap-2">
                  <div className="w-6 h-6 rounded-full bg-violet-500 flex-shrink-0 flex items-center justify-center text-white text-xs">A</div>
                  <p className="text-sm text-gray-700 dark:text-gray-300">{greetingMessage}</p>
                </div>
              </div>
            )}
          </section>

          {/* Tone */}
          <section className="bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-800 p-6">
            <SectionTitle
              icon={Zap}
              title="Tone & Style"
              desc="Sets the overall communication style injected into every system prompt."
            />
            <div className="grid grid-cols-2 gap-3">
              {TONES.map((t) => (
                <button
                  key={t.value}
                  onClick={() => { setTone(t.value); mark() }}
                  className={`p-4 rounded-xl border-2 text-left transition-all ${
                    tone === t.value
                      ? 'border-violet-500 bg-violet-50 dark:bg-violet-900/20'
                      : 'border-gray-200 dark:border-gray-700 hover:border-violet-300'
                  }`}
                >
                  <p className={`text-sm font-semibold ${tone === t.value ? 'text-violet-700 dark:text-violet-300' : 'text-gray-900 dark:text-white'}`}>
                    {t.label}
                  </p>
                  <p className="text-xs text-gray-500 mt-0.5">{t.desc}</p>
                </button>
              ))}
            </div>
          </section>

          {/* Instructions */}
          <section className="bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-800 p-6">
            <SectionTitle
              icon={Info}
              title="Operator Instructions"
              desc="Detailed instructions injected into the system prompt. Tell the agent exactly how to behave, what to focus on, business context, pricing, policies, etc."
            />
            <textarea
              value={instructions}
              onChange={(e) => { setInstructions(e.target.value); mark() }}
              rows={8}
              placeholder={`You are the AI assistant for Bella Pizza, a family-run restaurant in downtown Chicago.

Our opening hours are Mon-Sat 11am-10pm and Sun 12pm-9pm.
Our bestsellers are the Margherita ($14), Pepperoni ($16), and BBQ Chicken ($17).

When a customer asks about allergens, always recommend they call us directly at 555-0123.
Always upsell our combo deals: any large pizza + 2 sides for $22.

Never discuss competitor restaurants. If asked, say "We focus on making the best pizza in town!"`}
              className="w-full text-sm rounded-xl border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 px-4 py-3 text-gray-900 dark:text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-violet-400 resize-none font-mono"
            />
            <p className="text-xs text-gray-400 mt-2">{instructions.length} characters</p>
          </section>

          {/* Dos & Don'ts */}
          <section className="bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-800 p-6">
            <SectionTitle
              icon={CheckCircle2}
              title="Dos &amp; Don'ts"
              desc="Quick rules the agent always follows. Rendered as a checklist in the system prompt."
            />
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              <div>
                <p className="text-xs font-semibold text-green-600 uppercase tracking-wide mb-3">
                  ✓ Always do
                </p>
                <ListEditor
                  items={dos}
                  onChange={(v) => { setDos(v); mark() }}
                  placeholder="e.g. Greet the customer by name if known"
                  addLabel="Add"
                />
              </div>
              <div>
                <p className="text-xs font-semibold text-red-500 uppercase tracking-wide mb-3">
                  ✗ Never do
                </p>
                <ListEditor
                  items={donts}
                  onChange={(v) => { setDonts(v); mark() }}
                  placeholder="e.g. Share customer data with third parties"
                  addLabel="Add"
                />
              </div>
            </div>
          </section>

          {/* Scenario Playbook */}
          <section className="bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-800 p-6">
            <SectionTitle
              icon={List}
              title="Scenario Playbook"
              desc="Define trigger phrases and the exact response the agent should give. Great for FAQs, objection handling, and key topics."
            />
            <ScenarioEditor
              scenarios={scenarios}
              onChange={(v) => { setScenarios(v); mark() }}
            />
          </section>

          {/* Fallbacks */}
          <section className="bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-800 p-6">
            <SectionTitle
              icon={AlertCircle}
              title="Fallback Responses"
              desc="What the agent says when it can't answer, or when someone asks something out of scope."
            />
            <div className="space-y-4">
              <div>
                <label className="text-xs font-medium text-gray-500 uppercase tracking-wide block mb-2">
                  Out-of-scope response
                </label>
                <textarea
                  value={outOfScope}
                  onChange={(e) => { setOutOfScope(e.target.value); mark() }}
                  rows={2}
                  placeholder="I'm only able to help with questions about our menu and orders. For anything else, please call us at 555-0123."
                  className="w-full text-sm rounded-xl border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 px-4 py-3 text-gray-900 dark:text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-violet-400 resize-none"
                />
              </div>
              <div>
                <label className="text-xs font-medium text-gray-500 uppercase tracking-wide block mb-2">
                  General fallback (when unsure)
                </label>
                <textarea
                  value={fallback}
                  onChange={(e) => { setFallback(e.target.value); mark() }}
                  rows={2}
                  placeholder="I'm not sure about that. Let me connect you with our team — please call 555-0123 or leave your number and we'll call you back."
                  className="w-full text-sm rounded-xl border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 px-4 py-3 text-gray-900 dark:text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-violet-400 resize-none"
                />
              </div>
              <div>
                <label className="text-xs font-medium text-gray-500 uppercase tracking-wide block mb-2">
                  Human handoff / escalation message
                </label>
                <textarea
                  value={escalationMessage}
                  onChange={(e) => { setEscalationMessage(e.target.value); mark() }}
                  rows={2}
                  placeholder="I'm transferring you to one of our team members now. They'll be with you shortly!"
                  className="w-full text-sm rounded-xl border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 px-4 py-3 text-gray-900 dark:text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-violet-400 resize-none"
                />
              </div>
            </div>
          </section>

          {/* Save footer */}
          <div className="flex justify-end pb-4">
            <button
              onClick={() => save.mutate()}
              disabled={save.isPending || !isDirty}
              className="flex items-center gap-2 px-6 py-3 rounded-xl bg-violet-600 hover:bg-violet-700 disabled:opacity-40 text-white font-medium transition-colors"
            >
              <Save size={16} />
              {save.isPending ? 'Saving…' : 'Save Playbook'}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
