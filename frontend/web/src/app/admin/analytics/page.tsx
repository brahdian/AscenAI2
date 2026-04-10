'use client'

import { useEffect, useState } from 'react'
import { adminApi, api } from '@/lib/api'
import {
  BarChart3, MessageSquare, Bot, Building2, AlertCircle, DollarSign, Mic, Mic2,
} from 'lucide-react'
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  PieChart, Pie, Cell, Legend,
} from 'recharts'

const PLAN_PRICES: Record<string, number> = {
  professional: 99,
  business: 299,
  enterprise: 499,
  starter: 0,
  trial: 0,
}

const PLAN_COLORS: Record<string, string> = {
  Starter: '#94a3b8',
  Professional: '#7c3aed',
  Business: '#2563eb',
  Enterprise: '#059669',
  Trial: '#f59e0b',
}

interface TenantUsage {
  tenant_id: string
  tenant_name: string
  current_month_messages: number
  current_month_chat_units: number
  current_month_sessions: number
  current_month_stt_tokens: number
  current_month_tts_tokens: number
  current_month_cost_usd: number
}

interface Metrics {
  active_tenants: number
  total_agents: number
  sessions_today: number
  messages_today: number
}

interface Tenant {
  id: string
  plan: string
  status: string
  business_name: string
  name: string
  created_at: string
}

const TABS = ['Usage', 'Revenue', 'Tenants'] as const
type Tab = typeof TABS[number]

function StatCard({
  icon: Icon,
  label,
  value,
  sub,
  color,
}: {
  icon: React.ElementType
  label: string
  value: string | number
  sub?: string
  color: string
}) {
  return (
    <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 p-5">
      <div className="flex items-start justify-between mb-3">
        <span className="text-sm font-medium text-gray-500 dark:text-gray-400">{label}</span>
        <div className={`w-9 h-9 rounded-lg ${color} flex items-center justify-center`}>
          <Icon size={18} className="text-white" />
        </div>
      </div>
      <p className="text-2xl font-bold text-gray-900 dark:text-white">{value}</p>
      {sub && <p className="text-xs text-gray-400 mt-1">{sub}</p>}
    </div>
  )
}

