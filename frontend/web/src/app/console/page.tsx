'use client'

import { useEffect, useState, useCallback, useRef } from 'react'
import { useRouter } from 'next/navigation'
import { useAuthStore } from '@/store/auth'
import {
  Terminal,
  ClipboardList,
  Activity,
  RefreshCw,
  Search,
  Filter,
  ChevronLeft,
  ChevronRight,
  AlertCircle,
  CheckCircle2,
  Clock,
  Bot,
  MessageSquare,
  ShieldAlert,
  LogIn,
  LogOut,
  Key,
  UserCog,
  Trash2,
  X,
  Download,
  Play,
  Pause,
  Shield,
} from 'lucide-react'


// ─── Types ──────────────────────────────────────────────────────────────────

interface AuditEntry {
  id: string
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

interface Session {
  id: string
  agent_id: string
  agent_name?: string
  channel: string
  status: string
  turn_count: number
  customer_identifier?: string
  created_at: string
  last_activity_at?: string
}

// ─── Helpers ────────────────────────────────────────────────────────────────

const CATEGORY_COLORS: Record<string, string> = {
  auth: 'text-blue-500',
  user: 'text-purple-500',
  tenant: 'text-yellow-500',
  agent: 'text-green-500',
  billing: 'text-orange-500',
  admin: 'text-red-500',
  data: 'text-gray-500',
  api_key: 'text-indigo-500',
  general: 'text-gray-400',
}

function ActionIcon({ action, category }: { action: string; category: string }) {
  const cls = `w-3.5 h-3.5 ${CATEGORY_COLORS[category] ?? 'text-gray-400'}`
  if (action.includes('login')) return <LogIn className={cls} />
  if (action.includes('logout')) return <LogOut className={cls} />
  if (action.includes('delete')) return <Trash2 className={cls} />
  if (action.includes('role')) return <UserCog className={cls} />
  if (action.includes('api_key')) return <Key className={cls} />
  if (category === 'auth') return <ShieldAlert className={cls} />
  return <Activity className={cls} />
}

function ts(iso: string) {
  return new Date(iso).toLocaleString(undefined, {
    month: 'short', day: 'numeric',
    hour: '2-digit', minute: '2-digit', second: '2-digit',
  })
}

// ─── Main component ──────────────────────────────────────────────────────────

export default function ConsolePage() {
  const { isAuthenticated, _hasHydrated } = useAuthStore()
  const router = useRouter()

  // Redirect if not authenticated
  useEffect(() => {
    if (_hasHydrated && !isAuthenticated) {
      router.replace('/login')
    }
  }, [_hasHydrated, isAuthenticated, router])

  const [tab, setTab] = useState<'audit' | 'sessions'>('audit')

  // ── Audit log state ────────────────────────────────────────────────────────
  const [auditData, setAuditData] = useState<{ items: AuditEntry[]; total: number; pages: number } | null>(null)
  const [auditPage, setAuditPage] = useState(1)
  const [auditCategory, setAuditCategory] = useState('')
  const [auditStatus, setAuditStatus] = useState('')
  const [auditSince, setAuditSince] = useState('')
  const [auditUntil, setAuditUntil] = useState('')
  const [auditSearch, setAuditSearch] = useState('')

  const [auditDebounced, setAuditDebounced] = useState('')
  const [expandedId, setExpandedId] = useState<string | null>(null)

  // ── Session state ──────────────────────────────────────────────────────────
  const [activityData, setActivityData] = useState<{ sessions: { sessions: Session[]; total: number }; recent_events: AuditEntry[] } | null>(null)
  const [agentFilter, setAgentFilter] = useState('')
  const [agents, setAgents] = useState<{ id: string; name: string }[]>([])

  // ── Shared state ───────────────────────────────────────────────────────────
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [autoRefresh, setAutoRefresh] = useState(false)
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // Debounce audit search
  useEffect(() => {
    const t = setTimeout(() => setAuditDebounced(auditSearch), 400)
    return () => clearTimeout(t)
  }, [auditSearch])

  // Reset page on filter change
  useEffect(() => { setAuditPage(1) }, [auditCategory, auditStatus, auditDebounced])

  // Load agents for filter
  useEffect(() => {
    fetch('/api/v1/console/agents', { credentials: 'include' })
      .then(r => r.ok ? r.json() : { agents: [] })
      .then(d => setAgents(d.agents ?? []))
      .catch(() => {})
  }, [])

  const fetchAudit = useCallback(async (isSilent = false) => {
    setLoading(!isSilent)
    setError(null)
    try {
      const p = new URLSearchParams({
        page: String(auditPage),
        per_page: '50',
        silent: String(isSilent),
        ...(auditCategory && { category: auditCategory }),
        ...(auditStatus && { status: auditStatus }),
        ...(auditDebounced && { action: auditDebounced }),
        ...(auditSince && { since: new Date(auditSince).toISOString() }),
        ...(auditUntil && { until: new Date(auditUntil).toISOString() }),
      })

      const res = await fetch(`/api/v1/console/audit-logs?${p}`, { credentials: 'include' })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      setAuditData(await res.json())
    } catch (e) {
      if (!isSilent) setError(e instanceof Error ? e.message : 'Failed to load')
    } finally {
      setLoading(false)
    }
  }, [auditPage, auditCategory, auditStatus, auditDebounced, auditSince, auditUntil])



  const fetchActivity = useCallback(async (isSilent = false) => {
    setLoading(!isSilent)
    setError(null)
    try {
      const p = new URLSearchParams({ 
        limit: '50', 
        silent: String(isSilent),
        ...(agentFilter && { agent_id: agentFilter }) 
      })
      const res = await fetch(`/api/v1/console/activity?${p}`, { credentials: 'include' })
      if (!res.ok) throw new Error(`Orchestrator Activity: HTTP ${res.status}`)
      setActivityData(await res.json())
    } catch (e) {
      if (!isSilent) setError(e instanceof Error ? e.message : 'Failed to load activity')
    } finally {
      setLoading(false)
    }
  }, [agentFilter])


  const refresh = useCallback((isSilent = false) => {
    if (tab === 'audit') fetchAudit(isSilent)
    else fetchActivity(isSilent)
  }, [tab, fetchAudit, fetchActivity])



  useEffect(() => { fetchAudit() }, [fetchAudit])
  useEffect(() => { if (tab === 'sessions') fetchActivity() }, [tab, fetchActivity])

  // Auto-refresh
  useEffect(() => {
    if (autoRefresh) {
      intervalRef.current = setInterval(() => refresh(true), 10_000)
    } else {

      if (intervalRef.current) clearInterval(intervalRef.current)
    }
    return () => { if (intervalRef.current) clearInterval(intervalRef.current) }
  }, [autoRefresh, refresh])

  const exportCsv = async () => {
    try {
      const reason = window.prompt("Compliance Requirement: Please provide a justification for this forensic export (e.g., Ticket ID, Case #). Minimum 5 characters:");
      if (!reason || reason.trim().length < 5) {
        setError('A valid justification (min 5 characters) is required to export data.');
        return;
      }

      const p = new URLSearchParams({
        reason: reason.trim(),
        ...(auditCategory && { category: auditCategory }),
        ...(auditStatus && { status: auditStatus }),
        ...(auditDebounced && { action: auditDebounced }),
        ...(auditSince && { since: new Date(auditSince).toISOString() }),
        ...(auditUntil && { until: new Date(auditUntil).toISOString() }),
      })

      const res = await fetch(`/api/v1/console/export?${p}`, { credentials: 'include' })
      if (!res.ok) {
        if (res.status === 403) throw new Error('Export restricted to Owners')
        throw new Error('Export failed')
      }
      
      const isTruncated = res.headers.get('X-Export-Truncated') === 'true'
      if (isTruncated) {
        window.alert('Note: This export was limited to the last 1,000 logs. For a full historical dump, please contact support or adjust your date filters.')
      }

      const blob = await res.blob()

      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `audit-export-${new Date().toISOString().split('T')[0]}.csv`
      a.click()
      URL.revokeObjectURL(url)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Export failed')
    }
  }


  if (!_hasHydrated || !isAuthenticated) {
    return (
      <div className="flex h-screen items-center justify-center bg-gray-950">
        <div className="animate-spin rounded-full h-8 w-8 border-t-2 border-b-2 border-indigo-500" />
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-gray-950 text-gray-100 font-mono">
      {/* Top bar */}
      <header className="border-b border-gray-800 bg-gray-900 px-5 py-3 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Terminal className="w-5 h-5 text-green-400" />
          <span className="text-sm font-bold text-green-400 tracking-wider">CONSOLE</span>
          <span className="text-xs text-gray-600">·</span>
          <span className="text-xs text-gray-500">tenant activity &amp; audit trail</span>
          <div className="ml-4 flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-indigo-950/40 border border-indigo-800/50 text-[10px] text-indigo-400 font-bold uppercase tracking-tighter">
            <Shield className="w-2.5 h-2.5" />
            Audited Access
          </div>
        </div>

        <div className="flex items-center gap-2">
          {/* Auto-refresh toggle */}
          <button
            onClick={() => setAutoRefresh(v => !v)}
            title={autoRefresh ? 'Pause auto-refresh' : 'Start auto-refresh (10s)'}
            className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded text-xs font-medium transition-colors ${
              autoRefresh
                ? 'bg-green-900/50 text-green-400 border border-green-800'
                : 'bg-gray-800 text-gray-400 border border-gray-700 hover:text-gray-200'
            }`}
          >
            {autoRefresh ? <Pause className="w-3.5 h-3.5" /> : <Play className="w-3.5 h-3.5" />}
            {autoRefresh && <span className="w-1.5 h-1.5 rounded-full bg-green-400 animate-pulse" />}
            {autoRefresh ? 'live' : 'paused'}
          </button>

          <button
            onClick={refresh}
            disabled={loading}
            className="flex items-center gap-1.5 px-2.5 py-1.5 rounded text-xs bg-gray-800 border border-gray-700 text-gray-400 hover:text-gray-200 disabled:opacity-40 transition-colors"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
            refresh
          </button>
          <button
            onClick={() => router.push('/dashboard')}
            className="flex items-center gap-1.5 px-2.5 py-1.5 rounded text-xs bg-gray-800 border border-gray-700 text-gray-400 hover:text-gray-200 transition-colors"
          >
            <X className="w-3.5 h-3.5" />
            close
          </button>
        </div>
      </header>

      {/* Tab bar */}
      <div className="border-b border-gray-800 bg-gray-900 px-5 flex gap-0">
        {([
          { id: 'audit', label: 'Audit Trail', icon: ClipboardList },
          { id: 'sessions', label: 'Sessions & Activity', icon: Activity },
        ] as const).map(t => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`flex items-center gap-2 px-4 py-2.5 text-xs font-medium border-b-2 transition-colors ${
              tab === t.id
                ? 'border-green-500 text-green-400'
                : 'border-transparent text-gray-500 hover:text-gray-300'
            }`}
          >
            <t.icon className="w-3.5 h-3.5" />
            {t.label}
          </button>
        ))}
      </div>

      <div className="p-4 space-y-3">
        {error && (
          <div className="flex items-center gap-2 text-xs text-red-400 bg-red-950/30 border border-red-900 rounded px-3 py-2">
            <AlertCircle className="w-3.5 h-3.5 flex-shrink-0" />
            {error}
          </div>
        )}

        {/* ── AUDIT TAB ──────────────────────────────────────────────────── */}
        {tab === 'audit' && (
          <>
            {/* Filter bar */}
            <div className="flex flex-wrap items-center gap-2 bg-gray-900 border border-gray-800 rounded px-3 py-2">
              <Filter className="w-3.5 h-3.5 text-gray-600" />
              <div className="relative flex-1 min-w-[160px]">
                <Search className="absolute left-2 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-600" />
                <input
                  value={auditSearch}
                  onChange={e => setAuditSearch(e.target.value)}
                  placeholder="filter by action..."
                  className="w-full pl-7 pr-2 py-1 text-xs bg-gray-800 border border-gray-700 rounded text-gray-300 placeholder-gray-600 focus:outline-none focus:border-green-700"
                />
              </div>
              <select
                value={auditCategory}
                onChange={e => setAuditCategory(e.target.value)}
                className="text-xs bg-gray-800 border border-gray-700 rounded px-2 py-1 text-gray-300 focus:outline-none focus:border-green-700"
              >
                <option value="">all categories</option>
                {['auth','user','tenant','agent','billing','admin','data','api_key'].map(c => (
                  <option key={c} value={c}>{c}</option>
                ))}
              </select>
              <select
                value={auditStatus}
                onChange={e => setAuditStatus(e.target.value)}
                className="text-xs bg-gray-800 border border-gray-700 rounded px-2 py-1 text-gray-300 focus:outline-none focus:border-green-700"
              >
                <option value="">all statuses</option>
                <option value="success">success</option>
                <option value="failure">failure</option>
              </select>
              <div className="flex items-center gap-1.5 bg-gray-800 border border-gray-700 rounded px-2 py-0.5">
                <Clock className="w-3 h-3 text-gray-500" />
                <input
                  type="datetime-local"
                  value={auditSince}
                  onChange={e => setAuditSince(e.target.value)}
                  className="text-[10px] bg-transparent text-gray-400 focus:outline-none"
                  title="Filter from (Since)"
                />
                <span className="text-gray-700 mx-0.5">-</span>
                <input
                  type="datetime-local"
                  value={auditUntil}
                  onChange={e => setAuditUntil(e.target.value)}
                  className="text-[10px] bg-transparent text-gray-400 focus:outline-none"
                  title="Filter until"
                />
                {(auditSince || auditUntil) && (
                  <button onClick={() => { setAuditSince(''); setAuditUntil(''); }} className="ml-1 text-gray-600 hover:text-gray-400">
                    <X className="w-3 h-3" />
                  </button>
                )}
              </div>
              {auditData && (

                <span className="text-xs text-gray-600 ml-auto">
                  {auditData.total.toLocaleString()} events
                </span>
              )}
              <button
                onClick={exportCsv}
                disabled={!auditData?.items.length}
                className="flex items-center gap-1 px-2 py-1 text-xs bg-gray-800 border border-gray-700 text-gray-400 hover:text-gray-200 rounded disabled:opacity-30 transition-colors"
              >
                <Download className="w-3 h-3" />
                csv
              </button>
            </div>

            {/* Log lines */}
            <div className="bg-gray-900 border border-gray-800 rounded overflow-hidden">
              {loading && !auditData ? (
                <div className="text-center text-xs text-gray-600 py-8">loading...</div>
              ) : !auditData?.items.length ? (
                <div className="text-center text-xs text-gray-600 py-8">no audit events found</div>
              ) : (
                <div className="divide-y divide-gray-800/60">
                  {auditData.items
                    .filter(row => {
                      if (auditSearch.toLowerCase().includes('console')) return true
                      return !row.action.startsWith('console.')
                    })
                    .map(row => (
                    <div key={row.id}>
                      <div
                        className="flex items-center gap-2 px-3 py-2 hover:bg-gray-800/40 cursor-pointer group"
                        onClick={() => setExpandedId(expandedId === row.id ? null : row.id)}
                      >

                        {/* Timestamp */}
                        <span className="text-xs text-gray-600 w-36 flex-shrink-0 font-mono">
                          {ts(row.created_at)}
                        </span>
                        {/* Status indicator */}
                        {row.status === 'success'
                          ? <CheckCircle2 className="w-3 h-3 text-green-500 flex-shrink-0" />
                          : <AlertCircle className="w-3 h-3 text-red-500 flex-shrink-0" />
                        }
                        {/* Action icon + name */}
                        <ActionIcon action={row.action} category={row.category} />
                        <span className={`text-xs font-bold ${CATEGORY_COLORS[row.category] ?? 'text-gray-400'}`}>
                          {row.action}
                        </span>
                        {/* Actor */}
                        <span className="text-xs text-gray-500 truncate">
                          {row.actor_email ? `· ${row.actor_email}` : ''}
                        </span>
                        {/* Resource */}
                        {row.resource_id && (
                          <span className="text-xs text-gray-700 ml-auto font-mono truncate">
                            {row.resource_type}/{row.resource_id.slice(0, 8)}
                          </span>
                        )}
                        {/* IP */}
                        {row.ip_address && (
                          <span className="text-xs text-gray-700 font-mono flex-shrink-0">
                            {row.ip_address}
                          </span>
                        )}
                      </div>
                      {expandedId === row.id && (
                        <div className="px-3 py-2 bg-gray-950 border-t border-gray-800 text-xs space-y-1">
                          <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-gray-500">
                            <span><span className="text-gray-600">id</span> {row.id}</span>
                            <span><span className="text-gray-600">role</span> {row.actor_role ?? '—'}</span>
                            {row.user_agent && (
                              <span className="col-span-2"><span className="text-gray-600">agent</span> {row.user_agent.slice(0, 100)}</span>
                            )}
                          </div>
                          {row.details && (
                            <>
                              {row.details.__truncated && (
                                <div className="mt-2 mb-1 px-2 py-1 bg-yellow-900/30 border border-yellow-800/50 rounded flex items-center gap-2 text-[10px] text-yellow-500">
                                  <AlertCircle className="w-3 h-3" />
                                  <span>Forensic detail truncated for performance (10KB cap)</span>
                                </div>
                              )}
                              <pre className="mt-1 text-xs text-green-300 overflow-x-auto">
                                {JSON.stringify(row.details, null, 2)}
                              </pre>
                            </>
                          )}

                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Pagination */}
            {auditData && auditData.pages > 1 && (
              <div className="flex items-center justify-between text-xs">
                <button
                  onClick={() => setAuditPage(p => Math.max(1, p - 1))}
                  disabled={auditPage === 1}
                  className="flex items-center gap-1 px-2 py-1 bg-gray-800 border border-gray-700 rounded text-gray-400 hover:text-gray-200 disabled:opacity-30"
                >
                  <ChevronLeft className="w-3.5 h-3.5" /> prev
                </button>
                <span className="text-gray-600">page {auditPage} / {auditData.pages}</span>
                <button
                  onClick={() => setAuditPage(p => Math.min(auditData.pages, p + 1))}
                  disabled={auditPage === auditData.pages}
                  className="flex items-center gap-1 px-2 py-1 bg-gray-800 border border-gray-700 rounded text-gray-400 hover:text-gray-200 disabled:opacity-30"
                >
                  next <ChevronRight className="w-3.5 h-3.5" />
                </button>
              </div>
            )}
          </>
        )}

        {/* ── SESSIONS TAB ───────────────────────────────────────────────── */}
        {tab === 'sessions' && (
          <>
            {/* Agent filter */}
            {agents.length > 0 && (
              <div className="flex items-center gap-2 bg-gray-900 border border-gray-800 rounded px-3 py-2">
                <Bot className="w-3.5 h-3.5 text-gray-600" />
                <select
                  value={agentFilter}
                  onChange={e => setAgentFilter(e.target.value)}
                  className="text-xs bg-gray-800 border border-gray-700 rounded px-2 py-1 text-gray-300 focus:outline-none focus:border-green-700"
                >
                  <option value="">all agents</option>
                  {agents.map(a => (
                    <option key={a.id} value={a.id}>{a.name}</option>
                  ))}
                </select>
              </div>
            )}

            {loading && !activityData ? (
              <div className="text-center text-xs text-gray-600 py-8">loading...</div>
            ) : (
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
                {/* Recent Sessions */}
                <div className="bg-gray-900 border border-gray-800 rounded overflow-hidden">
                  <div className="flex items-center gap-2 px-3 py-2 border-b border-gray-800 bg-gray-800/40">
                    <MessageSquare className="w-3.5 h-3.5 text-indigo-400" />
                    <span className="text-xs font-bold text-gray-300">Recent Sessions</span>
                    {activityData?.sessions?.total != null && (
                      <span className="ml-auto text-xs text-gray-600">{activityData.sessions.total} total</span>
                    )}
                  </div>
                  {!activityData?.sessions?.sessions?.length ? (
                    <div className="text-center text-xs text-gray-600 py-6">no sessions</div>
                  ) : (
                    <div className="divide-y divide-gray-800/60 max-h-96 overflow-y-auto">
                      {activityData.sessions.sessions.map((s: Session) => (
                        <div key={s.id} className="flex items-center gap-2 px-3 py-2 text-xs">
                          <span className={`w-2 h-2 rounded-full flex-shrink-0 ${
                            s.status === 'active' ? 'bg-green-500' :
                            s.status === 'escalated' ? 'bg-yellow-500' : 'bg-gray-600'
                          }`} />
                          <span className="text-gray-400 truncate flex-1">
                            {s.customer_identifier ?? s.id.slice(0, 8)}
                          </span>
                          <span className="text-gray-600 font-mono">{s.channel}</span>
                          <span className="text-gray-600 flex items-center gap-1">
                            <MessageSquare className="w-3 h-3" />{s.turn_count}
                          </span>
                          <span className="text-gray-700 flex-shrink-0">
                            {s.last_activity_at ? ts(s.last_activity_at) : ts(s.created_at)}
                          </span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>

                {/* Recent Events */}
                <div className="bg-gray-900 border border-gray-800 rounded overflow-hidden">
                  <div className="flex items-center gap-2 px-3 py-2 border-b border-gray-800 bg-gray-800/40">
                    <Activity className="w-3.5 h-3.5 text-green-400" />
                    <span className="text-xs font-bold text-gray-300">Recent Events</span>
                  </div>
                  {!activityData?.recent_events?.length ? (
                    <div className="text-center text-xs text-gray-600 py-6">no events</div>
                  ) : (
                    <div className="divide-y divide-gray-800/60 max-h-96 overflow-y-auto">
                      {activityData.recent_events.map((e: AuditEntry) => (
                        <div key={e.id} className="flex items-center gap-2 px-3 py-2 text-xs">
                          {e.status === 'success'
                            ? <CheckCircle2 className="w-3 h-3 text-green-500 flex-shrink-0" />
                            : <AlertCircle className="w-3 h-3 text-red-500 flex-shrink-0" />
                          }
                          <ActionIcon action={e.action} category={e.category} />
                          <span className={`font-bold ${CATEGORY_COLORS[e.category] ?? 'text-gray-400'}`}>
                            {e.action}
                          </span>
                          <span className="text-gray-600 ml-auto flex-shrink-0">
                            {ts(e.created_at)}
                          </span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}
