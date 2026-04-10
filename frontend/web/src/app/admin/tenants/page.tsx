'use client'

import { useEffect, useState } from 'react'
import { adminApi } from '@/lib/api'
import { Building2, Plus, Search, ChevronLeft, ChevronRight, X, ExternalLink, ArrowRight, Users } from 'lucide-react'

interface Tenant {
  id: string
  name: string
  business_name: string
  plan: string
  status: string
  created_at: string
  agent_count?: number
  user_count?: number
}

interface TenantsResponse {
  tenants: Tenant[]
  pagination: {
    page: number
    per_page: number
    total: number
    pages: number
  }
}

export default function TenantsPage() {
  const [data, setData] = useState<TenantsResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [page, setPage] = useState(1)
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [showCreateModal, setShowCreateModal] = useState(false)

  useEffect(() => {
    async function fetchTenants() {
      setLoading(true)
      try {
        const result = await adminApi.listTenants({ page, per_page: 20, status: statusFilter || undefined })
        setData(result)
        setError(null)
      } catch (err) {
        setError('Failed to load tenants')
        console.error(err)
      } finally {
        setLoading(false)
      }
    }
    fetchTenants()
  }, [page, statusFilter])

  const filteredTenants = data?.tenants?.filter((t) =>
    search
      ? (t.business_name || t.name || '').toLowerCase().includes(search.toLowerCase())
      : true
  )

  const totalPages = data?.pagination?.pages || 1

  return (
    <div className="p-8 space-y-8">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white tracking-tight">Tenants</h1>
          <p className="text-gray-500 dark:text-gray-400 text-sm mt-1">Manage and provision organization accounts across the platform.</p>
        </div>
        <button
          onClick={() => setShowCreateModal(true)}
          className="inline-flex items-center justify-center gap-2 px-4 py-2 bg-violet-600 hover:bg-violet-700 text-white rounded-xl text-sm font-bold transition-all shadow-lg shadow-violet-500/20 active:scale-95"
        >
          <Plus size={18} />
          Provision New Tenant
        </button>
      </div>

      {/* Filters Bar */}
      <div className="flex flex-col sm:flex-row items-center gap-4 bg-white dark:bg-gray-900 p-4 rounded-2xl border border-gray-100 dark:border-gray-800 shadow-sm">
        <div className="relative flex-1 w-full">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
          <input
            type="text"
            placeholder="Search by business name or slug..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full pl-10 pr-4 py-2 bg-gray-50 dark:bg-gray-950 border border-gray-100 dark:border-gray-800 rounded-xl text-gray-900 dark:text-white text-sm placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-violet-500/20 focus:border-violet-500 transition-all"
          />
        </div>
        <select
          value={statusFilter}
          onChange={(e) => { setStatusFilter(e.target.value); setPage(1); }}
          className="w-full sm:w-auto px-4 py-2 bg-gray-50 dark:bg-gray-950 border border-gray-100 dark:border-gray-800 rounded-xl text-gray-900 dark:text-white text-sm font-medium focus:outline-none focus:ring-2 focus:ring-violet-500/20"
        >
          <option value="">All Statuses</option>
          <option value="active">Active</option>
          <option value="suspended">Suspended</option>
          <option value="deleted">Deleted</option>
        </select>
      </div>

      {/* Table Container */}
      <div className="bg-white dark:bg-gray-900 border border-gray-100 dark:border-gray-800 rounded-2xl shadow-sm overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="bg-gray-50/50 dark:bg-gray-800/30 border-b border-gray-100 dark:border-gray-800">
                <th className="px-6 py-4 text-[10px] font-bold text-gray-400 dark:text-gray-500 uppercase tracking-widest">Organization</th>
                <th className="px-6 py-4 text-[10px] font-bold text-gray-400 dark:text-gray-500 uppercase tracking-widest">Plan</th>
                <th className="px-6 py-4 text-[10px] font-bold text-gray-400 dark:text-gray-500 uppercase tracking-widest">Agents</th>
                <th className="px-6 py-4 text-[10px] font-bold text-gray-400 dark:text-gray-500 uppercase tracking-widest">Status</th>
                <th className="px-6 py-4 text-[10px] font-bold text-gray-400 dark:text-gray-500 uppercase tracking-widest">Created</th>
                <th className="px-6 py-4 text-right"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50 dark:divide-gray-800">
              {loading ? (
                <tr>
                  <td colSpan={5} className="px-6 py-20 text-center">
                    <div className="flex flex-col items-center gap-3">
                        <div className="w-8 h-8 border-2 border-violet-500 border-t-transparent rounded-full animate-spin"></div>
                        <p className="text-sm text-gray-500 font-medium tracking-tight">Loading tenants…</p>
                    </div>
                  </td>
                </tr>
              ) : filteredTenants?.length === 0 ? (
                <tr>
                  <td colSpan={5} className="px-6 py-20 text-center">
                     <Building2 size={40} className="mx-auto text-gray-200 dark:text-gray-800 mb-4" />
                     <p className="text-gray-900 dark:text-white font-bold text-lg">No tenants found</p>
                     <p className="text-gray-500 text-sm">No results match your current search or filter criteria.</p>
                  </td>
                </tr>
              ) : (
                filteredTenants?.map((tenant) => (
                  <tr 
                    key={tenant.id} 
                    className="hover:bg-gray-50 dark:hover:bg-violet-900/5 transition-colors cursor-pointer group"
                    onClick={() => window.location.href = `/admin/tenants/${tenant.id}`}
                  >
                    <td className="px-6 py-4">
                      <div className="flex items-center gap-4">
                        <div className="w-10 h-10 rounded-xl bg-gray-100 dark:bg-gray-800 flex items-center justify-center text-gray-400 dark:text-gray-600 group-hover:bg-violet-100 dark:group-hover:bg-violet-900/30 group-hover:text-violet-600 dark:group-hover:text-violet-400 transition-all duration-300">
                          <Building2 size={20} />
                        </div>
                        <div>
                          <p className="text-sm font-bold text-gray-900 dark:text-white decoration-violet-500/30 group-hover:underline">
                            {tenant.business_name || tenant.name || 'Unnamed Organization'}
                          </p>
                          <p className="text-[10px] text-gray-400 font-mono uppercase tracking-tight">{tenant.id.split('-')[0]}</p>
                        </div>
                      </div>
                    </td>
                    <td className="px-6 py-4">
                      <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-violet-50 dark:bg-violet-900/10 text-violet-700 dark:text-violet-300 capitalize">
                        {tenant.plan || 'Free'}
                      </span>
                    </td>
                    <td className="px-6 py-4 text-sm text-gray-500 dark:text-gray-400">
                      {tenant.agent_count ?? '—'}
                    </td>
                    <td className="px-6 py-4">
                      <span
                        className={`inline-flex items-center gap-1.5 text-xs font-medium px-2.5 py-0.5 rounded-full ${
                          tenant.status === 'active'
                            ? 'bg-emerald-50 dark:bg-emerald-900/10 text-emerald-700 dark:text-emerald-400'
                            : tenant.status === 'suspended'
                            ? 'bg-red-50 dark:bg-red-900/10 text-red-700 dark:text-red-400'
                            : 'bg-gray-100 dark:bg-gray-800 text-gray-500 dark:text-gray-400'
                        }`}
                      >
                         {tenant.status}
                      </span>
                    </td>
                    <td className="px-6 py-4">
                      <span className="text-sm text-gray-500 font-medium">
                        {new Date(tenant.created_at).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })}
                      </span>
                    </td>
                    <td className="px-6 py-4 text-right text-gray-300">
                       <ExternalLink size={16} className="ml-auto group-hover:text-violet-500 transition-colors" />
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
              Showing {filteredTenants?.length || 0} of {data?.pagination?.total || 0} tenants
           </p>
           {totalPages > 1 && (
             <div className="flex items-center gap-1">
                <button
                  onClick={(e) => { e.stopPropagation(); setPage((p) => Math.max(1, p - 1)); }}
                  disabled={page <= 1}
                  className="p-1.5 border border-gray-200 dark:border-gray-800 rounded-lg text-gray-500 hover:text-violet-600 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                >
                  <ChevronLeft size={16} />
                </button>
                <div className="flex gap-1">
                   {Array.from({ length: Math.min(5, totalPages) }, (_, i) => (
                      <button 
                        key={i} 
                        onClick={(e) => { e.stopPropagation(); setPage(i + 1); }}
                        className={`w-8 h-8 rounded-lg text-xs font-bold transition-all ${page === i + 1 ? 'bg-violet-600 text-white shadow-md shadow-violet-500/20' : 'text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800'}`}
                      >
                         {i + 1}
                      </button>
                   ))}
                </div>
                <button
                  onClick={(e) => { e.stopPropagation(); setPage((p) => Math.min(totalPages, p + 1)); }}
                  disabled={page >= totalPages}
                  className="p-1.5 border border-gray-200 dark:border-gray-800 rounded-lg text-gray-500 hover:text-violet-600 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                >
                  <ChevronRight size={16} />
                </button>
             </div>
           )}
        </div>
      </div>

      {/* Create Tenant Modal */}
      {showCreateModal && (
        <CreateTenantModal
          onClose={() => setShowCreateModal(false)}
          onCreated={(tenant) => {
            setShowCreateModal(false)
            window.location.href = `/admin/tenants/${tenant.id}`
          }}
        />
      )}
    </div>
  )
}

function CreateTenantModal({ onClose, onCreated }: { onClose: () => void; onCreated: (tenant: { id: string }) => void }) {
  const [form, setForm] = useState({
    name: '',
    business_name: '',
    plan: 'starter',
    admin_email: '',
    admin_password: '',
  })
  const [error, setError] = useState<string | null>(null)
  const [creating, setCreating] = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setCreating(true)
    setError(null)
    try {
      const response = await adminApi.createTrialTenant(form)
      onCreated(response)
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to create tenant')
    } finally {
      setCreating(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-gray-950/40 backdrop-blur-md animate-in fade-in duration-300">
      <div className="bg-white dark:bg-gray-900 border border-gray-100 dark:border-gray-800 rounded-3xl w-full max-w-lg shadow-2xl shadow-gray-950/20 overflow-hidden ring-1 ring-white/10">
        <div className="flex items-center justify-between px-8 py-6 border-b border-gray-100 dark:border-gray-800 bg-gray-50/50 dark:bg-gray-800/20">
          <div>
              <h2 className="text-xl font-bold text-gray-900 dark:text-white tracking-tight">Provision New Tenant</h2>
              <p className="text-xs text-gray-500 dark:text-gray-400 font-medium">Create a new organization account with an admin user.</p>
          </div>
          <button onClick={onClose} className="p-2 text-gray-400 hover:text-gray-600 dark:hover:text-white hover:bg-gray-100 dark:hover:bg-gray-800 rounded-xl transition-all">
            <X size={20} />
          </button>
        </div>
        <form onSubmit={handleSubmit} className="p-8 space-y-6">
          {error && (
            <div className="p-4 bg-red-50 dark:bg-red-900/10 border border-red-100 dark:border-red-900/30 rounded-2xl text-red-600 dark:text-red-400 text-xs font-bold uppercase tracking-wide flex items-center gap-3">
              <div className="w-1.5 h-1.5 rounded-full bg-red-600 animate-pulse"></div>
              {error}
            </div>
          )}
          
          <div className="grid grid-cols-2 gap-4">
             <div className="col-span-2 sm:col-span-1">
                <label className="block text-[10px] font-bold text-gray-400 dark:text-gray-500 uppercase tracking-widest mb-2">Slug (URL identifier)</label>
                <input
                  type="text"
                  required
                  value={form.name}
                  onChange={(e) => setForm({ ...form, name: e.target.value })}
                  className="w-full px-4 py-2.5 bg-gray-50 dark:bg-gray-950 border border-gray-100 dark:border-gray-800 rounded-xl text-gray-900 dark:text-white text-sm focus:outline-none focus:ring-2 focus:ring-violet-500/20 focus:border-violet-500 transition-all"
                  placeholder="acme-corp"
                />
             </div>
             <div className="col-span-2 sm:col-span-1">
                <label className="block text-[10px] font-bold text-gray-400 dark:text-gray-500 uppercase tracking-widest mb-2">Service Tier</label>
                <select
                  value={form.plan}
                  onChange={(e) => setForm({ ...form, plan: e.target.value })}
                  className="w-full px-4 py-2.5 bg-gray-50 dark:bg-gray-950 border border-gray-100 dark:border-gray-800 rounded-xl text-gray-900 dark:text-white text-sm font-bold focus:outline-none focus:ring-2 focus:ring-violet-500/20"
                >
                  <option value="starter">Starter</option>
                  <option value="professional">Professional</option>
                  <option value="enterprise">Enterprise</option>
                </select>
             </div>
          </div>

          <div>
            <label className="block text-[10px] font-bold text-gray-400 dark:text-gray-500 uppercase tracking-widest mb-2">Commercial Business Name</label>
            <input
              type="text"
              required
              value={form.business_name}
              onChange={(e) => setForm({ ...form, business_name: e.target.value })}
              className="w-full px-4 py-2.5 bg-gray-50 dark:bg-gray-950 border border-gray-100 dark:border-gray-800 rounded-xl text-gray-900 dark:text-white text-sm focus:outline-none focus:ring-2 focus:ring-violet-500/20 focus:border-violet-500 transition-all"
              placeholder="Acme Corporation LLC"
            />
          </div>

          <div className="p-6 bg-violet-50/50 dark:bg-violet-900/5 rounded-3xl border border-violet-100 dark:border-violet-900/20 space-y-4">
             <h3 className="text-xs font-bold text-violet-600 dark:text-violet-400 uppercase tracking-widest flex items-center gap-2">
                <Users size={14} /> Admin Account
             </h3>
             <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div>
                   <label className="block text-[10px] font-bold text-gray-400 dark:text-gray-500 uppercase tracking-widest mb-2">Admin Email</label>
                   <input
                     type="email"
                     required
                     value={form.admin_email}
                     onChange={(e) => setForm({ ...form, admin_email: e.target.value })}
                     className="w-full px-4 py-2.5 bg-white dark:bg-gray-900 border border-gray-100 dark:border-gray-800 rounded-xl text-gray-900 dark:text-white text-sm focus:outline-none focus:ring-2 focus:ring-violet-500/20"
                     placeholder="admin@acme.com"
                   />
                </div>
                <div>
                   <label className="block text-[10px] font-bold text-gray-400 dark:text-gray-500 uppercase tracking-widest mb-2">Secure Passcode</label>
                   <input
                     type="password"
                     required
                     value={form.admin_password}
                     onChange={(e) => setForm({ ...form, admin_password: e.target.value })}
                     className="w-full px-4 py-2.5 bg-white dark:bg-gray-900 border border-gray-100 dark:border-gray-800 rounded-xl text-gray-900 dark:text-white text-sm focus:outline-none focus:ring-2 focus:ring-violet-500/20"
                     placeholder="••••••••"
                   />
                </div>
             </div>
          </div>

          <div className="flex gap-4 pt-4">
            <button
              type="button"
              onClick={onClose}
              className="flex-1 px-6 py-3 bg-gray-100 dark:bg-gray-800 hover:bg-gray-200 dark:hover:bg-gray-700 text-gray-600 dark:text-white rounded-xl text-sm font-bold transition-all"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={creating}
              className="flex-1 px-6 py-3 bg-violet-600 hover:bg-violet-700 text-white rounded-xl text-sm font-bold transition-all shadow-lg shadow-violet-500/20 disabled:opacity-50 disabled:cursor-not-allowed group"
            >
              {creating ? (
                  <div className="flex items-center justify-center gap-2">
                     <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin"></div>
                     <span>Provisioning...</span>
                  </div>
              ) : (
                  <div className="flex items-center justify-center gap-2">
                     <span>Provision Tenant</span>
                     <ArrowRight size={16} className="group-hover:translate-x-1 transition-transform" />
                  </div>
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}