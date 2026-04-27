'use client'

import { useEffect, useState } from 'react'
import { billingApi } from '@/lib/api'
import {
  Zap,
  MessageSquare,
  Bot,
  Mic,
  CheckCircle,
  AlertCircle,
  Clock,
  ChevronLeft,
  ChevronRight,
  Sparkles,
  Phone,
  ArrowLeft
} from 'lucide-react'
import Link from 'next/link'

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

export default function AnalyticsPage() {
  const [overview, setOverview] = useState<BillingOverview | null>(null)
  const [agents, setAgents] = useState<AgentBilling[]>([])
  const [selectedAgentId, setSelectedAgentId] = useState<string>('total')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    Promise.all([
      billingApi.overview(),
      billingApi.agents(),
    ])
      .then(([ov, ag]) => {
        setOverview(ov)
        setAgents(ag)
        if (ag.length > 0) {
          setSelectedAgentId('total')
        }
      })
      .finally(() => setLoading(false))
  }, [])

  if (loading) {
    return (
      <div className="p-8 flex items-center justify-center min-h-[400px]">
        <div className="flex flex-col items-center gap-3">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-violet-600" />
          <p className="text-sm text-gray-500">Loading analytics...</p>
        </div>
      </div>
    )
  }

  const fmt = (n: number) => `$${n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
  const fmtNum = (n: number) => n.toLocaleString()
  const fmtLimit = (n: number | null) => n == null ? 'Unlimited' : fmtNum(n)

  const hasSelectedPlan = !!(overview?.plan && overview.plan !== 'none')

  return (
    <div className="p-8 w-full max-w-6xl mx-auto">
      <Link href="/tenant-admin/billing" className="flex items-center gap-1.5 text-sm text-gray-500 hover:text-violet-600 dark:hover:text-violet-400 mb-6 transition-colors">
        <ArrowLeft size={14} /> Back to Billing
      </Link>

      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white flex items-center gap-2">
            <Zap size={24} className="text-violet-500" />
            Agent Analytics & Usage
          </h1>
          <p className="text-gray-500 mt-1">
            Track resource consumption and performance per agent
          </p>
        </div>
      </div>

      {hasSelectedPlan && (
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
      )}

      {hasSelectedPlan && (
        <div className="bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-800 p-6 mb-8">
          <div className="flex items-center justify-between mb-6">
            <h2 className="text-base font-bold text-gray-900 dark:text-white flex items-center gap-2">
              <Zap size={18} className="text-violet-500" />
              Resource Utilization
            </h2>
            
            <div className="flex items-center gap-2">
              <button
                onClick={() => {
                  const allOptions = ['total', ...agents.map(a => a.agent_id || '')]
                  const idx = allOptions.indexOf(selectedAgentId)
                  const prev = idx > 0 ? allOptions[idx - 1] : allOptions[allOptions.length - 1]
                  setSelectedAgentId(prev)
                }}
                className="p-1.5 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 text-gray-400 hover:text-violet-600 transition-colors"
              >
                <ChevronLeft size={16} />
              </button>
              <div className="flex items-center gap-2 bg-gray-50 dark:bg-gray-800 p-1 rounded-xl border border-gray-100 dark:border-gray-700 overflow-hidden">
                <span className="px-3 py-1 text-[10px] font-black text-violet-600 dark:text-violet-400 uppercase tracking-widest whitespace-nowrap">
                  {selectedAgentId === 'total' ? 'All Agents' : agents.find(a => a.agent_id === selectedAgentId)?.agent_name || 'Select Agent'}
                </span>
              </div>
              <button
                onClick={() => {
                  const allOptions = ['total', ...agents.map(a => a.agent_id || '')]
                  const idx = allOptions.indexOf(selectedAgentId)
                  const next = idx < allOptions.length - 1 ? allOptions[idx + 1] : allOptions[0]
                  setSelectedAgentId(next)
                }}
                className="p-1.5 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 text-gray-400 hover:text-violet-600 transition-colors"
              >
                <ChevronRight size={16} />
              </button>
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
            {[
              { 
                label: 'Chat Equivalents', 
                used: overview?.usage.chats || 0, 
                limit: overview?.limits.chat_messages, 
                pct: overview?.usage.messages_pct,
                desc: '1 Unit = 10 messages. Voice minutes convert at 1:100.'
              },
              { 
                label: 'Voice Minutes', 
                used: overview?.usage.voice_minutes || 0, 
                limit: overview?.limits.voice_minutes, 
                pct: overview?.usage.voice_pct,
                desc: 'Usage pooled with chat units (1 min = 100 units)'
              },
            ].map(({ label, used, limit, pct, desc }) => {
              let displayUsed = used
              let displayPct = pct

              if (selectedAgentId !== 'total') {
                const agent = agents.find(a => a.agent_id === selectedAgentId)
                if (agent) {
                  if (label === 'Chat Equivalents') {
                    displayUsed = (agent as any).chats ?? (agent.messages / 10)
                    displayPct = limit ? (displayUsed / limit) * 100 : 0
                  } else {
                    displayUsed = agent.voice_minutes
                    displayPct = limit ? (displayUsed / limit) * 100 : 0
                  }
                }
              }

              return (
                <div key={label} className="space-y-3">
                  <div className="flex justify-between items-end">
                    <div>
                      <p className="text-sm font-bold text-gray-900 dark:text-white">{label}</p>
                      <p className="text-[10px] text-gray-500 mt-0.5">{desc}</p>
                    </div>
                    <div className="text-right">
                      <p className="text-sm font-mono font-bold text-gray-900 dark:text-white">
                        {fmtNum(Math.round(displayUsed))} <span className="text-gray-400 font-normal">/ {fmtLimit(limit)}</span>
                      </p>
                    </div>
                  </div>
                  <div className="h-2.5 bg-gray-100 dark:bg-gray-800 rounded-full overflow-hidden">
                    <div
                      className={`h-full transition-all duration-700 ease-out rounded-full ${
                        (displayPct || 0) > 100 ? 'bg-red-500 shadow-[0_0_8px_rgba(239,68,68,0.4)]' : 
                        (displayPct || 0) > 85 ? 'bg-amber-500' : 
                        'bg-violet-600'
                      }`}
                      style={{ width: `${Math.min(displayPct || 0, 100)}%` }}
                    />
                  </div>
                  <div className="flex justify-between text-[10px]">
                    <span className={ (displayPct || 0) > 100 ? 'text-red-500 font-bold' : 'text-gray-400' }>
                      { (displayPct || 0) > 100 ? 'Overage Applied' : `${Math.round(displayPct || 0)}% of limit used` }
                    </span>
                    {(displayPct || 0) > 85 && (
                      <span className="flex items-center gap-1 text-amber-600 dark:text-amber-400 font-medium">
                        <AlertCircle size={10} />
                        Approaching limit
                      </span>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* Per-agent breakdown table */}
      {hasSelectedPlan && (
        <div className="bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-800 overflow-hidden shadow-sm">
          <div className="px-6 py-5 border-b border-gray-100 dark:border-gray-800 flex items-center justify-between">
            <h2 className="text-base font-bold text-gray-900 dark:text-white">Active Agent Usage Details</h2>
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
                            <p className="text-[10px] text-gray-400">
                              {a.agent_id ? `ID: ${a.agent_id.slice(0, 8)}…` : 'Available slot'}
                            </p>
                          </div>
                        </div>
                      </td>
                      <td className="px-4 py-4 text-right text-sm font-mono text-gray-600 dark:text-gray-400">{fmtNum(a.messages ?? 0)}</td>
                      <td className="px-4 py-4 text-right text-sm font-mono text-gray-600 dark:text-gray-400">{(a.voice_minutes ?? 0).toFixed(1)}</td>
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
      )}
    </div>
  )
}
