'use client'

import { useEffect, useState, useCallback } from 'react'
import {
  ClipboardList,
  Search,
  Filter,
  RefreshCw,
  ChevronLeft,
  ChevronRight,
  ShieldCheck,
  ShieldAlert,
  LogIn,
  LogOut,
  UserCog,
  Trash2,
  Settings,
  Download,
  AlertCircle,
  CheckCircle2,
} from 'lucide-react'

interface AuditLogEntry {
  id: string
  tenant_id: string | null
  actor_user_id: string | null
  actor_email: string | null
  actor_role: string | null
  action: string
  category: string
  resource_type: string | null
  resource_id: string | null
  status: 'success' | 'failure'
  details: Record<string, unknown> | null
  ip_address: string | null
  user_agent: string | null
  created_at: string
}

interface AuditLogPage {
  items: AuditLogEntry[]
  total: number
  page: number
  per_page: number
  pages: number
}

const CATEGORY_OPTIONS = [
  { value: '', label: 'All Categories' },
  { value: 'auth', label: 'Authentication' },
  { value: 'user', label: 'User Management' },
  { value: 'tenant', label: 'Tenant' },
  { value: 'agent', label: 'Agent' },
  { value: 'billing', label: 'Billing' },
  { value: 'admin', label: 'Admin Actions' },
  { value: 'data', label: 'Data Operations' },
  { value: 'api_key', label: 'API Keys' },
]

const STATUS_OPTIONS = [
  { value: '', label: 'All Statuses' },
  { value: 'success', label: 'Success' },
  { value: 'failure', label: 'Failure' },
]

function ActionIcon({ action, category }: { action: string; category: string }) {
  if (action.includes('login')) return <LogIn className="w-4 h-4" />
  if (action.includes('logout')) return <LogOut className="w-4 h-4" />
  if (action.includes('delete') || action.includes('deleted')) return <Trash2 className="w-4 h-4" />
  if (action.includes('role') || action.includes('user')) return <UserCog className="w-4 h-4" />
  if (category === 'admin') return <Settings className="w-4 h-4" />
  if (category === 'auth') return <ShieldCheck className="w-4 h-4" />
  return <ClipboardList className="w-4 h-4" />
}

