'use client'

import { useEffect, useState } from 'react'
import { Users, Plus, MoreHorizontal, CheckCircle, Clock, XCircle, Bot, Database, Shield } from 'lucide-react'
import Link from 'next/link'

interface Member {
  id: string
  user_id: string | null
  email: string
  full_name: string
  status: string
  is_crm_only: boolean
  permissions: {
    can_access_agents: boolean
    can_access_crm: boolean
    can_access_billing: boolean
    can_access_admin: boolean
    agents_role: string
    crm_role: string
  }
  accepted_at: string | null
  created_at: string
}

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, { label: string; cls: string; icon: React.ElementType }> = {
    active: { label: 'Active', cls: 'bg-emerald-50 text-emerald-700 dark:bg-emerald-900/20 dark:text-emerald-400', icon: CheckCircle },
    pending: { label: 'Pending', cls: 'bg-yellow-50 text-yellow-700 dark:bg-yellow-900/20 dark:text-yellow-400', icon: Clock },
    revoked: { label: 'Revoked', cls: 'bg-red-50 text-red-700 dark:bg-red-900/20 dark:text-red-400', icon: XCircle },
  }
  const cfg = map[status] || map.pending
  return (
    <span className={`flex items-center gap-1 text-xs font-medium px-2 py-0.5 rounded-full ${cfg.cls}`}>
      <cfg.icon size={11} />
      {cfg.label}
    </span>
  )
}

function AccessBadge({ enabled, label, icon: Icon }: { enabled: boolean; label: string; icon: React.ElementType }) {
  return (
    <span className={`flex items-center gap-1 text-[11px] font-medium px-1.5 py-0.5 rounded ${
      enabled
        ? 'bg-violet-50 text-violet-700 dark:bg-violet-900/20 dark:text-violet-400'
        : 'bg-gray-100 text-gray-400 dark:bg-gray-800 dark:text-gray-600 line-through'
    }`}>
      <Icon size={10} />
      {label}
    </span>
  )
}

async function togglePermission(memberId: string, field: string, value: boolean) {
  await fetch(`/api/v1/tenant-admin/members/${memberId}/permissions`, {
    method: 'PATCH',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ [field]: value }),
  })
}

export default function MembersPage() {
  const [members, setMembers] = useState<Member[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const fetchMembers = () => {
    setLoading(true)
    fetch('/api/v1/tenant-admin/members', { credentials: 'include' })
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then((d) => setMembers(d.members ?? []))
      .catch(() => setError('Failed to load members'))
      .finally(() => setLoading(false))
  }

  useEffect(fetchMembers, [])

  const handleToggle = async (memberId: string, field: string, current: boolean) => {
    setMembers((prev) =>
      prev.map((m) =>
        m.id === memberId
          ? { ...m, permissions: { ...m.permissions, [field]: !current } }
          : m
      )
    )
    await togglePermission(memberId, field, !current)
  }

  return (
    <div className="p-8">
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Members & RBAC</h1>
          <p className="text-gray-500 dark:text-gray-400 mt-1">
            Manage your team and control access to each product.
          </p>
        </div>
        <Link
          href="/tenant-admin/members/invite"
          className="flex items-center gap-2 px-4 py-2 bg-violet-600 hover:bg-violet-700 text-white text-sm font-medium rounded-lg transition-colors"
        >
          <Plus size={16} />
          Invite member
        </Link>
      </div>

      {error && (
        <div className="mb-4 px-4 py-3 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg text-sm text-red-700 dark:text-red-400">
          {error}
        </div>
      )}

      <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 overflow-hidden">
        {/* Table header */}
        <div className="grid grid-cols-12 gap-4 px-6 py-3 border-b border-gray-100 dark:border-gray-800 bg-gray-50/50 dark:bg-gray-800/20 text-xs font-semibold text-gray-500 uppercase tracking-wider">
          <span className="col-span-4">Member</span>
          <span className="col-span-2">Status</span>
          <span className="col-span-4">Product Access</span>
          <span className="col-span-2">Role</span>
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-16">
            <div className="animate-spin rounded-full h-8 w-8 border-t-2 border-b-2 border-violet-500" />
          </div>
        ) : !members.length ? (
          <div className="flex flex-col items-center justify-center py-16 text-gray-500">
            <Users size={32} className="mb-3 opacity-30" />
            <p className="text-sm">No members yet.</p>
            <Link href="/tenant-admin/members/invite" className="mt-2 text-sm text-violet-600 dark:text-violet-400 hover:underline">
              Invite your first member →
            </Link>
          </div>
        ) : (
          <div className="divide-y divide-gray-100 dark:divide-gray-800">
            {members.map((m) => (
              <div key={m.id} className="grid grid-cols-12 gap-4 px-6 py-4 items-center hover:bg-gray-50/50 dark:hover:bg-gray-800/20 transition-colors">
                {/* Member info */}
                <div className="col-span-4 flex items-center gap-3">
                  <div className="w-8 h-8 rounded-full bg-gradient-to-br from-violet-400 to-blue-400 flex items-center justify-center text-white text-xs font-bold flex-shrink-0">
                    {(m.full_name || m.email).charAt(0).toUpperCase()}
                  </div>
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-gray-900 dark:text-white truncate">
                      {m.full_name || '—'}
                    </p>
                    <p className="text-xs text-gray-500 truncate">{m.email}</p>
                    {m.is_crm_only && (
                      <span className="text-[10px] font-medium text-blue-600 dark:text-blue-400">CRM only</span>
                    )}
                  </div>
                </div>

                {/* Status */}
                <div className="col-span-2">
                  <StatusBadge status={m.status} />
                </div>

                {/* Product toggles — inline click-to-toggle */}
                <div className="col-span-4 flex flex-wrap gap-1.5">
                  {!m.is_crm_only && (
                    <button
                      onClick={() => handleToggle(m.id, 'can_access_agents', m.permissions.can_access_agents)}
                      title="Toggle AI Agents access"
                    >
                      <AccessBadge enabled={m.permissions.can_access_agents} label="Agents" icon={Bot} />
                    </button>
                  )}
                  <button
                    onClick={() => handleToggle(m.id, 'can_access_crm', m.permissions.can_access_crm)}
                    title="Toggle CRM access"
                  >
                    <AccessBadge enabled={m.permissions.can_access_crm} label="CRM" icon={Database} />
                  </button>
                  {!m.is_crm_only && (
                    <button
                      onClick={() => handleToggle(m.id, 'can_access_admin', m.permissions.can_access_admin)}
                      title="Toggle Admin access"
                    >
                      <AccessBadge enabled={m.permissions.can_access_admin} label="Admin" icon={Shield} />
                    </button>
                  )}
                </div>

                {/* Role */}
                <div className="col-span-2 text-sm text-gray-600 dark:text-gray-400 capitalize">
                  {m.permissions.agents_role}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