export default function AnalyticsPage() {
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [metrics, setMetrics] = useState<Metrics | null>(null)
  const [tenantUsage, setTenantUsage] = useState<TenantUsage[]>([])
  const [allTenants, setAllTenants] = useState<Tenant[]>([])
  const [activeTab, setActiveTab] = useState<Tab>('Usage')
  const [sortBy, setSortBy] = useState<'messages' | 'sessions' | 'cost'>('messages')

  useEffect(() => {
    async function fetchData() {
      try {
        const [metricsData, usageData, tenantsData] = await Promise.all([
          adminApi.getMetrics(),
          api.get('/admin/tenants/usage').catch(() => ({ data: { tenants: [] } })),
          adminApi.listTenants({ per_page: 200 }),
        ])
        setMetrics(metricsData)
        setTenantUsage(usageData.data?.tenants || [])
        setAllTenants(tenantsData.tenants || [])
      } catch (err) {
        setError('Failed to load analytics data')
        console.error(err)
      } finally {
        setLoading(false)
      }
    }
    fetchData()
  }, [])

  if (loading) {
    return (
      <div className="animate-pulse space-y-6">
        <div className="h-8 w-40 bg-gray-200 dark:bg-gray-800 rounded" />
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          {[1, 2, 3, 4].map((i) => <div key={i} className="h-28 bg-gray-100 dark:bg-gray-800 rounded-xl" />)}
        </div>
        <div className="h-80 bg-gray-100 dark:bg-gray-800 rounded-xl" />
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex items-center justify-center min-h-[400px]">
        <div className="flex items-center gap-2 text-red-600 dark:text-red-400">
          <AlertCircle size={20} />
          <span className="text-sm">{error}</span>
        </div>
      </div>
    )
  }

  const totalMessages = tenantUsage.reduce((s, t) => s + (t.current_month_messages || 0), 0)
  const totalSessions = tenantUsage.reduce((s, t) => s + (t.current_month_sessions || 0), 0)
  const totalStt = tenantUsage.reduce((s, t) => s + (t.current_month_stt_tokens || 0), 0)
  const totalTts = tenantUsage.reduce((s, t) => s + (t.current_month_tts_tokens || 0), 0)
  const totalRevenue = tenantUsage.reduce((s, t) => s + (t.current_month_cost_usd || 0), 0)

  // Plan distribution for pie chart
  const planCounts = allTenants.reduce((acc, t) => {
    const plan = (t.plan || 'unknown').charAt(0).toUpperCase() + (t.plan || 'unknown').slice(1)
    acc[plan] = (acc[plan] || 0) + 1
    return acc
  }, {} as Record<string, number>)
  const planPieData = Object.entries(planCounts).map(([name, value]) => ({ name, value }))

  // MRR by plan
  const mrrByPlan = allTenants
    .filter((t) => t.status === 'active')
    .reduce((acc, t) => {
      const plan = t.plan?.toLowerCase() || 'unknown'
      acc[plan] = (acc[plan] || 0) + (PLAN_PRICES[plan] || 0)
      return acc
    }, {} as Record<string, number>)
  const mrrData = Object.entries(mrrByPlan)
    .filter(([, v]) => v > 0)
    .map(([plan, mrr]) => ({
      plan: plan.charAt(0).toUpperCase() + plan.slice(1),
      mrr,
    }))
  const estimatedMRR = Object.values(mrrByPlan).reduce((s, v) => s + v, 0)

  // Top tenants chart data
  const sortKey: Record<typeof sortBy, keyof TenantUsage> = {
    messages: 'current_month_messages',
    sessions: 'current_month_sessions',
    cost: 'current_month_cost_usd',
  }
  const topTenantsData = [...tenantUsage]
    .sort((a, b) => ((b[sortKey[sortBy]] as number) || 0) - ((a[sortKey[sortBy]] as number) || 0))
    .slice(0, 8)
    .map((t) => ({
      name: (t.tenant_name || t.tenant_id).slice(0, 16),
      value: (t[sortKey[sortBy]] as number) || 0,
    }))

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Analytics</h1>
        <p className="text-sm text-gray-500 mt-0.5">Platform usage and revenue breakdown</p>
      </div>

      {/* KPI Row */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard label="Messages Today" value={(metrics?.messages_today ?? 0).toLocaleString()} icon={MessageSquare} color="bg-blue-500" sub="Across all tenants" />
        <StatCard label="Sessions Today" value={(metrics?.sessions_today ?? 0).toLocaleString()} icon={BarChart3} color="bg-violet-500" sub="Active conversations" />
        <StatCard label="Total Agents" value={(metrics?.total_agents ?? 0).toLocaleString()} icon={Bot} color="bg-emerald-500" sub="Deployed this month" />
        <StatCard label="Est. MRR" value={`$${estimatedMRR.toLocaleString()}`} icon={DollarSign} color="bg-orange-500" sub="From active subscriptions" />
      </div>

      {/* Tabs */}
      <div className="border-b border-gray-200 dark:border-gray-800">
        <nav className="flex gap-1">
          {TABS.map((tab) => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={`px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${
                activeTab === tab
                  ? 'border-violet-600 text-violet-600 dark:text-violet-400'
                  : 'border-transparent text-gray-500 hover:text-gray-900 dark:hover:text-white'
              }`}
            >
              {tab}
            </button>
          ))}
        </nav>
      </div>

      {/* Tab Content */}
      {activeTab === 'Usage' && (
        <div className="space-y-6">
          {/* Top Tenants Chart */}
          <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 p-5">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-sm font-semibold text-gray-900 dark:text-white">Top Tenants — This Month</h2>
              <div className="flex gap-2">
                {(['messages', 'sessions', 'cost'] as const).map((s) => (
                  <button
                    key={s}
                    onClick={() => setSortBy(s)}
                    className={`px-3 py-1 text-xs font-medium rounded-md transition-colors ${
                      sortBy === s
                        ? 'bg-violet-100 dark:bg-violet-900/30 text-violet-700 dark:text-violet-300'
                        : 'text-gray-500 hover:text-gray-900 dark:hover:text-white'
                    }`}
                  >
                    {s.charAt(0).toUpperCase() + s.slice(1)}
                  </button>
                ))}
              </div>
            </div>
            {topTenantsData.length > 0 ? (
              <ResponsiveContainer width="100%" height={260}>
                <BarChart data={topTenantsData} margin={{ top: 0, right: 0, left: -10, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                  <XAxis dataKey="name" tick={{ fontSize: 11 }} />
                  <YAxis tick={{ fontSize: 11 }} />
                  <Tooltip
                    contentStyle={{ borderRadius: 8, border: '1px solid #e5e7eb', fontSize: 12 }}
                    formatter={(v: number) => [sortBy === 'cost' ? `$${v.toFixed(2)}` : v.toLocaleString(), sortBy]}
                  />
                  <Bar dataKey="value" fill="#7c3aed" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <div className="h-48 flex items-center justify-center text-sm text-gray-400">
                No usage data recorded this month
              </div>
            )}
          </div>

          {/* Voice Summary */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 p-5">
              <div className="flex items-center gap-3 mb-4">
                <div className="w-9 h-9 rounded-lg bg-orange-100 dark:bg-orange-900/20 flex items-center justify-center text-orange-600">
                  <Mic size={18} />
                </div>
                <div>
                  <p className="text-sm font-semibold text-gray-900 dark:text-white">Speech-to-Text</p>
                  <p className="text-xs text-gray-400">Monthly STT usage</p>
                </div>
              </div>
              <p className="text-3xl font-bold text-gray-900 dark:text-white">{totalStt.toLocaleString()}</p>
              <p className="text-xs text-gray-400 mt-1">tokens processed</p>
              <div className="mt-3 pt-3 border-t border-gray-100 dark:border-gray-800 flex justify-between text-xs text-gray-500">
                <span>Avg per tenant</span>
                <span className="font-medium text-gray-900 dark:text-white">
                  {tenantUsage.length > 0 ? Math.round(totalStt / tenantUsage.length).toLocaleString() : 0}
                </span>
              </div>
            </div>

            <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 p-5">
              <div className="flex items-center gap-3 mb-4">
                <div className="w-9 h-9 rounded-lg bg-emerald-100 dark:bg-emerald-900/20 flex items-center justify-center text-emerald-600">
                  <Mic2 size={18} />
                </div>
                <div>
                  <p className="text-sm font-semibold text-gray-900 dark:text-white">Text-to-Speech</p>
                  <p className="text-xs text-gray-400">Monthly TTS usage</p>
                </div>
              </div>
              <p className="text-3xl font-bold text-gray-900 dark:text-white">{totalTts.toLocaleString()}</p>
              <p className="text-xs text-gray-400 mt-1">tokens synthesized</p>
              <div className="mt-3 pt-3 border-t border-gray-100 dark:border-gray-800 flex justify-between text-xs text-gray-500">
                <span>Avg per tenant</span>
                <span className="font-medium text-gray-900 dark:text-white">
                  {tenantUsage.length > 0 ? Math.round(totalTts / tenantUsage.length).toLocaleString() : 0}
                </span>
              </div>
            </div>
          </div>
        </div>
      )}

      {activeTab === 'Revenue' && (
        <div className="space-y-6">
          {/* Revenue Summary Cards */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 p-5">
              <p className="text-sm text-gray-500 mb-2">Estimated MRR</p>
              <p className="text-3xl font-bold text-gray-900 dark:text-white">${estimatedMRR.toLocaleString()}</p>
              <p className="text-xs text-gray-400 mt-1">Monthly recurring revenue</p>
            </div>
            <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 p-5">
              <p className="text-sm text-gray-500 mb-2">Estimated ARR</p>
              <p className="text-3xl font-bold text-gray-900 dark:text-white">${(estimatedMRR * 12).toLocaleString()}</p>
              <p className="text-xs text-gray-400 mt-1">Annualized run rate</p>
            </div>
            <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 p-5">
              <p className="text-sm text-gray-500 mb-2">Revenue This Month</p>
              <p className="text-3xl font-bold text-gray-900 dark:text-white">${totalRevenue.toFixed(2)}</p>
              <p className="text-xs text-gray-400 mt-1">Across all tenants</p>
            </div>
          </div>

          {/* MRR by Plan + Plan Distribution */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 p-5">
              <h2 className="text-sm font-semibold text-gray-900 dark:text-white mb-4">MRR by Plan</h2>
              {mrrData.length > 0 ? (
                <ResponsiveContainer width="100%" height={220}>
                  <BarChart data={mrrData} margin={{ top: 0, right: 0, left: -10, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                    <XAxis dataKey="plan" tick={{ fontSize: 12 }} />
                    <YAxis tick={{ fontSize: 12 }} tickFormatter={(v) => `$${v}`} />
                    <Tooltip
                      contentStyle={{ borderRadius: 8, border: '1px solid #e5e7eb', fontSize: 12 }}
                      formatter={(v: number) => [`$${v.toLocaleString()}`, 'MRR']}
                    />
                    <Bar dataKey="mrr" fill="#7c3aed" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              ) : (
                <div className="h-48 flex items-center justify-center text-sm text-gray-400">
                  No paid subscriptions yet
                </div>
              )}
            </div>

            <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 p-5">
              <h2 className="text-sm font-semibold text-gray-900 dark:text-white mb-4">Tenants by Plan</h2>
              {planPieData.length > 0 ? (
                <ResponsiveContainer width="100%" height={220}>
                  <PieChart>
                    <Pie
                      data={planPieData}
                      cx="50%"
                      cy="45%"
                      innerRadius={55}
                      outerRadius={80}
                      paddingAngle={3}
                      dataKey="value"
                    >
                      {planPieData.map((entry, i) => (
                        <Cell key={i} fill={PLAN_COLORS[entry.name] || '#6b7280'} />
                      ))}
                    </Pie>
                    <Tooltip
                      contentStyle={{ borderRadius: 8, border: '1px solid #e5e7eb', fontSize: 12 }}
                      formatter={(v: number) => [v, 'tenants']}
                    />
                    <Legend iconType="circle" iconSize={8} wrapperStyle={{ fontSize: 12 }} />
                  </PieChart>
                </ResponsiveContainer>
              ) : (
                <div className="h-48 flex items-center justify-center text-sm text-gray-400">
                  No tenant data
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {activeTab === 'Tenants' && (
        <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 overflow-hidden">
          <div className="px-5 py-4 border-b border-gray-100 dark:border-gray-800">
            <h2 className="text-sm font-semibold text-gray-900 dark:text-white">
              All Tenants — Usage Summary ({allTenants.length} total)
            </h2>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-gray-50 dark:bg-gray-800/50">
                  <th className="text-left px-5 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Organization</th>
                  <th className="text-left px-5 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Plan</th>
                  <th className="text-right px-5 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Messages</th>
                  <th className="text-right px-5 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Sessions</th>
                  <th className="text-right px-5 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Revenue</th>
                  <th className="text-left px-5 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
                {allTenants.length === 0 ? (
                  <tr>
                    <td colSpan={6} className="px-5 py-12 text-center text-gray-400 text-sm">No tenants found</td>
                  </tr>
                ) : (
                  allTenants.map((tenant) => {
                    const usage = tenantUsage.find((u) => u.tenant_id === tenant.id)
                    return (
                      <tr key={tenant.id} className="hover:bg-gray-50 dark:hover:bg-gray-800/30 transition-colors">
                        <td className="px-5 py-3.5 font-medium text-gray-900 dark:text-white">
                          {tenant.business_name || tenant.name}
                        </td>
                        <td className="px-5 py-3.5">
                          <span className="text-xs font-medium px-2 py-0.5 rounded-full bg-violet-50 dark:bg-violet-900/20 text-violet-700 dark:text-violet-300 capitalize">
                            {tenant.plan}
                          </span>
                        </td>
                        <td className="px-5 py-3.5 text-right text-gray-600 dark:text-gray-400">
                          {(usage?.current_month_messages || 0).toLocaleString()}
                        </td>
                        <td className="px-5 py-3.5 text-right text-gray-600 dark:text-gray-400">
                          {(usage?.current_month_sessions || 0).toLocaleString()}
                        </td>
                        <td className="px-5 py-3.5 text-right text-gray-600 dark:text-gray-400">
                          ${(usage?.current_month_cost_usd || 0).toFixed(2)}
                        </td>
                        <td className="px-5 py-3.5">
                          <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${
                            tenant.status === 'active'
                              ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-900/20 dark:text-emerald-400'
                              : 'bg-red-50 text-red-700 dark:bg-red-900/20 dark:text-red-400'
                          }`}>
                            {tenant.status}
                          </span>
                        </td>
                      </tr>
                    )
                  })
                )}
              </tbody>
              {allTenants.length > 0 && (
                <tfoot>
                  <tr className="bg-gray-50 dark:bg-gray-800/50 border-t border-gray-200 dark:border-gray-800">
                    <td className="px-5 py-3 text-xs font-semibold text-gray-500" colSpan={2}>Totals</td>
                    <td className="px-5 py-3 text-right text-xs font-semibold text-gray-900 dark:text-white">{totalMessages.toLocaleString()}</td>
                    <td className="px-5 py-3 text-right text-xs font-semibold text-gray-900 dark:text-white">{totalSessions.toLocaleString()}</td>
                    <td className="px-5 py-3 text-right text-xs font-semibold text-gray-900 dark:text-white">${totalRevenue.toFixed(2)}</td>
                    <td />
                  </tr>
                </tfoot>
              )}
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
