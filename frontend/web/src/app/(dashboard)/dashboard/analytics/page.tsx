'use client'

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { analyticsApi } from '@/lib/api'
import {
  LineChart,
  Line,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from 'recharts'
import {
  MessageSquare,
  Zap,
  DollarSign,
  Clock,
  TrendingUp,
  Wrench,
  AlertTriangle,
  ThumbsUp,
} from 'lucide-react'

function StatCard({
  label,
  value,
  sub,
  icon: Icon,
  color = 'violet',
}: {
  label: string
  value: string | number
  sub?: string
  icon: any
  color?: string
}) {
  const colors: Record<string, string> = {
    violet: 'bg-violet-50 text-violet-600 dark:bg-violet-900/20 dark:text-violet-400',
    blue: 'bg-blue-50 text-blue-600 dark:bg-blue-900/20 dark:text-blue-400',
    green: 'bg-green-50 text-green-600 dark:bg-green-900/20 dark:text-green-400',
    amber: 'bg-amber-50 text-amber-600 dark:bg-amber-900/20 dark:text-amber-400',
    red: 'bg-red-50 text-red-600 dark:bg-red-900/20 dark:text-red-400',
  }
  return (
    <div className="bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-800 p-5">
      <div className="flex items-start justify-between mb-3">
        <p className="text-sm text-gray-500 dark:text-gray-400">{label}</p>
        <div className={`w-9 h-9 rounded-xl flex items-center justify-center ${colors[color]}`}>
          <Icon size={18} />
        </div>
      </div>
      <p className="text-2xl font-bold text-gray-900 dark:text-white">{value}</p>
      {sub && <p className="text-xs text-gray-400 mt-1">{sub}</p>}
    </div>
  )
}

const PERIOD_OPTIONS = [
  { label: '7d', days: 7 },
  { label: '30d', days: 30 },
  { label: '90d', days: 90 },
]

export default function AnalyticsPage() {
  const [days, setDays] = useState(30)

  const { data, isLoading } = useQuery({
    queryKey: ['analytics', days],
    queryFn: () => analyticsApi.overview({ days }),
    staleTime: 60_000,
  })

  function fmt(n: number, decimals = 0) {
    if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
    if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`
    return n.toFixed(decimals)
  }

  const dailyData = (data?.daily ?? []).map((d: any) => ({
    ...d,
    date: d.date.slice(5),          // "MM-DD"
    cost: +d.estimated_cost_usd.toFixed(4),
  }))

  const agentData = (data?.by_agent ?? []).map((a: any) => ({
    name: a.agent_name.length > 14 ? a.agent_name.slice(0, 14) + '…' : a.agent_name,
    messages: a.total_messages,
    cost: +a.estimated_cost_usd.toFixed(4),
    latency: a.avg_latency_ms,
    feedback: a.positive_feedback_pct ?? 0,
  }))

  return (
    <div className="p-8">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Analytics</h1>
          <p className="text-gray-500 dark:text-gray-400 mt-1">
            Usage, cost, and performance across all agents.
          </p>
        </div>
        {/* Period selector */}
        <div className="flex bg-gray-100 dark:bg-gray-800 rounded-xl p-1 gap-1">
          {PERIOD_OPTIONS.map((opt) => (
            <button
              key={opt.days}
              onClick={() => setDays(opt.days)}
              className={`px-4 py-1.5 rounded-lg text-sm font-medium transition-colors ${
                days === opt.days
                  ? 'bg-white dark:bg-gray-700 text-gray-900 dark:text-white shadow-sm'
                  : 'text-gray-500 hover:text-gray-700 dark:hover:text-gray-300'
              }`}
            >
              {opt.label}
            </button>
          ))}
        </div>
      </div>

      {isLoading ? (
        <div className="grid grid-cols-4 gap-4 mb-8">
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="h-28 rounded-2xl bg-gray-100 dark:bg-gray-800 animate-pulse" />
          ))}
        </div>
      ) : (
        <>
          {/* Stat cards */}
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
            <StatCard
              label="Total Sessions"
              value={fmt(data?.total_sessions ?? 0)}
              sub={`Last ${days} days`}
              icon={MessageSquare}
              color="violet"
            />
            <StatCard
              label="Total Messages"
              value={fmt(data?.total_messages ?? 0)}
              icon={TrendingUp}
              color="blue"
            />
            <StatCard
              label="Tokens Used"
              value={fmt(data?.total_tokens ?? 0)}
              icon={Zap}
              color="amber"
            />
            <StatCard
              label="Est. Cost"
              value={`$${(data?.total_cost_usd ?? 0).toFixed(4)}`}
              icon={DollarSign}
              color="green"
            />
            <StatCard
              label="Avg Latency"
              value={`${Math.round(data?.avg_latency_ms ?? 0)}ms`}
              icon={Clock}
              color="blue"
            />
            <StatCard
              label="Tool Executions"
              value={fmt(data?.total_tool_executions ?? 0)}
              icon={Wrench}
              color="violet"
            />
            <StatCard
              label="Escalations"
              value={fmt(data?.total_escalations ?? 0)}
              icon={AlertTriangle}
              color="red"
            />
            <StatCard
              label="Positive Feedback"
              value={data?.feedback_positive_pct != null ? `${data.feedback_positive_pct}%` : '—'}
              icon={ThumbsUp}
              color="green"
            />
          </div>

          {/* Daily sessions + messages line chart */}
          {dailyData.length > 0 && (
            <div className="bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-800 p-6 mb-6">
              <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-4">
                Sessions & Messages Over Time
              </h2>
              <ResponsiveContainer width="100%" height={240}>
                <LineChart data={dailyData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                  <XAxis dataKey="date" tick={{ fontSize: 11 }} stroke="#9ca3af" />
                  <YAxis tick={{ fontSize: 11 }} stroke="#9ca3af" />
                  <Tooltip contentStyle={{ fontSize: 12 }} />
                  <Legend wrapperStyle={{ fontSize: 12 }} />
                  <Line
                    type="monotone"
                    dataKey="total_sessions"
                    name="Sessions"
                    stroke="#7c3aed"
                    strokeWidth={2}
                    dot={false}
                  />
                  <Line
                    type="monotone"
                    dataKey="total_messages"
                    name="Messages"
                    stroke="#3b82f6"
                    strokeWidth={2}
                    dot={false}
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
            {/* Daily cost */}
            {dailyData.length > 0 && (
              <div className="bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-800 p-6">
                <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-4">
                  Daily Cost (USD)
                </h2>
                <ResponsiveContainer width="100%" height={200}>
                  <BarChart data={dailyData}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                    <XAxis dataKey="date" tick={{ fontSize: 11 }} stroke="#9ca3af" />
                    <YAxis tick={{ fontSize: 11 }} stroke="#9ca3af" />
                    <Tooltip contentStyle={{ fontSize: 12 }} formatter={(v: any) => `$${v}`} />
                    <Bar dataKey="cost" name="Cost $" fill="#7c3aed" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}

            {/* Per-agent messages */}
            {agentData.length > 0 && (
              <div className="bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-800 p-6">
                <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-4">
                  Messages by Agent
                </h2>
                <ResponsiveContainer width="100%" height={200}>
                  <BarChart data={agentData} layout="vertical">
                    <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                    <XAxis type="number" tick={{ fontSize: 11 }} stroke="#9ca3af" />
                    <YAxis type="category" dataKey="name" width={100} tick={{ fontSize: 11 }} stroke="#9ca3af" />
                    <Tooltip contentStyle={{ fontSize: 12 }} />
                    <Bar dataKey="messages" name="Messages" fill="#3b82f6" radius={[0, 4, 4, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}
          </div>

          {/* Agent breakdown table */}
          {agentData.length > 0 && (
            <div className="bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-800 overflow-hidden">
              <div className="px-6 py-4 border-b border-gray-100 dark:border-gray-800">
                <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-300">
                  Per-Agent Breakdown
                </h2>
              </div>
              <table className="w-full text-sm">
                <thead className="bg-gray-50 dark:bg-gray-800/50">
                  <tr>
                    {['Agent', 'Sessions', 'Messages', 'Tokens', 'Cost', 'Avg Latency', '👍 %'].map((h) => (
                      <th key={h} className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wider">
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-50 dark:divide-gray-800">
                  {data?.by_agent.map((a: any) => (
                    <tr key={a.agent_id} className="hover:bg-gray-50 dark:hover:bg-gray-800/30">
                      <td className="px-4 py-3 font-medium text-gray-900 dark:text-white">{a.agent_name}</td>
                      <td className="px-4 py-3 text-gray-600 dark:text-gray-400">{a.total_sessions}</td>
                      <td className="px-4 py-3 text-gray-600 dark:text-gray-400">{fmt(a.total_messages)}</td>
                      <td className="px-4 py-3 text-gray-600 dark:text-gray-400">{fmt(a.total_tokens)}</td>
                      <td className="px-4 py-3 text-gray-600 dark:text-gray-400">${a.estimated_cost_usd.toFixed(4)}</td>
                      <td className="px-4 py-3 text-gray-600 dark:text-gray-400">{Math.round(a.avg_latency_ms)}ms</td>
                      <td className="px-4 py-3">
                        {a.positive_feedback_pct != null ? (
                          <span className={`font-medium ${a.positive_feedback_pct >= 70 ? 'text-green-600' : a.positive_feedback_pct >= 40 ? 'text-amber-500' : 'text-red-500'}`}>
                            {a.positive_feedback_pct}%
                          </span>
                        ) : (
                          <span className="text-gray-400">—</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {!data?.total_sessions && !isLoading && (
            <div className="text-center py-16 bg-white dark:bg-gray-900 rounded-xl border border-dashed border-gray-200 dark:border-gray-700">
              <TrendingUp size={40} className="mx-auto text-gray-300 dark:text-gray-600 mb-3" />
              <p className="text-gray-500">No analytics data yet for this period.</p>
            </div>
          )}
        </>
      )}
    </div>
  )
}
