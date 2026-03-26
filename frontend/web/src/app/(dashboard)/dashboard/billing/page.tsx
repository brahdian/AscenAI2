'use client'

import { useEffect, useState } from 'react'
import { billingApi } from '@/lib/api'
import { CreditCard, Zap, MessageSquare, Bot, Mic } from 'lucide-react'

interface BillingOverview {
  plan: string
  agent_count: number
  monthly_agent_cost: number
  usage: {
    sessions: number
    messages: number
    tokens: number
    voice_minutes: number
  }
  estimated_bill: {
    agents: number
    overage: number
    total: number
  }
  billing_period: {
    start: string
    end: string
  }
}

interface AgentBilling {
  agent_id: string
  agent_name: string
  sessions: number
  messages: number
  tokens: number
  monthly_cost: number
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

  return (
    <div className="p-8 max-w-4xl mx-auto">
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-gray-900 dark:text-white flex items-center gap-2">
          <CreditCard size={24} className="text-violet-500" />
          Billing
        </h1>
        <p className="text-gray-500 mt-1">$100 per active agent per month.</p>
      </div>

      {/* Plan summary */}
      <div className="bg-gradient-to-br from-violet-600 to-blue-600 rounded-xl p-6 text-white mb-6">
        <div className="flex items-start justify-between">
          <div>
            <p className="text-violet-200 text-sm font-medium mb-1">Professional Plan</p>
            <p className="text-3xl font-bold">{fmt(overview?.estimated_bill.total || 0)}</p>
            <p className="text-violet-200 text-sm mt-1">
              {overview?.agent_count || 0} active agent{(overview?.agent_count || 0) !== 1 ? 's' : ''} × $100/month
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
            Agents are billed from the date they are created. Contact{' '}
            <a href="mailto:billing@ascenai.com" className="underline">billing@ascenai.com</a> to manage your subscription.
          </p>
        </div>
      </div>

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
            <p className="text-xs text-gray-500 mt-0.5">{label} this month</p>
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
                <th className="text-right px-6 py-3 text-xs font-medium text-gray-500 uppercase">Sessions</th>
                <th className="text-right px-6 py-3 text-xs font-medium text-gray-500 uppercase">Messages</th>
                <th className="text-right px-6 py-3 text-xs font-medium text-gray-500 uppercase">Tokens</th>
                <th className="text-right px-6 py-3 text-xs font-medium text-gray-500 uppercase">Cost</th>
              </tr>
            </thead>
            <tbody>
              {agents.map((a) => (
                <tr key={a.agent_id} className="border-b border-gray-50 dark:border-gray-800 last:border-0 hover:bg-gray-50 dark:hover:bg-gray-800/30">
                  <td className="px-6 py-4">
                    <div className="flex items-center gap-2">
                      <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-violet-500 to-blue-500 flex items-center justify-center text-white text-xs font-bold">
                        {a.agent_name.charAt(0)}
                      </div>
                      <span className="text-sm font-medium text-gray-900 dark:text-white">{a.agent_name}</span>
                    </div>
                  </td>
                  <td className="px-6 py-4 text-right text-sm text-gray-600 dark:text-gray-400">{fmtNum(a.sessions)}</td>
                  <td className="px-6 py-4 text-right text-sm text-gray-600 dark:text-gray-400">{fmtNum(a.messages)}</td>
                  <td className="px-6 py-4 text-right text-sm text-gray-600 dark:text-gray-400">{fmtNum(a.tokens)}</td>
                  <td className="px-6 py-4 text-right">
                    <span className="text-sm font-semibold text-gray-900 dark:text-white">{fmt(a.monthly_cost)}</span>
                  </td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr className="bg-gray-50 dark:bg-gray-800/50">
                <td colSpan={4} className="px-6 py-3 text-sm font-semibold text-gray-700 dark:text-gray-300 text-right">Total</td>
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
