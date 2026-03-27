'use client'

import { useEffect, useState } from 'react'
import { billingApi } from '@/lib/api'
import { CreditCard, Zap, MessageSquare, Bot, Mic } from 'lucide-react'

interface BillingOverview {
  plan: string
  plan_display_name: string
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

export default function BillingPage() {
  const [overview, setOverview] = useState<BillingOverview | null>(null)
  const [agents, setAgents] = useState<AgentBilling[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    Promise.all([billingApi.overview(), billingApi.agents()])
      .then(([ov, ag]) => { setOverview(ov); setAgents(ag) })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  if (loading) {
    return (
      <div className="p-8 flex items-center justify-center">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-violet-600" />
      </div>
    )
  }

  const fmt = (n: number) => `$${n.toFixed(2)}`
  const fmtNum = (n: number) => n.toLocaleString()
  const fmtLimit = (n: number | null) => n == null ? 'Unlimited' : fmtNum(n)

  return (
    <div className="p-8 max-w-4xl mx-auto">
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-gray-900 dark:text-white flex items-center gap-2">
          <CreditCard size={24} className="text-violet-500" />
          Billing
        </h1>
        <p className="text-gray-500 mt-1">
          {overview?.plan_display_name || 'Plan'} · {fmt(overview?.price_per_agent || 0)} per active agent/month
        </p>
      </div>

      {/* Plan summary */}
      <div className="bg-gradient-to-br from-violet-600 to-blue-600 rounded-xl p-6 text-white mb-6">
        <div className="flex items-start justify-between">
          <div>
            <p className="text-violet-200 text-sm font-medium mb-1">
              {overview?.plan_display_name || 'Plan'}
            </p>
            <p className="text-3xl font-bold">{fmt(overview?.estimated_bill.total || 0)}</p>
            <p className="text-violet-200 text-sm mt-1">
              {overview?.agent_count || 0} agent{(overview?.agent_count || 0) !== 1 ? 's' : ''} × {fmt(overview?.price_per_agent || 0)}/month
              {(overview?.estimated_bill.overage || 0) > 0 && (
                <span> + {fmt(overview?.estimated_bill.overage || 0)} overage</span>
              )}
            </p>
          </div>
          <div className="text-right">
            <p className="text-violet-200 text-xs">Billing period</p>
            <p className="text-sm font-medium mt-0.5">
              {overview?.billing_period.start} — {overview?.billing_period.end}
            </p>
          </div>
        </div>
        <div className="mt-4 pt-4 border-t border-violet-500/40">
          <p className="text-violet-100 text-xs">
            Contact{' '}
            <a href="mailto:billing@ascenai.com" className="underline">billing@ascenai.com</a>{' '}
            to manage your subscription or upgrade your plan.
          </p>
        </div>
      </div>

      {/* Plan limits */}
      {overview?.limits && (
        <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 p-5 mb-6">
          <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-4">Plan limits</h2>
          <div className="grid grid-cols-3 gap-4">
            {[
              { label: 'Chat messages', used: overview.usage.messages, limit: overview.limits.chat_messages, pct: overview.usage.messages_pct },
              { label: 'Voice minutes', used: overview.usage.voice_minutes, limit: overview.limits.voice_minutes, pct: overview.usage.voice_pct },
              { label: 'Team seats', used: null, limit: overview.limits.team_seats, pct: null },
            ].map(({ label, used, limit, pct }) => (
              <div key={label}>
                <div className="flex justify-between text-xs text-gray-500 mb-1">
                  <span>{label}</span>
                  <span>{used != null ? `${fmtNum(Math.round(used))} / ` : ''}{fmtLimit(limit)}</span>
                </div>
                {pct != null && (
                  <div className="h-1.5 bg-gray-100 dark:bg-gray-800 rounded-full overflow-hidden">
                    <div
                      className={`h-full rounded-full transition-all ${pct > 90 ? 'bg-red-500' : pct > 70 ? 'bg-amber-500' : 'bg-violet-500'}`}
                      style={{ width: `${Math.min(pct, 100)}%` }}
                    />
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Usage cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
        {[
          { icon: MessageSquare, label: 'Sessions', value: fmtNum(overview?.usage.sessions || 0), color: 'text-blue-500' },
          { icon: Zap, label: 'Messages', value: fmtNum(overview?.usage.messages || 0), color: 'text-violet-500' },
          { icon: Bot, label: 'Tokens Used', value: fmtNum(overview?.usage.tokens || 0), color: 'text-green-500' },
          { icon: Mic, label: 'Voice Minutes', value: `${(overview?.usage.voice_minutes || 0).toFixed(1)}m`, color: 'text-orange-500' },
        ].map(({ icon: Icon, label, value, color }) => (
          <div key={label} className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 p-4">
            <Icon size={18} className={`${color} mb-2`} />
            <p className="text-2xl font-bold text-gray-900 dark:text-white">{value}</p>
            <p className="text-xs text-gray-500 mt-0.5">{label} · {overview?.billing_period.start} – {overview?.billing_period.end}</p>
          </div>
        ))}
      </div>

      {/* Per-agent breakdown */}
      <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800">
        <div className="px-6 py-4 border-b border-gray-100 dark:border-gray-800">
          <h2 className="text-sm font-semibold text-gray-900 dark:text-white">Per-Agent Breakdown</h2>
        </div>
        {agents.length === 0 ? (
          <div className="p-8 text-center text-gray-500 text-sm">No active agents this billing period.</div>
        ) : (
          <table className="w-full">
            <thead>
              <tr className="border-b border-gray-50 dark:border-gray-800">
                <th className="text-left px-6 py-3 text-xs font-medium text-gray-500 uppercase">Agent</th>
                <th className="text-right px-6 py-3 text-xs font-medium text-gray-500 uppercase">Messages</th>
                <th className="text-right px-6 py-3 text-xs font-medium text-gray-500 uppercase">Voice min</th>
                <th className="text-right px-6 py-3 text-xs font-medium text-gray-500 uppercase">Base</th>
                <th className="text-right px-6 py-3 text-xs font-medium text-gray-500 uppercase">Overage</th>
                <th className="text-right px-6 py-3 text-xs font-medium text-gray-500 uppercase">Total</th>
              </tr>
            </thead>
            <tbody>
              {agents.map((a, i) => (
                <tr key={a.agent_id ?? i} className="border-b border-gray-50 dark:border-gray-800 last:border-0 hover:bg-gray-50 dark:hover:bg-gray-800/30">
                  <td className="px-6 py-4">
                    <div className="flex items-center gap-2">
                      <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-violet-500 to-blue-500 flex items-center justify-center text-white text-xs font-bold">
                        {a.agent_name.charAt(0)}
                      </div>
                      <span className="text-sm font-medium text-gray-900 dark:text-white">{a.agent_name}</span>
                    </div>
                  </td>
                  <td className="px-6 py-4 text-right text-sm text-gray-600 dark:text-gray-400">{fmtNum(a.messages)}</td>
                  <td className="px-6 py-4 text-right text-sm text-gray-600 dark:text-gray-400">{a.voice_minutes.toFixed(1)}</td>
                  <td className="px-6 py-4 text-right text-sm text-gray-600 dark:text-gray-400">{fmt(a.base_cost)}</td>
                  <td className="px-6 py-4 text-right text-sm text-gray-600 dark:text-gray-400">{fmt(a.overage)}</td>
                  <td className="px-6 py-4 text-right">
                    <span className="text-sm font-semibold text-gray-900 dark:text-white">{fmt(a.total_cost)}</span>
                  </td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr className="bg-gray-50 dark:bg-gray-800/50">
                <td colSpan={5} className="px-6 py-3 text-sm font-semibold text-gray-700 dark:text-gray-300 text-right">Total</td>
                <td className="px-6 py-3 text-right">
                  <span className="text-sm font-bold text-violet-600 dark:text-violet-400">
                    {fmt(overview?.estimated_bill.total || 0)}
                  </span>
                </td>
              </tr>
            </tfoot>
          </table>
        )}
      </div>
    </div>
  )
}
