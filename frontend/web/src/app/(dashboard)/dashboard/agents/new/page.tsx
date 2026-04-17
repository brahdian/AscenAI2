'use client'

import { useState, useEffect, useRef } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { agentsApi, templatesApi, billingApi } from '@/lib/api'
import toast from 'react-hot-toast'
import Link from 'next/link'
import {
  ArrowLeft, ArrowRight, Bot, Sparkles, Search,
  Building2, Stethoscope, Scissors, ShoppingCart,
  MessageCircle, PhoneCall, TrendingUp, MapPin,
  RefreshCw, GitBranch, BookOpen, Wrench, CheckCircle2,
  Users, Briefcase, Scale, DollarSign, Monitor,
} from 'lucide-react'
import { PlaybookMentionsEditor } from '@/components/PlaybookMentionsEditor'

// ---------------------------------------------------------------------------
// Template metadata (category icons, gradients, taglines)
// ---------------------------------------------------------------------------
const CATEGORY_META: Record<string, { icon: any; gradient: string; badge: string }> = {
  sales:     { icon: TrendingUp,    gradient: 'from-violet-500/10 to-blue-500/10',   badge: 'bg-violet-100 dark:bg-violet-900/30 text-violet-700 dark:text-violet-300' },
  booking:   { icon: Building2,     gradient: 'from-blue-500/10 to-cyan-500/10',     badge: 'bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300' },
  support:   { icon: MessageCircle, gradient: 'from-emerald-500/10 to-teal-500/10',  badge: 'bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-300' },
  ecommerce: { icon: ShoppingCart,  gradient: 'from-orange-500/10 to-amber-500/10',  badge: 'bg-orange-100 dark:bg-orange-900/30 text-orange-700 dark:text-orange-300' },
  service:   { icon: Scissors,      gradient: 'from-pink-500/10 to-rose-500/10',     badge: 'bg-pink-100 dark:bg-pink-900/30 text-pink-700 dark:text-pink-300' },
  medical:   { icon: Stethoscope,   gradient: 'from-green-500/10 to-emerald-500/10', badge: 'bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-300' },
  routing:   { icon: PhoneCall,     gradient: 'from-indigo-500/10 to-violet-500/10', badge: 'bg-indigo-100 dark:bg-indigo-900/30 text-indigo-700 dark:text-indigo-300' },
  local:     { icon: MapPin,        gradient: 'from-yellow-500/10 to-orange-500/10', badge: 'bg-yellow-100 dark:bg-yellow-900/30 text-yellow-700 dark:text-yellow-300' },
  retention: { icon: RefreshCw,     gradient: 'from-cyan-500/10 to-blue-500/10',     badge: 'bg-cyan-100 dark:bg-cyan-900/30 text-cyan-700 dark:text-cyan-300' },
  workflow:  { icon: GitBranch,     gradient: 'from-slate-500/10 to-gray-500/10',    badge: 'bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300' },
  general:   { icon: Bot,           gradient: 'from-gray-500/10 to-slate-500/10',    badge: 'bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300' },
  // New categories for expanded template set
  hr:        { icon: Users,         gradient: 'from-purple-500/10 to-pink-500/10',   badge: 'bg-purple-100 dark:bg-purple-900/30 text-purple-700 dark:text-purple-300' },
  operations:{ icon: Briefcase,     gradient: 'from-slate-500/10 to-blue-500/10',    badge: 'bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300' },
  legal:     { icon: Scale,         gradient: 'from-amber-500/10 to-yellow-500/10',  badge: 'bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-300' },
  finance:   { icon: DollarSign,    gradient: 'from-green-500/10 to-teal-500/10',    badge: 'bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-300' },
}

const CATEGORY_LABELS: Record<string, string> = {
  sales: 'Sales', booking: 'Appointments', support: 'Support',
  ecommerce: 'E-Commerce', service: 'Service', medical: 'Medical',
  routing: 'Routing', local: 'Local Business', retention: 'Retention',
  workflow: 'Workflow', general: 'General',
  hr: 'HR', operations: 'Operations', legal: 'Legal', finance: 'Finance',
}

