'use client'

import { useEffect, useState } from 'react'
import { teamApi } from '@/lib/api'
import { Users, Plus, Trash2, Shield, X } from 'lucide-react'

interface Member {
  id: string
  full_name: string
  email: string
  role: string
  is_active: boolean
  created_at: string
}

const ROLES = ['owner', 'admin', 'developer', 'viewer']

const roleBadge = (role: string) => {
  const map: Record<string, string> = {
    owner: 'bg-violet-100 text-violet-700 dark:bg-violet-900/30 dark:text-violet-300',
    admin: 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300',
    developer: 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-300',
    viewer: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400',
  }
  return map[role] || map.viewer
}

export default function TeamPage() {
  const [members, setMembers] = useState<Member[]>([])
  const [loading, setLoading] = useState(true)
  const [showInvite, setShowInvite] = useState(false)
  const [inviteForm, setInviteForm] = useState({ email: '', full_name: '', role: 'developer' })
  const [inviting, setInviting] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')

  const load = () => {
    setLoading(true)
    teamApi.list()
      .then(setMembers)
      .catch(() => setError('Failed to load team members'))
      .finally(() => setLoading(false))
  }

  useEffect(() => { load() }, [])

  const invite = async () => {
    if (!inviteForm.email || !inviteForm.full_name) {
      setError('Email and full name are required')
      return
    }
    setInviting(true)
    setError('')
    try {
      await teamApi.invite(inviteForm)
      setSuccess(`Invitation sent to ${inviteForm.email}`)
      setInviteForm({ email: '', full_name: '', role: 'developer' })
      setShowInvite(false)
      load()
    } catch (e: any) {
      setError(e?.response?.data?.detail || 'Failed to invite member')
    } finally {
      setInviting(false)
    }
  }

  const changeRole = async (userId: string, role: string) => {
    try {
      await teamApi.updateRole(userId, role)
      load()
    } catch (e: any) {
      setError(e?.response?.data?.detail || 'Failed to update role')
    }
  }

  const remove = async (userId: string, name: string) => {
    if (!confirm(`Remove ${name} from the team?`)) return
    try {
      await teamApi.remove(userId)
      load()
    } catch (e: any) {
      setError(e?.response?.data?.detail || 'Failed to remove member')
    }
  }

  return (
    <div className="p-8 max-w-4xl mx-auto">
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white flex items-center gap-2">
            <Users size={24} className="text-violet-500" />
            Team
          </h1>
          <p className="text-gray-500 mt-1">Manage who has access to your AscenAI account.</p>
        </div>
        <button
          onClick={() => { setShowInvite(true); setError(''); setSuccess('') }}
          className="flex items-center gap-2 px-4 py-2 bg-violet-600 hover:bg-violet-700 text-white rounded-lg text-sm font-medium transition-colors"
        >
          <Plus size={16} />
          Invite Member
        </button>
      </div>

      {error && (
        <div className="mb-4 p-3 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg text-sm text-red-700 dark:text-red-400">
          {error}
        </div>
      )}
      {success && (
        <div className="mb-4 p-3 bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800 rounded-lg text-sm text-green-700 dark:text-green-400">
          {success}
        </div>
      )}

      {/* Invite Modal */}
      {showInvite && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-white dark:bg-gray-900 rounded-xl shadow-xl p-6 w-full max-w-md mx-4">
            <div className="flex items-center justify-between mb-5">
              <h2 className="text-lg font-semibold text-gray-900 dark:text-white">Invite Team Member</h2>
              <button onClick={() => setShowInvite(false)} className="text-gray-400 hover:text-gray-600">
                <X size={20} />
              </button>
            </div>
            <div className="space-y-4">
              <div>
                <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">Full Name</label>
                <input
                  type="text"
                  value={inviteForm.full_name}
                  onChange={(e) => setInviteForm({ ...inviteForm, full_name: e.target.value })}
                  placeholder="Jane Smith"
                  className="w-full px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-sm text-gray-900 dark:text-white"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">Email Address</label>
                <input
                  type="email"
                  value={inviteForm.email}
                  onChange={(e) => setInviteForm({ ...inviteForm, email: e.target.value })}
                  placeholder="jane@company.com"
                  className="w-full px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-sm text-gray-900 dark:text-white"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">Role</label>
                <select
                  value={inviteForm.role}
                  onChange={(e) => setInviteForm({ ...inviteForm, role: e.target.value })}
                  className="w-full px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-sm text-gray-900 dark:text-white"
                >
                  {ROLES.map((r) => <option key={r} value={r}>{r.charAt(0).toUpperCase() + r.slice(1)}</option>)}
                </select>
              </div>
              <div className="flex gap-3 pt-2">
                <button
                  onClick={() => setShowInvite(false)}
                  className="flex-1 px-4 py-2 rounded-lg border border-gray-200 dark:border-gray-700 text-sm text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors"
                >
                  Cancel
                </button>
                <button
                  onClick={invite}
                  disabled={inviting}
                  className="flex-1 px-4 py-2 bg-violet-600 hover:bg-violet-700 disabled:opacity-50 text-white rounded-lg text-sm font-medium transition-colors"
                >
                  {inviting ? 'Inviting…' : 'Send Invite'}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Members table */}
      <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 overflow-hidden">
        {loading ? (
          <div className="p-8 text-center text-gray-500">Loading team…</div>
        ) : members.length === 0 ? (
          <div className="p-8 text-center">
            <Users size={32} className="mx-auto mb-3 text-gray-300" />
            <p className="text-gray-500 text-sm">No team members yet. Invite someone to get started.</p>
          </div>
        ) : (
          <table className="w-full">
            <thead>
              <tr className="border-b border-gray-100 dark:border-gray-800">
                <th className="text-left px-6 py-3 text-xs font-medium text-gray-500 uppercase">Member</th>
                <th className="text-left px-6 py-3 text-xs font-medium text-gray-500 uppercase">Role</th>
                <th className="text-left px-6 py-3 text-xs font-medium text-gray-500 uppercase">Status</th>
                <th className="text-left px-6 py-3 text-xs font-medium text-gray-500 uppercase">Joined</th>
                <th className="px-6 py-3" />
              </tr>
            </thead>
            <tbody>
              {members.map((m) => (
                <tr key={m.id} className="border-b border-gray-50 dark:border-gray-800 last:border-0 hover:bg-gray-50 dark:hover:bg-gray-800/50">
                  <td className="px-6 py-4">
                    <div className="flex items-center gap-3">
                      <div className="w-8 h-8 rounded-full bg-gradient-to-br from-violet-400 to-blue-400 flex items-center justify-center text-white text-xs font-bold">
                        {m.full_name.charAt(0)}
                      </div>
                      <div>
                        <p className="text-sm font-medium text-gray-900 dark:text-white">{m.full_name}</p>
                        <p className="text-xs text-gray-500">{m.email}</p>
                      </div>
                    </div>
                  </td>
                  <td className="px-6 py-4">
                    <select
                      value={m.role}
                      onChange={(e) => changeRole(m.id, e.target.value)}
                      className={`px-2 py-1 rounded-full text-xs font-medium border-0 cursor-pointer ${roleBadge(m.role)}`}
                    >
                      {ROLES.map((r) => <option key={r} value={r}>{r.charAt(0).toUpperCase() + r.slice(1)}</option>)}
                    </select>
                  </td>
                  <td className="px-6 py-4">
                    <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${
                      m.is_active ? 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400' : 'bg-gray-100 text-gray-500'
                    }`}>
                      {m.is_active ? 'Active' : 'Inactive'}
                    </span>
                  </td>
                  <td className="px-6 py-4 text-sm text-gray-500">
                    {new Date(m.created_at).toLocaleDateString()}
                  </td>
                  <td className="px-6 py-4 text-right">
                    <button
                      onClick={() => remove(m.id, m.full_name)}
                      className="p-1.5 text-gray-400 hover:text-red-500 transition-colors"
                      title="Remove member"
                    >
                      <Trash2 size={14} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="mt-4 flex items-center gap-2 text-xs text-gray-500">
        <Shield size={12} />
        <span>Your plan includes unlimited team members. Roles control what each member can access.</span>
      </div>
    </div>
  )
}
