'use client'

import { useEffect, useState } from 'react'
import { teamApi } from '@/lib/api'
import { Users, Plus, Trash2, Shield, X, Mail, RefreshCw, UserCheck, AlertCircle } from 'lucide-react'

interface Member {
  id: string
  full_name: string
  email: string
  role: string
  is_active: boolean
  created_at: string
}

interface Invite {
  id: string
  email: string
  role: string
  token: string
  expires_at: string
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
  const [invites, setInvites] = useState<Invite[]>([])
  const [loading, setLoading] = useState(true)
  const [showInvite, setShowInvite] = useState(false)
  const [inviteForm, setInviteForm] = useState({ email: '', full_name: '', role: 'viewer' })
  const [inviting, setInviting] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')

  const load = async () => {
    setLoading(true)
    setError('')
    try {
      const [membersData, invitesData] = await Promise.all([
        teamApi.list(),
        teamApi.listInvites()
      ])
      setMembers(membersData)
      setInvites(invitesData)
    } catch (e: any) {
      setError('Failed to load team data')
    } finally {
      setLoading(false)
    }
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
      setInviteForm({ email: '', full_name: '', role: 'viewer' })
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

  const deactivate = async (userId: string, name: string) => {
    if (!confirm(`Deactivate ${name}? They will lose access immediately.`)) return
    try {
      await teamApi.remove(userId)
      load()
    } catch (e: any) {
      setError(e?.response?.data?.detail || 'Failed to deactivate member')
    }
  }

  const reactivate = async (userId: string) => {
    try {
      await teamApi.reactivate(userId)
      setSuccess('User reactivated successfully.')
      load()
    } catch (e: any) {
      setError(e?.response?.data?.detail || 'Failed to reactivate member')
    }
  }

  const hardRemove = async (userId: string, name: string) => {
    if (!confirm(`PERMANENTLY DELETE ${name}? This will erase their user profile and API keys from our system. This action cannot be undone.`)) return
    try {
      await teamApi.hardRemove(userId)
      setSuccess(`${name} has been permanently removed.`)
      load()
    } catch (e: any) {
      setError(e?.response?.data?.detail || 'Failed to permanently remove member')
    }
  }

  return (
    <div className="p-8 w-full">
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white flex items-center gap-2">
            <Users size={24} className="text-violet-500" />
            Team Management
          </h1>
          <p className="text-gray-500 mt-1">Manage team members, roles, and pending invitations.</p>
        </div>
        <button
          onClick={() => { setShowInvite(true); setError(''); setSuccess('') }}
          className="flex items-center gap-2 px-4 py-2 bg-violet-600 hover:bg-violet-700 text-white rounded-lg text-sm font-medium transition-colors shadow-sm"
        >
          <Plus size={16} />
          Invite Member
        </button>
      </div>

      {error && (
        <div className="mb-6 p-4 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-xl text-sm text-red-700 dark:text-red-400 flex items-start gap-3">
          <AlertCircle size={18} className="shrink-0 mt-0.5" />
          {error}
        </div>
      )}
      {success && (
        <div className="mb-6 p-4 bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800 rounded-xl text-sm text-green-700 dark:text-green-400">
          {success}
        </div>
      )}

      {/* Invite Modal */}
      {showInvite && (
        <div className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-50">
          <div className="bg-white dark:bg-gray-900 rounded-2xl shadow-2xl p-6 w-full max-w-md mx-4 border border-gray-200 dark:border-gray-800">
            <div className="flex items-center justify-between mb-6">
              <h2 className="text-xl font-bold text-gray-900 dark:text-white">Invite Team Member</h2>
              <button onClick={() => setShowInvite(false)} className="p-1 text-gray-400 hover:text-gray-600 dark:hover:text-gray-200">
                <X size={20} />
              </button>
            </div>
            <div className="space-y-4">
              <div>
                <label className="block text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-1.5">Full Name</label>
                <input
                  type="text"
                  value={inviteForm.full_name}
                  onChange={(e) => setInviteForm({ ...inviteForm, full_name: e.target.value })}
                  placeholder="Jane Smith"
                  className="w-full px-4 py-2.5 rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-sm text-gray-900 dark:text-white focus:ring-2 focus:ring-violet-500 outline-none transition-all"
                />
              </div>
              <div>
                <label className="block text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-1.5">Email Address</label>
                <input
                  type="email"
                  value={inviteForm.email}
                  onChange={(e) => setInviteForm({ ...inviteForm, email: e.target.value })}
                  placeholder="jane@company.com"
                  className="w-full px-4 py-2.5 rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-sm text-gray-900 dark:text-white focus:ring-2 focus:ring-violet-500 outline-none transition-all"
                />
              </div>
              <div>
                <label className="block text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-1.5">Role</label>
                <select
                  value={inviteForm.role}
                  onChange={(e) => setInviteForm({ ...inviteForm, role: e.target.value })}
                  className="w-full px-4 py-2.5 rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-sm text-gray-900 dark:text-white focus:ring-2 focus:ring-violet-500 outline-none transition-all"
                >
                  {ROLES.map((r) => <option key={r} value={r}>{r.charAt(0).toUpperCase() + r.slice(1)}</option>)}
                </select>
              </div>
              <div className="flex gap-3 pt-4">
                <button
                  onClick={() => setShowInvite(false)}
                  className="flex-1 px-4 py-2.5 rounded-xl border border-gray-200 dark:border-gray-700 text-sm font-medium text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors"
                >
                  Cancel
                </button>
                <button
                  onClick={invite}
                  disabled={inviting}
                  className="flex-1 px-4 py-2.5 bg-violet-600 hover:bg-violet-700 disabled:opacity-50 text-white rounded-xl text-sm font-bold transition-all shadow-md shadow-violet-500/20"
                >
                  {inviting ? 'Inviting…' : 'Send Invitation'}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Pending Invites */}
      {invites.length > 0 && (
        <div className="mb-10">
          <h2 className="text-sm font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-4 flex items-center gap-2">
            <Mail size={16} />
            Pending Invitations ({invites.length})
          </h2>
          <div className="bg-amber-50/50 dark:bg-amber-900/10 border border-amber-200 dark:border-amber-900/30 rounded-2xl overflow-hidden">
            <table className="w-full">
              <thead>
                <tr className="border-b border-amber-200/50 dark:border-amber-900/20 text-left">
                  <th className="px-6 py-3 text-xs font-bold text-amber-800/70 dark:text-amber-400/70">Email</th>
                  <th className="px-6 py-3 text-xs font-bold text-amber-800/70 dark:text-amber-400/70">Role</th>
                  <th className="px-6 py-3 text-xs font-bold text-amber-800/70 dark:text-amber-400/70">Expires</th>
                  <th className="px-6 py-3 text-xs font-bold text-amber-800/70 dark:text-amber-400/70 text-right">Action</th>
                </tr>
              </thead>
              <tbody>
                {invites.map((i) => (
                  <tr key={i.id} className="last:border-0 border-b border-amber-200/30 dark:border-amber-900/10">
                    <td className="px-6 py-4 text-sm font-medium text-amber-900 dark:text-amber-100">{i.email}</td>
                    <td className="px-6 py-4">
                      <span className={`px-2 py-1 rounded-full text-xs font-bold ${roleBadge(i.role)}`}>
                        {i.role}
                      </span>
                    </td>
                    <td className="px-6 py-4 text-xs text-amber-700/70 dark:text-amber-400/70">
                      {new Date(i.expires_at).toLocaleDateString()}
                    </td>
                    <td className="px-6 py-4 text-right">
                      <button className="text-amber-700 hover:text-amber-900 dark:text-amber-400 dark:hover:text-amber-200 transition-colors">
                        <X size={16} />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Members table */}
      <h2 className="text-sm font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-4 flex items-center gap-2">
        <UserCheck size={16} />
        Active & Inactive Members
      </h2>
      <div className="bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-800 overflow-hidden shadow-sm">
        {loading ? (
          <div className="p-12 text-center flex flex-col items-center gap-3">
            <RefreshCw size={24} className="animate-spin text-violet-500" />
            <p className="text-gray-500 text-sm">Loading your team…</p>
          </div>
        ) : members.length === 0 ? (
          <div className="p-12 text-center">
            <Users size={48} className="mx-auto mb-4 text-gray-200" />
            <h3 className="text-gray-900 dark:text-white font-medium">No team members</h3>
            <p className="text-gray-500 text-sm mt-1">Invite your colleagues to start collaborating.</p>
          </div>
        ) : (
          <table className="w-full">
            <thead>
              <tr className="border-b border-gray-100 dark:border-gray-800 bg-gray-50/50 dark:bg-gray-800/30">
                <th className="text-left px-6 py-4 text-xs font-bold text-gray-500 uppercase tracking-widest">Member</th>
                <th className="text-left px-6 py-4 text-xs font-bold text-gray-500 uppercase tracking-widest">Role</th>
                <th className="text-left px-6 py-4 text-xs font-bold text-gray-500 uppercase tracking-widest">Status</th>
                <th className="text-left px-6 py-4 text-xs font-bold text-gray-500 uppercase tracking-widest">Joined</th>
                <th className="px-6 py-4 text-right text-xs font-bold text-gray-500 uppercase tracking-widest">Actions</th>
              </tr>
            </thead>
            <tbody>
              {members.map((m) => (
                <tr key={m.id} className="border-b border-gray-50 dark:border-gray-800 last:border-0 hover:bg-gray-50/80 dark:hover:bg-gray-800/50 transition-colors">
                  <td className="px-6 py-4">
                    <div className="flex items-center gap-3">
                      <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-violet-500 to-indigo-600 flex items-center justify-center text-white text-sm font-bold shadow-md shadow-violet-500/20">
                        {m.full_name.charAt(0).toUpperCase()}
                      </div>
                      <div>
                        <p className="text-sm font-bold text-gray-900 dark:text-white">{m.full_name}</p>
                        <p className="text-xs text-gray-500 font-medium">{m.email}</p>
                      </div>
                    </div>
                  </td>
                  <td className="px-6 py-4">
                    <select
                      value={m.role}
                      onChange={(e) => changeRole(m.id, e.target.value)}
                      className={`px-3 py-1.5 rounded-xl text-xs font-bold border-0 cursor-pointer focus:ring-0 transition-opacity ${roleBadge(m.role)} ${!m.is_active ? 'opacity-50' : ''}`}
                      disabled={!m.is_active}
                    >
                      {ROLES.map((r) => <option key={r} value={r}>{r.charAt(0).toUpperCase() + r.slice(1)}</option>)}
                    </select>
                  </td>
                  <td className="px-6 py-4">
                    <span className={`px-2.5 py-1 rounded-lg text-[10px] font-black uppercase tracking-widest ${m.is_active ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400' : 'bg-gray-100 text-gray-500 dark:bg-gray-800 dark:text-gray-400'
                      }`}>
                      {m.is_active ? 'Active' : 'Inactive'}
                    </span>
                  </td>
                  <td className="px-6 py-4 text-xs font-medium text-gray-500">
                    {new Date(m.created_at).toLocaleDateString()}
                  </td>
                  <td className="px-6 py-4">
                    <div className="flex items-center justify-end gap-2">
                      {m.is_active ? (
                        <button
                          onClick={() => deactivate(m.id, m.full_name)}
                          className="p-2 text-gray-400 hover:text-amber-500 hover:bg-amber-50 dark:hover:bg-amber-900/20 rounded-lg transition-all"
                          title="Deactivate member"
                        >
                          <X size={18} />
                        </button>
                      ) : (
                        <button
                          onClick={() => reactivate(m.id)}
                          className="p-2 text-emerald-500 hover:bg-emerald-50 dark:hover:bg-emerald-900/20 rounded-lg transition-all"
                          title="Reactivate member"
                        >
                          <UserCheck size={18} />
                        </button>
                      )}
                      <button
                        onClick={() => hardRemove(m.id, m.full_name)}
                        className="p-2 text-gray-400 hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-900/20 rounded-lg transition-all"
                        title="Permanently remove (GDPR)"
                      >
                        <Trash2 size={18} />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="mt-8 p-4 bg-violet-50/50 dark:bg-violet-900/10 border border-violet-100 dark:border-violet-900/20 rounded-2xl flex items-start gap-3">
        <Shield size={18} className="text-violet-500 shrink-0 mt-0.5" />
        <div className="text-xs text-violet-800/70 dark:text-violet-400/70 leading-relaxed">
          <p className="font-bold mb-1">Security Guardrails</p>
          <p>
            You are managing team members for your workspace. Roles control platform permissions.
            Invitations expire in 7 days for security. Deactivated users cannot log in.
            Permanent deletion erases all associated PII to ensure GDPR compliance.
          </p>
        </div>
      </div>
    </div>
  )
}