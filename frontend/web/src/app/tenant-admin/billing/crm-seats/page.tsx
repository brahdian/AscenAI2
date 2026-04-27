'use client'

import { useEffect, useState } from 'react'
import { Database, Plus, Minus, ArrowLeft, ExternalLink } from 'lucide-react'
import Link from 'next/link'

const PRICE_PER_SEAT = Number(process.env.NEXT_PUBLIC_CRM_SEAT_PRICE || 19)

interface Workspace {
  id: string
  company_name: string
  subdomain: string
  user_slots: number
  url: string
}

export default function CRMSeatsPage() {
  const [workspaces, setWorkspaces] = useState<Workspace[]>([])
  const [quantities, setQuantities] = useState<Record<string, number>>({})
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState<string | null>(null)
  const [success, setSuccess] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetch('/api/v1/tenant-admin/crm/workspaces', { credentials: 'include' })
      .then((r) => (r.ok ? r.json() : { workspaces: [] }))
      .then((d) => {
        setWorkspaces(d.workspaces)
        const q: Record<string, number> = {}
        for (const w of d.workspaces) q[w.id] = w.user_slots
        setQuantities(q)
      })
      .finally(() => setLoading(false))
  }, [])

  const handleUpdate = async (workspaceId: string) => {
    setSaving(workspaceId)
    setError(null)
    try {
      const res = await fetch('/api/v1/tenant-admin/billing/crm-seats/update', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ workspace_id: workspaceId, seats: quantities[workspaceId] }),
      })
      if (!res.ok) throw new Error('Failed to update')
      setWorkspaces((prev) =>
        prev.map((w) => (w.id === workspaceId ? { ...w, user_slots: quantities[workspaceId] } : w))
      )
      setSuccess(workspaceId)
      setTimeout(() => setSuccess(null), 2000)
    } catch {
      setError(`Failed to update workspace ${workspaceId}`)
    } finally {
      setSaving(null)
    }
  }

  const totalSeats = workspaces.reduce((s, w) => s + w.user_slots, 0)
  const totalCost = totalSeats * PRICE_PER_SEAT

  return (
    <div className="p-8 max-w-2xl">
      <Link href="/tenant-admin/billing" className="flex items-center gap-1.5 text-sm text-gray-500 hover:text-violet-600 dark:hover:text-violet-400 mb-6 transition-colors">
        <ArrowLeft size={14} /> Back to Billing
      </Link>

      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">CRM Seats</h1>
          <p className="text-gray-500 dark:text-gray-400 mt-1">
            Manage seats per CRM workspace. ${PRICE_PER_SEAT}/seat/mo.
          </p>
        </div>
        <Link
          href="/tenant-admin/crm"
          className="flex items-center gap-1.5 text-sm text-violet-600 dark:text-violet-400 hover:underline"
        >
          Manage workspaces →
        </Link>
      </div>

      {/* Total banner */}
      <div className="mb-6 p-4 bg-violet-50 dark:bg-violet-900/10 border border-violet-100 dark:border-violet-900/30 rounded-xl flex items-center justify-between">
        <span className="text-sm text-violet-700 dark:text-violet-300">Total CRM seats across all workspaces</span>
        <div className="text-right">
          <span className="text-xl font-bold text-violet-700 dark:text-violet-300">{totalSeats} seats</span>
          <span className="text-sm text-violet-600/70 dark:text-violet-400/70 ml-2">${totalCost}/mo</span>
        </div>
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-20">
          <div className="animate-spin rounded-full h-8 w-8 border-t-2 border-b-2 border-violet-500" />
        </div>
      ) : !workspaces.length ? (
        <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 p-8 text-center text-gray-500">
          <Database size={32} className="mx-auto mb-3 opacity-30" />
          <p className="text-sm">No CRM workspaces yet.</p>
          <Link href="/tenant-admin/crm" className="mt-2 inline-block text-sm text-violet-600 dark:text-violet-400 hover:underline">
            Create your first workspace →
          </Link>
        </div>
      ) : (
        <div className="space-y-4">
          {error && (
            <div className="px-4 py-3 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg text-sm text-red-700 dark:text-red-400">
              {error}
            </div>
          )}
          {workspaces.map((ws) => {
            const qty = quantities[ws.id] ?? ws.user_slots
            const diff = qty - ws.user_slots
            return (
              <div key={ws.id} className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 p-5">
                <div className="flex items-center justify-between mb-4">
                  <div className="flex items-center gap-3">
                    <div className="w-9 h-9 rounded-lg bg-blue-100 dark:bg-blue-900/30 flex items-center justify-center">
                      <Database size={18} className="text-blue-600 dark:text-blue-400" />
                    </div>
                    <div>
                      <p className="text-sm font-semibold text-gray-900 dark:text-white">{ws.company_name}</p>
                      <p className="text-xs text-gray-500">{ws.subdomain}.{process.env.NEXT_PUBLIC_ROOT_DOMAIN?.split(':')[0] || 'lvh.me'}</p>
                    </div>
                  </div>
                  <a href={ws.url} target="_blank" rel="noopener noreferrer" className="text-gray-400 hover:text-violet-600 dark:hover:text-violet-400 transition-colors">
                    <ExternalLink size={14} />
                  </a>
                </div>

                {/* Slider */}
                <div className="flex items-center gap-3 mb-4">
                  <button
                    onClick={() => setQuantities((q) => ({ ...q, [ws.id]: Math.max(0, (q[ws.id] ?? ws.user_slots) - 1) }))}
                    className="w-8 h-8 rounded-lg border border-gray-200 dark:border-gray-700 flex items-center justify-center text-gray-600 hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors disabled:opacity-30"
                    disabled={qty <= 0}
                  >
                    <Minus size={14} />
                  </button>
                  <div className="flex-1">
                    <input
                      type="range"
                      min={0}
                      max={100}
                      value={qty}
                      onChange={(e) => setQuantities((q) => ({ ...q, [ws.id]: Number(e.target.value) }))}
                      className="w-full accent-violet-600"
                    />
                    <div className="flex justify-between text-xs text-gray-400 mt-0.5">
                      <span>0</span>
                      <span className="font-bold text-gray-900 dark:text-white">{qty} seats · ${qty * PRICE_PER_SEAT}/mo</span>
                      <span>100</span>
                    </div>
                  </div>
                  <button
                    onClick={() => setQuantities((q) => ({ ...q, [ws.id]: Math.min(100, (q[ws.id] ?? ws.user_slots) + 1) }))}
                    className="w-8 h-8 rounded-lg border border-gray-200 dark:border-gray-700 flex items-center justify-center text-gray-600 hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors"
                  >
                    <Plus size={14} />
                  </button>
                </div>

                <div className="flex items-center justify-between">
                  {diff !== 0 ? (
                    <p className="text-xs text-gray-500">
                      {diff > 0 ? `+${diff} seat${diff > 1 ? 's' : ''} — prorated charge today` : `${Math.abs(diff)} seat${Math.abs(diff) > 1 ? 's' : ''} removed — credit on next invoice`}
                    </p>
                  ) : (
                    <span />
                  )}
                  <div className="flex items-center gap-2">
                    {success === ws.id && (
                      <span className="text-xs text-emerald-600 dark:text-emerald-400">✓ Saved</span>
                    )}
                    <button
                      onClick={() => handleUpdate(ws.id)}
                      disabled={saving === ws.id || qty === ws.user_slots}
                      className="px-3 py-1.5 text-xs font-medium bg-violet-600 hover:bg-violet-700 disabled:opacity-50 text-white rounded-lg transition-colors"
                    >
                      {saving === ws.id ? 'Saving…' : 'Save'}
                    </button>
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
