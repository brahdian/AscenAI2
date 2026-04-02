'use client'

import { useEffect, useState } from 'react'
import { billingApi } from '@/lib/api'
import { getPlanDisplayName } from '@/lib/plans'
import {
  CreditCard,
  Zap,
  MessageSquare,
  Bot,
  Mic,
  ExternalLink,
  Download,
  CheckCircle,
  AlertCircle,
  Clock,
  ChevronRight,
  TrendingUp,
  Sparkles,
  Phone,
} from 'lucide-react'
import toast from 'react-hot-toast'

interface BillingOverview {
  plan: string
  plan_display_name: string
  subscription_status?: string
  price_per_agent: number
  agent_count: number
  limits: {
    chat_messages: number | null
    voice_minutes: number | null
    team_seats: number | null
  }
  usage: {
    sessions: number
    messages: number
    chats: number
    tokens: number
    voice_minutes: number
    messages_pct: number | null
    voice_pct: number | null
  }
  estimated_bill: {
    base: number
    overage: number
    total: number
  }
  billing_period: {
    start: string
    end: string
  }
  portal_url?: string | null
}

interface AgentBilling {
  agent_id: string | null
  agent_name: string
  sessions: number
  messages: number
  tokens: number
  voice_minutes: number
  base_cost: number
  overage: number
  total_cost: number
}

interface Invoice {
  id: string
  amount_due: number
  amount_paid: number
  status: string
  created: number
  invoice_pdf: string
  hosted_invoice_url: string
}

