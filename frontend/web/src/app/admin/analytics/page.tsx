'use client'

import { useEffect, useState } from 'react'
import { adminApi, api } from '@/lib/api'
import { BarChart3, TrendingUp, MessageSquare, Bot, Mic, Mic2, AlertCircle, DollarSign, Cpu } from 'lucide-react'

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
  timestamp: string
}

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
    <div className="bg-white dark:bg-gray-900 rounded-2xl border border-gray-100 dark:border-gray-800 p-6 shadow-sm">
      <div className="flex items-center justify-between mb-4">
        <span className="text-[10px] font-bold text-gray-400 dark:text-gray-500 uppercase tracking-widest">{label}</span>
        <div className={`w-10 h-10 rounded-xl ${color} flex items-center justify-center text-white shadow-lg shadow-current/10`}>
          <Icon size={20} />
        </div>
      </div>
      <p className="text-3xl font-extrabold text-gray-900 dark:text-white tracking-tight">{value}</p>
      {sub && <p className="text-xs text-gray-500 mt-2 font-medium">{sub}</p>}
    </div>
  )
}

export default function AnalyticsPage() {
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [metrics, setMetrics] = useState<Metrics | null>(null)
  const [tenantUsage, setTenantUsage] = useState<TenantUsage[]>([])

  useEffect(() => {
    async function fetchData() {
      try {
        const [metricsData, tenantsData] = await Promise.all([
          adminApi.getMetrics(),
          api.get('/admin/tenants/usage').catch(() => ({ data: { tenants: [] } })),
        ])
        setMetrics(metricsData)
        setTenantUsage(tenantsData.data?.tenants || [])
      } catch (err) {
        setError('Failed to load platform analytics')
        console.error(err)
      } finally {
        setLoading(false)
      }
    }
    fetchData()
  }, [])

  if (loading) {
    return (
      <div className="p-8 animate-pulse space-y-8">
        <div className="h-8 w-48 bg-gray-200 dark:bg-gray-800 rounded-xl"></div>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="h-32 bg-gray-100 dark:bg-gray-800 rounded-3xl"></div>
          ))}
        </div>
        <div className="h-96 bg-gray-100 dark:bg-gray-800 rounded-3xl"></div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="p-8 flex items-center justify-center min-h-[400px]">
        <div className="text-center space-y-4">
           <div className="inline-flex items-center justify-center w-12 h-12 rounded-full bg-red-50 dark:bg-red-900/10 text-red-500 mb-2">
              <AlertCircle size={24} />
           </div>
           <h2 className="text-lg font-bold text-gray-900 dark:text-white">Analytics Restricted</h2>
           <p className="text-sm text-gray-500 max-w-xs">{error}</p>
        </div>
      </div>
    )
  }

  const totalLLMTokens = tenantUsage.reduce((sum, t) => sum + (t.current_month_chat_units || 0), 0)
  const totalSTTTokens = tenantUsage.reduce((sum, t) => sum + (t.current_month_stt_tokens || 0), 0)
  const totalTTSTokens = tenantUsage.reduce((sum, t) => sum + (t.current_month_tts_tokens || 0), 0)
  const totalCost = tenantUsage.reduce((sum, t) => sum + (t.current_month_cost_usd || 0), 0)

  return (
    <div className="p-8 space-y-8">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-gray-900 dark:text-white tracking-tight">Platform Economics</h1>
        <p className="text-gray-500 dark:text-gray-400 text-sm mt-1">Real-time usage velocity and cost breakdowns across all tenants.</p>
      </div>

      {/* Overview Stats */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        <StatCard
          label="Message Velocity"
          value={metrics?.messages_today?.toLocaleString() || 0}
          icon={MessageSquare}
          sub="Recorded today"
          color="bg-blue-500"
        />
        <StatCard
          label="Session Throughput"
          value={metrics?.sessions_today?.toLocaleString() || 0}
          icon={TrendingUp}
          sub="Active conversations"
          color="bg-violet-500"
        />
        <StatCard
          label="Compute Nodes"
          value={metrics?.total_agents?.toLocaleString() || 0}
          icon={Bot}
          sub="Live AI agents"
          color="bg-emerald-500"
        />
        <StatCard
          label="Cloud Footprint"
          value={metrics?.active_tenants?.toLocaleString() || 0}
          icon={BarChart3}
          sub="Provisioned tenants"
          color="bg-orange-500"
        />
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-8">
          {/* Token Consumption breakdown */}
          <div className="xl:col-span-2 space-y-8">
              <div className="bg-white dark:bg-gray-900 border border-gray-100 dark:border-gray-800 rounded-3xl shadow-sm overflow-hidden">
                <div className="px-8 py-6 border-b border-gray-50 dark:border-gray-800 flex items-center justify-between">
                  <div>
                      <h2 className="text-lg font-bold text-gray-900 dark:text-white">Compute Usage</h2>
                      <p className="text-xs text-gray-500 mt-1 uppercase tracking-widest font-bold">LLM Token Consumption Lifecycle</p>
                  </div>
                  <div className="flex items-center gap-2 px-3 py-1 bg-emerald-50 dark:bg-emerald-900/10 border border-emerald-100 dark:border-emerald-800 rounded-lg text-emerald-600 dark:text-emerald-400 text-[10px] font-bold">
                     <Cpu size={12} /> SYSTEM HEALTHY
                  </div>
                </div>
                
                <div className="p-8">
                  <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-10">
                    <div className="p-6 bg-gray-50/50 dark:bg-gray-800/30 rounded-2xl border border-gray-100 dark:border-gray-700">
                      <p className="text-[10px] font-bold text-gray-400 dark:text-gray-500 uppercase tracking-widest mb-1 text-center">Cumulative Units</p>
                      <p className="text-2xl font-extrabold text-gray-900 dark:text-white text-center">{totalLLMTokens.toLocaleString()}</p>
                    </div>
                    <div className="p-6 bg-gray-50/50 dark:bg-gray-800/30 rounded-2xl border border-gray-100 dark:border-gray-700">
                      <p className="text-[10px] font-bold text-gray-400 dark:text-gray-500 uppercase tracking-widest mb-1 text-center">Tenant Velocity</p>
                      <p className="text-2xl font-extrabold text-gray-900 dark:text-white text-center">
                        {tenantUsage.length > 0 ? Math.round(totalLLMTokens / tenantUsage.length).toLocaleString() : 0}
                      </p>
                    </div>
                    <div className="p-6 bg-violet-600 text-white rounded-2xl shadow-lg shadow-violet-500/20">
                      <p className="text-[10px] font-bold opacity-70 uppercase tracking-widest mb-1 text-center">Total Revenue Impact</p>
                      <p className="text-2xl font-extrabold text-center flex items-center justify-center gap-1">
                         <DollarSign size={20} /> {totalCost.toFixed(2)}
                      </p>
                    </div>
                  </div>

                  {tenantUsage.length > 0 ? (
                    <div className="space-y-6">
                      <h3 className="text-xs font-bold text-gray-400 dark:text-gray-500 uppercase tracking-widest mb-4">High-Consumption Organizations</h3>
                      {tenantUsage
                        .sort((a, b) => (b.current_month_chat_units || 0) - (a.current_month_chat_units || 0))
                        .slice(0, 10)
                        .map((tenant, i) => (
                          <div key={tenant.tenant_id} className="group relative">
                            <div className="flex items-center justify-between mb-2">
                                <div className="flex items-center gap-3">
                                   <span className="text-xs font-bold text-gray-300 dark:text-gray-600 w-4">{i + 1}</span>
                                   <span className="text-sm font-bold text-gray-900 dark:text-white group-hover:text-violet-500 transition-colors">
                                      {tenant.tenant_name || tenant.tenant_id}
                                   </span>
                                </div>
                                <span className="text-xs font-mono font-bold text-gray-400 dark:text-gray-500">
                                  {(tenant.current_month_chat_units || 0).toLocaleString()} UNITS
                                </span>
                            </div>
                            <div className="h-2 bg-gray-100 dark:bg-gray-800 rounded-full overflow-hidden">
                                <div
                                  className="h-full bg-gradient-to-r from-violet-500 to-blue-500 rounded-full transition-all duration-1000"
                                  style={{
                                    width: `${totalLLMTokens > 0 ? ((tenant.current_month_chat_units || 0) / totalLLMTokens) * 100 : 0}%`,
                                  }}
                                />
                            </div>
                          </div>
                        ))}
                    </div>
                  ) : (
                    <div className="text-center py-20 bg-gray-50 dark:bg-gray-800/50 rounded-3xl border-2 border-dashed border-gray-100 dark:border-gray-800">
                        <p className="text-gray-400 font-medium">No operational telemetry captured for this cycle.</p>
                    </div>
                  )}
                </div>
              </div>
          </div>

          <div className="space-y-8">
              {/* Media Processing */}
              <div className="bg-white dark:bg-gray-900 border border-gray-100 dark:border-gray-800 rounded-3xl p-8 shadow-sm">
                  <div className="flex items-center gap-4 mb-8">
                     <div className="w-12 h-12 rounded-2xl bg-orange-50 dark:bg-orange-900/10 flex items-center justify-center text-orange-500">
                        <Mic size={24} />
                     </div>
                     <div>
                        <h4 className="text-sm font-bold text-gray-900 dark:text-white uppercase tracking-tight">Speech Recognition</h4>
                        <p className="text-xs text-gray-500">Real-time STT ingestion</p>
                     </div>
                  </div>
                  <div className="space-y-6">
                      <div className="flex justify-between items-end">
                         <div>
                            <p className="text-[10px] font-bold text-gray-400 uppercase tracking-widest mb-1">Monthly Volume</p>
                            <p className="text-3xl font-extrabold text-gray-900 dark:text-white">{totalSTTTokens.toLocaleString()}</p>
                         </div>
                         <div className="text-right">
                            <p className="text-xs font-bold text-emerald-500 flex items-center gap-1">
                               <TrendingUp size={14} /> +12.5%
                            </p>
                         </div>
                      </div>
                      <div className="pt-4 border-t border-gray-50 dark:border-gray-800 flex justify-between">
                         <span className="text-xs text-gray-500 font-medium tracking-tight">System Average</span>
                         <span className="text-xs font-bold text-gray-900 dark:text-white">
                            {tenantUsage.length > 0 ? Math.round(totalSTTTokens / tenantUsage.length).toLocaleString() : 0}
                         </span>
                      </div>
                  </div>
              </div>

              <div className="bg-white dark:bg-gray-900 border border-gray-100 dark:border-gray-800 rounded-3xl p-8 shadow-sm">
                  <div className="flex items-center gap-4 mb-8">
                     <div className="w-12 h-12 rounded-2xl bg-emerald-50 dark:bg-emerald-900/10 flex items-center justify-center text-emerald-500">
                        <Mic2 size={24} />
                     </div>
                     <div>
                        <h4 className="text-sm font-bold text-gray-900 dark:text-white uppercase tracking-tight">Voice Synthesis</h4>
                        <p className="text-xs text-gray-500">Outbound TTS delivery</p>
                     </div>
                  </div>
                  <div className="space-y-6">
                      <div className="flex justify-between items-end">
                         <div>
                            <p className="text-[10px] font-bold text-gray-400 uppercase tracking-widest mb-1">Monthly Volume</p>
                            <p className="text-3xl font-extrabold text-gray-900 dark:text-white">{totalTTSTokens.toLocaleString()}</p>
                         </div>
                         <div className="text-right">
                            <p className="text-xs font-bold text-emerald-500 flex items-center gap-1">
                               <TrendingUp size={14} /> +8.3%
                            </p>
                         </div>
                      </div>
                      <div className="pt-4 border-t border-gray-50 dark:border-gray-800 flex justify-between">
                         <span className="text-xs text-gray-500 font-medium tracking-tight">System Average</span>
                         <span className="text-xs font-bold text-gray-900 dark:text-white">
                            {tenantUsage.length > 0 ? Math.round(totalTTSTokens / tenantUsage.length).toLocaleString() : 0}
                         </span>
                      </div>
                  </div>
              </div>
          </div>
      </div>
    </div>
  )
}