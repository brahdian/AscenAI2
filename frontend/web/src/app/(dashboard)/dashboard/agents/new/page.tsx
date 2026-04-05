'use client'

import { useState, useEffect } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { agentsApi, templatesApi, billingApi } from '@/lib/api'
import toast from 'react-hot-toast'
import Link from 'next/link'
import { ArrowLeft, ArrowRight, Bot, Check, Sparkles, Building2, Stethoscope, Scissors } from 'lucide-react'

// Map known icons
const CATEGORY_ICONS: Record<string, any> = {
  general: Bot,
  retail: Building2,
  medical: Stethoscope,
  beauty: Scissors,
}

export default function NewAgentPage() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const success = searchParams.get('success') === 'true'
  const qc = useQueryClient()

  useEffect(() => {
    if (success) {
      toast.success('Payment successful! Deploying your agent...')
      // Redirect to agents list to see the new agent appear
      setTimeout(() => {
        router.push('/dashboard/agents')
      }, 2000)
    }
  }, [success, router])

  const templateIdParam = searchParams.get('template')

  const [selectedTemplate, setSelectedTemplate] = useState<any | null>(null)
  // If a template ID was passed from the marketplace, jump straight to step 2
  const [step, setStep] = useState<number>(templateIdParam ? 2 : 1)

  // Form State
  const [agentName, setAgentName] = useState('')
  const [description, setDescription] = useState('')
  const [language, setLanguage] = useState('en')
  const [voiceEnabled, setVoiceEnabled] = useState(true)
  const [variables, setVariables] = useState<Record<string, any>>({})
  const [selectedPlan, setSelectedPlan] = useState<'starter' | 'growth' | 'business'>('growth')

  // Fetch Templates
  const { data: templates = [], isLoading: loadingTemplates } = useQuery({
    queryKey: ['templates'],
    queryFn: templatesApi.list,
    // Pre-select template from marketplace link once templates are loaded
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

  // Fetch current agents and billing to check slots
  const { data: agents = [], isLoading: loadingAgents } = useQuery({
    queryKey: ['agents'],
    queryFn: () => agentsApi.list({}),
  })

  const { data: billing, isLoading: loadingBilling } = useQuery({
    queryKey: ['billing-overview'],
    queryFn: () => billingApi.overview(),
  })

  const purchasedSlots = billing?.agent_count || 0
  const actualAgentCount = agents.length
  const hasAvailableSlot = actualAgentCount < purchasedSlots

  // Mutations
  const createMutation = useMutation({
    mutationFn: async () => {
      // 1. Create Base Agent (Draft-First)
      const agent = await agentsApi.create({
        name: agentName,
        description,
        business_type: selectedTemplate?.category || 'generic',
        language,
        voice_enabled: voiceEnabled,
        plan: selectedPlan, // Pass requested plan for potential upgrade checkout
      })

      // 2. Instantiate Template if selected
      if (selectedTemplate && selectedTemplate.versions?.length > 0) {
        // Use the latest version
        const latestVersion = selectedTemplate.versions[selectedTemplate.versions.length - 1];
        try {
          await templatesApi.instantiate(selectedTemplate.id, {
            agent_id: agent.id,
            template_version_id: latestVersion.id,
            variable_values: variables,
            tool_configs: {}, // Default tool configs
          })
        } catch (err) {
          // Rollback: delete the agent if template instantiation fails
          console.error('Template instantiation failed, rolling back agent:', err);
          await agentsApi.delete(agent.id);
          throw err;
        }
      }

      return agent
    },
    onSuccess: (agent) => {
      qc.invalidateQueries({ queryKey: ['agents'] })
      toast.success('Agent deployed successfully!')
      router.push(`/dashboard/agents/${agent.id}`)
    },
    onError: (err: any) => {
      // Handle Payment Redirect (Draft saved successfully but needs activation)
      if (err?.response?.status === 402 && err?.response?.data?.detail?.payment_url) {
        toast.loading('Redirecting to Stripe for payment...', { duration: 2000 })
        setTimeout(() => {
          window.location.href = err.response.data.detail.payment_url
        }, 1000)
        return
      }
      
      const detail = err?.response?.data?.detail
      const msg = typeof detail === 'string' ? detail : detail?.message || 'Failed to create agent'
      toast.error(msg)
    },
  })

  // Handlers
  const handleNext = () => setStep(2)
  const handleBack = () => setStep(1)
  
  const handleVariableChange = (key: string, value: any) => {
    setVariables(prev => ({ ...prev, [key]: value }))
  }

  // Render Skeleton
  if (loadingTemplates || loadingAgents || loadingBilling) {
    return (
      <div className="p-8 max-w-5xl mx-auto space-y-6 animate-pulse">
        <div className="h-8 w-48 bg-gray-200 dark:bg-gray-800 rounded"></div>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {[1,2,3,4,5,6].map(i => (
            <div key={i} className="h-64 bg-gray-100 dark:bg-gray-800 rounded-xl"></div>
          ))}
        </div>
      </div>
    )
  }

  return (
    <div className="p-8 max-w-5xl mx-auto">
      <Link
        href="/dashboard/agents"
        className="inline-flex items-center gap-2 text-sm text-gray-500 hover:text-gray-900 dark:hover:text-white mb-6 transition-colors"
      >
        <ArrowLeft size={16} /> Back to agents
      </Link>

      {/* Header */}
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-gray-900 dark:text-white flex items-center gap-2">
          <Sparkles className="text-violet-500" size={28} />
          {step === 1 ? 'Choose a Template' : 'Configure Agent'}
        </h1>
        <p className="text-gray-500 mt-2">
          {step === 1 
            ? 'Select a prebuilt template to instantly deploy an agent with optimized workflows.' 
            : `Set up your ${selectedTemplate?.name || 'custom'} agent below.`}
        </p>
      </div>

      {step === 1 && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {/* Custom Agent Card */}
          <div 
            onClick={() => {
              setSelectedTemplate(null);
              setStep(2);
            }}
            className="group cursor-pointer relative flex flex-col justify-between p-6 bg-white dark:bg-gray-900 rounded-2xl border-2 border-dashed border-gray-300 dark:border-gray-700 hover:border-violet-500 dark:hover:border-violet-500 transition-colors h-full"
          >
            <div>
              <div className="w-12 h-12 rounded-xl bg-gray-100 dark:bg-gray-800 flex items-center justify-center mb-4 group-hover:bg-violet-100 dark:group-hover:bg-violet-900/30 transition-colors">
                <Bot size={24} className="text-gray-500 dark:text-gray-400 group-hover:text-violet-600 dark:group-hover:text-violet-400" />
              </div>
              <h3 className="text-lg font-bold text-gray-900 dark:text-white">Start from Scratch</h3>
              <p className="text-sm text-gray-500 mt-2 leading-relaxed">
                Build a new agent from the ground up. You will write the system prompt and define schemas manually.
              </p>
            </div>
          </div>

          {/* Template Cards */}
          {templates.map((tpl: any) => {
            const Icon = CATEGORY_ICONS[tpl.category] || Bot;
            return (
              <div 
                key={tpl.id}
                onClick={() => {
                  setSelectedTemplate(tpl);
                  
                  // Initialize default variables
                  const defaults: Record<string, any> = {};
                  tpl.variables?.forEach((v: any) => {
                    if (v.default_value?.value) {
                      defaults[v.key] = v.default_value.value;
                    }
                  });
                  setVariables(defaults);
                  setAgentName(`My ${tpl.name}`);
                  setStep(2);
                }}
                className="group cursor-pointer relative flex flex-col justify-between p-6 bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-800 hover:border-violet-500 hover:shadow-xl hover:shadow-violet-500/10 transition-all h-full"
              >
                <div>
                  <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-violet-500/10 to-blue-500/10 flex items-center justify-center mb-4">
                    <Icon size={24} className="text-violet-600 dark:text-violet-400" />
                  </div>
                  <h3 className="text-lg font-bold text-gray-900 dark:text-white">{tpl.name}</h3>
                  <p className="text-sm text-gray-500 mt-2 leading-relaxed line-clamp-3">
                    {tpl.description}
                  </p>
                </div>
                <div className="mt-4 flex items-center gap-2">
                  <span className="text-xs font-semibold px-2.5 py-1 bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-300 rounded-full capitalize">
                    {tpl.category}
                  </span>
                  <span className="text-xs font-semibold px-2.5 py-1 bg-violet-50 dark:bg-violet-900/20 text-violet-600 dark:text-violet-400 rounded-full">
                    {tpl.versions?.[0]?.playbooks?.length || 0} Playbooks
                  </span>
                </div>
              </div>
            )
          })}
        </div>
      )}

      {step === 2 && !hasAvailableSlot && (
        <div className="mb-6 p-4 bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 rounded-xl flex items-start gap-3">
          <Sparkles className="text-amber-600 mt-0.5" size={18} />
          <div>
            <h4 className="text-sm font-bold text-amber-900 dark:text-amber-100">Slot Limit Reached</h4>
            <p className="text-xs text-amber-700 dark:text-amber-300 mt-1">
              You've used all your {purchasedSlots} purchased agent slots. 
              To deploy this new agent, you'll need to purchase an additional slot.
            </p>
          </div>
        </div>
      )}

      {step === 2 && (
        <div className="max-w-2xl bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-800 shadow-sm overflow-hidden mb-8">
          {!hasAvailableSlot && (
            <div className="p-6 border-b border-gray-100 dark:border-gray-800 bg-amber-50/10 dark:bg-amber-900/10">
              <label className="block text-sm font-bold text-gray-900 dark:text-white mb-4">
                Select a Plan for this Slot
              </label>
              <div className="grid grid-cols-3 gap-3">
                {[
                  { id: 'starter', name: 'Starter', price: 39 },
                  { id: 'growth', name: 'Growth', price: 99 },
                  { id: 'business', name: 'Business', price: 199 },
                ].map((p) => (
                  <button
                    key={p.id}
                    type="button"
                    onClick={() => setSelectedPlan(p.id as any)}
                    className={`p-3 rounded-xl border-2 text-left transition-all ${
                      selectedPlan === p.id 
                        ? 'border-violet-600 bg-violet-50 dark:bg-violet-900/20' 
                        : 'border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 hover:border-gray-300'
                    }`}
                  >
                    <div className={`text-[10px] font-bold uppercase tracking-wider ${selectedPlan === p.id ? 'text-violet-600' : 'text-gray-400'}`}>
                      {p.name}
                    </div>
                    <div className="text-lg font-bold text-gray-900 dark:text-white mt-1">
                      ${p.price}
                    </div>
                    <div className="text-[10px] text-gray-500 mt-0.5">/ month</div>
                  </button>
                ))}
              </div>
            </div>
          )}
          <div className="p-6 border-b border-gray-100 dark:border-gray-800 bg-gray-50/50 dark:bg-gray-800/20">
            <h2 className="font-semibold text-gray-900 dark:text-white">Basic Settings</h2>
          </div>
          <div className="p-6 space-y-6">
            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1.5">
                Agent Name *
              </label>
              <input
                value={agentName}
                onChange={(e) => setAgentName(e.target.value)}
                placeholder="e.g. Sales Bot"
                className="w-full px-3 py-2.5 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-violet-500"
              />
            </div>
            
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1.5">
                  Language
                </label>
                <select
                  value={language}
                  onChange={(e) => setLanguage(e.target.value)}
                  className="w-full px-3 py-2.5 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-violet-500"
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
                    className="w-5 h-5 accent-violet-600 rounded"
                  />
                  <span className="text-sm font-medium text-gray-700 dark:text-gray-300">
                    Enable Voice Integration
                  </span>
                </label>
              </div>
            </div>
          </div>

          {selectedTemplate && selectedTemplate.variables?.length > 0 && (
            <>
              <div className="p-6 border-y border-gray-100 dark:border-gray-800 bg-gray-50/50 dark:bg-gray-800/20">
                <h2 className="font-semibold text-gray-900 dark:text-white">Template Configuration</h2>
                <p className="text-sm text-gray-500 mt-1">Configure specific settings for this template. You can always edit these later.</p>
              </div>
              <div className="p-6 space-y-6">
                {selectedTemplate.variables.map((vari: any) => (
                  <div key={vari.id}>
                    <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1.5 flex items-center justify-between">
                      <span>{vari.label} {vari.is_required && '*'}</span>
                      <span className="text-xs text-gray-400 font-mono bg-gray-100 dark:bg-gray-800 px-1.5 py-0.5 rounded">{vari.key}</span>
                    </label>
                    
                    {vari.type === 'textarea' || vari.type === 'list' ? (
                      <textarea
                        value={variables[vari.key] || ''}
                        onChange={(e) => handleVariableChange(vari.key, e.target.value)}
                        className="w-full px-3 py-2.5 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-violet-500 min-h-[100px]"
                        placeholder={`Enter ${vari.label.toLowerCase()}`}
                      />
                    ) : (
                      <input
                        type={vari.type === 'number' ? 'number' : 'text'}
                        value={variables[vari.key] || ''}
                        onChange={(e) => handleVariableChange(vari.key, e.target.value)}
                        className="w-full px-3 py-2.5 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-violet-500"
                        placeholder={`Enter ${vari.label.toLowerCase()}`}
                      />
                    )}
                  </div>
                ))}
              </div>
            </>
          )}

          {/* Footer Controls */}
          <div className="p-6 border-t border-gray-100 dark:border-gray-800 bg-gray-50/50 dark:bg-gray-800/20 flex gap-3">
            <button
              onClick={handleBack}
              className="px-5 py-2.5 rounded-lg border border-gray-200 dark:border-gray-700 text-sm font-medium text-gray-700 dark:text-gray-300 hover:bg-white dark:hover:bg-gray-800 transition-colors"
            >
              Back
            </button>
            <button
              onClick={() => createMutation.mutate()}
              disabled={createMutation.isPending || !agentName || (!hasAvailableSlot && !selectedPlan)}
              className={`flex-1 px-5 py-2.5 rounded-lg text-white text-sm font-medium hover:opacity-90 disabled:opacity-50 transition-opacity flex items-center justify-center gap-2 ${
                hasAvailableSlot 
                  ? 'bg-gradient-to-r from-violet-600 to-blue-600' 
                  : 'bg-gradient-to-r from-amber-500 to-orange-600'
              }`}
            >
              {createMutation.isPending 
                ? (hasAvailableSlot ? 'Deploying Agent...' : 'Saving Draft & Redirecting...')
                : hasAvailableSlot 
                  ? 'Create & Deploy' 
                  : `Purchase & Deploy Slot`}
              {!createMutation.isPending && <ArrowRight size={16} />}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
