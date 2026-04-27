'use client'

import { useEffect, useState } from 'react'
import { billingApi } from '@/lib/api'
import {
  CreditCard, Zap, MessageSquare, Bot, Mic, ExternalLink, Download,
  CheckCircle, AlertCircle, Clock, ChevronLeft, ChevronRight,
  Loader2, TrendingUp, Sparkles, Phone, Minus, Plus, ArrowLeft,
} from 'lucide-react'
import toast from 'react-hot-toast'
import Link from 'next/link'

const PLAN_ORDER = ['starter', 'growth', 'business', 'enterprise']

interface PlanDefinition {
  display_name: string
  price_per_agent: number | null
  price_per_agent_yearly: number | null
  chat_equivalents_included: number | null
  voice_minutes_included: number | null
  voice_enabled: boolean
}

interface BillingOverview {
  plan: string
  plan_display_name: string
  subscription_status?: string
  price_per_agent: number
  agent_count: number
  limits: { chat_messages: number | null; voice_minutes: number | null; team_seats: number | null }
  usage: { sessions: number; messages: number; chats: number; tokens: number; voice_minutes: number; messages_pct: number | null; voice_pct: number | null }
  estimated_bill: { base: number; overage: number; total: number }
  billing_period: { start: string; end: string }
  portal_url?: string | null
}

interface AgentBilling {
  agent_id: string | null
  agent_name: string
  sessions: number
  messages: number
  chats?: number
  tokens: number
  voice_minutes: number
  base_cost: number
  overage: number
  total_cost: number
}

interface Invoice {
  id: string
  amount_due: number
  status: string
  created: number
  invoice_pdf: string
  hosted_invoice_url: string
}

