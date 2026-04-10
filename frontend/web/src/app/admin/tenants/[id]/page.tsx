'use client'

import { useEffect, useState } from 'react'
import { useParams } from 'next/navigation'
import { adminApi } from '@/lib/api'
import { Building2, Bot, Users, AlertTriangle, CheckCircle, XCircle, ArrowLeft, ShieldAlert, Cpu, Calendar, Activity } from 'lucide-react'
import Link from 'next/link'

interface TenantDetail {
  id: string
  name: string
  business_name: string
  plan: string
  status: string
  created_at: string
  updated_at: string
  agent_count: number
  user_count: number
}

function StatTile({
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
    <div className="bg-white dark:bg-gray-900 border border-gray-100 dark:border-gray-800 p-6 rounded-3xl shadow-sm">
      <div className="flex items-center gap-4 mb-4">
        <div className={`w-10 h-10 rounded-xl ${color} flex items-center justify-center text-white shadow-lg shadow-current/10`}>
          <Icon size={20} />
        </div>
        <span className="text-[10px] font-bold text-gray-400 dark:text-gray-500 uppercase tracking-widest">{label}</span>
      </div>
      <p className="text-2xl font-black text-gray-900 dark:text-white tracking-tight">{value}</p>
    </div>
  )
}

export default function TenantDetailPage() {
  const params = useParams()
  const tenantId = params.id as string
  const [tenant, setTenant] = useState<TenantDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [actionLoading, setActionLoading] = useState(false)

  useEffect(() => {
    async function fetchTenant() {
      try {
        const data = await adminApi.getTenant(tenantId)
        setTenant(data)
      } catch (err) {
        setError('Failed to load tenant telemetry')
        console.error(err)
      } finally {
        setLoading(false)
      }
    }
    fetchTenant()
  }, [tenantId])

  const handleSuspend = async () => {
    if (!confirm('Are you certain you want to suspend this organization? All active agents will be terminated.')) return
    setActionLoading(true)
    try {
      await adminApi.suspendTenant(tenantId, 'Suspended by admin overhaul')
      const data = await adminApi.getTenant(tenantId)
      setTenant(data)
    } catch (err) {
      alert('Failed to suspend tenant')
    } finally {
      setActionLoading(false)
    }
  }

  const handleReactivate = async () => {
    setActionLoading(true)
    try {
      await adminApi.reactivateTenant(tenantId)
      const data = await adminApi.getTenant(tenantId)
      setTenant(data)
    } catch (err) {
      alert('Failed to reactivate tenant')
    } finally {
      setActionLoading(false)
    }
  }

  if (loading) {
    return (
      <div className="p-8 space-y-8 animate-pulse text-gray-400 dark:text-gray-800">
        <div className="h-8 w-64 bg-current rounded-xl"></div>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-32 bg-current rounded-3xl"></div>
          ))}
        </div>
      </div>
    )
  }

  if (error || !tenant) {
    return (
      <div className="p-8 flex flex-col items-center justify-center min-h-[400px] text-center">
        <div className="w-16 h-16 rounded-full bg-red-50 dark:bg-red-950/20 text-red-500 flex items-center justify-center mb-6">
           <ShieldAlert size={32} />
        </div>
        <h2 className="text-xl font-bold text-gray-900 dark:text-white mb-2">Access Denied</h2>
        <p className="text-gray-500 text-sm mb-6 max-w-sm">{error || 'The requested organization identifier could not be validated in our registry.'}</p>
        <Link 
          href="/admin/tenants" 
          className="px-6 py-2 bg-gray-900 dark:bg-white text-white dark:text-gray-900 rounded-xl text-sm font-bold active:scale-95 transition-all shadow-xl shadow-gray-950/20"
        >
          Return to Registry
        </Link>
      </div>
    )
  }

  return (
    <div className="p-8 space-y-8">
      {/* Breadcrumb & Global Controls */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-6">
        <div className="flex items-center gap-6">
          <Link
            href="/admin/tenants"
            className="p-3 bg-white dark:bg-gray-900 border border-gray-100 dark:border-gray-800 rounded-2xl text-gray-400 hover:text-gray-900 dark:hover:text-white transition-all shadow-sm group active:scale-90"
          >
            <ArrowLeft size={20} className="group-hover:-translate-x-1 transition-transform" />
          </Link>
          <div>
            <div className="flex items-center gap-3">
               <h1 className="text-2xl font-black text-gray-900 dark:text-white tracking-tight">{tenant.business_name || tenant.name}</h1>
               <span className={`px-2 py-0.5 text-[10px] font-bold rounded-full border ${
                 tenant.status === 'active' ? 'bg-emerald-50 dark:bg-emerald-900/10 border-emerald-100 dark:border-emerald-800 text-emerald-600 dark:text-emerald-400' : 'bg-red-50 dark:bg-red-900/10 border-red-100 dark:border-red-900/30 text-red-600 dark:text-red-400'
               }`}>
                  {tenant.status.toUpperCase()}
               </span>
            </div>
            <p className="text-gray-500 dark:text-gray-400 text-xs font-mono mt-1 opacity-70 uppercase tracking-tighter">{tenant.id}</p>
          </div>
        </div>
        
        <div className="flex items-center gap-3">
          {tenant.status === 'active' ? (
            <button
              onClick={handleSuspend}
              disabled={actionLoading}
              className="inline-flex items-center gap-2.5 px-5 py-2.5 bg-white dark:bg-gray-950 text-red-600 border-2 border-red-100 dark:border-red-900/30 rounded-2xl text-xs font-bold hover:bg-red-50 dark:hover:bg-red-900/10 transition-all active:scale-95 disabled:opacity-50"
            >
              <AlertTriangle size={14} />
              Suspend Instance
            </button>
          ) : tenant.status === 'suspended' ? (
            <button
              onClick={handleReactivate}
              disabled={actionLoading}
              className="inline-flex items-center gap-2.5 px-6 py-2.5 bg-emerald-600 text-white rounded-2xl text-xs font-bold hover:bg-emerald-700 transition-all active:scale-95 disabled:opacity-50 shadow-lg shadow-emerald-500/20"
            >
              <CheckCircle size={14} />
              Re-Authorize Organization
            </button>
          ) : null}
        </div>
      </div>

      {/* Instance Critical Warning */}
      {tenant.status !== 'active' && (
        <div className="relative overflow-hidden p-6 bg-red-50 dark:bg-red-900/5 border border-red-100 dark:border-red-900/20 rounded-3xl group">
          <div className="relative z-10 flex items-center gap-4">
             <div className="w-12 h-12 rounded-2xl bg-red-100 dark:bg-red-900/20 flex items-center justify-center text-red-600">
                 {tenant.status === 'suspended' ? <AlertTriangle size={24} /> : <XCircle size={24} />}
             </div>
             <div>
                <h4 className="text-sm font-black text-red-700 dark:text-red-400 uppercase tracking-tight">Lifecycle Exception Detected</h4>
                <p className="text-xs text-red-600 dark:text-red-500 font-medium">
                  {tenant.status === 'suspended' 
                    ? "Administrative suspension active. All compute resources and frontend authentication for this organization are hard-locked." 
                    : "Instance marked for garbage collection. All persistent data associated with this organization is scheduled for purge."}
                </p>
             </div>
          </div>
          <div className="absolute top-0 right-0 p-2 opacity-10 group-hover:opacity-20 transition-opacity">
              {tenant.status === 'suspended' ? <AlertTriangle size={80} /> : <XCircle size={80} />}
          </div>
        </div>
      )}

      {/* Snapshot Stats */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <StatTile
          label="Provisioned Tier"
          value={tenant.plan || 'Community'}
          icon={Calendar}
          color="bg-violet-600 text-white"
        />
        <StatTile
          label="Compute Nodes"
          value={tenant.agent_count || 0}
          icon={Bot}
          color="bg-blue-500 text-white"
        />
        <StatTile
          label="Identified Users"
          value={tenant.user_count || 0}
          icon={Users}
          color="bg-emerald-500 text-white"
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
          {/* Metadata Registry */}
          <div className="lg:col-span-2">
              <div className="bg-white dark:bg-gray-900 border border-gray-100 dark:border-gray-800 rounded-3xl shadow-sm overflow-hidden">
                <div className="px-8 py-6 border-b border-gray-50 dark:border-gray-800 bg-gray-50/30 dark:bg-gray-800/20">
                  <h2 className="text-sm font-black text-gray-900 dark:text-white uppercase tracking-widest flex items-center gap-2">
                     <Cpu size={16} /> Configuration Registry
                  </h2>
                </div>
                <div className="divide-y divide-gray-50 dark:divide-gray-800">
                  {[
                    { label: 'Lifecycle State', value: tenant.status, color: tenant.status === 'active' ? 'text-emerald-500' : 'text-red-500' },
                    { label: 'Platform Identifier', value: tenant.id, mono: true },
                    { label: 'Human Readable Slug', value: tenant.name, mono: true },
                    { label: 'Deployment Timestamp', value: new Date(tenant.created_at).toLocaleString() },
                    { label: 'Last State Mutation', value: new Date(tenant.updated_at).toLocaleString() },
                  ].map((row, i) => (
                    <div key={i} className="flex flex-col sm:flex-row sm:items-center justify-between px-8 py-5 group hover:bg-gray-50 dark:hover:bg-violet-900/5 transition-colors">
                      <span className="text-xs font-bold text-gray-400 dark:text-gray-500 uppercase tracking-widest">{row.label}</span>
                      <span className={`text-[13px] font-bold mt-1 sm:mt-0 ${row.color || 'text-gray-900 dark:text-white'} ${row.mono ? 'font-mono uppercase tracking-tighter' : ''}`}>
                        {row.value}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
          </div>

          {/* Activity Placeholder */}
          <div>
              <div className="bg-white dark:bg-gray-900 border border-gray-100 dark:border-gray-800 rounded-3xl p-8 shadow-sm">
                  <div className="flex items-center gap-3 mb-6 font-black text-gray-900 dark:text-white text-sm uppercase tracking-widest">
                     <Activity size={18} className="text-violet-500" /> System Pulse
                  </div>
                  <div className="space-y-6">
                      <div className="flex items-center gap-4">
                         <div className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse"></div>
                         <p className="text-xs text-gray-500 font-bold uppercase tracking-tight">Orchestrator Heartbeat: NOMINAL</p>
                      </div>
                      <div className="p-6 bg-gray-50 dark:bg-gray-800/50 rounded-2xl border-2 border-dashed border-gray-100 dark:border-gray-800 text-center">
                          <p className="text-[10px] font-bold text-gray-400 uppercase tracking-widest leading-relaxed">
                             Detailed activity monitoring for isolated instances is currently being streamed to the primary data lake.
                          </p>
                      </div>
                  </div>
              </div>
          </div>
      </div>
    </div>
  )
}