export default function BillingPage() {
  const [overview, setOverview] = useState<BillingOverview | null>(null)
  const [agents, setAgents] = useState<AgentBilling[]>([])
  const [invoices, setInvoices] = useState<Invoice[]>([])
  const [loading, setLoading] = useState(true)
  const [portalLoading, setPortalLoading] = useState(false)

  useEffect(() => {
    Promise.all([
      billingApi.overview(),
      billingApi.agents(),
      billingApi.getInvoices().then(r => r.invoices).catch(() => []),
    ])
      .then(([ov, ag, inv]) => {
        setOverview(ov)
        setAgents(ag)
        setInvoices(inv)
      })
      .catch((err) => {
        console.error('Failed to load billing data:', err)
        toast.error('Failed to load billing data')
      })
      .finally(() => setLoading(false))
  }, [])

  const handleManageBilling = async () => {
    if (overview?.portal_url) {
      window.open(overview.portal_url, '_blank')
      return
    }

    setPortalLoading(true)
    try {
      const { portal_url } = await billingApi.createPortalSession()
      window.open(portal_url, '_blank')
    } catch (err) {
      toast.error('Failed to open billing portal')
    } finally {
      setPortalLoading(false)
    }
  }

  if (loading) {
    return (
      <div className="p-8 flex items-center justify-center min-h-[400px]">
        <div className="flex flex-col items-center gap-3">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-violet-600" />
          <p className="text-sm text-gray-500">Loading billing information...</p>
        </div>
      </div>
    )
  }

  const fmt = (n: number) => `$${n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
  const fmtNum = (n: number) => n.toLocaleString()
  const fmtLimit = (n: number | null) => n == null ? 'Unlimited' : fmtNum(n)
  const formatDate = (ts: number) => new Date(ts * 1000).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })

  const isOverage = (overview?.estimated_bill.overage || 0) > 0

  return (
    <div className="p-8 w-full max-w-6xl mx-auto">
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white flex items-center gap-2">
            <CreditCard size={24} className="text-violet-500" />
            Billing & Usage
          </h1>
          <p className="text-gray-500 mt-1">
            Manage your subscription and track resource consumption
          </p>
        </div>
        <button
          onClick={handleManageBilling}
          disabled={portalLoading}
          className="flex items-center gap-2 px-4 py-2 bg-gray-100 dark:bg-gray-800 hover:bg-gray-200 dark:hover:bg-gray-700 text-gray-700 dark:text-gray-200 rounded-lg text-sm font-medium transition-colors"
        >
          {portalLoading ? (
            <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-current" />
          ) : (
            <ExternalLink size={16} />
          )}
          Manage Billing in Stripe
        </button>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-8">
        {/* Left Column: Plan & Cost */}
        <div className="lg:col-span-2 space-y-6">
          <div className="bg-gradient-to-br from-violet-600 to-indigo-700 rounded-2xl p-6 text-white shadow-lg shadow-violet-500/20 relative overflow-hidden">
            <div className="absolute top-0 right-0 p-8 opacity-10">
              <TrendingUp size={120} />
            </div>
            <div className="relative z-10">
              <div className="flex justify-between items-start">
                <div>
                  <div className="flex items-center gap-3 mb-3">
                    <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold bg-white/20 text-white">
                      Current Plan
                    </span>
                    {overview?.subscription_status && (
                      <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider ${
                        overview.subscription_status === 'active' 
                          ? 'bg-emerald-400/20 text-emerald-100 border border-emerald-400/30' 
                          : 'bg-amber-400/20 text-amber-100 border border-amber-400/30'
                      }`}>
                        {overview.subscription_status}
                      </span>
                    )}
                  </div>
                  <p className="text-3xl font-bold mb-1">
                    {overview?.plan_display_name || 'Standard'}
                  </p>
                  <p className="text-violet-100 text-sm opacity-80">
                    {fmt(overview?.price_per_agent || 0)} per active agent / month
                  </p>
                </div>
                <div className="text-right">
                  <p className="text-violet-100 text-xs font-medium uppercase tracking-wider mb-1">Estimated Cost</p>
                  <p className="text-4xl font-black">{fmt(overview?.estimated_bill.total || 0)}</p>
                  <div className="mt-2 flex items-center justify-end gap-1.5 text-xs text-violet-200">
                    <Clock size={12} />
                    <span>Period ends {overview?.billing_period.end}</span>
                  </div>
                </div>
              </div>

              <div className="mt-8 pt-6 border-t border-white/10 flex items-center justify-between">
                <div className="flex gap-6">
                  <div>
                    <p className="text-xs text-violet-200 mb-0.5">Active Agents</p>
                    <p className="text-lg font-bold">{overview?.agent_count || 0}</p>
                  </div>
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
                </div>
                <button
                  onClick={() => window.open('https://ascenai.com/pricing', '_blank')}
                  className="px-4 py-2 bg-white text-violet-600 rounded-xl text-sm font-bold hover:bg-violet-50 transition-colors shadow-sm"
                >
                  Change Plan
                </button>
              </div>
            </div>
          </div>

          {/* Plan Progress */}
          <div className="bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-800 p-6">
            <h2 className="text-base font-bold text-gray-900 dark:text-white mb-6 flex items-center gap-2">
              <Zap size={18} className="text-violet-500" />
              Resource Utilization
            </h2>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
              {[
                { 
                  label: 'Chat Equivalents', 
                  used: overview?.usage.chats || 0, 
                  limit: overview?.limits.chat_messages, 
                  pct: overview?.usage.messages_pct,
                  desc: 'Calculated as 10 regular messages per chat unit'
                },
                { 
                  label: 'Voice Minutes', 
                  used: overview?.usage.voice_minutes || 0, 
                  limit: overview?.limits.voice_minutes, 
                  pct: overview?.usage.voice_pct,
                  desc: 'Total duration of all AI-user voice calls'
                },
              ].map(({ label, used, limit, pct, desc }) => (
                <div key={label} className="space-y-3">
                  <div className="flex justify-between items-end">
                    <div>
                      <p className="text-sm font-bold text-gray-900 dark:text-white">{label}</p>
                      <p className="text-[10px] text-gray-500 mt-0.5">{desc}</p>
                    </div>
                    <div className="text-right">
                      <p className="text-sm font-mono font-bold text-gray-900 dark:text-white">
                        {fmtNum(Math.round(used))} <span className="text-gray-400 font-normal">/ {fmtLimit(limit)}</span>
                      </p>
                    </div>
                  </div>
                  <div className="h-2.5 bg-gray-100 dark:bg-gray-800 rounded-full overflow-hidden">
                    <div
                      className={`h-full transition-all duration-700 ease-out rounded-full ${
                        (pct || 0) > 100 ? 'bg-red-500 shadow-[0_0_8px_rgba(239,68,68,0.4)]' : 
                        (pct || 0) > 85 ? 'bg-amber-500' : 
                        'bg-violet-600'
                      }`}
                      style={{ width: `${Math.min(pct || 0, 100)}%` }}
                    />
                  </div>
                  <div className="flex justify-between text-[10px]">
                    <span className={ (pct || 0) > 100 ? 'text-red-500 font-bold' : 'text-gray-400' }>
                      { (pct || 0) > 100 ? 'Overage Applied' : `${Math.round(pct || 0)}% of limit used` }
                    </span>
                    {(pct || 0) > 85 && (
                      <span className="flex items-center gap-1 text-amber-600 dark:text-amber-400 font-medium">
                        <AlertCircle size={10} />
                        Approaching limit
                      </span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Right Column: Invoices & Stats */}
        <div className="space-y-6">
          <div className="bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-800 p-6 h-full flex flex-col">
            <h2 className="text-base font-bold text-gray-900 dark:text-white mb-4 flex items-center gap-2">
              <Download size={18} className="text-violet-500" />
              Recent Invoices
            </h2>
            {invoices.length === 0 ? (
              <div className="flex-1 flex flex-col items-center justify-center text-center p-8 border-2 border-dashed border-gray-100 dark:border-gray-800 rounded-xl">
                <AlertCircle size={32} className="text-gray-300 mb-2" />
                <p className="text-sm text-gray-500">No invoices found yet.</p>
              </div>
            ) : (
              <div className="space-y-3 flex-1 overflow-y-auto pr-1">
                {invoices.map((inv) => (
                  <div 
                    key={inv.id} 
                    className="group p-3 rounded-xl border border-gray-100 dark:border-gray-800 hover:border-violet-200 dark:hover:border-violet-900 hover:bg-violet-50/30 dark:hover:bg-violet-900/10 transition-all cursor-pointer"
                    onClick={() => window.open(inv.hosted_invoice_url, '_blank')}
                  >
                    <div className="flex justify-between items-start mb-1.5">
                      <p className="text-xs font-bold text-gray-900 dark:text-white">{formatDate(inv.created)}</p>
                      <span className={`text-[10px] px-1.5 py-0.5 rounded-full font-medium ${
                        inv.status === 'paid' ? 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400' : 'bg-amber-100 text-amber-700'
                      }`}>
                        {inv.status.toUpperCase()}
                      </span>
                    </div>
                    <div className="flex justify-between items-center">
                      <p className="text-lg font-black text-gray-900 dark:text-white">
                        ${(inv.amount_due / 100).toFixed(2)}
                      </p>
                      <a 
                        href={inv.invoice_pdf} 
                        target="_blank" 
                        rel="noreferrer"
                        className="text-gray-400 hover:text-violet-600 transition-colors"
                        onClick={(e) => e.stopPropagation()}
                      >
                        <Download size={14} />
                      </a>
                    </div>
                  </div>
                ))}
              </div>
            )}
            <button
               onClick={handleManageBilling}
               className="mt-6 w-full py-2.5 text-xs text-gray-500 dark:text-gray-400 hover:text-violet-600 font-medium border border-gray-100 dark:border-gray-800 rounded-xl hover:bg-gray-50 dark:hover:bg-gray-800 transition-all"
            >
              See all billing history
            </button>
          </div>
        </div>
      </div>

      {/* Usage breakdown cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-8">
        {[
          { icon: Sparkles, label: 'Sessions', value: fmtNum(overview?.usage.sessions || 0), desc: 'Total conversations', color: 'bg-blue-50 text-blue-600 dark:bg-blue-900/20' },
          { icon: MessageSquare, label: 'Chats', value: fmtNum(overview?.usage.chats || 0), desc: 'Inbound + Outbound', color: 'bg-violet-50 text-violet-600 dark:bg-violet-900/20' },
          { icon: Phone, label: 'Voice Minutes', value: `${(overview?.usage.voice_minutes || 0).toFixed(1)}m`, desc: 'AI-user calls', color: 'bg-orange-50 text-orange-600 dark:bg-orange-900/20' },
        ].map(({ icon: Icon, label, value, desc, color }) => (
          <div key={label} className="bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-800 p-5 group hover:shadow-md transition-shadow">
            <div className={`w-10 h-10 rounded-xl ${color} flex items-center justify-center mb-4 group-hover:scale-110 transition-transform`}>
              <Icon size={20} />
            </div>
            <p className="text-xs font-medium text-gray-500 uppercase tracking-wider mb-1">{label}</p>
            <p className="text-2xl font-black text-gray-900 dark:text-white leading-none">{value}</p>
            <p className="text-[10px] text-gray-400 mt-2">{desc}</p>
          </div>
        ))}
      </div>

      {/* Per-agent breakdown table */}
      <div className="bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-800 overflow-hidden shadow-sm">
        <div className="px-6 py-5 border-b border-gray-100 dark:border-gray-800 flex items-center justify-between">
          <h2 className="text-base font-bold text-gray-900 dark:text-white">Active Agent Usage</h2>
          <span className="text-xs text-gray-400 bg-gray-50 dark:bg-gray-800 px-2 py-1 rounded-lg">
            Billing for {overview?.billing_period.start} — {overview?.billing_period.end}
          </span>
        </div>
        
        {agents.length === 0 ? (
          <div className="py-20 flex flex-col items-center justify-center text-gray-400">
            <Bot size={48} strokeWidth={1} className="mb-3 opacity-20" />
            <p className="text-sm italic">No agents recorded usage in this window.</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse">
              <thead>
                <tr className="bg-gray-50/50 dark:bg-gray-800/30">
                  <th className="pl-6 py-4 text-[10px] font-black text-gray-400 uppercase tracking-widest">Agent Persona</th>
                  <th className="px-4 py-4 text-[10px] font-black text-gray-400 uppercase tracking-widest text-right">Messages</th>
                  <th className="px-4 py-4 text-[10px] font-black text-gray-400 uppercase tracking-widest text-right">Voice Minutes</th>
                  <th className="px-4 py-4 text-[10px] font-black text-gray-400 uppercase tracking-widest text-right">Base Cost</th>
                  <th className="px-4 py-4 text-[10px] font-black text-gray-400 uppercase tracking-widest text-right">Overage</th>
                  <th className="pr-6 py-4 text-[10px] font-black text-gray-400 uppercase tracking-widest text-right">Total Contribution</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
                {agents.map((a, i) => (
                  <tr key={a.agent_id ?? i} className="hover:bg-violet-50/20 dark:hover:bg-violet-900/5 transition-colors group">
                    <td className="pl-6 py-4">
                      <div className="flex items-center gap-3">
                        <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-gray-100 to-gray-200 dark:from-gray-800 dark:to-gray-700 flex items-center justify-center text-gray-400 group-hover:from-violet-500 group-hover:to-indigo-500 group-hover:text-white transition-all">
                          <Bot size={20} />
                        </div>
                        <div>
                          <p className="text-sm font-bold text-gray-900 dark:text-white">{a.agent_name}</p>
                          <p className="text-[10px] text-gray-400">ID: {a.agent_id?.slice(0,8)}...</p>
                        </div>
                      </div>
                    </td>
                    <td className="px-4 py-4 text-right text-sm font-mono text-gray-600 dark:text-gray-400">{fmtNum(a.messages)}</td>
                    <td className="px-4 py-4 text-right text-sm font-mono text-gray-600 dark:text-gray-400">{a.voice_minutes.toFixed(1)}</td>
                    <td className="px-4 py-4 text-right text-sm font-mono text-gray-600 dark:text-gray-400 font-medium">{fmt(a.base_cost)}</td>
                    <td className="px-4 py-4 text-right text-sm font-mono text-amber-600 dark:text-amber-400 font-medium">{a.overage > 0 ? fmt(a.overage) : '—'}</td>
                    <td className="pr-6 py-4 text-right">
                      <p className="text-sm font-black text-gray-900 dark:text-white">{fmt(a.total_cost)}</p>
                    </td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr className="bg-gray-50/50 dark:bg-gray-800/30">
                  <td colSpan={5} className="pl-6 py-5 text-right text-xs font-bold text-gray-500">Statement Total</td>
                  <td className="pr-6 py-5 text-right">
                    <span className="text-lg font-black text-violet-600 dark:text-violet-400">
                      {fmt(overview?.estimated_bill.total || 0)}
                    </span>
                  </td>
                </tr>
              </tfoot>
            </table>
          </div>
        )}
      </div>

      {/* Helpful alerts */}
      <div className="mt-8 grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="flex items-start gap-4 p-4 rounded-2xl bg-violet-50/50 dark:bg-violet-900/10 border border-violet-100 dark:border-violet-900/30">
          <Zap size={20} className="text-violet-600 flex-shrink-0 mt-0.5" />
          <div>
            <p className="text-sm font-bold text-gray-900 dark:text-white mb-1">Scaling smoothly</p>
            <p className="text-xs text-gray-600 dark:text-gray-400 leading-relaxed">
              We charge for overages automatically so your agents never stop responding. 
              If you expect significantly higher volume, upgrading to the Business plan saves up to 40% on unit costs.
            </p>
          </div>
        </div>
        <div className="flex items-start gap-4 p-4 rounded-2xl bg-emerald-50/50 dark:bg-emerald-900/10 border border-emerald-100 dark:border-emerald-900/30">
          <CheckCircle size={20} className="text-emerald-600 flex-shrink-0 mt-0.5" />
          <div>
            <p className="text-sm font-bold text-gray-900 dark:text-white mb-1">Billing cycle</p>
            <p className="text-xs text-gray-600 dark:text-gray-400 leading-relaxed">
              Your next invoice will be generated on {overview?.billing_period.end}. 
              Payment will be processed automatically using your primary card on file.
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}