export default function AgentSlotsPage() {
  const [overview, setOverview] = useState<BillingOverview | null>(null)
  const [agents, setAgents] = useState<AgentBilling[]>([])
  const [invoices, setInvoices] = useState<Invoice[]>([])
  const [plans, setPlans] = useState<Record<string, PlanDefinition>>({})
  const [billingCycle, setBillingCycle] = useState<'monthly' | 'yearly'>('monthly')
  const [loading, setLoading] = useState(true)
  const [portalLoading, setPortalLoading] = useState(false)
  const [changingPlan, setChangingPlan] = useState(false)
  const [syncLoading, setSyncLoading] = useState(false)
  const [selectedAgentId, setSelectedAgentId] = useState<string>('total')
  // Slot slider
  const [slotQty, setSlotQty] = useState(1)
  const [savingSlots, setSavingSlots] = useState(false)

  useEffect(() => {
    Promise.all([billingApi.overview(), billingApi.agents(), billingApi.listPlans(), billingApi.getInvoices().then(r => r.invoices).catch(() => [])])
      .then(([ov, ag, pl, inv]) => {
        setOverview(ov); setAgents(ag); setPlans(pl); setInvoices(inv)
        setSlotQty(ov.agent_count || 1)
        if (ag.length > 0) setSelectedAgentId('total')
      })
      .finally(() => setLoading(false))
  }, [])

  const handleManageBilling = async () => {
    if (overview?.portal_url) { window.open(overview.portal_url, '_blank'); return }
    setPortalLoading(true)
    try { const { portal_url } = await billingApi.createPortalSession(); window.open(portal_url, '_blank') }
    catch { toast.error('Failed to open billing portal') }
    finally { setPortalLoading(false) }
  }

  const handleUpgrade = async (plan: string) => {
    setChangingPlan(true)
    try {
      const data = await billingApi.createCheckoutSession({ plan, billing_cycle: billingCycle })
      if (data.checkout_url) window.location.href = data.checkout_url
    } catch { toast.error('Failed to start plan change'); setChangingPlan(false) }
  }

  const handleSyncSubscription = async () => {
    setSyncLoading(true)
    try {
      const result = await billingApi.syncSubscription()
      if (result.status === 'active') {
        const n = result.agents_activated ?? 0
        toast.success(n > 0 ? `✅ Synced! ${n} agent${n !== 1 ? 's' : ''} activated.` : 'All agents already active.')
        const [ov, ag] = await Promise.all([billingApi.overview(), billingApi.agents()])
        setOverview(ov); setAgents(ag); setSlotQty(ov.agent_count || 1)
      } else { toast.error(`Subscription status: ${result.subscription_status}`) }
    } catch { toast.error('Failed to sync subscription') }
    finally { setSyncLoading(false) }
  }

  const handleUpdateSlots = async () => {
    setSavingSlots(true)
    try {
      const res = await fetch('/api/v1/tenant-admin/billing/agent-slots/update', {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ quantity: slotQty }),
      })
      if (!res.ok) throw new Error()
      toast.success(`Updated to ${slotQty} agent slot${slotQty !== 1 ? 's' : ''}`)
      const ov = await billingApi.overview()
      setOverview(ov)
    } catch { toast.error('Failed to update slots') }
    finally { setSavingSlots(false) }
  }

  if (loading) return (
    <div className="p-8 flex items-center justify-center min-h-[400px]">
      <div className="flex flex-col items-center gap-3">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-violet-600" />
        <p className="text-sm text-gray-500">Loading billing information...</p>
      </div>
    </div>
  )

  const fmt = (n: number) => `$${n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
  const fmtNum = (n: number) => n.toLocaleString()
  const fmtLimit = (n: number | null) => n == null ? 'Unlimited' : fmtNum(n)
  const formatDate = (ts: number) => new Date(ts * 1000).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })
  const hasSelectedPlan = !!(overview?.plan && overview.plan !== 'none')
  const isSubscribed = hasSelectedPlan && (overview?.subscription_status === 'active' || overview?.subscription_status === 'trialing')
  const currentPlanKey = overview?.plan || 'none'
  const currentPlanIndex = PLAN_ORDER.indexOf(currentPlanKey)
  const isOverage = (overview?.estimated_bill.overage || 0) > 0
  const slotDiff = slotQty - (overview?.agent_count || 0)

  return (
    <div className="p-8 w-full max-w-6xl mx-auto">
      <Link href="/tenant-admin/billing" className="flex items-center gap-1.5 text-sm text-gray-500 hover:text-violet-600 dark:hover:text-violet-400 mb-6 transition-colors">
        <ArrowLeft size={14} /> Back to Billing
      </Link>

      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white flex items-center gap-2">
            <CreditCard size={24} className="text-violet-500" />Agent Slots & Billing
          </h1>
          <p className="text-gray-500 mt-1">Manage your subscription plan and active agent seats</p>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={handleSyncSubscription} disabled={syncLoading}
            className="flex items-center gap-2 px-4 py-2 bg-emerald-50 dark:bg-emerald-900/20 hover:bg-emerald-100 text-emerald-700 dark:text-emerald-400 border border-emerald-200 dark:border-emerald-800 rounded-lg text-sm font-medium transition-colors">
            {syncLoading ? <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-current" /> : <CheckCircle size={16} />}
            Sync Agent Status
          </button>
          <button onClick={handleManageBilling} disabled={portalLoading}
            className="flex items-center gap-2 px-4 py-2 bg-gray-100 dark:bg-gray-800 hover:bg-gray-200 text-gray-700 dark:text-gray-200 rounded-lg text-sm font-medium transition-colors">
            {portalLoading ? <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-current" /> : <ExternalLink size={16} />}
            Stripe Portal
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-8">
        <div className="lg:col-span-2 space-y-6">
          {/* Plan hero card */}
          <div className="bg-gradient-to-br from-violet-600 to-indigo-700 rounded-2xl p-6 text-white shadow-lg shadow-violet-500/20 relative overflow-hidden">
            <div className="absolute top-0 right-0 p-8 opacity-10"><TrendingUp size={120} /></div>
            <div className="relative z-10">
              <div className="flex justify-between items-start">
                <div>
                  <div className="flex items-center gap-3 mb-3">
                    <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold bg-white/20">Current Plan</span>
                    {overview?.subscription_status && (
                      <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider ${overview.subscription_status === 'active' ? 'bg-emerald-400/20 text-emerald-100 border border-emerald-400/30' : 'bg-amber-400/20 text-amber-100 border border-amber-400/30'}`}>
                        {overview.subscription_status}
                      </span>
                    )}
                  </div>
                  <p className="text-3xl font-bold mb-1">{overview?.plan_display_name || 'Not Subscribed'}</p>
                  <p className="text-violet-100 text-sm opacity-80">{fmt(overview?.price_per_agent || 0)} per active agent / month</p>
                </div>
                <div className="text-right">
                  <p className="text-violet-100 text-xs font-medium uppercase tracking-wider mb-1">Estimated Cost</p>
                  <p className="text-4xl font-black">{fmt(overview?.estimated_bill.total || 0)}</p>
                  <div className="mt-2 flex items-center justify-end gap-1.5 text-xs text-violet-200">
                    <Clock size={12} /><span>Period ends {overview?.billing_period.end}</span>
                  </div>
                </div>
              </div>
              <div className="mt-8 pt-6 border-t border-white/10 flex items-center justify-between">
                <div className="flex gap-6">
                  <div>
                    <p className="text-xs text-violet-200 mb-0.5">Active Agent Slots</p>
                    <p className="text-lg font-bold">{overview?.agent_count || 0}</p>
                  </div>
                  {isSubscribed && (<>
                    <div>
                      <p className="text-xs text-violet-200 mb-0.5">Base Fee</p>
                      <p className="text-lg font-bold">{fmt(overview?.estimated_bill.base || 0)}</p>
                    </div>
                    {isOverage && (
                      <div>
                        <p className="text-xs text-violet-200 mb-0.5">Overage</p>
                        <p className="text-lg font-bold text-amber-300">{fmt(overview?.estimated_bill.overage || 0)}</p>
                      </div>
                    )}
                  </>)}
                </div>
                <button onClick={handleManageBilling} className="px-4 py-2 bg-white text-violet-600 rounded-xl text-sm font-bold hover:bg-violet-50 transition-colors shadow-sm">
                  {isSubscribed ? 'Change Plan' : 'Choose Plan'}
                </button>
              </div>
            </div>
          </div>

          {/* Slot slider */}
          <div className="bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-800 p-6">
            <h2 className="text-base font-bold text-gray-900 dark:text-white flex items-center gap-2 mb-6">
              <Bot size={18} className="text-violet-500" />Adjust Agent Slots
            </h2>
            <div className="flex items-center gap-4 mb-4">
              <button onClick={() => setSlotQty(q => Math.max(1, q - 1))} disabled={slotQty <= 1}
                className="w-10 h-10 rounded-lg border border-gray-200 dark:border-gray-700 flex items-center justify-center text-gray-600 hover:bg-gray-50 dark:hover:bg-gray-800 disabled:opacity-30 transition-colors">
                <Minus size={16} />
              </button>
              <div className="flex-1">
                <input type="range" min={1} max={50} value={slotQty} onChange={e => setSlotQty(Number(e.target.value))} className="w-full accent-violet-600" />
                <div className="flex justify-between text-xs text-gray-400 mt-1">
                  <span>1</span>
                  <span className="font-bold text-gray-900 dark:text-white">{slotQty} slots · {fmt(slotQty * (overview?.price_per_agent || 0))}/mo</span>
                  <span>50</span>
                </div>
              </div>
              <button onClick={() => setSlotQty(q => Math.min(50, q + 1))}
                className="w-10 h-10 rounded-lg border border-gray-200 dark:border-gray-700 flex items-center justify-center text-gray-600 hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors">
                <Plus size={16} />
              </button>
            </div>
            {slotDiff !== 0 && (
              <p className="text-xs text-gray-500 mb-4">
                {slotDiff > 0 ? `+${slotDiff} slot${slotDiff > 1 ? 's' : ''} — prorated charge applied today.` : `${Math.abs(slotDiff)} slot${Math.abs(slotDiff) > 1 ? 's' : ''} removed — credit on next invoice.`}
              </p>
            )}
            <button onClick={handleUpdateSlots} disabled={savingSlots || slotQty === (overview?.agent_count || 0)}
              className="w-full py-2.5 bg-violet-600 hover:bg-violet-700 disabled:opacity-50 text-white text-sm font-medium rounded-xl transition-colors">
              {savingSlots ? 'Updating…' : slotQty === (overview?.agent_count || 0) ? 'No changes' : `Update to ${slotQty} slot${slotQty !== 1 ? 's' : ''}`}
            </button>
          </div>
        </div>

        {/* Invoices */}
        <div className="bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-800 p-6 flex flex-col">
          <h2 className="text-base font-bold text-gray-900 dark:text-white mb-4 flex items-center gap-2">
            <Download size={18} className="text-violet-500" />Recent Invoices
          </h2>
          {invoices.length === 0 ? (
            <div className="flex-1 flex flex-col items-center justify-center text-center p-8 border-2 border-dashed border-gray-100 dark:border-gray-800 rounded-xl">
              <AlertCircle size={32} className="text-gray-300 mb-2" />
              <p className="text-sm text-gray-500">No invoices found yet.</p>
            </div>
          ) : (
            <div className="space-y-3 flex-1 overflow-y-auto pr-1">
              {invoices.map(inv => (
                <div key={inv.id} className="group p-3 rounded-xl border border-gray-100 dark:border-gray-800 hover:border-violet-200 hover:bg-violet-50/30 transition-all cursor-pointer" onClick={() => window.open(inv.hosted_invoice_url, '_blank')}>
                  <div className="flex justify-between items-start mb-1.5">
                    <p className="text-xs font-bold text-gray-900 dark:text-white">{formatDate(inv.created)}</p>
                    <span className={`text-[10px] px-1.5 py-0.5 rounded-full font-medium ${inv.status === 'paid' ? 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400' : 'bg-amber-100 text-amber-700'}`}>
                      {inv.status.toUpperCase()}
                    </span>
                  </div>
                  <div className="flex justify-between items-center">
                    <p className="text-lg font-black text-gray-900 dark:text-white">${(inv.amount_due / 100).toFixed(2)}</p>
                    <a href={inv.invoice_pdf} target="_blank" rel="noreferrer" className="text-gray-400 hover:text-violet-600 transition-colors" onClick={e => e.stopPropagation()}>
                      <Download size={14} />
                    </a>
                  </div>
                </div>
              ))}
            </div>
          )}
          <button onClick={handleManageBilling} className="mt-6 w-full py-2.5 text-xs text-gray-500 hover:text-violet-600 font-medium border border-gray-100 dark:border-gray-800 rounded-xl hover:bg-gray-50 dark:hover:bg-gray-800 transition-all">
            See all billing history
          </button>
        </div>
      </div>

      {/* Plans */}
      <div id="plans-section" className="bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-800 p-8 shadow-sm">
        <div className="flex items-center justify-between mb-8">
          <div>
            <h2 className="text-xl font-bold text-gray-900 dark:text-white">Available Plans</h2>
            <p className="text-sm text-gray-500 mt-1">Scale your AI operations with predictable, per-agent pricing</p>
          </div>
          <div className="flex items-center gap-1 p-1 bg-gray-100 dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700">
            {(['monthly', 'yearly'] as const).map(c => (
              <button key={c} onClick={() => setBillingCycle(c)} className={`px-4 py-1.5 text-xs font-bold rounded-lg transition-all flex items-center gap-2 ${billingCycle === c ? 'bg-white dark:bg-gray-700 text-violet-600 shadow-sm' : 'text-gray-500 hover:text-gray-700 dark:hover:text-gray-300'}`}>
                {c === 'yearly' ? 'Yearly' : 'Monthly'}
                {c === 'yearly' && <span className="px-1.5 py-0.5 bg-emerald-100 dark:bg-emerald-900/30 text-emerald-600 text-[10px] font-black rounded-md">-20%</span>}
              </button>
            ))}
          </div>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6">
          {Object.entries(plans).map(([key, plan]) => {
            const isCurrentPlan = key === currentPlanKey && isSubscribed
            const planIndex = PLAN_ORDER.indexOf(key)
            const isUpgrade = currentPlanKey !== 'none' && planIndex > currentPlanIndex
            const isDowngrade = currentPlanKey !== 'none' && planIndex < currentPlanIndex
            return (
              <div key={key} className={`relative group p-6 rounded-2xl border-2 transition-all duration-300 ${isCurrentPlan ? 'border-violet-500 bg-violet-50/30 dark:bg-violet-900/10 shadow-lg shadow-violet-500/5' : 'border-gray-100 dark:border-gray-800 hover:border-violet-200 dark:hover:border-violet-800 bg-white dark:bg-gray-900'}`}>
                {isCurrentPlan && <div className="absolute -top-3 left-1/2 -translate-x-1/2 px-3 py-1 bg-violet-600 text-white text-[10px] font-black uppercase tracking-widest rounded-full shadow-lg">Current Plan</div>}
                <h3 className="font-bold text-gray-900 dark:text-white text-lg mb-1">{plan.display_name}</h3>
                <div className="mb-4">
                  <p className="text-3xl font-black text-gray-900 dark:text-white">{billingCycle === 'yearly' ? (plan.price_per_agent_yearly ? `$${plan.price_per_agent_yearly}` : 'Custom') : (plan.price_per_agent ? `$${plan.price_per_agent}` : 'Custom')}</p>
                  {plan.price_per_agent && <p className="text-[10px] font-bold text-gray-400 uppercase tracking-tighter">Per Active Agent / {billingCycle === 'yearly' ? 'Year' : 'Month'}</p>}
                </div>
                <div className="space-y-3 mb-8">
                  <div className="flex items-center gap-2 text-sm text-gray-600 dark:text-gray-400"><MessageSquare size={14} className="text-violet-500" /><span>{plan.chat_equivalents_included ? `${(plan.chat_equivalents_included / 1000).toFixed(1)}K Units` : 'Custom Units'}</span></div>
                  <div className="flex items-center gap-2 text-sm text-gray-600 dark:text-gray-400"><Mic size={14} className="text-violet-500" /><span>{plan.voice_minutes_included ? `${plan.voice_minutes_included}m Voice` : plan.voice_minutes_included === 0 ? 'No Voice' : 'Custom Voice'}</span></div>
                </div>
                {isCurrentPlan ? (
                  <button disabled className="w-full py-3 text-sm font-bold text-violet-600 bg-violet-100 dark:bg-violet-900/30 rounded-xl flex items-center justify-center gap-2"><CheckCircle size={16} />Current</button>
                ) : (
                  <button onClick={() => handleUpgrade(key)} disabled={changingPlan} className={`w-full py-3 text-sm font-bold rounded-xl transition-all flex items-center justify-center gap-2 ${isUpgrade ? 'bg-violet-600 text-white hover:bg-violet-700 shadow-lg shadow-violet-600/20' : 'bg-gray-100 dark:bg-gray-800 text-gray-900 dark:text-white hover:bg-gray-200 dark:hover:bg-gray-700'}`}>
                    {changingPlan ? <Loader2 className="w-4 h-4 animate-spin" /> : key === 'enterprise' ? 'Talk to Sales' : isUpgrade ? 'Upgrade' : isDowngrade ? 'Downgrade' : 'Select'}
                  </button>
                )}
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