const TAGLINES: Record<string, string> = {
  lead_capture:                'Qualify inbound traffic and pass leads to your CRM automatically.',
  appointment_booking:         'Let customers self-book and confirm appointments 24/7.',
  customer_support:            'Answer FAQs and resolve common issues with zero wait time.',
  order_checkout:              'Guide customers through a conversational order flow.',
  quote_generator:             'Collect requirements and instantly generate quotes.',
  triage_routing:              'Classify intent and route callers to the right department.',
  sales_assistant:             'Consultative selling — handle objections and close deals.',
  local_business:              'Answer hours, location, pricing for brick-and-mortar shops.',
  follow_up:                   'Re-engage cold leads and drive return visits automatically.',
  strict_workflow:             'Enforce a multi-step compliance process end-to-end.',
  // New templates
  business_receptionist:       'Professional virtual receptionist — greet, route calls, take messages, and answer FAQs.',
  sales_qualifier:             'BANT qualification, objection handling, and discovery call booking for inbound leads.',
  technical_support:           'Diagnose and resolve technical issues, create tickets, and escalate to Tier 2.',
  customer_success:            'Drive adoption, run onboarding check-ins, and handle renewals proactively.',
  hr_assistant:                'Answer HR policy questions, schedule interviews, and guide new hire onboarding.',
  appointment_scheduler_pro:   'Full-service scheduling with booking, rescheduling, cancellations, and waitlists.',
  order_support:               'Track orders, process returns and exchanges, and resolve delivery issues.',
  healthcare_receptionist:     'HIPAA-aware scheduling and routing for medical practices.',
  real_estate_assistant:       'Qualify buyers, answer property questions, and schedule viewings.',
  legal_intake:                'Conduct structured intake, conflict checks, and schedule attorney consultations.',
  financial_advisor_assistant: 'Suitability pre-screen and consultation booking — no investment advice given.',
  it_help_desk:                'Password resets, access requests, troubleshooting triage, and ticket creation.',
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------
export default function NewAgentPage() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const success = searchParams.get('success') === 'true'
  const qc = useQueryClient()

  // Track if we've already attempted to create the agent after payment
  const postPaymentAttempted = useRef(false)

  useEffect(() => {
    if (!success || postPaymentAttempted.current) return
    postPaymentAttempted.current = true

    const agentIdParam = searchParams.get('agent_id')

    if (agentIdParam) {
      // PATH A: Draft agent exists. All logic (creation + template instantiation) 
      // was already handled by the Gateway before the redirect.
      // All that's left is to activate the agent.
      toast.loading('Payment confirmed! Activating your agent...', { id: 'post-payment' })
      sessionStorage.removeItem('ascenai_pending_agent')

      // Zero-trust: the backend blocks direct activation of PENDING_PAYMENT agents.
      // Subscribe to the SSE activation-stream so we get an instant push the moment
      // the Stripe webhook fires — no repeated round-trips.
      const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'
      const waitForActivation = async () => {
        try {
          const resp = await fetch(
            `${API_URL}/api/v1/proxy/agents/${agentIdParam}/activation-stream`,
            { credentials: 'include' },
          )
          if (!resp.ok || !resp.body) throw new Error('stream_unavailable')
          const reader = resp.body.getReader()
          const decoder = new TextDecoder()
          while (true) {
            const { done, value } = await reader.read()
            if (done) break
            const chunk = decoder.decode(value, { stream: true })
            for (const line of chunk.split('\n')) {
              if (!line.startsWith('data: ')) continue
              try {
                const evt = JSON.parse(line.slice(6))
                if (evt.status === 'active') {
                  toast.success('Agent is now active!', { id: 'post-payment' })
                  qc.invalidateQueries({ queryKey: ['agents'] })
                  qc.invalidateQueries({ queryKey: ['billing-overview'] })
                  router.push(`/dashboard/agents/${agentIdParam}`)
                  return
                }
                // status === 'timeout' — server closed after 40s
              } catch { /* ignore malformed lines */ }
            }
          }
        } catch { /* stream unavailable */ }
        // Fallback: webhook may still be in-flight
        toast.success('Payment confirmed! Your agent will be active shortly.', { id: 'post-payment' })
        qc.invalidateQueries({ queryKey: ['agents'] })
        qc.invalidateQueries({ queryKey: ['billing-overview'] })
        router.push('/dashboard/agents')
      }
      waitForActivation()
      return
    }

    // PATH B: No draft agent — check sessionStorage for pending config
    const pendingRaw = sessionStorage.getItem('ascenai_pending_agent')
    if (pendingRaw) {
      try {
        const pendingConfig = JSON.parse(pendingRaw)
        sessionStorage.removeItem('ascenai_pending_agent')
        toast.loading('Payment successful! Creating your agent...', { id: 'post-payment' })
        
        // Extract template context and include it in the creation payload
        const { template_id, template_version_id, variables: pendingVars, ...agentConfig } = pendingConfig
        if (template_id) {
          agentConfig.template_context = {
            template_id,
            template_version_id,
            variable_values: pendingVars || {},
          }
        }
        
        agentsApi.create(agentConfig)
          .then(async (agent: any) => {
            toast.success('Agent deployed successfully!', { id: 'post-payment' })
            qc.invalidateQueries({ queryKey: ['agents'] })
            router.push(`/dashboard/agents/${agent.id}`)
          })
          .catch((err: any) => {
            const detail = err?.response?.data?.detail
            toast.error(typeof detail === 'string' ? detail : 'Agent creation failed. Please contact support.', { id: 'post-payment' })
            router.push('/dashboard/agents')
          })
      } catch {
        sessionStorage.removeItem('ascenai_pending_agent')
        toast.success('Payment received! Please create your agent.')
        router.push('/dashboard/agents/new')
      }
    } else {
      // PATH C: Generic slot purchase (no specific agent)
      toast.success('Payment successful! Your new agent slot is ready.')
      qc.invalidateQueries({ queryKey: ['billing-overview'] })
      setTimeout(() => router.push('/dashboard/agents'), 2000)
    }
  }, [success, router, qc, searchParams])

  const templateIdParam = searchParams.get('template')

  const [selectedTemplate, setSelectedTemplate] = useState<any | null>(null)
  const [step, setStep] = useState<number>(templateIdParam ? 2 : 1)

  // Template search/filter (step 1)
  const [search, setSearch] = useState('')
  const [activeCategory, setActiveCategory] = useState<string>('all')

  // Agent form state (step 2)
  const [agentName, setAgentName] = useState('')
  const [description, setDescription] = useState('')
  const [language, setLanguage] = useState('en')
  const [voiceEnabled, setVoiceEnabled] = useState(true)
  const [variables, setVariables] = useState<Record<string, any>>({})
  const [selectedPlan, setSelectedPlan] = useState<'starter' | 'growth' | 'business'>('growth')

  // Fetch templates
  const { data: templates = [], isLoading: loadingTemplates } = useQuery({
    queryKey: ['templates'],
    queryFn: templatesApi.list,
    select: (data: any[]) => {
      if (templateIdParam && !selectedTemplate) {
        const preselected = data.find((t) => t.id === templateIdParam)
        if (preselected) {
          setSelectedTemplate(preselected)
          const defaults: Record<string, any> = {}
          preselected.variables?.forEach((v: any) => {
            if (v.default_value?.value) defaults[v.key] = v.default_value.value
          })
          setVariables(defaults)
          setAgentName(`My ${preselected.name}`)
        }
      }
      return data
    },
  })

  const { data: agents = [], isLoading: loadingAgents } = useQuery({
    queryKey: ['agents'],
    queryFn: () => agentsApi.list({}),
  })

  const { data: billing, isLoading: loadingBilling } = useQuery({
    queryKey: ['billing-overview'],
    queryFn: () => billingApi.overview(),
  })

  const purchasedSlots = billing?.agent_count || 0
  const hasAvailableSlot = (agents as any[]).length < purchasedSlots

  // Filtered templates for step 1
  const presentCategories = ['all', ...Array.from(new Set<string>((templates as any[]).map((t: any) => t.category)))]
  const filteredTemplates = (templates as any[]).filter((t: any) => {
    const matchSearch = !search || t.name.toLowerCase().includes(search.toLowerCase()) || (t.description || '').toLowerCase().includes(search.toLowerCase())
    const matchCat = activeCategory === 'all' || t.category === activeCategory
    return matchSearch && matchCat
  })

  // Keys across all templates that represent the primary business / org name.
  // When none of these is explicitly filled by the user, agentName is used as fallback.
  const NAME_LIKE_KEYS = ['business_name', 'company_name', 'practice_name', 'firm_name', 'clinic_name', 'agent_name']

  /**
   * Build the final variable_values payload sent to templatesApi.instantiate.
   * 1. Seed every "name-like" key with agentName so no {{placeholder}} goes unrendered.
   * 2. Spread user-filled values on top — skip empty strings so fallbacks still apply.
   * 3. Always include business_type and language for context.
   */
  const buildVariableValues = (sourceVars: Record<string, any> = variables) => {
    const filledVars = Object.fromEntries(
      Object.entries(sourceVars).filter(([, v]) => v !== '' && v !== null && v !== undefined)
    )
    const fallbacks: Record<string, string> = {}
    NAME_LIKE_KEYS.forEach(k => { fallbacks[k] = agentName })
    return {
      ...fallbacks,
      ...filledVars,
      business_type: selectedTemplate?.category || 'generic',
      language,
    }
  }

  // Create mutation
  const createMutation = useMutation({
    mutationFn: async () => {
      const agentConfig: any = {
        name: agentName,
        description,
        business_type: selectedTemplate?.category || 'generic',
        language,
        voice_enabled: voiceEnabled,
        plan: selectedPlan,
      }

      if (selectedTemplate && selectedTemplate.versions?.length > 0) {
        const latestVersion = [...selectedTemplate.versions].sort((a: any, b: any) => b.version - a.version)[0]
        agentConfig.template_context = {
          template_id: selectedTemplate.id,
          template_version_id: latestVersion.id,
          variable_values: buildVariableValues(),
          tool_configs: {},
        }
      }

      return await agentsApi.create(agentConfig)
    },
    onSuccess: (agent) => {
      qc.invalidateQueries({ queryKey: ['agents'] })
      toast.success('Agent deployed successfully!')
      router.push(`/dashboard/agents/${agent.id}`)
    },
    onError: async (err: any) => {
      if (err?.response?.status === 402 && err?.response?.data?.detail?.payment_url) {
        const draftAgentId: string | undefined = err.response.data.detail.agent_id
        const paymentUrl: string = err.response.data.detail.payment_url

        // Save pending config for recovery if session expires or checkout is abandoned
        const pendingConfig: Record<string, any> = {
          name: agentName,
          description,
          business_type: selectedTemplate?.category || 'generic',
          language,
          voice_enabled: voiceEnabled,
          is_active: true,
        }
        if (selectedTemplate) {
          pendingConfig.template_id = selectedTemplate.id
          pendingConfig.template_version_id = selectedTemplate.versions?.length
            ? [...selectedTemplate.versions].sort((a: any, b: any) => b.version - a.version)[0]?.id
            : null
          pendingConfig.variables = buildVariableValues()
        }
        sessionStorage.setItem('ascenai_pending_agent', JSON.stringify(pendingConfig))
        
        toast.loading('Redirecting to Stripe for payment...', { duration: 2000 })
        setTimeout(() => { window.location.href = paymentUrl }, 1000)
        return
      }
      const detail = err?.response?.data?.detail
      toast.error(typeof detail === 'string' ? detail : detail?.message || 'Failed to create agent')
    },
  })

  const handleSelectTemplate = (tpl: any | null) => {
    setSelectedTemplate(tpl)
    if (tpl) {
      const initialName = `My ${tpl.name}`
      const defaults: Record<string, any> = {}
      tpl.variables?.forEach((v: any) => {
        if (v.default_value?.value) {
          defaults[v.key] = v.default_value.value
        } else if (NAME_LIKE_KEYS.includes(v.key)) {
          // Pre-fill every name-like variable so the form isn't blank
          defaults[v.key] = initialName
        }
      })
      setVariables(defaults)
      setAgentName(initialName)
    } else {
      setVariables({})
      setAgentName('')
    }
    setStep(2)
  }

  if (loadingTemplates || loadingAgents || loadingBilling) {
    return (
      <div className="p-8 max-w-6xl mx-auto space-y-6 animate-pulse">
        <div className="h-8 w-48 bg-gray-200 dark:bg-gray-800 rounded" />
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
          {[1,2,3,4,5,6].map(i => <div key={i} className="h-64 bg-gray-100 dark:bg-gray-800 rounded-2xl" />)}
        </div>
      </div>
    )
  }

  return (
    <div className="p-8 max-w-6xl mx-auto">
      <Link
        href="/dashboard/agents"
        className="inline-flex items-center gap-2 text-sm text-gray-500 hover:text-gray-900 dark:hover:text-white mb-6 transition-colors"
      >
        <ArrowLeft size={16} /> Back to agents
      </Link>

      {/* Header */}
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900 dark:text-white flex items-center gap-2">
          <Sparkles className="text-violet-500" size={24} />
          {step === 1 ? 'Choose a Template' : 'Configure Agent'}
        </h1>
        <p className="text-gray-500 mt-1 text-sm">
          {step === 1
            ? 'Start from a prebuilt template or build from scratch.'
            : `Set up your ${selectedTemplate?.name || 'custom'} agent below.`}
        </p>
      </div>

      {/* ------------------------------------------------------------------ */}
      {/* Step 1 — Template marketplace                                        */}
      {/* ------------------------------------------------------------------ */}
      {step === 1 && (
        <div>
          {/* Search + category filters */}
          <div className="flex flex-col sm:flex-row gap-3 mb-6">
            <div className="relative flex-1 max-w-xs">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" size={15} />
              <input
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search templates…"
                className="w-full pl-9 pr-4 py-2 text-sm rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 text-gray-900 dark:text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-violet-500/30 focus:border-violet-400 transition-colors"
              />
            </div>
            <div className="flex flex-wrap gap-2">
              {presentCategories.map((cat) => (
                <button
                  key={cat}
                  onClick={() => setActiveCategory(cat)}
                  className={`px-3 py-1.5 rounded-full text-xs font-semibold transition-colors ${
                    activeCategory === cat
                      ? 'bg-violet-600 text-white'
                      : 'bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-700'
                  }`}
                >
                  {cat === 'all' ? 'All' : CATEGORY_LABELS[cat] || cat}
                </button>
              ))}
            </div>
          </div>

          {/* Template grid */}
          {filteredTemplates.length === 0 && search ? (
            <div className="text-center py-16 text-gray-400">
              <Bot size={36} className="mx-auto mb-3 opacity-30" />
              <p className="text-sm">No templates match your search.</p>
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
              {/* Start from Scratch */}
              <div
                onClick={() => handleSelectTemplate(null)}
                className="group cursor-pointer flex flex-col justify-between p-6 bg-white dark:bg-gray-900 rounded-2xl border-2 border-dashed border-gray-300 dark:border-gray-700 hover:border-violet-500 dark:hover:border-violet-500 transition-colors"
              >
                <div>
                  <div className="w-11 h-11 rounded-xl bg-gray-100 dark:bg-gray-800 flex items-center justify-center mb-4 group-hover:bg-violet-100 dark:group-hover:bg-violet-900/30 transition-colors">
                    <Bot size={22} className="text-gray-400 group-hover:text-violet-600 dark:group-hover:text-violet-400 transition-colors" />
                  </div>
                  <h3 className="text-base font-bold text-gray-900 dark:text-white">Start from Scratch</h3>
                  <p className="text-sm text-gray-500 mt-2 leading-relaxed">
                    Build a completely custom agent. Write your own system prompt and define workflows manually.
                  </p>
                </div>
                <div className="mt-4 flex items-center gap-1 text-sm font-semibold text-violet-600 dark:text-violet-400 group-hover:gap-2 transition-all">
                  Create custom <ArrowRight size={14} />
                </div>
              </div>

              {/* Template cards */}
              {filteredTemplates.map((tpl: any) => {
                const meta = CATEGORY_META[tpl.category] || CATEGORY_META.general
                const Icon = meta.icon
                const tagline = TAGLINES[tpl.key] || tpl.description || ''
                const playbookCount = tpl.versions?.[0]?.playbooks?.length ?? 0
                const toolCount = tpl.versions?.[0]?.tools?.length ?? 0
                const variableCount = tpl.variables?.length ?? 0

                return (
                  <div
                    key={tpl.id}
                    onClick={() => handleSelectTemplate(tpl)}
                    className="group cursor-pointer flex flex-col bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-800 hover:border-violet-500 hover:shadow-xl hover:shadow-violet-500/10 transition-all overflow-hidden"
                  >
                    <div className="p-6 flex-1 flex flex-col">
                      <div className={`w-11 h-11 rounded-xl bg-gradient-to-br ${meta.gradient} flex items-center justify-center mb-4`}>
                        <Icon size={20} className="text-violet-600 dark:text-violet-400" />
                      </div>

                      <div className="flex items-start justify-between gap-2 mb-2">
                        <h3 className="text-base font-bold text-gray-900 dark:text-white leading-tight">{tpl.name}</h3>
                        <span className={`shrink-0 text-[10px] font-bold uppercase tracking-wide px-2 py-0.5 rounded-full ${meta.badge}`}>
                          {CATEGORY_LABELS[tpl.category] || tpl.category}
                        </span>
                      </div>

                      <p className="text-sm text-gray-500 leading-relaxed line-clamp-3 flex-1">{tagline}</p>

                      <div className="mt-4 flex items-center gap-3 text-xs text-gray-400">
                        {playbookCount > 0 && (
                          <span className="flex items-center gap-1"><BookOpen size={11} />{playbookCount} playbook{playbookCount !== 1 ? 's' : ''}</span>
                        )}
                        {toolCount > 0 && (
                          <span className="flex items-center gap-1"><Wrench size={11} />{toolCount} tool{toolCount !== 1 ? 's' : ''}</span>
                        )}
                        {variableCount > 0 && (
                          <span className="flex items-center gap-1"><CheckCircle2 size={11} />{variableCount} var{variableCount !== 1 ? 's' : ''}</span>
                        )}
                      </div>
                    </div>

                    <div className="px-6 pb-5 pt-0">
                      <div className="w-full flex items-center justify-center gap-2 px-4 py-2.5 bg-violet-600 group-hover:bg-violet-700 text-white text-sm font-semibold rounded-xl transition-colors">
                        Use Template <ArrowRight size={14} />
                      </div>
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </div>
      )}

      {/* ------------------------------------------------------------------ */}
      {/* Step 2 — Configure agent                                            */}
      {/* ------------------------------------------------------------------ */}
      {step === 2 && (
        <>
          {!hasAvailableSlot && (
            <div className="mb-6 p-4 bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 rounded-xl flex items-start gap-3">
              <Sparkles className="text-amber-600 mt-0.5 shrink-0" size={18} />
              <div>
                <h4 className="text-sm font-bold text-amber-900 dark:text-amber-100">No available slot</h4>
                <p className="text-xs text-amber-700 dark:text-amber-300 mt-1">
                  You've used all {purchasedSlots} agent slots. Purchasing a new slot will activate this agent.
                </p>
              </div>
            </div>
          )}

          <div className="max-w-2xl bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-800 shadow-sm overflow-hidden mb-8">
            {/* Plan selector — only when no slot available */}
            {!hasAvailableSlot && (
              <div className="p-6 border-b border-gray-100 dark:border-gray-800">
                <label className="block text-sm font-semibold text-gray-900 dark:text-white mb-4">
                  Select a plan for this slot
                </label>
                <div className="grid grid-cols-3 gap-3">
                  {[
                    { id: 'starter', name: 'Starter', price: 39 },
                    { id: 'growth',  name: 'Growth',  price: 99 },
                    { id: 'business',name: 'Business',price: 199 },
                  ].map((p) => (
                    <button
                      key={p.id}
                      type="button"
                      onClick={() => setSelectedPlan(p.id as any)}
                      className={`p-3 rounded-xl border-2 text-left transition-all ${
                        selectedPlan === p.id
                          ? 'border-violet-600 bg-violet-50 dark:bg-violet-900/20'
                          : 'border-gray-200 dark:border-gray-800 hover:border-gray-300'
                      }`}
                    >
                      <div className={`text-[10px] font-bold uppercase tracking-wider ${selectedPlan === p.id ? 'text-violet-600' : 'text-gray-400'}`}>{p.name}</div>
                      <div className="text-lg font-bold text-gray-900 dark:text-white mt-1">${p.price}</div>
                      <div className="text-[10px] text-gray-500 mt-0.5">/ month</div>
                    </button>
                  ))}
                </div>
              </div>
            )}

            {/* Basic settings */}
            <div className="p-6 border-b border-gray-100 dark:border-gray-800 bg-gray-50/50 dark:bg-gray-800/20">
              <h2 className="font-semibold text-gray-900 dark:text-white text-sm">Basic Settings</h2>
            </div>
            <div className="p-6 space-y-5">
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1.5">Agent Name *</label>
                <input
                  value={agentName}
                  onChange={(e) => setAgentName(e.target.value)}
                  placeholder="e.g. Sales Bot"
                  className="w-full px-3 py-2.5 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-violet-500/30 focus:border-violet-400 transition-colors text-sm"
                />
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1.5">Language</label>
                  <select
                    value={language}
                    onChange={(e) => setLanguage(e.target.value)}
                    className="w-full px-3 py-2.5 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-violet-500/30 text-sm"
                  >
                    <option value="en">English</option>
                    <option value="es">Spanish</option>
                    <option value="fr">French</option>
                  </select>
                </div>
                <div className="flex items-end">
                  <label className="flex items-center gap-3 h-[42px] cursor-pointer">
                    <input
                      type="checkbox"
                      checked={voiceEnabled}
                      onChange={(e) => setVoiceEnabled(e.target.checked)}
                      className="w-4 h-4 accent-violet-600 rounded"
                    />
                    <span className="text-sm font-medium text-gray-700 dark:text-gray-300">Enable Voice</span>
                  </label>
                </div>
              </div>
            </div>

            {/* Template variables */}
            {selectedTemplate && selectedTemplate.variables?.length > 0 && (
              <>
                <div className="p-6 border-y border-gray-100 dark:border-gray-800 bg-gray-50/50 dark:bg-gray-800/20">
                  <h2 className="font-semibold text-gray-900 dark:text-white text-sm">Template Configuration</h2>
                  <p className="text-xs text-gray-500 mt-1">Customize this template's settings. You can edit these later.</p>
                </div>
                <div className="p-6 space-y-5">
                  {selectedTemplate.variables
                    .filter((v: any) => !['business_name', 'business_type', 'language'].includes(v.key))
                    .map((vari: any) => (
                    <div key={vari.id}>
                      <label className="flex items-center justify-between text-sm font-medium text-gray-700 dark:text-gray-300 mb-1.5">
                        <span>{vari.label}{vari.is_required && ' *'}</span>
                        <span className="text-xs text-gray-400 font-mono bg-gray-100 dark:bg-gray-800 px-1.5 py-0.5 rounded">{vari.key}</span>
                      </label>
                      {vari.type === 'textarea' || vari.type === 'list' ? (
                        <div className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 overflow-hidden focus-within:ring-2 focus-within:ring-violet-500/30 transition-all">
                          <PlaybookMentionsEditor
                            value={variables[vari.key] || ''}
                            onChange={(val) => setVariables(p => ({ ...p, [vari.key]: val }))}
                            placeholder={`Enter ${vari.label.toLowerCase()}`}
                            minHeight="120px"
                            variables={selectedTemplate.variables.map((v: any) => ({
                              name: v.key,
                              description: v.label
                            }))}
                          />
                        </div>
                      ) : (
                        <input
                          type={vari.type === 'number' ? 'number' : 'text'}
                          value={variables[vari.key] || ''}
                          onChange={(e) => setVariables(p => ({ ...p, [vari.key]: e.target.value }))}
                          className="w-full px-3 py-2.5 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-violet-500/30 text-sm"
                          placeholder={`Enter ${vari.label.toLowerCase()}`}
                        />
                      )}
                    </div>
                  ))}
                </div>
              </>
            )}

            {/* Footer */}
            <div className="p-6 border-t border-gray-100 dark:border-gray-800 bg-gray-50/50 dark:bg-gray-800/20 flex gap-3">
              <button
                onClick={() => setStep(1)}
                className="px-5 py-2.5 rounded-lg border border-gray-200 dark:border-gray-700 text-sm font-medium text-gray-700 dark:text-gray-300 hover:bg-white dark:hover:bg-gray-800 transition-colors"
              >
                Back
              </button>
              <button
                onClick={() => createMutation.mutate()}
                disabled={createMutation.isPending || !agentName.trim() || (!hasAvailableSlot && !selectedPlan)}
                className={`flex-1 px-5 py-2.5 rounded-lg text-white text-sm font-medium disabled:opacity-50 transition-opacity flex items-center justify-center gap-2 ${
                  hasAvailableSlot
                    ? 'bg-gradient-to-r from-violet-600 to-blue-600 hover:opacity-90'
                    : 'bg-gradient-to-r from-amber-500 to-orange-600 hover:opacity-90'
                }`}
              >
                {createMutation.isPending ? (
                  <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                ) : (
                  <ArrowRight size={16} />
                )}
                {createMutation.isPending
                  ? (hasAvailableSlot ? 'Deploying…' : 'Redirecting to payment…')
                  : hasAvailableSlot ? 'Create & Deploy' : 'Purchase & Deploy Slot'}
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  )
}
