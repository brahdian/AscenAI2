'use client'

import { useEffect, useState } from 'react'
import { platformSettingsApi, billingApi } from '@/lib/api'
import { 
  Save, 
  RefreshCw, 
  Zap, 
  Layout, 
  BaggageClaim, 
  Shield, 
  ChevronRight,
  Plus,
  DollarSign,
  Cloud,
  Cpu,
  Layers,
  ArrowRight
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

export default function AdminPlansPage() {
  const [plans, setPlans] = useState<Plans | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [activePlanKey, setActivePlanKey] = useState<string>('growth')

  useEffect(() => {
    fetchPlans()
  }, [])

  const fetchPlans = async () => {
    try {
      setLoading(true)
      const data = await billingApi.listPlans()
      setPlans(data)
    } catch (err) {
      toast.error('Registry Sync Failed')
    } finally {
      setLoading(false)
    }
  }

  const handleUpdate = async () => {
    if (!plans) return
    try {
      setSaving(true)
      await platformSettingsApi.update('billing_plans', plans)
      toast.success('Core billing logic successfully persisted')
    } catch (err) {
      toast.error('Failed to update platform pricing')
    } finally {
      setSaving(false)
    }
  }

  const updatePlanField = (planKey: string, field: keyof Plan, value: any) => {
    if (!plans) return
    setPlans({
      ...plans,
      [planKey]: {
        ...plans[planKey],
        [field]: value
      }
    })
  }

  if (loading || !plans) {
    return (
      <div className="flex flex-col items-center justify-center h-[400px] text-gray-400">
        <RefreshCw className="animate-spin mb-4" size={32} />
        <p className="text-sm font-bold uppercase tracking-widest">Hydrating Billing Registry...</p>
      </div>
    )
  }

  const activePlan = plans[activePlanKey]

  return (
    <div className="p-8 max-w-7xl mx-auto space-y-10">
      {/* Header Section */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-6">
        <div>
          <h1 className="text-3xl font-black text-gray-900 dark:text-white tracking-tight flex items-center gap-3">
             Pricing Logic Manager
          </h1>
          <p className="text-gray-500 dark:text-gray-400 text-sm mt-1">Configure global service tiers, resource quotas, and commercial economics.</p>
        </div>
        <button
          onClick={handleUpdate}
          disabled={saving}
          className="inline-flex items-center justify-center gap-3 px-8 py-4 bg-violet-600 hover:bg-violet-700 text-white rounded-2xl text-sm font-black transition-all shadow-xl shadow-violet-500/20 active:scale-95 disabled:opacity-50"
        >
          {saving ? <RefreshCw className="animate-spin" size={18} /> : <Save size={18} />}
          Persist Platform Plans
        </button>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-10">
        {/* Tier Selector Sidebar */}
        <div className="lg:col-span-1 space-y-3">
          <p className="px-4 mb-4 text-[10px] font-bold uppercase tracking-widest text-gray-400 dark:text-gray-600">Defined Service Tiers</p>
          {Object.entries(plans).map(([key, plan]) => (
            <button
              key={key}
              onClick={() => setActivePlanKey(key)}
              className={`w-full flex items-center justify-between p-5 rounded-2xl border transition-all duration-300 group ${
                activePlanKey === key 
                ? 'bg-white dark:bg-gray-900 border-violet-500 text-gray-900 dark:text-white shadow-xl shadow-violet-500/5' 
                : 'bg-transparent border-transparent text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800/40 hover:text-gray-600'
              }`}
            >
              <div className="text-left">
                <div className={`text-xs font-black uppercase tracking-widest ${activePlanKey === key ? 'text-violet-600' : ''}`}>{key}</div>
                <div className="text-[10px] font-bold opacity-60 mt-0.5">{plan.display_name}</div>
              </div>
              <ChevronRight size={16} className={`transition-all ${activePlanKey === key ? 'text-violet-500 translate-x-1' : 'opacity-0'}`} />
            </button>
          ))}
          <button className="w-full flex items-center justify-center gap-2 p-5 rounded-2xl border-2 border-dashed border-gray-100 dark:border-gray-800 text-gray-400 hover:border-violet-500/30 hover:text-violet-500 transition-all text-[10px] font-black uppercase tracking-widest mt-6">
            <Plus size={14} /> Provision New Tier
          </button>
        </div>

        {/* Configuration Hub */}
        <div className="lg:col-span-3 space-y-8 animate-in fade-in slide-in-from-bottom-4 duration-500">
          
          {/* Visual Presentation Card */}
          <div className="bg-white dark:bg-gray-900 border border-gray-100 dark:border-gray-800 rounded-3xl shadow-sm overflow-hidden">
            <div className="px-8 py-6 border-b border-gray-50 dark:border-gray-800 bg-gray-50/50 dark:bg-gray-800/20 flex items-center justify-between">
              <div>
                <h2 className="text-sm font-black text-gray-900 dark:text-white uppercase tracking-widest flex items-center gap-2">
                  <Layout size={18} className="text-violet-500" /> Public Presentation
                </h2>
                <p className="text-[10px] text-gray-500 font-bold uppercase tracking-widest mt-1">Frontend pricing attributes</p>
              </div>
            </div>
            <div className="p-8 grid grid-cols-1 md:grid-cols-2 gap-8">
              <div className="space-y-3">
                <label className="text-[10px] font-black text-gray-400 dark:text-gray-500 uppercase tracking-widest">Public Display Label</label>
                <input 
                  value={activePlan.display_name} 
                  onChange={(e) => updatePlanField(activePlanKey, 'display_name', e.target.value)}
                  className="w-full bg-gray-50 dark:bg-gray-950 border border-gray-100 dark:border-gray-800 rounded-xl px-4 py-3 text-gray-900 dark:text-white text-sm font-bold focus:outline-none focus:ring-2 focus:ring-violet-500/20 transition-all"
                />
              </div>
              <div className="space-y-3">
                <label className="text-[10px] font-black text-gray-400 dark:text-gray-500 uppercase tracking-widest">Marketing Badge</label>
                <input 
                  value={activePlan.badge || ''} 
                  onChange={(e) => updatePlanField(activePlanKey, 'badge', e.target.value)}
                  placeholder="e.g. Recommended"
                  className="w-full bg-gray-50 dark:bg-gray-950 border border-gray-100 dark:border-gray-800 rounded-xl px-4 py-3 text-gray-900 dark:text-white text-sm font-bold focus:outline-none focus:ring-2 focus:ring-violet-500/20 transition-all"
                />
              </div>
              <div className="space-y-3 md:col-span-2">
                <label className="text-[10px] font-black text-gray-400 dark:text-gray-500 uppercase tracking-widest">Tier Narrative</label>
                <textarea 
                  value={activePlan.description} 
                  onChange={(e) => updatePlanField(activePlanKey, 'description', e.target.value)}
                  rows={2}
                  className="w-full bg-gray-50 dark:bg-gray-950 border border-gray-100 dark:border-gray-800 rounded-xl px-4 py-3 text-gray-900 dark:text-white text-sm font-medium focus:outline-none focus:ring-2 focus:ring-violet-500/20 transition-all"
                />
              </div>
              
              <div className="flex items-center gap-4">
                 <button 
                  onClick={() => updatePlanField(activePlanKey, 'highlight', !activePlan.highlight)}
                  className={`w-12 h-6 rounded-full transition-all relative ${activePlan.highlight ? 'bg-violet-600' : 'bg-gray-200 dark:bg-gray-800'}`}
                 >
                   <div className={`absolute top-1 w-4 h-4 bg-white rounded-full shadow-sm transition-all ${activePlan.highlight ? 'left-7' : 'left-1'}`} />
                 </button>
                 <span className="text-xs font-bold text-gray-500 uppercase tracking-widest">High-Impact Visual State</span>
              </div>
            </div>
          </div>

          {/* Economics Card */}
          <div className="bg-white dark:bg-gray-900 border border-gray-100 dark:border-gray-800 rounded-3xl shadow-sm overflow-hidden">
            <div className="px-8 py-6 border-b border-gray-50 dark:border-gray-800 bg-gray-50/50 dark:bg-gray-800/20">
              <h2 className="text-sm font-black text-gray-900 dark:text-white uppercase tracking-widest flex items-center gap-2">
                <BaggageClaim size={18} className="text-emerald-500" /> Platform Economics & Quotas
              </h2>
            </div>
            <div className="p-8 grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-8">
              <div className="space-y-3">
                <label className="text-[10px] font-black text-gray-400 dark:text-gray-500 uppercase tracking-widest flex items-center justify-between">
                  Unit Price 
                  <span className="text-violet-500">USD/AGENT</span>
                </label>
                <div className="relative group">
                  <span className="absolute left-4 top-1/2 -translate-y-1/2 text-gray-300 group-focus-within:text-violet-500 transition-colors"><DollarSign size={14} /></span>
                  <input 
                    type="number"
                    value={activePlan.price_per_agent || ''} 
                    onChange={(e) => updatePlanField(activePlanKey, 'price_per_agent', parseFloat(e.target.value) || 0)}
                    className="w-full bg-gray-50 dark:bg-gray-950 border border-gray-100 dark:border-gray-800 rounded-xl pl-10 pr-4 py-3 text-gray-900 dark:text-white text-sm font-black focus:outline-none focus:ring-2 focus:ring-violet-500/20"
                  />
                </div>
              </div>

              <div className="space-y-3">
                <label className="text-[10px] font-black text-gray-400 dark:text-gray-500 uppercase tracking-widest">Base Compute Capacity</label>
                <div className="relative group">
                   <span className="absolute left-4 top-1/2 -translate-y-1/2 text-gray-300 group-focus-within:text-violet-500 transition-colors"><Cpu size={14} /></span>
                   <input 
                     type="number"
                     value={activePlan.chat_equivalents_included || ''} 
                     onChange={(e) => updatePlanField(activePlanKey, 'chat_equivalents_included', parseInt(e.target.value) || 0)}
                     className="w-full bg-gray-50 dark:bg-gray-950 border border-gray-100 dark:border-gray-800 rounded-xl pl-10 pr-4 py-3 text-gray-900 dark:text-white text-sm font-black focus:outline-none focus:ring-2 focus:ring-violet-500/20"
                   />
                </div>
              </div>

              <div className="space-y-3">
                <label className="text-[10px] font-black text-gray-400 dark:text-gray-500 uppercase tracking-widest">Voice Allotment (Min)</label>
                <div className="relative group">
                   <span className="absolute left-4 top-1/2 -translate-y-1/2 text-gray-300 group-focus-within:text-violet-500 transition-colors"><Zap size={14} /></span>
                   <input 
                     type="number"
                     value={activePlan.voice_minutes_included || ''} 
                     onChange={(e) => updatePlanField(activePlanKey, 'voice_minutes_included', parseInt(e.target.value) || 0)}
                     className="w-full bg-gray-50 dark:bg-gray-950 border border-gray-100 dark:border-gray-800 rounded-xl pl-10 pr-4 py-3 text-gray-900 dark:text-white text-sm font-black focus:outline-none focus:ring-2 focus:ring-violet-500/20"
                   />
                </div>
              </div>

              {/* Overage Matrix */}
              <div className="lg:col-span-3 p-6 bg-violet-50/50 dark:bg-violet-900/5 rounded-3xl border border-violet-100 dark:border-violet-900/20 space-y-6 mt-4">
                 <div className="flex items-center justify-between">
                    <h4 className="text-xs font-black text-violet-600 dark:text-violet-400 uppercase tracking-widest flex items-center gap-2">
                       <Cloud size={14} /> Consumption Overage Matrix
                    </h4>
                 </div>
                 <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
                    <div className="space-y-3">
                      <label className="text-[10px] font-black text-gray-400 dark:text-gray-500 uppercase tracking-widest">Compute Unit Surcharge</label>
                      <div className="flex items-center gap-3">
                         <input 
                            type="number"
                            step="0.0001"
                            value={activePlan.overage_per_chat_equivalent} 
                            onChange={(e) => updatePlanField(activePlanKey, 'overage_per_chat_equivalent', parseFloat(e.target.value) || 0)}
                            className="flex-1 bg-white dark:bg-gray-900 border border-violet-100 dark:border-violet-900/30 rounded-xl px-4 py-3 text-gray-900 dark:text-white font-mono text-xs font-black"
                         />
                         <span className="text-[10px] font-bold text-violet-400 uppercase">/ UNIT</span>
                      </div>
                    </div>
                    <div className="space-y-3">
                      <label className="text-[10px] font-black text-gray-400 dark:text-gray-500 uppercase tracking-widest">Voice Delivery Surcharge</label>
                      <div className="flex items-center gap-3">
                         <input 
                            type="number"
                            step="0.0001"
                            value={activePlan.overage_per_voice_minute} 
                            onChange={(e) => updatePlanField(activePlanKey, 'overage_per_voice_minute', parseFloat(e.target.value) || 0)}
                            className="flex-1 bg-white dark:bg-gray-900 border border-violet-100 dark:border-violet-900/30 rounded-xl px-4 py-3 text-gray-900 dark:text-white font-mono text-xs font-black"
                         />
                         <span className="text-[10px] font-bold text-violet-400 uppercase">/ MIN</span>
                      </div>
                    </div>
                 </div>
              </div>
            </div>
          </div>

          {/* Capabilities Card */}
          <div className="bg-white dark:bg-gray-900 border border-gray-100 dark:border-gray-800 rounded-3xl shadow-sm overflow-hidden">
            <div className="px-8 py-6 border-b border-gray-50 dark:border-gray-800 bg-gray-50/50 dark:bg-gray-800/20 flex items-center justify-between">
               <h2 className="text-sm font-black text-gray-900 dark:text-white uppercase tracking-widest flex items-center gap-2">
                 <Shield size={18} className="text-violet-500" /> Platform Feature Gates
               </h2>
            </div>
            <div className="p-8 space-y-8">
              <div className="flex items-center justify-between p-6 bg-gray-50/50 dark:bg-gray-800/20 rounded-2xl border border-gray-100 dark:border-gray-800 group hover:border-violet-500/30 transition-all">
                <div className="flex items-center gap-4">
                   <div className="w-10 h-10 rounded-xl bg-violet-100 dark:bg-violet-900/30 flex items-center justify-center text-violet-600">
                      <Zap size={20} />
                   </div>
                   <div>
                      <div className="text-sm font-black text-gray-900 dark:text-white">Active Voice Synchronization</div>
                      <div className="text-[10px] text-gray-500 font-bold uppercase tracking-widest mt-1">Multi-modal audio ingest & delivery</div>
                   </div>
                </div>
                <button 
                  onClick={() => updatePlanField(activePlanKey, 'voice_enabled', !activePlan.voice_enabled)}
                  className={`w-12 h-6 rounded-full transition-all relative ${activePlan.voice_enabled ? 'bg-violet-600 shadow-lg shadow-violet-500/30' : 'bg-gray-200 dark:bg-gray-800'}`}
                >
                   <div className={`absolute top-1 w-4 h-4 bg-white rounded-full transition-all ${activePlan.voice_enabled ? 'left-7' : 'left-1'}`} />
                </button>
              </div>

              <div className="space-y-3">
                <label className="text-[10px] font-black text-gray-400 dark:text-gray-500 uppercase tracking-widest">Compute Engine Override</label>
                <div className="relative group">
                   <span className="absolute left-4 top-1/2 -translate-y-1/2 text-gray-300 group-focus-within:text-violet-500 transition-colors"><Layers size={14} /></span>
                   <input 
                     value={activePlan.model} 
                     onChange={(e) => updatePlanField(activePlanKey, 'model', e.target.value)}
                     className="w-full bg-gray-50 dark:bg-gray-950 border border-gray-100 dark:border-gray-800 rounded-xl pl-10 pr-4 py-3 text-gray-900 dark:text-white font-mono text-xs font-black focus:outline-none focus:ring-2 focus:ring-violet-500/20"
                     placeholder="e.g. gemini-1.5-pro"
                   />
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
