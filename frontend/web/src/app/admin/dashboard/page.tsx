'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { adminApi, api } from '@/lib/api'
import {
  Building2, Bot, MessageSquare, Activity, Users, DollarSign,
  ArrowRight, TrendingUp, AlertCircle, CheckCircle2, Clock, RefreshCw,
} from 'lucide-react'
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell,
} from 'recharts'

// Plan price map for MRR estimation
const PLAN_PRICES: Record<string, number> = {
  professional: 99,
  business: 299,
  enterprise: 499,
  starter: 0,
  trial: 0,
}

interface Metrics {
  active_tenants: number
  total_agents: number
  sessions_today: number
  messages_today: number
  timestamp: string
}

interface Tenant {
  id: string
  name: string
  business_name: string
  plan: string
  status: string
  created_at: string
}

interface TenantUsage {
  tenant_id: string
  tenant_name: string
  current_month_messages: number
  current_month_chat_units: number
  current_month_sessions: number
}

interface AuditEvent {
  id: string
  action: string
  actor_email: string
  category: string
  status: string
  created_at: string
}

function KpiCard({
  icon: Icon,
  label,
  value,
  sub,
  accent,
}: {
  icon: React.ElementType
  label: string
  value: string | number
  sub?: string
  accent: string
}) {
  return (
    <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 p-5">
      <div className="flex items-start justify-between mb-3">
        <span className="text-sm font-medium text-gray-500 dark:text-gray-400">{label}</span>
        <div className={`w-9 h-9 rounded-lg ${accent} flex items-center justify-center`}>
          <Icon size={18} className="text-white" />
        </div>
      </div>
      <p className="text-2xl font-bold text-gray-900 dark:text-white">{value}</p>
      {sub && <p className="text-xs text-gray-400 mt-1">{sub}</p>}
    </div>
  )
}

const CHART_COLORS = ['#7c3aed', '#2563eb', '#059669', '#d97706', '#dc2626', '#0891b2']