function CategoryBadge({ category }: { category: string }) {
  const colors: Record<string, string> = {
    auth: 'bg-blue-100 text-blue-800',
    user: 'bg-purple-100 text-purple-800',
    tenant: 'bg-yellow-100 text-yellow-800',
    agent: 'bg-green-100 text-green-800',
    billing: 'bg-orange-100 text-orange-800',
    admin: 'bg-red-100 text-red-800',
    data: 'bg-gray-100 text-gray-800',
    api_key: 'bg-indigo-100 text-indigo-800',
  }
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${colors[category] ?? 'bg-gray-100 text-gray-700'}`}>
      {category}
    </span>
  )
}

export default function AuditLogsPage() {
  const [data, setData] = useState<AuditLogPage | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Filters
  const [page, setPage] = useState(1)
  const [category, setCategory] = useState('')
  const [status, setStatus] = useState('')
  const [search, setSearch] = useState('')
  const [debouncedSearch, setDebouncedSearch] = useState('')
  const [since, setSince] = useState('')
  const [until, setUntil] = useState('')
  const [expandedId, setExpandedId] = useState<string | null>(null)

  // Debounce search
  useEffect(() => {
    const t = setTimeout(() => setDebouncedSearch(search), 400)
    return () => clearTimeout(t)
  }, [search])

  const fetchLogs = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const params = new URLSearchParams({
        page: String(page),
        per_page: '50',
        ...(category && { category }),
        ...(status && { status }),
        ...(debouncedSearch && { action: debouncedSearch }),
        ...(since && { since }),
        ...(until && { until }),
      })
      const res = await fetch(`/api/v1/admin/audit-logs?${params}`, {
        credentials: 'include',
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      setData(await res.json())
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load audit logs')
    } finally {
      setLoading(false)
    }
  }, [page, category, status, debouncedSearch, since, until])

  useEffect(() => { fetchLogs() }, [fetchLogs])

  // Reset page when filters change
  useEffect(() => { setPage(1) }, [category, status, debouncedSearch, since, until])

  const exportCsv = () => {
    if (!data) return
    const headers = ['Time', 'Actor', 'Role', 'Action', 'Category', 'Resource', 'Status', 'IP']
    const rows = data.items.map(r => [
      r.created_at,
      r.actor_email ?? r.actor_user_id ?? 'system',
      r.actor_role ?? '',
      r.action,
      r.category,
      r.resource_id ? `${r.resource_type}/${r.resource_id}` : r.resource_type ?? '',
      r.status,
      r.ip_address ?? '',
    ])
    const csv = [headers, ...rows].map(row => row.map(c => `"${c}"`).join(',')).join('\n')
    const blob = new Blob([csv], { type: 'text/csv' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `audit-logs-${new Date().toISOString().split('T')[0]}.csv`
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <ClipboardList className="w-7 h-7 text-indigo-600" />
          <div>
            <h1 className="text-2xl font-bold text-gray-900">Audit Logs</h1>
            <p className="text-sm text-gray-500">SOC2 · GDPR · HIPAA compliance event trail</p>
          </div>
        </div>
        <div className="flex gap-2">
          <button
            onClick={exportCsv}
            disabled={!data || data.items.length === 0}
            className="flex items-center gap-2 px-3 py-2 text-sm border border-gray-300 rounded-lg hover:bg-gray-50 disabled:opacity-40"
          >
            <Download className="w-4 h-4" />
            Export CSV
          </button>
          <button
            onClick={fetchLogs}
            className="flex items-center gap-2 px-3 py-2 text-sm bg-indigo-600 text-white rounded-lg hover:bg-indigo-700"
          >
            <RefreshCw className="w-4 h-4" />
            Refresh
          </button>
        </div>
      </div>

      {/* Compliance notice */}
      <div className="bg-blue-50 border border-blue-200 rounded-lg p-4 flex gap-3">
        <ShieldAlert className="w-5 h-5 text-blue-600 flex-shrink-0 mt-0.5" />
        <div className="text-sm text-blue-800">
          <strong>Compliance requirement:</strong> Audit logs are required by SOC2 CC6.1/CC7.2,
          GDPR Article 30, HIPAA §164.312(b), and PCI-DSS 10.2. Logs are retained for 90 days
          minimum. Export regularly and archive to cold storage for long-term compliance.
        </div>
      </div>

      {/* Filters */}
      <div className="bg-white border border-gray-200 rounded-xl p-4 space-y-3">
        <div className="flex items-center gap-2 text-sm font-medium text-gray-700">
          <Filter className="w-4 h-4" />
          Filters
        </div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
            <input
              type="text"
              placeholder="Search action..."
              value={search}
              onChange={e => setSearch(e.target.value)}
              className="w-full pl-9 pr-3 py-2 text-sm border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500"
            />
          </div>
          <select
            value={category}
            onChange={e => setCategory(e.target.value)}
            className="text-sm border border-gray-300 rounded-lg px-3 py-2 focus:ring-2 focus:ring-indigo-500"
          >
            {CATEGORY_OPTIONS.map(o => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
          <select
            value={status}
            onChange={e => setStatus(e.target.value)}
            className="text-sm border border-gray-300 rounded-lg px-3 py-2 focus:ring-2 focus:ring-indigo-500"
          >
            {STATUS_OPTIONS.map(o => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
          <div className="flex gap-2">
            <input
              type="datetime-local"
              value={since}
              onChange={e => setSince(e.target.value)}
              title="From date"
              className="flex-1 text-sm border border-gray-300 rounded-lg px-2 py-2 focus:ring-2 focus:ring-indigo-500"
            />
            <input
              type="datetime-local"
              value={until}
              onChange={e => setUntil(e.target.value)}
              title="To date"
              className="flex-1 text-sm border border-gray-300 rounded-lg px-2 py-2 focus:ring-2 focus:ring-indigo-500"
            />
          </div>
        </div>
        {data && (
          <p className="text-xs text-gray-500">
            {data.total.toLocaleString()} total events · page {data.page} of {data.pages}
          </p>
        )}
      </div>

      {/* Log table */}
      <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
        {error && (
          <div className="flex items-center gap-2 p-4 text-red-700 bg-red-50 border-b border-red-200">
            <AlertCircle className="w-4 h-4" />
            {error}
          </div>
        )}
        {loading ? (
          <div className="flex items-center justify-center h-40 text-gray-500 text-sm">Loading...</div>
        ) : !data || data.items.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-40 text-gray-400">
            <ClipboardList className="w-8 h-8 mb-2" />
            <p className="text-sm">No audit events found</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 border-b border-gray-200">
                <tr>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Time</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Actor</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Action</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Category</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Resource</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Status</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">IP</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {data.items.map(row => (
                  <>
                    <tr
                      key={row.id}
                      className="hover:bg-gray-50 cursor-pointer"
                      onClick={() => setExpandedId(expandedId === row.id ? null : row.id)}
                    >
                      <td className="px-4 py-3 text-xs text-gray-500 whitespace-nowrap font-mono">
                        {new Date(row.created_at).toLocaleString()}
                      </td>
                      <td className="px-4 py-3">
                        <div className="font-medium text-gray-900 truncate max-w-[150px]">
                          {row.actor_email ?? 'system'}
                        </div>
                        {row.actor_role && (
                          <div className="text-xs text-gray-400">{row.actor_role}</div>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2">
                          <ActionIcon action={row.action} category={row.category} />
                          <span className="font-mono text-xs text-gray-700">{row.action}</span>
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        <CategoryBadge category={row.category} />
                      </td>
                      <td className="px-4 py-3 text-xs text-gray-500 font-mono">
                        {row.resource_id
                          ? `${row.resource_type ?? ''}/${row.resource_id.slice(0, 8)}…`
                          : row.resource_type ?? '—'}
                      </td>
                      <td className="px-4 py-3">
                        {row.status === 'success' ? (
                          <span className="flex items-center gap-1 text-green-700">
                            <CheckCircle2 className="w-3.5 h-3.5" />
                            <span className="text-xs">success</span>
                          </span>
                        ) : (
                          <span className="flex items-center gap-1 text-red-700">
                            <AlertCircle className="w-3.5 h-3.5" />
                            <span className="text-xs">failure</span>
                          </span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-xs text-gray-400 font-mono">
                        {row.ip_address ?? '—'}
                      </td>
                    </tr>
                    {expandedId === row.id && (
                      <tr key={`${row.id}-detail`} className="bg-gray-50">
                        <td colSpan={7} className="px-4 py-3">
                          <div className="text-xs space-y-1">
                            <div><span className="font-medium text-gray-600">Event ID:</span> <span className="font-mono text-gray-800">{row.id}</span></div>
                            {row.tenant_id && <div><span className="font-medium text-gray-600">Tenant:</span> <span className="font-mono text-gray-800">{row.tenant_id}</span></div>}
                            {row.actor_user_id && <div><span className="font-medium text-gray-600">User ID:</span> <span className="font-mono text-gray-800">{row.actor_user_id}</span></div>}
                            {row.user_agent && <div><span className="font-medium text-gray-600">User Agent:</span> <span className="text-gray-700">{row.user_agent.slice(0, 120)}</span></div>}
                            {row.details && (
                              <div>
                                <span className="font-medium text-gray-600">Details:</span>
                                <pre className="mt-1 bg-white border border-gray-200 rounded p-2 overflow-x-auto text-gray-800">
                                  {JSON.stringify(row.details, null, 2)}
                                </pre>
                              </div>
                            )}
                          </div>
                        </td>
                      </tr>
                    )}
                  </>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Pagination */}
      {data && data.pages > 1 && (
        <div className="flex items-center justify-between">
          <button
            onClick={() => setPage(p => Math.max(1, p - 1))}
            disabled={page === 1}
            className="flex items-center gap-1 px-3 py-2 text-sm border border-gray-300 rounded-lg hover:bg-gray-50 disabled:opacity-40"
          >
            <ChevronLeft className="w-4 h-4" />
            Previous
          </button>
          <span className="text-sm text-gray-500">
            Page {data.page} of {data.pages}
          </span>
          <button
            onClick={() => setPage(p => Math.min(data.pages, p + 1))}
            disabled={page === data.pages}
            className="flex items-center gap-1 px-3 py-2 text-sm border border-gray-300 rounded-lg hover:bg-gray-50 disabled:opacity-40"
          >
            Next
            <ChevronRight className="w-4 h-4" />
          </button>
        </div>
      )}
    </div>
  )
}
