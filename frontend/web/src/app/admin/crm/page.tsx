'use client'

import { useState, useEffect } from 'react'
import { adminCrmApi } from '@/lib/api'
import { CheckCircle2, XCircle, Database, Server, RefreshCw, Activity, AlertTriangle } from 'lucide-react'

export default function AdminCrmPage() {
  const [health, setHealth] = useState<any>(null)
  const [workspaces, setWorkspaces] = useState<any[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [repairingId, setRepairingId] = useState<string | null>(null)

  useEffect(() => {
    fetchData()
  }, [])

  const fetchData = async () => {
    setIsLoading(true)
    try {
      const [h, w] = await Promise.all([
        adminCrmApi.getHealth().catch((e) => e.response?.data || { database: 'error', redis_sso: 'error' }),
        adminCrmApi.getWorkspaces().catch(() => [])
      ])
      setHealth(h)
      setWorkspaces(w)
    } finally {
      setIsLoading(false)
    }
  }

  const handleRepair = async (id: string) => {
    setRepairingId(id)
    try {
      const res = await adminCrmApi.repairWorkspace(id)
      alert(`Repair status: ${res.status}\n\nLogs:\n${res.log.join('\n')}`)
      fetchData()
    } catch (e: any) {
      alert(`Repair failed: ${e.message}`)
    } finally {
      setRepairingId(null)
    }
  }

  if (isLoading && !health) {
    return (
      <div className="p-8 flex justify-center items-center h-full">
        <div className="animate-spin rounded-full h-8 w-8 border-t-2 border-b-2 border-violet-500"></div>
      </div>
    )
  }

  return (
    <div className="p-8 max-w-7xl mx-auto space-y-8">
      <div>
        <h1 className="text-2xl font-bold text-gray-900 dark:text-white flex items-center gap-2">
          <Database className="text-violet-500" />
          CRM Platform Management
        </h1>
        <p className="text-sm text-gray-500 mt-1">
          Monitor and manage Twenty CRM workspaces globally across all tenants.
        </p>
      </div>

      {/* System Health */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="bg-white dark:bg-gray-900 p-6 rounded-xl border border-gray-200 dark:border-gray-800 shadow-sm flex items-start justify-between">
          <div>
            <div className="flex items-center gap-2 mb-2">
              <Database size={18} className="text-gray-400" />
              <h3 className="font-semibold text-gray-900 dark:text-white">Twenty Database</h3>
            </div>
            <p className="text-sm text-gray-500">PostgreSQL core schema availability</p>
          </div>
          {health?.database === 'healthy' ? (
            <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md bg-emerald-50 text-emerald-600 dark:bg-emerald-500/10 dark:text-emerald-400 text-xs font-medium">
              <CheckCircle2 size={14} /> Healthy
            </span>
          ) : (
            <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md bg-red-50 text-red-600 dark:bg-red-500/10 dark:text-red-400 text-xs font-medium">
              <XCircle size={14} /> Degraded
            </span>
          )}
        </div>

        <div className="bg-white dark:bg-gray-900 p-6 rounded-xl border border-gray-200 dark:border-gray-800 shadow-sm flex items-start justify-between">
          <div>
            <div className="flex items-center gap-2 mb-2">
              <Server size={18} className="text-gray-400" />
              <h3 className="font-semibold text-gray-900 dark:text-white">SSO Redis</h3>
            </div>
            <p className="text-sm text-gray-500">Twenty Redis session store availability</p>
          </div>
          {health?.redis_sso === 'healthy' ? (
            <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md bg-emerald-50 text-emerald-600 dark:bg-emerald-500/10 dark:text-emerald-400 text-xs font-medium">
              <CheckCircle2 size={14} /> Healthy
            </span>
          ) : (
            <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md bg-red-50 text-red-600 dark:bg-red-500/10 dark:text-red-400 text-xs font-medium">
              <XCircle size={14} /> Offline
            </span>
          )}
        </div>
      </div>

      {/* Workspaces Table */}
      <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 shadow-sm overflow-hidden">
        <div className="px-6 py-4 border-b border-gray-200 dark:border-gray-800 flex items-center justify-between">
          <h2 className="font-semibold text-gray-900 dark:text-white flex items-center gap-2">
            <Activity size={18} className="text-violet-500" />
            Provisioned Workspaces
          </h2>
          <button
            onClick={fetchData}
            disabled={isLoading}
            className="p-2 rounded-lg text-gray-400 hover:text-gray-900 dark:hover:text-white hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
          >
            <RefreshCw size={18} className={isLoading ? 'animate-spin' : ''} />
          </button>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm whitespace-nowrap">
            <thead className="bg-gray-50 dark:bg-gray-800/50 text-gray-500 dark:text-gray-400">
              <tr>
                <th className="px-6 py-3 font-medium">Tenant</th>
                <th className="px-6 py-3 font-medium">Custom Subdomain</th>
                <th className="px-6 py-3 font-medium">Active Seats</th>
                <th className="px-6 py-3 font-medium">Status</th>
                <th className="px-6 py-3 font-medium text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
              {workspaces.map((w) => (
                <tr key={w.id} className="hover:bg-gray-50/50 dark:hover:bg-gray-800/20 transition-colors">
                  <td className="px-6 py-4">
                    <div className="font-medium text-gray-900 dark:text-white">{w.tenant_name}</div>
                    <div className="text-xs text-gray-500 truncate max-w-[150px]">{w.tenant_id}</div>
                  </td>
                  <td className="px-6 py-4">
                    {w.custom_subdomain ? (
                      <span className="text-blue-500 hover:underline cursor-pointer">
                        {w.custom_subdomain}.ascenai.com
                      </span>
                    ) : (
                      <span className="text-gray-400 italic">None</span>
                    )}
                  </td>
                  <td className="px-6 py-4">
                    <div className="flex items-center gap-2">
                      <span className={`font-medium ${w.active_users > w.allowed_seats ? 'text-red-500' : 'text-gray-900 dark:text-white'}`}>
                        {w.active_users}
                      </span>
                      <span className="text-gray-400">/ {w.allowed_seats}</span>
                      {w.active_users > w.allowed_seats && (
                        <AlertTriangle size={14} className="text-amber-500" title="Over seat limit" />
                      )}
                    </div>
                  </td>
                  <td className="px-6 py-4">
                    {w.is_active ? (
                      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-emerald-50 text-emerald-600 dark:bg-emerald-500/10 dark:text-emerald-400 text-xs font-medium">
                        Active
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400 text-xs font-medium">
                        Inactive
                      </span>
                    )}
                  </td>
                  <td className="px-6 py-4 text-right">
                    <button
                      onClick={() => handleRepair(w.id)}
                      disabled={repairingId === w.id}
                      className="text-xs font-medium px-3 py-1.5 rounded-lg border border-gray-200 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-800 text-gray-700 dark:text-gray-300 transition-colors"
                    >
                      {repairingId === w.id ? 'Repairing...' : 'Repair Mapping'}
                    </button>
                  </td>
                </tr>
              ))}
              {workspaces.length === 0 && (
                <tr>
                  <td colSpan={5} className="px-6 py-8 text-center text-gray-500">
                    No CRM workspaces found.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
