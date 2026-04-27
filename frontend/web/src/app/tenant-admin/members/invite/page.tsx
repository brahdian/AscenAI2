'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { ArrowLeft } from 'lucide-react'
import Link from 'next/link'

export default function InviteMemberPage() {
  const router = useRouter()
  const [form, setForm] = useState({
    email: '',
    full_name: '',
    agents_role: 'viewer',
    can_access_crm: false,
    crm_role: 'viewer',
    is_crm_only: false,
    can_access_admin: false,
  })
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState<{ email: string; is_crm_only: boolean } | null>(null)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true)
    setError(null)
    try {
      const res = await fetch('/api/v1/tenant-admin/members/invite', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(form),
      })
      if (!res.ok) {
        const d = await res.json()
        throw new Error(d.detail || 'Failed to send invite')
      }
      const data = await res.json()
      setSuccess({ email: form.email, is_crm_only: form.is_crm_only })
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to send invite')
    } finally {
      setLoading(false)
    }
  }

  if (success) {
    return (
      <div className="p-8 max-w-lg">
        <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 p-8 text-center">
          <div className="w-16 h-16 rounded-full bg-emerald-50 dark:bg-emerald-900/20 flex items-center justify-center mx-auto mb-4 text-3xl">
            ✉️
          </div>
          <h2 className="text-lg font-bold text-gray-900 dark:text-white mb-2">Invite sent!</h2>
          <p className="text-sm text-gray-500 dark:text-gray-400 mb-6">
            {success.is_crm_only
              ? `A CRM magic link has been sent to ${success.email}. They can access the CRM without an AscenAI account.`
              : `An invite email has been sent to ${success.email}.`}
          </p>
          <div className="flex gap-3 justify-center">
            <button
              onClick={() => { setSuccess(null); setForm({ email: '', full_name: '', agents_role: 'viewer', can_access_crm: false, crm_role: 'viewer', is_crm_only: false, can_access_admin: false }) }}
              className="px-4 py-2 text-sm font-medium text-gray-600 dark:text-gray-300 bg-gray-100 dark:bg-gray-800 rounded-lg hover:bg-gray-200 dark:hover:bg-gray-700 transition-colors"
            >
              Invite another
            </button>
            <Link
              href="/tenant-admin/members"
              className="px-4 py-2 text-sm font-medium text-white bg-violet-600 hover:bg-violet-700 rounded-lg transition-colors"
            >
              View members
            </Link>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="p-8 max-w-lg">
      <div className="mb-6">
        <Link href="/tenant-admin/members" className="flex items-center gap-1.5 text-sm text-gray-500 hover:text-violet-600 dark:hover:text-violet-400 mb-4 transition-colors">
          <ArrowLeft size={14} /> Back to Members
        </Link>
        <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Invite member</h1>
        <p className="text-gray-500 dark:text-gray-400 mt-1">
          Send an invite to add someone to your team.
        </p>
      </div>

      {error && (
        <div className="mb-4 px-4 py-3 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg text-sm text-red-700 dark:text-red-400">
          {error}
        </div>
      )}

      <form onSubmit={handleSubmit} className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 p-6 space-y-5">
        <div>
          <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1.5">Email *</label>
          <input
            type="email"
            required
            value={form.email}
            onChange={(e) => setForm((f) => ({ ...f, email: e.target.value }))}
            className="w-full px-3 py-2 text-sm border border-gray-200 dark:border-gray-700 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-violet-500"
            placeholder="name@company.com"
          />
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1.5">Full name</label>
          <input
            type="text"
            value={form.full_name}
            onChange={(e) => setForm((f) => ({ ...f, full_name: e.target.value }))}
            className="w-full px-3 py-2 text-sm border border-gray-200 dark:border-gray-700 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-violet-500"
            placeholder="Jane Smith"
          />
        </div>

        {/* CRM-only toggle */}
        <div className="p-4 rounded-lg border border-gray-100 dark:border-gray-800 bg-gray-50/50 dark:bg-gray-800/20">
          <label className="flex items-start gap-3 cursor-pointer">
            <input
              type="checkbox"
              checked={form.is_crm_only}
              onChange={(e) => setForm((f) => ({ ...f, is_crm_only: e.target.checked, can_access_crm: e.target.checked || f.can_access_crm }))}
              className="mt-0.5 accent-violet-600"
            />
            <div>
              <p className="text-sm font-medium text-gray-900 dark:text-white">CRM only access</p>
              <p className="text-xs text-gray-500 mt-0.5">
                This person will not have an AscenAI login. They access the CRM via a secure magic link.
              </p>
            </div>
          </label>
        </div>

        {/* AscenAI role — hidden if CRM-only */}
        {!form.is_crm_only && (
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1.5">AscenAI role</label>
            <select
              value={form.agents_role}
              onChange={(e) => setForm((f) => ({ ...f, agents_role: e.target.value }))}
              className="w-full px-3 py-2 text-sm border border-gray-200 dark:border-gray-700 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-violet-500"
            >
              <option value="viewer">Viewer — read only</option>
              <option value="editor">Editor — can configure agents</option>
              <option value="admin">Admin — full access</option>
            </select>
          </div>
        )}

        {/* CRM access */}
        <div>
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={form.can_access_crm || form.is_crm_only}
              disabled={form.is_crm_only}
              onChange={(e) => setForm((f) => ({ ...f, can_access_crm: e.target.checked }))}
              className="accent-violet-600"
            />
            <span className="text-sm font-medium text-gray-700 dark:text-gray-300">CRM access</span>
          </label>
          {(form.can_access_crm || form.is_crm_only) && (
            <select
              value={form.crm_role}
              onChange={(e) => setForm((f) => ({ ...f, crm_role: e.target.value }))}
              className="mt-2 w-full px-3 py-2 text-sm border border-gray-200 dark:border-gray-700 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-violet-500"
            >
              <option value="viewer">CRM Viewer</option>
              <option value="editor">CRM Editor</option>
              <option value="admin">CRM Admin</option>
            </select>
          )}
        </div>

        {/* Admin access */}
        {!form.is_crm_only && (
          <div>
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={form.can_access_admin}
                onChange={(e) => setForm((f) => ({ ...f, can_access_admin: e.target.checked }))}
                className="accent-violet-600"
              />
              <div>
                <span className="text-sm font-medium text-gray-700 dark:text-gray-300">Admin portal access</span>
                <p className="text-xs text-gray-500">Can manage team, billing, and settings</p>
              </div>
            </label>
          </div>
        )}

        <button
          type="submit"
          disabled={loading || !form.email}
          className="w-full px-4 py-2.5 bg-violet-600 hover:bg-violet-700 disabled:opacity-50 text-white text-sm font-medium rounded-lg transition-colors"
        >
          {loading ? 'Sending…' : 'Send invite'}
        </button>
      </form>
    </div>
  )
}
