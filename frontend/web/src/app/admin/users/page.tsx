'use client'

import { useEffect, useState } from 'react'
import { adminApi } from '@/lib/api'
import { Users, ChevronLeft, ChevronRight, Search, Shield, X, ArrowRight, ShieldCheck, Mail } from 'lucide-react'

interface User {
  id: string
  email: string
  name: string
  full_name: string
  role: string
  tenant_id: string
  is_active: boolean
  created_at: string
}

interface UsersResponse {
  users: User[]
  pagination: {
    page: number
    per_page: number
    total: number
    pages: number
  }
}

interface RolesResponse {
  roles: Record<string, { level: number; permissions: string[] }>
}

export default function UsersPage() {
  const [data, setData] = useState<UsersResponse | null>(null)
  const [roles, setRoles] = useState<RolesResponse['roles'] | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [page, setPage] = useState(1)
  const [search, setSearch] = useState('')
  const [editingUser, setEditingUser] = useState<User | null>(null)
  const [newRole, setNewRole] = useState('')
  const [updating, setUpdating] = useState(false)

  useEffect(() => {
    async function fetchData() {
      setLoading(true)
      try {
        const [usersData, rolesData] = await Promise.all([
          adminApi.listUsers({ page, per_page: 20 }),
          adminApi.listRoles(),
        ])
        setData(usersData)
        setRoles(rolesData.roles)
        setError(null)
      } catch (err) {
        setError('Failed to load users')
        console.error(err)
      } finally {
        setLoading(false)
      }
    }
    fetchData()
  }, [page])

  const filteredUsers = data?.users?.filter((u) =>
    search
      ? (u.email || '').toLowerCase().includes(search.toLowerCase()) ||
        (u.full_name || '').toLowerCase().includes(search.toLowerCase())
      : true
  )

  const totalPages = data?.pagination?.pages || 1

  const handleRoleUpdate = async () => {
    if (!editingUser || !newRole) return
    setUpdating(true)
    try {
      await adminApi.updateUserRole(editingUser.id, newRole)
      const usersData = await adminApi.listUsers({ page, per_page: 20 })
      setData(usersData)
      setEditingUser(null)
    } catch (err) {
      alert('Failed to update role')
    } finally {
      setUpdating(false)
    }
  }

  const getRoleLabel = (role: string) => {
    return role?.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase()) || 'Unknown'
  }

  return (
    <div className="p-8 space-y-8">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white tracking-tight">Identity Directory</h1>
          <p className="text-gray-500 dark:text-gray-400 text-sm mt-1">Audit and manage global user accounts and cross-tenant permissions.</p>
        </div>
      </div>

      {/* Filters Bar */}
      <div className="flex flex-col sm:flex-row items-center gap-4 bg-white dark:bg-gray-900 p-4 rounded-2xl border border-gray-100 dark:border-gray-800 shadow-sm">
        <div className="relative flex-1 w-full text-gray-400">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4" />
          <input
            type="text"
            placeholder="Search by name or email address..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full pl-10 pr-4 py-2 bg-gray-50 dark:bg-gray-950 border border-gray-100 dark:border-gray-800 rounded-xl text-gray-900 dark:text-white text-sm placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-violet-500/20 focus:border-violet-500 transition-all"
          />
        </div>
      </div>

      {/* Table Container */}
      <div className="bg-white dark:bg-gray-900 border border-gray-100 dark:border-gray-800 rounded-2xl shadow-sm overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="bg-gray-50/50 dark:bg-gray-800/30 border-b border-gray-100 dark:border-gray-800">
                <th className="px-6 py-4 text-[10px] font-bold text-gray-400 dark:text-gray-500 uppercase tracking-widest">Identified User</th>
                <th className="px-6 py-4 text-[10px] font-bold text-gray-400 dark:text-gray-500 uppercase tracking-widest">Access Level</th>
                <th className="px-6 py-4 text-[10px] font-bold text-gray-400 dark:text-gray-500 uppercase tracking-widest">Account Status</th>
                <th className="px-6 py-4 text-[10px] font-bold text-gray-400 dark:text-gray-500 uppercase tracking-widest">Member Since</th>
                <th className="px-6 py-4 text-right"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50 dark:divide-gray-800">
              {loading ? (
                <tr>
                  <td colSpan={5} className="px-6 py-20 text-center">
                    <div className="flex flex-col items-center gap-3">
                        <div className="w-8 h-8 border-2 border-violet-500 border-t-transparent rounded-full animate-spin"></div>
                        <p className="text-sm text-gray-500 font-medium tracking-tight">Syncing user directory...</p>
                    </div>
                  </td>
                </tr>
              ) : filteredUsers?.length === 0 ? (
                <tr>
                  <td colSpan={5} className="px-6 py-20 text-center">
                     <Users size={40} className="mx-auto text-gray-200 dark:text-gray-800 mb-4" />
                     <p className="text-gray-900 dark:text-white font-bold text-lg">No users found</p>
                     <p className="text-gray-500 text-sm">No results match your current search.</p>
                  </td>
                </tr>
              ) : (
                filteredUsers?.map((user) => (
                  <tr 
                    key={user.id} 
                    className="hover:bg-gray-50 dark:hover:bg-violet-900/5 transition-colors group"
                  >
                    <td className="px-6 py-4">
                      <div className="flex items-center gap-4">
                        <div className="w-10 h-10 rounded-full bg-gradient-to-br from-violet-500 to-blue-500 flex items-center justify-center text-white text-xs font-bold shadow-md">
                          {user.full_name?.charAt(0) || user.name?.charAt(0) || '?'}
                        </div>
                        <div>
                          <p className="text-sm font-bold text-gray-900 dark:text-white">
                            {user.full_name || user.name || 'Unknown User'}
                          </p>
                          <p className="text-xs text-gray-500 flex items-center gap-1.5 truncate max-w-[200px]">
                             <Mail size={12} className="opacity-50" /> {user.email}
                          </p>
                        </div>
                      </div>
                    </td>
                    <td className="px-6 py-4">
                      <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[10px] font-bold uppercase tracking-widest border ${
                        user.role === 'super_admin'
                          ? 'bg-red-50 dark:bg-red-900/10 border-red-100 dark:border-red-900/30 text-red-600 dark:text-red-400'
                          : user.role === 'tenant_owner'
                          ? 'bg-amber-50 dark:bg-amber-900/10 border-amber-100 dark:border-amber-900/30 text-amber-600 dark:text-amber-400'
                          : 'bg-blue-50 dark:bg-blue-900/10 border-blue-100 dark:border-blue-900/30 text-blue-600 dark:text-blue-400'
                      }`}>
                        {user.role === 'super_admin' && <ShieldCheck size={10} />}
                        {getRoleLabel(user.role)}
                      </span>
                    </td>
                    <td className="px-6 py-4">
                      <span
                        className={`inline-flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-widest px-2 py-1 rounded-md border ${
                          user.is_active
                            ? 'bg-emerald-50 dark:bg-emerald-900/10 border-emerald-100 dark:border-emerald-800 text-emerald-600 dark:text-emerald-400'
                            : 'bg-red-50 dark:bg-red-900/10 border-red-100 dark:border-red-900/30 text-red-600 dark:text-red-400'
                        }`}
                      >
                         <div className={`w-1 h-1 rounded-full ${user.is_active ? 'bg-emerald-500' : 'bg-red-500'}`}></div>
                         {user.is_active ? 'Active' : 'Suspended'}
                      </span>
                    </td>
                    <td className="px-6 py-4">
                      <span className="text-sm text-gray-500 font-medium">
                        {new Date(user.created_at).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })}
                      </span>
                    </td>
                    <td className="px-6 py-4 text-right">
                       <button 
                          onClick={() => {
                            setEditingUser(user)
                            setNewRole(user.role)
                          }}
                          className="px-3 py-1.5 text-xs font-bold text-violet-600 dark:text-violet-400 hover:bg-violet-50 dark:hover:bg-violet-900/20 rounded-lg transition-all"
                       >
                          Revise Role
                       </button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        {/* Pagination Status */}
        <div className="px-6 py-4 bg-gray-50/50 dark:bg-gray-800/30 border-t border-gray-100 dark:border-gray-800 flex items-center justify-between">
           <p className="text-xs font-bold text-gray-400 dark:text-gray-500 uppercase tracking-widest">
              Total Managed Identities: {data?.pagination?.total || 0}
           </p>
           {totalPages > 1 && (
             <div className="flex items-center gap-1">
                <button
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  disabled={page <= 1}
                  className="p-1.5 border border-gray-200 dark:border-gray-800 rounded-lg text-gray-500 hover:text-violet-600 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                >
                  <ChevronLeft size={16} />
                </button>
                <div className="flex gap-1">
                   {Array.from({ length: Math.min(5, totalPages) }, (_, i) => (
                      <button 
                        key={i} 
                        onClick={() => setPage(i + 1)}
                        className={`w-8 h-8 rounded-lg text-xs font-bold transition-all ${page === i + 1 ? 'bg-violet-600 text-white shadow-md shadow-violet-500/20' : 'text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800'}`}
                      >
                         {i + 1}
                      </button>
                   ))}
                </div>
                <button
                  onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                  disabled={page >= totalPages}
                  className="p-1.5 border border-gray-200 dark:border-gray-800 rounded-lg text-gray-500 hover:text-violet-600 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                >
                  <ChevronRight size={16} />
                </button>
             </div>
           )}
        </div>
      </div>

      {/* Edit Role Modal */}
      {editingUser && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-gray-950/40 backdrop-blur-md animate-in fade-in duration-300">
          <div className="bg-white dark:bg-gray-900 border border-gray-100 dark:border-gray-800 rounded-3xl w-full max-w-md shadow-2xl shadow-gray-950/20 overflow-hidden ring-1 ring-white/10">
            <div className="flex items-center justify-between px-8 py-6 border-b border-gray-100 dark:border-gray-800 bg-gray-50/50 dark:bg-gray-800/20">
              <div>
                  <h2 className="text-xl font-bold text-gray-900 dark:text-white tracking-tight">Identity Overhaul</h2>
                  <p className="text-xs text-gray-500 dark:text-gray-400 font-medium">Re-assigning platform-wide access level.</p>
              </div>
              <button 
                onClick={() => setEditingUser(null)} 
                className="p-2 text-gray-400 hover:text-gray-600 dark:hover:text-white hover:bg-gray-100 dark:hover:bg-gray-800 rounded-xl transition-all"
              >
                <X size={20} />
              </button>
            </div>
            <div className="p-8 space-y-6">
              <div className="flex items-center gap-4 p-4 bg-violet-50/50 dark:bg-violet-900/5 border border-violet-100 dark:border-violet-900/20 rounded-2xl">
                <div className="w-12 h-12 rounded-full bg-gradient-to-br from-violet-500 to-blue-500 flex items-center justify-center text-white text-sm font-bold shadow-md">
                   {editingUser.full_name?.charAt(0) || editingUser.name?.charAt(0)}
                </div>
                <div>
                  <p className="text-sm font-bold text-gray-900 dark:text-white">{editingUser.full_name || editingUser.name}</p>
                  <p className="text-xs text-violet-600 dark:text-violet-400 font-mono">{editingUser.email}</p>
                </div>
              </div>
              
              <div>
                <label className="block text-[10px] font-bold text-gray-400 dark:text-gray-500 uppercase tracking-widest mb-2">New Access Privilege</label>
                <select
                  value={newRole}
                  onChange={(e) => setNewRole(e.target.value)}
                  className="w-full px-4 py-3 bg-gray-50 dark:bg-gray-950 border border-gray-100 dark:border-gray-800 rounded-xl text-gray-900 dark:text-white text-sm font-bold focus:outline-none focus:ring-2 focus:ring-violet-500/20"
                >
                  {roles && Object.entries(roles).map(([role, config]) => (
                    <option key={role} value={role}>
                      {getRoleLabel(role)} (Level {config.level})
                    </option>
                  ))}
                </select>
                <p className="mt-2 text-[10px] text-gray-500 flex items-center gap-1.5">
                   <Shield size={12} className="opacity-50" /> Higher levels grant more destructive platform capabilities.
                </p>
              </div>

              <div className="flex gap-4 pt-4">
                <button
                  onClick={() => setEditingUser(null)}
                  className="flex-1 px-6 py-3 bg-gray-100 dark:bg-gray-800 hover:bg-gray-200 dark:hover:bg-gray-700 text-gray-600 dark:text-white rounded-xl text-sm font-bold transition-all"
                >
                  Cancel
                </button>
                <button
                  onClick={handleRoleUpdate}
                  disabled={updating || newRole === editingUser.role}
                  className="flex-1 px-6 py-3 bg-violet-600 hover:bg-violet-700 text-white rounded-xl text-sm font-bold transition-all shadow-lg shadow-violet-500/20 disabled:opacity-50 group"
                >
                  {updating ? (
                    <div className="flex items-center justify-center gap-2">
                       <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin"></div>
                       <span>Updating...</span>
                    </div>
                  ) : (
                    <div className="flex items-center justify-center gap-2">
                       <span>Apply Changes</span>
                       <ArrowRight size={16} className="group-hover:translate-x-1 transition-transform" />
                    </div>
                  )}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}