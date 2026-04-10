'use client'

import { useEffect, useState } from 'react'
import { platformSettingsApi, billingApi } from '@/lib/api'
import {
  Save, RefreshCw, Zap, Shield, ChevronRight, Plus, DollarSign, X,
  Cpu, Layers, MessageSquare, Mic, Users,
} from 'lucide-react'
import toast from 'react-hot-toast'

interface Plan {
  display_name: string
  description: string
  badge?: string
  color: string
  highlight: boolean
  price_per_agent: number | null
  chat_equivalents_included: number | null
  base_chat_equivalents: number
  voice_minutes_included: number | null
  playbooks_per_agent: number | null
  rag_documents: number | null
  team_seats: number | null
  overage_per_chat_equivalent: number
  overage_per_voice_minute: number
  voice_enabled: boolean
  model: string
}

type Plans = Record<string, Plan>

const DEFAULT_NEW_PLAN: Plan = {
  display_name: 'New Plan',
  description: 'Describe this plan.',
  badge: '',
  color: 'violet',
  highlight: false,
  price_per_agent: 0,
  chat_equivalents_included: 1000,
  base_chat_equivalents: 1000,
  voice_minutes_included: 0,
  playbooks_per_agent: 3,
  rag_documents: 10,
  team_seats: 3,
  overage_per_chat_equivalent: 0.01,
  overage_per_voice_minute: 0.05,
  voice_enabled: false,
  model: 'gemini-2.5-flash-lite',
}

function Toggle({ on, onChange }: { on: boolean; onChange: () => void }) {
  return (
    <button
      type="button"
      onClick={onChange}
      className={`w-11 h-6 rounded-full transition-colors relative flex-shrink-0 ${on ? 'bg-violet-600' : 'bg-gray-200 dark:bg-gray-700'}`}
    >
      <div className={`absolute top-1 w-4 h-4 bg-white rounded-full shadow transition-all ${on ? 'left-6' : 'left-1'}`} />
    </button>
  )
}

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between">
        <label className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide">{label}</label>
        {hint && <span className="text-[10px] text-gray-400">{hint}</span>}
      </div>
      {children}
    </div>
  )
}

const INPUT_CLS = 'w-full bg-gray-50 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg px-3 py-2.5 text-sm text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-violet-500/30 focus:border-violet-400 transition-colors'

