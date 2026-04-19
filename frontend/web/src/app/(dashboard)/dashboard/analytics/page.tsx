'use client'

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { analyticsApi, type AnalyticsOverview, type AgentAnalyticsSummary, type DailyAnalytics } from '@/lib/api'
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
  Clock,
  TrendingUp,
  Wrench,
  AlertTriangle,
  ThumbsUp,
  Mic,
  DollarSign,
} from 'lucide-react'

// ---------------------------------------------------------------------------
// StatCard
// ---------------------------------------------------------------------------
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
  icon: React.ElementType
  color?: string
}) {
  const colors: Record<string, string> = {
    violet: 'bg-violet-50 text-violet-600 dark:bg-violet-900/20 dark:text-violet-400',
    blue:   'bg-blue-50 text-blue-600 dark:bg-blue-900/20 dark:text-blue-400',
    green:  'bg-green-50 text-green-600 dark:bg-green-900/20 dark:text-green-400',
    amber:  'bg-amber-50 text-amber-600 dark:bg-amber-900/20 dark:text-amber-400',
    red:    'bg-red-50 text-red-600 dark:bg-red-900/20 dark:text-red-400',
    teal:   'bg-teal-50 text-teal-600 dark:bg-teal-900/20 dark:text-teal-400',
    orange: 'bg-orange-50 text-orange-600 dark:bg-orange-900/20 dark:text-orange-400',
  }
  return (
    <div className="bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-800 p-5">
      <div className="flex items-start justify-between mb-3">
        <p className="text-sm text-gray-500 dark:text-gray-400">{label}</p>
        <div className={`w-9 h-9 rounded-xl flex items-center justify-center ${colors[color] ?? colors.violet}`}>
          <Icon size={18} />
        </div>
      </div>
      <p className="text-2xl font-bold text-gray-900 dark:text-white">{value}</p>
      {sub && <p className="text-xs text-gray-400 mt-1">{sub}</p>}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Skeleton
// ---------------------------------------------------------------------------
function SkeletonCard() {
  return <div className="h-28 rounded-2xl bg-gray-100 dark:bg-gray-800 animate-pulse" />
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
const PERIOD_OPTIONS = [
  { label: '7d',  days: 7  },
  { label: '30d', days: 30 },
  { label: '90d', days: 90 },
]

function fmt(n: number, decimals = 0): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000)     return `${(n / 1_000).toFixed(1)}K`
  return n.toFixed(decimals)
}

/** Format USD — shows cents for values < $1 */
function fmtUsd(n: number): string {
  if (n === 0) return '$0.00'
  if (n < 0.01) return `$${n.toFixed(4)}`
  if (n >= 1_000) return `$${(n / 1_000).toFixed(1)}K`
  return `$${n.toFixed(2)}`
}

/** Format voice minutes — e.g. "12.3 min" or "1h 02m" */
function fmtMinutes(mins: number): string {
  if (mins < 1) return `${Math.round(mins * 60)}s`
  if (mins < 60) return `${mins.toFixed(1)} min`
  const h = Math.floor(mins / 60)
  const m = Math.round(mins % 60)
  return `${h}h ${String(m).padStart(2, '0')}m`
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------
export default function AnalyticsPage() {
  const [days, setDays] = useState(30)

  const { data, isLoading } = useQuery<AnalyticsOverview>({
    queryKey: ['analytics', days],
    queryFn:  () => analyticsApi.overview({ days }),
    staleTime: 60_000,
  })

  // --- Derived numbers --------------------------------------------------
  const totalChats       = data?.total_chats       ?? 0
  const totalSessions    = data?.total_sessions     ?? 0
  const totalVoiceMins   = data?.total_voice_minutes ?? 0   // NEW
  const totalCostUsd     = data?.total_cost_usd     ?? 0    // NEW
  const avgLatencyMs     = data?.avg_latency_ms     ?? 0
  const totalTools       = data?.total_tool_executions ?? 0
  const totalEscalations = data?.total_escalations  ?? 0
  const feedbackPct      = data?.feedback_positive_pct

  const avgTurnsPerChat =
    totalChats > 0 ? ((data?.total_messages ?? 0) / totalChats).toFixed(1) : '—'

  // Daily time-series
  const dailyData: (DailyAnalytics & { date: string })[] = (data?.daily ?? []).map((d) => ({
    ...d,
    date: d.date.slice(5), // "MM-DD"
  }))

  // Per-agent bar data (truncate long names)
  const agentData: (AgentAnalyticsSummary & { name: string; fullName: string })[] =
    (data?.by_agent ?? []).map((a) => ({
      ...a,
      name:     a.agent_name.length > 18 ? `${a.agent_name.slice(0, 18)}…` : a.agent_name,
      fullName: a.agent_name,
    }))

  // Dynamic bar chart height — at least 200px, 40px per agent
  const barChartHeight = Math.max(200, agentData.length * 44)

  return (
    <div className="p-8">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Analytics</h1>
          <p className="text-gray-500 dark:text-gray-400 mt-1">
            Usage and performance across all agents.
          </p>
        </div>

        {/* Period selector */}
        <div className="flex bg-gray-100 dark:bg-gray-800 rounded-xl p-1 gap-1">
          {PERIOD_OPTIONS.map((opt) => (
            <button
              key={opt.days}
              id={`period-${opt.label}`}
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

      {/* ── Skeleton / Content ─────────────────────────────────────────── */}
      {isLoading ? (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
          {Array.from({ length: 8 }).map((_, i) => <SkeletonCard key={i} />)}
        </div>
      ) : (
        <>
          {/* ── Stat cards ─────────────────────────────────────────────── */}
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
            <StatCard
              label="Total Sessions"
              value={fmt(totalSessions)}
              sub={`Last ${days} days`}
              icon={MessageSquare}
              color="violet"
            />
            <StatCard
              label="Total Chats"
              value={fmt(totalChats)}
              sub="1-10 turns = 1 chat, 11-20 = 2, …"
              icon={TrendingUp}
              color="blue"
            />
            <StatCard
              label="Avg Turns / Chat"
              value={avgTurnsPerChat}
              icon={TrendingUp}
              color="amber"
            />
            <StatCard
              label="Avg Latency"
              value={`${Math.round(avgLatencyMs)}ms`}
              icon={Clock}
              color="blue"
            />
            <StatCard
              label="Tool Executions"
              value={fmt(totalTools)}
              icon={Wrench}
              color="violet"
            />
            <StatCard
              label="Escalations"
              value={fmt(totalEscalations)}
              icon={AlertTriangle}
              color="red"
            />
            <StatCard
              label="Positive Feedback"
              value={feedbackPct != null ? `${feedbackPct}%` : '—'}
              icon={ThumbsUp}
              color="green"
            />
            {/* NEW: Voice Minutes */}
            <StatCard
              label="Voice Minutes"
              value={totalVoiceMins > 0 ? fmtMinutes(totalVoiceMins) : '—'}
              sub="Total voice session time"
              icon={Mic}
              color="teal"
            />
            {/* NEW: Estimated Cost */}
            <StatCard
              label="Est. Cost"
              value={fmtUsd(totalCostUsd)}
              sub="LLM token cost only"
              icon={DollarSign}
              color="orange"
            />
          </div>

          {/* ── Daily Sessions & Chats line chart ──────────────────────── */}
          {dailyData.length > 0 && (
            <div className="bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-800 p-6 mb-6">
              <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-4">
                Sessions &amp; Chats Over Time
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
                    dataKey="total_chats"
                    name="Chats"
                    stroke="#3b82f6"
                    strokeWidth={2}
                    dot={false}
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}

          {/* ── Latency trend chart ─────────────────────────────────────── */}
          {dailyData.length > 0 && (
            <div className="bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-800 p-6 mb-6">
              <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-4">
                Avg Response Latency Over Time (ms)
              </h2>
              <ResponsiveContainer width="100%" height={200}>
                <LineChart data={dailyData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                  <XAxis dataKey="date" tick={{ fontSize: 11 }} stroke="#9ca3af" />
                  <YAxis tick={{ fontSize: 11 }} stroke="#9ca3af" unit="ms" />
                  <Tooltip
                    contentStyle={{ fontSize: 12 }}
                    formatter={(v: any) => [`${Math.round(Number(v))}ms`, 'Latency']}
                  />
                  <Line
                    type="monotone"
                    dataKey="avg_latency_ms"
                    name="Latency"
                    stroke="#f59e0b"
                    strokeWidth={2}
                    dot={false}
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}

          {/* ── Per-agent charts row ──────────────────────────────────────── */}
          {agentData.length > 0 && (
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
              {/* Chats by Agent */}
              <div className="bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-800 p-6">
                <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-4">
                  Chats by Agent
                </h2>
                <ResponsiveContainer width="100%" height={barChartHeight}>
                  <BarChart data={agentData} layout="vertical">
                    <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                    <XAxis type="number" tick={{ fontSize: 11 }} stroke="#9ca3af" />
                    <YAxis
                      type="category"
                      dataKey="name"
                      width={130}
                      tick={{ fontSize: 11 }}
                      stroke="#9ca3af"
                    />
                    <Tooltip
                      contentStyle={{ fontSize: 12 }}
                      formatter={(v: any, _: any, props: any) => [
                        v,
                        props?.payload?.fullName ?? 'Chats',
                      ]}
                    />
                    <Bar dataKey="chats" name="Chats" fill="#3b82f6" radius={[0, 4, 4, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>

              {/* Avg Latency by Agent */}
              <div className="bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-800 p-6">
                <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-4">
                  Avg Latency by Agent (ms)
                </h2>
                <ResponsiveContainer width="100%" height={barChartHeight}>
                  <BarChart data={agentData} layout="vertical">
                    <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                    <XAxis type="number" tick={{ fontSize: 11 }} stroke="#9ca3af" unit="ms" />
                    <YAxis
                      type="category"
                      dataKey="name"
                      width={130}
                      tick={{ fontSize: 11 }}
                      stroke="#9ca3af"
                    />
                    <Tooltip
                      contentStyle={{ fontSize: 12 }}
                      formatter={(v: any) => [`${Math.round(Number(v))}ms`, 'Latency']}
                    />
                    <Bar dataKey="latency" name="Latency" fill="#f59e0b" radius={[0, 4, 4, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>
          )}

          {/* ── Per-agent breakdown table ────────────────────────────────── */}
          {agentData.length > 0 && (
            <div className="bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-800 overflow-hidden mb-6">
              <div className="px-6 py-4 border-b border-gray-100 dark:border-gray-800">
                <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-300">
                  Per-Agent Breakdown
                </h2>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="bg-gray-50 dark:bg-gray-800/50">
                    <tr>
                      {['Agent', 'Sessions', 'Chats', 'Avg Latency', 'Voice Min', 'Est. Cost', '👍 %'].map((h) => (
                        <th
                          key={h}
                          className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wider whitespace-nowrap"
                        >
                          {h}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-50 dark:divide-gray-800">
                    {(data?.by_agent ?? []).map((a: any) => (
                      <tr key={a.agent_id} className="hover:bg-gray-50 dark:hover:bg-gray-800/30">
                        <td className="px-4 py-3 font-medium text-gray-900 dark:text-white max-w-[180px] truncate" title={a.agent_name}>
                          {a.agent_name}
                        </td>
                        <td className="px-4 py-3 text-gray-600 dark:text-gray-400">{a.total_sessions}</td>
                        <td className="px-4 py-3 text-gray-600 dark:text-gray-400">{fmt(a.total_chats)}</td>
                        <td className="px-4 py-3 text-gray-600 dark:text-gray-400">{Math.round(a.avg_latency_ms)}ms</td>
                        {/* NEW: Voice minutes column */}
                        <td className="px-4 py-3 text-gray-600 dark:text-gray-400">
                          {a.total_voice_minutes > 0 ? fmtMinutes(a.total_voice_minutes) : <span className="text-gray-400">—</span>}
                        </td>
                        {/* NEW: Cost column */}
                        <td className="px-4 py-3 text-gray-600 dark:text-gray-400">
                          {fmtUsd(a.estimated_cost_usd ?? 0)}
                        </td>
                        <td className="px-4 py-3">
                          {a.positive_feedback_pct != null ? (
                            <span
                              className={`font-medium ${
                                a.positive_feedback_pct >= 70
                                  ? 'text-green-600'
                                  : a.positive_feedback_pct >= 40
                                  ? 'text-amber-500'
                                  : 'text-red-500'
                              }`}
                            >
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
            </div>
          )}

          {/* ── Empty state ────────────────────────────────────────────────── */}
          {!totalSessions && !isLoading && (
            <div className="text-center py-16 bg-white dark:bg-gray-900 rounded-xl border border-dashed border-gray-200 dark:border-gray-700">
              <TrendingUp size={40} className="mx-auto text-gray-300 dark:text-gray-600 mb-3" />
              <p className="font-medium text-gray-700 dark:text-gray-300 mb-1">No conversations yet</p>
              <p className="text-sm text-gray-500 dark:text-gray-400 mb-4">
                Start by testing your agent — data will appear here after the first session.
              </p>
              <a
                href="/dashboard/agents"
                className="inline-flex items-center gap-2 px-4 py-2 bg-violet-600 text-white text-sm font-medium rounded-xl hover:bg-violet-700 transition-colors"
              >
                Go to Agents
              </a>
            </div>
          )}
        </>
      )}
    </div>
  )
}
