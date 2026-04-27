'use client'

import { useEffect, useState } from 'react'
import { use } from 'react'
import { Database, Users, Plus, ArrowLeft, ExternalLink, CheckCircle, Clock, XCircle } from 'lucide-react'
import Link from 'next/link'
import toast from 'react-hot-toast'

interface Workspace {
  id: string
  company_name: string
  subdomain: string
  user_slots: number
  url: string
}

interface Member {
  id: string
  email: string
  full_name: string
  status: string
  crm_role: string
}

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, { cls: string; icon: React.ElementType }> = {
    active: { cls: 'bg-emerald-50 text-emerald-700 dark:bg-emerald-900/20 dark:text-emerald-400', icon: CheckCircle },
    pending: { cls: 'bg-yellow-50 text-yellow-700 dark:bg-yellow-900/20 dark:text-yellow-400', icon: Clock },
    revoked: { cls: 'bg-red-50 text-red-700 dark:bg-red-900/20 dark:text-red-400', icon: XCircle },
  }
  const cfg = map[status] ?? map.pending
  return (
    <span className={`flex items-center gap-1 text-xs font-medium px-2 py-0.5 rounded-full ${cfg.cls}`}>
      <cfg.icon size={11} />
      {status}
    </span>
  )
}

export default function CRMWorkspaceDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params)

  const [workspace, setWorkspace] = useState<Workspace | null>(null)
  const [members, setMembers] = useState<Member[]>([])
  const [loading, setLoading] = useState(true)
  const [ssoLoading, setSSOLoading] = useState(false)

  useEffect(() => {
    Promise.all([
      fetch('/api/v1/tenant-admin/crm/workspaces', { credentials: 'include' })
        .then((r) => (r.ok ? r.json() : { workspaces: [] }))
        .then((d) => (d.workspaces as Workspace[]).find((w) => w.id === id) ?? null),
      fetch(`/api/v1/tenant-admin/members?crm_workspace_id=${id}`, { credentials: 'include' })
        .then((r) => (r.ok ? r.json() : { members: [] }))
        .then((d) => d.members ?? []),
    ])
      .then(([ws, mbs]) => {
        setWorkspace(ws)
        setMembers(mbs)
      })
      .finally(() => setLoading(false))
  }, [id])

  const handleSSO = async () => {
    setSSOLoading(true)
    try {
      const res = await fetch(`/api/v1/tenant-admin/crm/sso-link?workspace_id=${id}`, { credentials: 'include' })
      if (!res.ok) throw new Error()
      const data = await res.json()
      window.open(data.crm_url, '_blank')
    } catch {
      toast.error('Failed to generate SSO link.')
    } finally {
      setSSOLoading(false)
    }
  }

  if (loading) {
    return (
      <div className="p-8 flex items-center justify-center min-h-[400px]">
        <div className="animate-spin rounded-full h-8 w-8 border-t-2 border-b-2 border-violet-500" />
      </div>
    )
  }

  if (!workspace) {
    return (
      <div className="p-8">
        <p className="text-gray-500">Workspace not found.</p>
        <Link href="/tenant-admin/crm" className="text-sm text-violet-600 hover:underline">← Back to CRM</Link>
      </div>
    )
  }

  return (
    <div className="p-8 max-w-3xl">
      <Link
        href="/tenant-admin/crm"
        className="flex items-center gap-1.5 text-sm text-gray-500 hover:text-violet-600 dark:hover:text-violet-400 mb-6 transition-colors"
      >
        <ArrowLeft size={14} /> Back to CRM Workspaces
      </Link>

      {/* Workspace header */}
      <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 p-6 mb-6">
        <div className="flex items-start justify-between">
          <div className="flex items-center gap-4">
            <div className="w-12 h-12 rounded-xl bg-blue-100 dark:bg-blue-900/30 flex items-center justify-center">
              <Database size={24} className="text-blue-600 dark:text-blue-400" />
            </div>
            <div>
              <h1 className="text-2xl font-bold text-gray-900 dark:text-white">{workspace.company_name}</h1>
              <p className="text-gray-500 text-sm">{workspace.subdomain}.{process.env.NEXT_PUBLIC_ROOT_DOMAIN?.split(':')[0] || 'lvh.me'}</p>
            </div>
          </div>
          <button
            onClick={handleSSO}
            disabled={ssoLoading}
            className="flex items-center gap-2 px-4 py-2 bg-violet-600 hover:bg-violet-700 disabled:opacity-50 text-white text-sm font-medium rounded-lg transition-colors"
          >
            <ExternalLink size={15} />
            {ssoLoading ? 'Opening…' : 'Open CRM'}
          </button>
        </div>

        <div className="grid grid-cols-3 gap-4 mt-6 pt-6 border-t border-gray-100 dark:border-gray-800">
          {[
            { label: 'Total Seats', value: workspace.user_slots },
            { label: 'Members', value: members.filter((m) => m.status === 'active').length },
            { label: 'Monthly Cost', value: `$${workspace.user_slots * Number(process.env.NEXT_PUBLIC_CRM_SEAT_PRICE || 19)}/mo` },
          ].map(({ label, value }) => (
            <div key={label} className="text-center">
              <p className="text-2xl font-bold text-gray-900 dark:text-white">{value}</p>
              <p className="text-xs text-gray-500 mt-0.5">{label}</p>
            </div>
          ))}
        </div>
      </div>

      {/* Members */}
      <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 overflow-hidden">
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100 dark:border-gray-800">
          <h2 className="text-base font-semibold text-gray-900 dark:text-white flex items-center gap-2">
            <Users size={18} className="text-violet-500" />
            Members ({members.length})
          </h2>
          <Link
            href={`/tenant-admin/members/invite?workspace=${id}`}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-white bg-violet-600 hover:bg-violet-700 rounded-lg transition-colors"
          >
            <Plus size={13} /> Invite
          </Link>
        </div>

        {members.length === 0 ? (
          <div className="py-12 text-center text-gray-500">
            <Users size={32} className="mx-auto mb-3 opacity-20" />
            <p className="text-sm">No members in this workspace yet.</p>
            <Link
              href={`/tenant-admin/members/invite?workspace=${id}`}
              className="mt-2 inline-block text-sm text-violet-600 dark:text-violet-400 hover:underline"
            >
              Invite your first member →
            </Link>
          </div>
        ) : (
          <div className="divide-y divide-gray-100 dark:divide-gray-800">
            {members.map((m) => (
              <div key={m.id} className="flex items-center gap-4 px-6 py-4">
                <div className="w-8 h-8 rounded-full bg-gradient-to-br from-blue-400 to-indigo-400 flex items-center justify-center text-white text-xs font-bold flex-shrink-0">
                  {(m.full_name || m.email).charAt(0).toUpperCase()}
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-gray-900 dark:text-white truncate">
                    {m.full_name || '—'}
                  </p>
                  <p className="text-xs text-gray-500 truncate">{m.email}</p>
                </div>
                <span className="text-xs text-gray-500 capitalize mr-2">{m.crm_role}</span>
                <StatusBadge status={m.status} />
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Seats quick link */}
      <div className="mt-4 flex justify-end">
        <Link
          href="/tenant-admin/billing/crm-seats"
          className="text-sm text-violet-600 dark:text-violet-400 hover:underline"
        >
          Adjust seats for this workspace →
        </Link>
      </div>
    </div>
  )
}
