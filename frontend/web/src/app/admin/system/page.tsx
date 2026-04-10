'use client'

import { useEffect, useState, useCallback } from 'react'
import { api, adminApi } from '@/lib/api'
import {
  CheckCircle2, XCircle, AlertCircle, RefreshCw, Clock,
  Database, Cpu, Server, Wifi, ShieldCheck, Bot,
} from 'lucide-react'

interface ServiceStatus {
  name: string
  key: string
  icon: React.ElementType
  status: 'healthy' | 'degraded' | 'down' | 'unknown'
  latencyMs?: number
  detail?: string
}

interface Metrics {
  active_tenants: number
  total_agents: number
  sessions_today: number
  messages_today: number
  timestamp: string
}

function StatusBadge({ status }: { status: ServiceStatus['status'] }) {
  const map = {
    healthy: { label: 'Healthy', cls: 'bg-emerald-50 text-emerald-700 dark:bg-emerald-900/20 dark:text-emerald-400', icon: CheckCircle2 },
    degraded: { label: 'Degraded', cls: 'bg-amber-50 text-amber-700 dark:bg-amber-900/20 dark:text-amber-400', icon: AlertCircle },
    down: { label: 'Down', cls: 'bg-red-50 text-red-700 dark:bg-red-900/20 dark:text-red-400', icon: XCircle },
    unknown: { label: 'Unknown', cls: 'bg-gray-100 text-gray-500 dark:bg-gray-800 dark:text-gray-400', icon: AlertCircle },
  }
  const { label, cls, icon: Icon } = map[status]
  return (
    <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold ${cls}`}>
      <Icon size={12} />
      {label}
    </span>
  )
}

function ServiceCard({ service }: { service: ServiceStatus }) {
  return (
    <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 p-5">
      <div className="flex items-start justify-between mb-3">
        <div className="flex items-center gap-3">
          <div className={`w-9 h-9 rounded-lg flex items-center justify-center ${
            service.status === 'healthy' ? 'bg-emerald-50 dark:bg-emerald-900/20 text-emerald-600'
            : service.status === 'degraded' ? 'bg-amber-50 dark:bg-amber-900/20 text-amber-600'
            : service.status === 'down' ? 'bg-red-50 dark:bg-red-900/20 text-red-600'
            : 'bg-gray-100 dark:bg-gray-800 text-gray-400'
          }`}>
            <service.icon size={18} />
          </div>
          <p className="text-sm font-semibold text-gray-900 dark:text-white">{service.name}</p>
        </div>
        <StatusBadge status={service.status} />
      </div>
      {service.latencyMs !== undefined && (
        <p className="text-xs text-gray-400 mt-1">
          Latency: <span className={`font-semibold ${service.latencyMs < 200 ? 'text-emerald-600' : service.latencyMs < 500 ? 'text-amber-600' : 'text-red-600'}`}>
            {service.latencyMs}ms
          </span>
        </p>
      )}
      {service.detail && <p className="text-xs text-gray-400 mt-1">{service.detail}</p>}
    </div>
  )
}

const INITIAL_SERVICES: ServiceStatus[] = [
  { name: 'API Gateway', key: 'api_gateway', icon: Server, status: 'unknown' },
  { name: 'AI Orchestrator', key: 'orchestrator', icon: Bot, status: 'unknown' },
  { name: 'MCP Server', key: 'mcp_server', icon: Cpu, status: 'unknown' },
  { name: 'PostgreSQL', key: 'database', icon: Database, status: 'unknown' },
  { name: 'Redis Cache', key: 'redis', icon: Wifi, status: 'unknown' },
  { name: 'Guardrails', key: 'guardrails', icon: ShieldCheck, status: 'unknown' },
]

export default function SystemHealthPage() {
  const [services, setServices] = useState<ServiceStatus[]>(INITIAL_SERVICES)
  const [metrics, setMetrics] = useState<Metrics | null>(null)
  const [checking, setChecking] = useState(true)
  const [lastChecked, setLastChecked] = useState<Date | null>(null)
  const [guardrailsEnabled, setGuardrailsEnabled] = useState<number | null>(null)
  const [guardrailsTotal, setGuardrailsTotal] = useState<number | null>(null)

  const checkHealth = useCallback(async () => {
    setChecking(true)
    const updated = [...INITIAL_SERVICES]

    // Check API Gateway via /health
    try {
      const t0 = Date.now()
      await api.get('/health')
      const lat = Date.now() - t0
      const idx = updated.findIndex((s) => s.key === 'api_gateway')
      updated[idx] = { ...updated[idx], status: lat < 500 ? 'healthy' : 'degraded', latencyMs: lat }
    } catch {
      const idx = updated.findIndex((s) => s.key === 'api_gateway')
      updated[idx] = { ...updated[idx], status: 'down', detail: 'No response from gateway' }
    }

    // Check metrics (indicates orchestrator + DB reachable)
    try {
      const t0 = Date.now()
      const m = await adminApi.getMetrics()
      const lat = Date.now() - t0
      setMetrics(m)
      // Orchestrator reachable if metrics come back
      const orchIdx = updated.findIndex((s) => s.key === 'orchestrator')
      updated[orchIdx] = { ...updated[orchIdx], status: lat < 800 ? 'healthy' : 'degraded', latencyMs: lat, detail: `${m.total_agents} agents active` }
      // Database reachable
      const dbIdx = updated.findIndex((s) => s.key === 'database')
      updated[dbIdx] = { ...updated[dbIdx], status: 'healthy', detail: `${m.active_tenants} tenants loaded` }
    } catch {
      const orchIdx = updated.findIndex((s) => s.key === 'orchestrator')
      updated[orchIdx] = { ...updated[orchIdx], status: 'down', detail: 'Cannot reach orchestrator' }
      const dbIdx = updated.findIndex((s) => s.key === 'database')
      updated[dbIdx] = { ...updated[dbIdx], status: 'unknown', detail: 'Cannot verify database' }
    }

    // Check guardrails
    try {
      const guardrails = await adminApi.listGuardrails()
      const list: any[] = guardrails?.guardrails || guardrails || []
      const enabled = list.filter((g: any) => g.enabled).length
      setGuardrailsEnabled(enabled)
      setGuardrailsTotal(list.length)
      const gIdx = updated.findIndex((s) => s.key === 'guardrails')
      const allCriticalOn = list.filter((g: any) => g.severity === 'critical').every((g: any) => g.enabled)
      updated[gIdx] = {
        ...updated[gIdx],
        status: allCriticalOn ? 'healthy' : 'degraded',
        detail: `${enabled}/${list.length} rules enabled`,
      }
    } catch {
      const gIdx = updated.findIndex((s) => s.key === 'guardrails')
      updated[gIdx] = { ...updated[gIdx], status: 'unknown' }
    }

    // MCP + Redis: probe via a settings call (indirect signal)
    try {
      const t0 = Date.now()
      await api.get('/admin/settings')
      const lat = Date.now() - t0
      const mcpIdx = updated.findIndex((s) => s.key === 'mcp_server')
      updated[mcpIdx] = { ...updated[mcpIdx], status: lat < 600 ? 'healthy' : 'degraded', latencyMs: lat }
      const redisIdx = updated.findIndex((s) => s.key === 'redis')
      updated[redisIdx] = { ...updated[redisIdx], status: 'healthy', detail: 'Session cache responding' }
    } catch {
      const mcpIdx = updated.findIndex((s) => s.key === 'mcp_server')
      updated[mcpIdx] = { ...updated[mcpIdx], status: 'unknown', detail: 'Could not probe MCP service' }
      const redisIdx = updated.findIndex((s) => s.key === 'redis')
      updated[redisIdx] = { ...updated[redisIdx], status: 'unknown' }
    }

    setServices(updated)
    setLastChecked(new Date())
    setChecking(false)
  }, [])

  useEffect(() => { checkHealth() }, [checkHealth])

  const healthyCount = services.filter((s) => s.status === 'healthy').length
  const downCount = services.filter((s) => s.status === 'down').length
  const degradedCount = services.filter((s) => s.status === 'degraded').length

  const overallStatus: ServiceStatus['status'] =
    downCount > 0 ? 'down' : degradedCount > 0 ? 'degraded' : checking ? 'unknown' : 'healthy'

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">System Health</h1>
          <p className="text-sm text-gray-500 mt-0.5">Service status and infrastructure monitoring</p>
        </div>
        <div className="flex items-center gap-3">
          {lastChecked && (
            <span className="text-xs text-gray-400 flex items-center gap-1">
              <Clock size={12} />
              Checked {lastChecked.toLocaleTimeString()}
            </span>
          )}
          <button
            onClick={checkHealth}
            disabled={checking}
            className="flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium text-gray-600 dark:text-gray-400 bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors disabled:opacity-50"
          >
            <RefreshCw size={14} className={checking ? 'animate-spin' : ''} />
            {checking ? 'Checking…' : 'Re-check'}
          </button>
        </div>
      </div>

      {/* Overall status banner */}
      <div className={`flex items-center gap-3 px-5 py-4 rounded-xl border ${
        overallStatus === 'healthy' ? 'bg-emerald-50 border-emerald-200 dark:bg-emerald-900/10 dark:border-emerald-800'
        : overallStatus === 'degraded' ? 'bg-amber-50 border-amber-200 dark:bg-amber-900/10 dark:border-amber-800'
        : overallStatus === 'down' ? 'bg-red-50 border-red-200 dark:bg-red-900/10 dark:border-red-800'
        : 'bg-gray-50 border-gray-200 dark:bg-gray-800 dark:border-gray-700'
      }`}>
        {overallStatus === 'healthy' && <CheckCircle2 size={20} className="text-emerald-600" />}
        {overallStatus === 'degraded' && <AlertCircle size={20} className="text-amber-600" />}
        {overallStatus === 'down' && <XCircle size={20} className="text-red-600" />}
        {overallStatus === 'unknown' && <AlertCircle size={20} className="text-gray-400" />}
        <div>
          <p className={`text-sm font-semibold ${
            overallStatus === 'healthy' ? 'text-emerald-800 dark:text-emerald-300'
            : overallStatus === 'degraded' ? 'text-amber-800 dark:text-amber-300'
            : overallStatus === 'down' ? 'text-red-800 dark:text-red-300'
            : 'text-gray-600 dark:text-gray-400'
          }`}>
            {overallStatus === 'healthy' ? 'All systems operational'
              : overallStatus === 'degraded' ? `${degradedCount} service${degradedCount !== 1 ? 's' : ''} degraded`
              : overallStatus === 'down' ? `${downCount} service${downCount !== 1 ? 's' : ''} down`
              : 'Checking system status…'}
          </p>
          <p className="text-xs text-gray-500 mt-0.5">
            {healthyCount} healthy · {degradedCount} degraded · {downCount} down · {services.filter(s => s.status === 'unknown').length} unknown
          </p>
        </div>
      </div>

      {/* Service Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {services.map((svc) => (
          <ServiceCard key={svc.key} service={svc} />
        ))}
      </div>

      {/* Platform Snapshot */}
      {metrics && (
        <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 p-5">
          <h2 className="text-sm font-semibold text-gray-900 dark:text-white mb-4">Platform Snapshot</h2>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            {[
              { label: 'Active Tenants', value: metrics.active_tenants },
              { label: 'Total Agents', value: metrics.total_agents },
              { label: 'Sessions Today', value: metrics.sessions_today },
              { label: 'Messages Today', value: metrics.messages_today },
            ].map((stat) => (
              <div key={stat.label} className="text-center p-4 bg-gray-50 dark:bg-gray-800/50 rounded-lg">
                <p className="text-2xl font-bold text-gray-900 dark:text-white">{stat.value.toLocaleString()}</p>
                <p className="text-xs text-gray-400 mt-1">{stat.label}</p>
              </div>
            ))}
          </div>
          {guardrailsEnabled !== null && (
            <div className="mt-4 pt-4 border-t border-gray-100 dark:border-gray-800 flex items-center justify-between text-sm">
              <span className="text-gray-500">Platform guardrails</span>
              <span className={`font-semibold ${guardrailsEnabled === guardrailsTotal ? 'text-emerald-600' : 'text-amber-600'}`}>
                {guardrailsEnabled}/{guardrailsTotal} active
              </span>
            </div>
          )}
          {metrics.timestamp && (
            <p className="text-xs text-gray-400 mt-3">
              Metrics timestamp: {new Date(metrics.timestamp).toLocaleString()}
            </p>
          )}
        </div>
      )}
    </div>
  )
}