export default function AdminPlansPage() {
  const [plans, setPlans] = useState<Plans | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [activePlanKey, setActivePlanKey] = useState<string>('')
  const [showAddModal, setShowAddModal] = useState(false)
  const [newPlanKey, setNewPlanKey] = useState('')
  const [newPlan, setNewPlan] = useState<Plan>({ ...DEFAULT_NEW_PLAN })

  useEffect(() => { fetchPlans() }, [])

  async function fetchPlans() {
    try {
      setLoading(true)
      const data = await billingApi.listPlans()
      setPlans(data)
      setActivePlanKey(Object.keys(data)[0] || '')
    } catch {
      toast.error('Failed to load plans')
    } finally {
      setLoading(false)
    }
  }

  async function handleSave() {
    if (!plans) return
    try {
      setSaving(true)
      await platformSettingsApi.update('billing_plans', plans)
      toast.success('Plans saved successfully')
    } catch {
      toast.error('Failed to save plans')
    } finally {
      setSaving(false)
    }
  }

  function updateField(planKey: string, field: keyof Plan, value: any) {
    if (!plans) return
    setPlans({ ...plans, [planKey]: { ...plans[planKey], [field]: value } })
  }

  function handleAddPlan() {
    const key = newPlanKey.trim().toLowerCase().replace(/\s+/g, '_')
    if (!key || !plans) return
    if (plans[key]) { toast.error('A plan with that key already exists'); return }
    setPlans({ ...plans, [key]: { ...newPlan } })
    setActivePlanKey(key)
    setShowAddModal(false)
    setNewPlanKey('')
    setNewPlan({ ...DEFAULT_NEW_PLAN })
    toast.success(`Plan "${key}" added — click Save to persist`)
  }

  function handleDeletePlan(key: string) {
    if (!plans) return
    const remaining = Object.keys(plans).filter((k) => k !== key)
    if (remaining.length === 0) { toast.error('Cannot delete the last plan'); return }
    const updated = { ...plans }
    delete updated[key]
    setPlans(updated)
    setActivePlanKey(remaining[0])
    toast('Plan removed — click Save to persist', { icon: '🗑' })
  }

  if (loading || !plans) {
    return (
      <div className="flex items-center justify-center h-80">
        <div className="flex items-center gap-3 text-gray-400">
          <RefreshCw className="animate-spin" size={20} />
          <span className="text-sm">Loading plans…</span>
        </div>
      </div>
    )
  }

  const activePlan = plans[activePlanKey]
  if (!activePlan) return null

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Plans & Pricing</h1>
          <p className="text-sm text-gray-500 mt-0.5">Manage service tiers, quotas, and overage rates</p>
        </div>
        <button
          onClick={handleSave}
          disabled={saving}
          className="flex items-center gap-2 px-4 py-2 bg-violet-600 hover:bg-violet-700 text-white rounded-lg text-sm font-semibold transition-colors disabled:opacity-50"
        >
          {saving ? <RefreshCw size={15} className="animate-spin" /> : <Save size={15} />}
          Save Changes
        </button>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
        {/* Sidebar */}
        <div className="lg:col-span-1 space-y-1">
          <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide px-2 mb-3">Plans</p>
          {Object.entries(plans).map(([key, plan]) => (
            <button
              key={key}
              onClick={() => setActivePlanKey(key)}
              className={`w-full flex items-center justify-between px-3 py-2.5 rounded-lg text-sm transition-colors ${
                activePlanKey === key
                  ? 'bg-violet-50 dark:bg-violet-900/20 text-violet-700 dark:text-violet-300 font-semibold'
                  : 'text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800'
              }`}
            >
              <div className="text-left">
                <p className="font-medium">{plan.display_name}</p>
                <p className="text-xs opacity-60">
                  {plan.price_per_agent !== null ? `$${plan.price_per_agent}/mo` : 'Custom'}
                </p>
              </div>
              {activePlanKey === key && <ChevronRight size={14} />}
            </button>
          ))}
          <button
            onClick={() => setShowAddModal(true)}
            className="w-full flex items-center justify-center gap-2 px-3 py-2.5 mt-2 rounded-lg border-2 border-dashed border-gray-200 dark:border-gray-700 text-sm text-gray-400 hover:border-violet-400 hover:text-violet-600 transition-colors"
          >
            <Plus size={14} /> Add Plan
          </button>
        </div>

        {/* Editor */}
        <div className="lg:col-span-3 space-y-4">
          {/* Presentation */}
          <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 p-5 space-y-4">
            <div className="flex items-center justify-between">
              <h2 className="text-sm font-semibold text-gray-900 dark:text-white">Presentation</h2>
              <button
                onClick={() => handleDeletePlan(activePlanKey)}
                className="text-xs text-red-500 hover:text-red-600 font-medium transition-colors"
              >
                Delete plan
              </button>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <Field label="Display Name">
                <input value={activePlan.display_name} onChange={(e) => updateField(activePlanKey, 'display_name', e.target.value)} className={INPUT_CLS} />
              </Field>
              <Field label="Badge" hint="e.g. Most Popular">
                <input value={activePlan.badge || ''} onChange={(e) => updateField(activePlanKey, 'badge', e.target.value)} className={INPUT_CLS} placeholder="Optional" />
              </Field>
              <Field label="Description" >
                <textarea value={activePlan.description} onChange={(e) => updateField(activePlanKey, 'description', e.target.value)} rows={2} className={INPUT_CLS} />
              </Field>
              <Field label="LLM Model">
                <input value={activePlan.model} onChange={(e) => updateField(activePlanKey, 'model', e.target.value)} className={`${INPUT_CLS} font-mono`} placeholder="e.g. gemini-2.5-flash-lite" />
              </Field>
            </div>
            <div className="flex items-center gap-3 pt-1">
              <Toggle on={activePlan.highlight} onChange={() => updateField(activePlanKey, 'highlight', !activePlan.highlight)} />
              <span className="text-sm text-gray-600 dark:text-gray-400">Highlight as recommended</span>
            </div>
          </div>

          {/* Pricing & Quotas */}
          <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 p-5 space-y-4">
            <h2 className="text-sm font-semibold text-gray-900 dark:text-white flex items-center gap-2">
              <DollarSign size={15} className="text-violet-500" /> Pricing & Quotas
            </h2>
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-4">
              <Field label="Price / Agent / Month" hint="USD">
                <div className="relative">
                  <span className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 text-sm">$</span>
                  <input type="number" min="0" value={activePlan.price_per_agent ?? ''} onChange={(e) => updateField(activePlanKey, 'price_per_agent', parseFloat(e.target.value) || 0)} className={`${INPUT_CLS} pl-7`} />
                </div>
              </Field>
              <Field label="Chat Messages" hint="included/mo">
                <div className="relative">
                  <MessageSquare size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
                  <input type="number" min="0" value={activePlan.chat_equivalents_included ?? ''} onChange={(e) => updateField(activePlanKey, 'chat_equivalents_included', parseInt(e.target.value) || 0)} className={`${INPUT_CLS} pl-8`} />
                </div>
              </Field>
              <Field label="Voice Minutes" hint="included/mo">
                <div className="relative">
                  <Mic size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
                  <input type="number" min="0" value={activePlan.voice_minutes_included ?? ''} onChange={(e) => updateField(activePlanKey, 'voice_minutes_included', parseInt(e.target.value) || 0)} className={`${INPUT_CLS} pl-8`} />
                </div>
              </Field>
              <Field label="Team Seats">
                <div className="relative">
                  <Users size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
                  <input type="number" min="1" value={activePlan.team_seats ?? ''} onChange={(e) => updateField(activePlanKey, 'team_seats', parseInt(e.target.value) || 1)} className={`${INPUT_CLS} pl-8`} />
                </div>
              </Field>
              <Field label="Playbooks / Agent">
                <div className="relative">
                  <Layers size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
                  <input type="number" min="1" value={activePlan.playbooks_per_agent ?? ''} onChange={(e) => updateField(activePlanKey, 'playbooks_per_agent', parseInt(e.target.value) || 1)} className={`${INPUT_CLS} pl-8`} />
                </div>
              </Field>
              <Field label="RAG Documents">
                <div className="relative">
                  <Cpu size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
                  <input type="number" min="0" value={activePlan.rag_documents ?? ''} onChange={(e) => updateField(activePlanKey, 'rag_documents', parseInt(e.target.value) || 0)} className={`${INPUT_CLS} pl-8`} />
                </div>
              </Field>
            </div>

            {/* Overage */}
            <div className="pt-2 border-t border-gray-100 dark:border-gray-800">
              <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">Overage rates</p>
              <div className="grid grid-cols-2 gap-4">
                <Field label="Per extra message" hint="USD">
                  <div className="relative">
                    <span className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 text-sm">$</span>
                    <input type="number" step="0.0001" min="0" value={activePlan.overage_per_chat_equivalent} onChange={(e) => updateField(activePlanKey, 'overage_per_chat_equivalent', parseFloat(e.target.value) || 0)} className={`${INPUT_CLS} pl-7 font-mono`} />
                  </div>
                </Field>
                <Field label="Per extra voice minute" hint="USD">
                  <div className="relative">
                    <span className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 text-sm">$</span>
                    <input type="number" step="0.0001" min="0" value={activePlan.overage_per_voice_minute} onChange={(e) => updateField(activePlanKey, 'overage_per_voice_minute', parseFloat(e.target.value) || 0)} className={`${INPUT_CLS} pl-7 font-mono`} />
                  </div>
                </Field>
              </div>
            </div>
          </div>

          {/* Feature Flags */}
          <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 p-5 space-y-3">
            <h2 className="text-sm font-semibold text-gray-900 dark:text-white flex items-center gap-2">
              <Shield size={15} className="text-violet-500" /> Feature Flags
            </h2>
            <div className="flex items-center justify-between py-2">
              <div>
                <p className="text-sm font-medium text-gray-900 dark:text-white flex items-center gap-2">
                  <Zap size={14} className="text-violet-500" /> Voice enabled
                </p>
                <p className="text-xs text-gray-400 mt-0.5">Allow tenants on this plan to use STT/TTS</p>
              </div>
              <Toggle on={activePlan.voice_enabled} onChange={() => updateField(activePlanKey, 'voice_enabled', !activePlan.voice_enabled)} />
            </div>
          </div>
        </div>
      </div>

      {/* Add Plan Modal */}
      {showAddModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm">
          <div className="bg-white dark:bg-gray-900 rounded-2xl shadow-xl border border-gray-200 dark:border-gray-800 w-full max-w-md p-6">
            <div className="flex items-center justify-between mb-5">
              <h2 className="text-base font-semibold text-gray-900 dark:text-white">Add New Plan</h2>
              <button onClick={() => setShowAddModal(false)} className="text-gray-400 hover:text-gray-600 dark:hover:text-white transition-colors">
                <X size={18} />
              </button>
            </div>
            <div className="space-y-4">
              <Field label="Plan Key" hint="e.g. starter, growth, enterprise">
                <input
                  value={newPlanKey}
                  onChange={(e) => setNewPlanKey(e.target.value)}
                  placeholder="plan_key"
                  className={`${INPUT_CLS} font-mono`}
                />
              </Field>
              <Field label="Display Name">
                <input value={newPlan.display_name} onChange={(e) => setNewPlan({ ...newPlan, display_name: e.target.value })} className={INPUT_CLS} />
              </Field>
              <Field label="Price / Agent / Month" hint="USD">
                <div className="relative">
                  <span className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 text-sm">$</span>
                  <input type="number" min="0" value={newPlan.price_per_agent ?? 0} onChange={(e) => setNewPlan({ ...newPlan, price_per_agent: parseFloat(e.target.value) || 0 })} className={`${INPUT_CLS} pl-7`} />
                </div>
              </Field>
              <Field label="Description">
                <textarea value={newPlan.description} onChange={(e) => setNewPlan({ ...newPlan, description: e.target.value })} rows={2} className={INPUT_CLS} />
              </Field>
            </div>
            <div className="flex justify-end gap-3 mt-6">
              <button onClick={() => setShowAddModal(false)} className="px-4 py-2 text-sm text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-white transition-colors">
                Cancel
              </button>
              <button
                onClick={handleAddPlan}
                disabled={!newPlanKey.trim()}
                className="px-4 py-2 bg-violet-600 hover:bg-violet-700 text-white rounded-lg text-sm font-semibold transition-colors disabled:opacity-50"
              >
                Add Plan
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
