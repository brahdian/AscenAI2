'use client'

import { useEffect, useState } from 'react'
import { adminApi } from '@/lib/api'
import { Building2, Bot, MessageSquare, Activity, TrendingUp, Users, AlertCircle, ArrowRight } from 'lucide-react'

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

interface TenantsResponse {
  tenants: Tenant[]
  pagination: {
    page: number
    per_page: number
    total: number
    pages: number
  }
}

function StatCard({
  icon: Icon,
  label,
  value,
  color,
}: {
  icon: React.ElementType
  label: string
  value: string | number
  color: string
}) {
  return (
    <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 p-5">
      <div className="flex items-center justify-between mb-3">
        <span className="text-sm text-gray-500 dark:text-gray-400">{label}</span>
        <div className={`w-8 h-8 rounded-lg ${color} flex items-center justify-center`}>
          <Icon size={16} className="text-white" />
        </div>
      </div>
      <p className="text-2xl font-bold text-gray-900 dark:text-white">{value}</p>
    </div>
  )
}

export default function AdminDashboard() {
  const [metrics, setMetrics] = useState<Metrics | null>(null)
  const [tenants, setTenants] = useState<Tenant[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    async function fetchData() {
      try {
        const [metricsData, tenantsData] = await Promise.all([
          adminApi.getMetrics(),
          adminApi.listTenants({ per_page: 5 }),
        ])
        setMetrics(metricsData)
        setTenants(tenantsData.tenants || [])
      } catch (err) {
        setError('Failed to load dashboard data')
        console.error(err)
      } finally {
        setLoading(false)
      }
    }
    fetchData()
  }, [])

  if (loading) {
    return (
      <div className="p-8 animate-pulse space-y-6">
        <div className="h-8 w-48 bg-gray-200 dark:bg-gray-800 rounded"></div>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="h-32 bg-gray-100 dark:bg-gray-800 rounded-xl"></div>
          ))}
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="p-8 text-center">
        <div className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-red-50 dark:bg-red-900/10 border border-red-100 dark:border-red-900/30 text-red-600 dark:text-red-400">
           <AlertCircle size={18} />
           <span>{error}</span>
        </div>
      </div>
    )
  }

  return (
    <div className="p-8">
      {/* Header */}
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Platform Overview</h1>
        <p className="text-gray-500 dark:text-gray-400 mt-1">Global platform metrics and recent tenant activity.</p>
      </div>

      {/* Stats Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
        <StatCard
          label="Active Tenants"
          value={metrics?.active_tenants ?? 0}
          icon={Building2}
          color="bg-blue-500"
        />
        <StatCard
          label="Total Agents"
          value={metrics?.total_agents ?? 0}
          icon={Bot}
          color="bg-violet-500"
        />
        <StatCard
          label="Sessions Today"
          value={metrics?.sessions_today ?? 0}
          icon={MessageSquare}
          color="bg-emerald-500"
        />
        <StatCard
          label="Messages Today"
          value={metrics?.messages_today ?? 0}
          icon={Activity}
          color="bg-orange-500"
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
          {/* Recent Tenants */}
          <div className="lg:col-span-2 bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-xl shadow-sm overflow-hidden">
            <div className="px-6 py-5 border-b border-gray-100 dark:border-gray-800 flex items-center justify-between">
              <h2 className="font-semibold text-gray-900 dark:text-white">Recent Tenants</h2>
              <a href="/admin/tenants" className="text-xs font-semibold text-violet-600 dark:text-violet-400 hover:underline">
                View all tenants
              </a>
            </div>
            <div className="divide-y divide-gray-100 dark:divide-gray-800">
              {tenants.length === 0 ? (
                <div className="px-6 py-12 text-center text-gray-500">No active tenants found.</div>
              ) : (
                tenants.map((tenant) => (
                  <div
                    key={tenant.id}
                    className="flex items-center justify-between px-6 py-4 hover:bg-gray-50 dark:hover:bg-gray-800/50 transition-colors group cursor-pointer"
                    onClick={() => window.location.href = `/admin/tenants/${tenant.id}`}
                  >
                    <div className="flex items-center gap-4">
                      <div className="w-10 h-10 rounded-xl bg-gray-100 dark:bg-gray-800 flex items-center justify-center text-gray-500 group-hover:bg-violet-100 dark:group-hover:bg-violet-900/30 group-hover:text-violet-600 dark:group-hover:text-violet-400 transition-colors">
                        <Building2 size={20} />
                      </div>
                      <div>
                        <p className="text-sm font-semibold text-gray-900 dark:text-white">{tenant.business_name || tenant.name}</p>
                        <p className="text-xs text-gray-500 uppercase tracking-tight">{tenant.plan} Plan</p>
                      </div>
                    </div>
                    <div className="flex items-center gap-4">
                        <span
                          className={`text-[10px] font-bold uppercase tracking-widest px-2 py-1 rounded-md border ${
                            tenant.status === 'active'
                              ? 'bg-emerald-50 dark:bg-emerald-900/10 border-emerald-100 dark:border-emerald-800 text-emerald-600 dark:text-emerald-400'
                              : 'bg-red-50 dark:bg-red-900/10 border-red-100 dark:border-red-900/30 text-red-600 dark:text-red-400'
                          }`}
                        >
                          {tenant.status}
                        </span>
                        <ArrowRight size={14} className="text-gray-300 group-hover:text-violet-500 transition-colors" />
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>

          {/* Quick Stats & Links */}
          <div className="space-y-4">
            <h2 className="px-1 text-xs font-bold text-gray-400 dark:text-gray-500 uppercase tracking-widest">Global Management</h2>
            {[
                { label: 'Tenant Management', icon: Building2, href: '/admin/tenants', color: 'text-blue-500', bg: 'bg-blue-50 dark:bg-blue-900/10' },
                { label: 'User Directory', icon: Users, href: '/admin/users', color: 'text-violet-500', bg: 'bg-violet-50 dark:bg-violet-900/10' },
                { label: 'System Analytics', icon: Activity, href: '/admin/analytics', color: 'text-orange-500', bg: 'bg-orange-50 dark:bg-orange-900/10' },
            ].map((link) => (
                <a
                    key={link.label}
                    href={link.href}
                    className="flex items-center gap-4 p-4 bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-xl hover:border-violet-300 dark:hover:border-violet-700 hover:shadow-md transition-all group"
                >
                    <div className={`w-10 h-10 rounded-xl ${link.bg} flex items-center justify-center ${link.color} group-hover:scale-110 transition-transform`}>
                        <link.icon size={20} />
                    </div>
                    <div>
                        <p className="text-sm font-bold text-gray-900 dark:text-white group-hover:text-violet-600 transition-colors">{link.label}</p>
                        <p className="text-[10px] text-gray-500 uppercase tracking-tight">Access Control</p>
                    </div>
                </a>
            ))}
          </div>
      </div>
    </div>
  )
}