export default function AdminDashboard() {
  const [metrics, setMetrics] = useState<Metrics | null>(null)
  const [tenants, setTenants] = useState<Tenant[]>([])
  const [allTenants, setAllTenants] = useState<Tenant[]>([])
  const [tenantUsage, setTenantUsage] = useState<TenantUsage[]>([])
  const [recentEvents, setRecentEvents] = useState<AuditEvent[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [lastRefreshed, setLastRefreshed] = useState<Date | null>(null)

  async function fetchData() {
    setLoading(true)
    try {
      const [metricsData, tenantsData, allTenantsData, usageData, auditData] = await Promise.all([
        adminApi.getMetrics(),
        adminApi.listTenants({ per_page: 6 }),
        adminApi.listTenants({ per_page: 200 }),
        api.get('/admin/tenants/usage').catch(() => ({ data: { tenants: [] } })),
        api.get('/admin/audit-logs?per_page=5').catch(() => ({ data: { logs: [] } })),
      ])
      setMetrics(metricsData)
      setTenants(tenantsData.tenants || [])
      setAllTenants(allTenantsData.tenants || [])
      setTenantUsage(usageData.data?.tenants || [])
      setRecentEvents(auditData.data?.logs || [])
      setLastRefreshed(new Date())
      setError(null)
    } catch (err) {
      setError('Failed to load dashboard data. Check that the backend services are running.')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetchData() }, [])

  // Compute plan distribution for chart
  const planDistribution = Object.entries(
    allTenants.reduce((acc, t) => {
      const plan = t.plan || 'unknown'
      acc[plan] = (acc[plan] || 0) + 1
      return acc
    }, {} as Record<string, number>)
  ).map(([plan, count]) => ({ plan: plan.charAt(0).toUpperCase() + plan.slice(1), count }))

  // Estimated MRR
  const estimatedMRR = allTenants.reduce((sum, t) => {
    if (t.status !== 'active') return sum
    return sum + (PLAN_PRICES[t.plan?.toLowerCase()] || 0)
  }, 0)

  // Top tenants by messages for chart
  const topTenantsChart = [...tenantUsage]
    .sort((a, b) => (b.current_month_messages || 0) - (a.current_month_messages || 0))
    .slice(0, 6)
    .map((t) => ({
      name: (t.tenant_name || t.tenant_id).slice(0, 16),
      messages: t.current_month_messages || 0,
    }))

  if (loading) {
    return (
      <div className="animate-pulse space-y-6">
        <div className="h-8 w-48 bg-gray-200 dark:bg-gray-800 rounded" />
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          {[1, 2, 3, 4].map((i) => <div key={i} className="h-28 bg-gray-100 dark:bg-gray-800 rounded-xl" />)}
        </div>
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <div className="h-64 bg-gray-100 dark:bg-gray-800 rounded-xl" />
          <div className="h-64 bg-gray-100 dark:bg-gray-800 rounded-xl" />
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Overview</h1>
          <p className="text-sm text-gray-500 mt-0.5">Platform-wide metrics and tenant activity</p>
        </div>
        <div className="flex items-center gap-3">
          {lastRefreshed && (
            <span className="text-xs text-gray-400 flex items-center gap-1">
              <Clock size={12} />
              Updated {lastRefreshed.toLocaleTimeString()}
            </span>
          )}
          <button
            onClick={fetchData}
            className="flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium text-gray-600 dark:text-gray-400 bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors"
          >
            <RefreshCw size={14} />
            Refresh
          </button>
        </div>
      </div>

      {error && (
        <div className="flex items-center gap-2 px-4 py-3 rounded-lg bg-red-50 dark:bg-red-900/10 border border-red-100 dark:border-red-900/30 text-red-600 dark:text-red-400 text-sm">
          <AlertCircle size={16} />
          {error}
        </div>
      )}

      {/* KPI Cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <KpiCard label="Active Tenants" value={metrics?.active_tenants ?? 0} icon={Building2} accent="bg-blue-500" sub="Organizations on platform" />
        <KpiCard label="Total Agents" value={metrics?.total_agents ?? 0} icon={Bot} accent="bg-violet-500" sub="Deployed AI agents" />
        <KpiCard label="Messages Today" value={(metrics?.messages_today ?? 0).toLocaleString()} icon={MessageSquare} accent="bg-emerald-500" sub="Across all tenants" />
        <KpiCard
          label="Est. MRR"
          value={`$${estimatedMRR.toLocaleString()}`}
          icon={DollarSign}
          accent="bg-orange-500"
          sub="Based on active plans"
        />
      </div>

      {/* Charts Row */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Plan Distribution */}
        <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 p-5">
          <h2 className="text-sm font-semibold text-gray-900 dark:text-white mb-4">Tenants by Plan</h2>
          {planDistribution.length > 0 ? (
            <ResponsiveContainer width="100%" height={200}>
              <BarChart data={planDistribution} margin={{ top: 0, right: 0, left: -20, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                <XAxis dataKey="plan" tick={{ fontSize: 12 }} />
                <YAxis tick={{ fontSize: 12 }} allowDecimals={false} />
                <Tooltip
                  contentStyle={{ borderRadius: 8, border: '1px solid #e5e7eb', fontSize: 12 }}
                  formatter={(v: number) => [v, 'Tenants']}
                />
                <Bar dataKey="count" radius={[4, 4, 0, 0]}>
                  {planDistribution.map((_, i) => (
                    <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <div className="h-48 flex items-center justify-center text-sm text-gray-400">
              No tenant data available
            </div>
          )}
        </div>

        {/* Top Tenants by Usage */}
        <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 p-5">
          <h2 className="text-sm font-semibold text-gray-900 dark:text-white mb-4">Top Tenants by Messages (This Month)</h2>
          {topTenantsChart.length > 0 ? (
            <ResponsiveContainer width="100%" height={200}>
              <BarChart data={topTenantsChart} layout="vertical" margin={{ top: 0, right: 0, left: 0, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" horizontal={false} stroke="#f0f0f0" />
                <XAxis type="number" tick={{ fontSize: 11 }} />
                <YAxis dataKey="name" type="category" tick={{ fontSize: 11 }} width={80} />
                <Tooltip
                  contentStyle={{ borderRadius: 8, border: '1px solid #e5e7eb', fontSize: 12 }}
                  formatter={(v: number) => [v.toLocaleString(), 'Messages']}
                />
                <Bar dataKey="messages" fill="#7c3aed" radius={[0, 4, 4, 0]} />
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <div className="h-48 flex items-center justify-center text-sm text-gray-400">
              No usage data yet this month
            </div>
          )}
        </div>
      </div>

      {/* Bottom Row: Recent Tenants + Recent Activity */}
      <div className="grid grid-cols-1 lg:grid-cols-5 gap-6">
        {/* Recent Tenants */}
        <div className="lg:col-span-3 bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 overflow-hidden">
          <div className="px-5 py-4 border-b border-gray-100 dark:border-gray-800 flex items-center justify-between">
            <h2 className="text-sm font-semibold text-gray-900 dark:text-white">Recent Tenants</h2>
            <Link href="/admin/tenants" className="text-xs font-medium text-violet-600 dark:text-violet-400 hover:underline flex items-center gap-1">
              View all <ArrowRight size={12} />
            </Link>
          </div>
          <div className="divide-y divide-gray-50 dark:divide-gray-800">
            {tenants.length === 0 ? (
              <div className="px-5 py-10 text-center text-sm text-gray-400">No tenants yet</div>
            ) : (
              tenants.map((tenant) => (
                <Link
                  key={tenant.id}
                  href={`/admin/tenants/${tenant.id}`}
                  className="flex items-center justify-between px-5 py-3.5 hover:bg-gray-50 dark:hover:bg-gray-800/50 transition-colors group"
                >
                  <div className="flex items-center gap-3">
                    <div className="w-8 h-8 rounded-lg bg-gray-100 dark:bg-gray-800 flex items-center justify-center text-gray-500 group-hover:bg-violet-50 dark:group-hover:bg-violet-900/20 group-hover:text-violet-600 transition-colors">
                      <Building2 size={16} />
                    </div>
                    <div>
                      <p className="text-sm font-medium text-gray-900 dark:text-white group-hover:text-violet-600 transition-colors">
                        {tenant.business_name || tenant.name}
                      </p>
                      <p className="text-xs text-gray-400 capitalize">{tenant.plan} plan</p>
                    </div>
                  </div>
                  <div className="flex items-center gap-3">
                    <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${
                      tenant.status === 'active'
                        ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-900/20 dark:text-emerald-400'
                        : 'bg-red-50 text-red-700 dark:bg-red-900/20 dark:text-red-400'
                    }`}>
                      {tenant.status}
                    </span>
                    <ArrowRight size={14} className="text-gray-300 group-hover:text-violet-500 transition-colors" />
                  </div>
                </Link>
              ))
            )}
          </div>
        </div>

        {/* Recent Activity */}
        <div className="lg:col-span-2 bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 overflow-hidden">
          <div className="px-5 py-4 border-b border-gray-100 dark:border-gray-800 flex items-center justify-between">
            <h2 className="text-sm font-semibold text-gray-900 dark:text-white">Recent Activity</h2>
            <Link href="/admin/audit-logs" className="text-xs font-medium text-violet-600 dark:text-violet-400 hover:underline flex items-center gap-1">
              Audit logs <ArrowRight size={12} />
            </Link>
          </div>
          <div className="divide-y divide-gray-50 dark:divide-gray-800">
            {recentEvents.length === 0 ? (
              <div className="px-5 py-10 text-center text-sm text-gray-400">No recent events</div>
            ) : (
              recentEvents.map((event) => (
                <div key={event.id} className="px-5 py-3">
                  <div className="flex items-start gap-2.5">
                    {event.status === 'success' ? (
                      <CheckCircle2 size={14} className="text-emerald-500 mt-0.5 flex-shrink-0" />
                    ) : (
                      <AlertCircle size={14} className="text-red-500 mt-0.5 flex-shrink-0" />
                    )}
                    <div className="min-w-0">
                      <p className="text-xs font-medium text-gray-900 dark:text-white truncate">{event.action}</p>
                      <p className="text-xs text-gray-400 truncate">{event.actor_email || 'System'}</p>
                    </div>
                    <span className="text-[10px] text-gray-300 ml-auto flex-shrink-0 whitespace-nowrap">
                      {new Date(event.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                    </span>
                  </div>
                </div>
              ))
            )}
          </div>
          {/* Summary Stats */}
          <div className="px-5 py-4 border-t border-gray-100 dark:border-gray-800 grid grid-cols-2 gap-4 bg-gray-50/50 dark:bg-gray-800/20">
            <div className="text-center">
              <p className="text-lg font-bold text-gray-900 dark:text-white">{metrics?.sessions_today ?? 0}</p>
              <p className="text-[10px] text-gray-400 uppercase tracking-wide">Sessions today</p>
            </div>
            <div className="text-center">
              <p className="text-lg font-bold text-gray-900 dark:text-white">{allTenants.filter(t => t.status === 'active').length}</p>
              <p className="text-[10px] text-gray-400 uppercase tracking-wide">Active orgs</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
