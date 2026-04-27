'use client'

import { useEffect, useState } from 'react'
import { Database, Plus, ExternalLink, Users } from 'lucide-react'
import Link from 'next/link'
import toast from 'react-hot-toast'

interface Workspace {
  id: string
  company_name: string
  subdomain: string
  user_slots: number
  url: string
  created_at: string
}

export default function CRMPage() {
  const [workspaces, setWorkspaces] = useState<Workspace[]>([])
  const [loading, setLoading] = useState(true)
  const [creating, setCreating] = useState(false)
  const [showCreate, setShowCreate] = useState(false)
  const [newName, setNewName] = useState('')
  const [error, setError] = useState<string | null>(null)

  const fetchWorkspaces = () => {
    setLoading(true)
    fetch('/api/v1/tenant-admin/crm/workspaces', { credentials: 'include' })
      .then((r) => (r.ok ? r.json() : { workspaces: [] }))
      .then((d) => setWorkspaces(d.workspaces ?? []))
      .finally(() => setLoading(false))
  }

  useEffect(fetchWorkspaces, [])

  const handleCreate = async () => {
    if (!newName.trim()) return
    setCreating(true)
    setError(null)
    try {
      const res = await fetch('/api/v1/tenant-admin/crm/workspaces', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ company_name: newName.trim() }),
      })
      if (!res.ok) {
        const d = await res.json()
        throw new Error(d.detail || 'Failed to create workspace')
      }
      setNewName('')
      setShowCreate(false)
      fetchWorkspaces()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to create workspace')
    } finally {
      setCreating(false)
    }
  }

  const handleSSOLink = async (workspaceId: string) => {
    try {
      const res = await fetch(`/api/v1/tenant-admin/crm/sso-link?workspace_id=${workspaceId}`, { credentials: 'include' })
      if (!res.ok) throw new Error('Failed')
      const data = await res.json()
      window.open(data.crm_url, '_blank')
    } catch {
      toast.error('Failed to generate SSO link. Make sure your account is provisioned in the CRM.')
    }
  }

  return (
    <div className="p-8">
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">CRM Workspaces</h1>
          <p className="text-gray-500 dark:text-gray-400 mt-1">
            Each workspace is an isolated CRM environment for a company or team.
          </p>
        </div>
        <button
          onClick={() => setShowCreate(true)}
          className="flex items-center gap-2 px-4 py-2 bg-violet-600 hover:bg-violet-700 text-white text-sm font-medium rounded-lg transition-colors"
        >
          <Plus size={16} />
          New workspace
        </button>
      </div>

      {/* Create modal */}
      {showCreate && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 p-6 w-full max-w-md shadow-xl">
            <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">Create CRM workspace</h2>
            {error && (
              <div className="mb-4 px-3 py-2 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg text-sm text-red-700 dark:text-red-400">
                {error}
              </div>
            )}
            <input
              autoFocus
              type="text"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleCreate()}
              placeholder="Company name (e.g. Acme Corp)"
              className="w-full px-3 py-2 text-sm border border-gray-200 dark:border-gray-700 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-violet-500 mb-4"
            />
            <div className="flex gap-3">
              <button
                onClick={() => { setShowCreate(false); setNewName(''); setError(null) }}
                className="flex-1 px-4 py-2 text-sm text-gray-600 dark:text-gray-300 bg-gray-100 dark:bg-gray-800 rounded-lg hover:bg-gray-200 dark:hover:bg-gray-700 transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleCreate}
                disabled={creating || !newName.trim()}
                className="flex-1 px-4 py-2 text-sm font-medium text-white bg-violet-600 hover:bg-violet-700 disabled:opacity-50 rounded-lg transition-colors"
              >
                {creating ? 'Creating…' : 'Create'}
              </button>
            </div>
          </div>
        </div>
      )}

      {loading ? (
        <div className="flex items-center justify-center py-20">
          <div className="animate-spin rounded-full h-8 w-8 border-t-2 border-b-2 border-violet-500" />
        </div>
      ) : !workspaces.length ? (
        <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 p-12 text-center">
          <Database size={40} className="mx-auto mb-4 text-gray-300 dark:text-gray-600" />
          <h3 className="text-sm font-semibold text-gray-900 dark:text-white mb-1">No CRM workspaces</h3>
          <p className="text-sm text-gray-500 mb-4">Create a workspace to set up the CRM for your company.</p>
          <button
            onClick={() => setShowCreate(true)}
            className="px-4 py-2 bg-violet-600 hover:bg-violet-700 text-white text-sm font-medium rounded-lg transition-colors"
          >
            Create workspace
          </button>
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          {workspaces.map((ws) => (
            <div
              key={ws.id}
              className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 p-5"
            >
              <div className="flex items-start justify-between mb-4">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-xl bg-blue-50 dark:bg-blue-900/20 flex items-center justify-center">
                    <Database size={20} className="text-blue-600 dark:text-blue-400" />
                  </div>
                  <div>
                    <Link href={`/tenant-admin/crm/${ws.id}`} className="text-sm font-semibold text-gray-900 dark:text-white hover:text-violet-700 dark:hover:text-violet-300 transition-colors">
                      {ws.company_name}
                    </Link>
                    <p className="text-xs text-gray-500">{ws.subdomain}.{process.env.NEXT_PUBLIC_ROOT_DOMAIN?.split(':')[0] || 'lvh.me'}</p>
                  </div>
                </div>
              </div>

              {/* Stats */}
              <div className="grid grid-cols-2 gap-3 mb-4">
                <div className="p-3 rounded-lg bg-gray-50 dark:bg-gray-800/40">
                  <p className="text-xs text-gray-500 mb-1">CRM Seats</p>
                  <p className="text-lg font-bold text-gray-900 dark:text-white">{ws.user_slots}</p>
                </div>
                <div className="p-3 rounded-lg bg-gray-50 dark:bg-gray-800/40">
                  <p className="text-xs text-gray-500 mb-1">Monthly</p>
                  <p className="text-lg font-bold text-gray-900 dark:text-white">${ws.user_slots * Number(process.env.NEXT_PUBLIC_CRM_SEAT_PRICE || 19)}</p>
                </div>
              </div>

              {/* Actions */}
              <div className="flex items-center gap-2">
                <button
                  onClick={() => handleSSOLink(ws.id)}
                  className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-white bg-violet-600 hover:bg-violet-700 rounded-lg transition-colors"
                >
                  <ExternalLink size={12} />
                  Open CRM
                </button>
                <Link
                  href={`/tenant-admin/billing/crm-seats`}
                  className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-gray-600 dark:text-gray-300 border border-gray-200 dark:border-gray-700 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors"
                >
                  Manage seats
                </Link>
                <Link
                  href={`/tenant-admin/members/invite?workspace=${ws.id}`}
                  className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-gray-600 dark:text-gray-300 border border-gray-200 dark:border-gray-700 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors"
                >
                  <Users size={12} />
                  Invite
                </Link>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
