'use client'

import { useEffect, useState } from 'react'
import { CreditCard, Bot, Database, FileText, BarChart2, ArrowRight } from 'lucide-react'
import Link from 'next/link'

interface BillingOverview {
  plan: string
  plan_display_name: string
  subscription_status: string
  agent_slots: { purchased: number; price_per_slot: number; monthly_cost: number }
  crm_seats: { total_purchased: number; price_per_seat: number; monthly_cost: number }
  estimated_total: number
}

function BillingCard({
  icon: Icon,
  title,
  value,
  sub,
  color,
  href,
}: {
  icon: React.ElementType
  title: string
  value: string
  sub?: string
  color: string
  href: string
}) {
  return (
    <Link
      href={href}
      className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 p-5 hover:border-violet-200 dark:hover:border-violet-700 transition-colors group"
    >
      <div className="flex items-center justify-between mb-3">
        <span className="text-sm text-gray-500 dark:text-gray-400">{title}</span>
        <div className={`w-8 h-8 rounded-lg ${color} flex items-center justify-center`}>
          <Icon size={16} className="text-white" />
        </div>
      </div>
      <p className="text-2xl font-bold text-gray-900 dark:text-white">{value}</p>
      {sub && <p className="text-xs text-gray-500 mt-1">{sub}</p>}
      <div className="mt-3 flex items-center gap-1 text-xs text-violet-600 dark:text-violet-400 opacity-0 group-hover:opacity-100 transition-opacity">
        Manage <ArrowRight size={12} />
      </div>
    </Link>
  )
}

export default function BillingPage() {
  const [data, setData] = useState<BillingOverview | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetch('/api/v1/tenant-admin/billing/overview', { credentials: 'include' })
      .then((r) => (r.ok ? r.json() : null))
      .then(setData)
      .finally(() => setLoading(false))
  }, [])

  return (
    <div className="p-8">
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Billing</h1>
        <p className="text-gray-500 dark:text-gray-400 mt-1">
          Manage your plan, agent slots, and CRM seats.
        </p>
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-20">
          <div className="animate-spin rounded-full h-8 w-8 border-t-2 border-b-2 border-violet-500" />
        </div>
      ) : (
        <>
          {/* Plan banner */}
          <div className="mb-6 bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 p-5 flex items-center justify-between">
            <div className="flex items-center gap-4">
              <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-violet-500 to-blue-500 flex items-center justify-center">
                <CreditCard size={20} className="text-white" />
              </div>
              <div>
                <p className="text-sm text-gray-500 dark:text-gray-400">Current plan</p>
                <p className="text-lg font-bold text-gray-900 dark:text-white">{data?.plan_display_name ?? '—'}</p>
              </div>
            </div>
            <div className="text-right">
              <p className="text-xs text-gray-500">Est. monthly</p>
              <p className="text-2xl font-bold text-gray-900 dark:text-white">
                ${data?.estimated_total?.toFixed(2) ?? '0.00'}
              </p>
            </div>
          </div>

          {/* Slot cards */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
            <BillingCard
              icon={Bot}
              title="Agent Slots"
              value={String(data?.agent_slots.purchased ?? 0)}
              sub={`$${data?.agent_slots.monthly_cost?.toFixed(2) ?? '0'}/mo`}
              color="bg-violet-500"
              href="/tenant-admin/billing/agent-slots"
            />
            <BillingCard
              icon={Database}
              title="CRM Seats"
              value={String(data?.crm_seats.total_purchased ?? 0)}
              sub={`$${data?.crm_seats.monthly_cost?.toFixed(2) ?? '0'}/mo`}
              color="bg-blue-500"
              href="/tenant-admin/billing/crm-seats"
            />
            <BillingCard
              icon={BarChart2}
              title="Analytics"
              value="View"
              sub="Usage & cost breakdown"
              color="bg-emerald-500"
              href="/tenant-admin/billing/analytics"
            />
            <BillingCard
              icon={FileText}
              title="Invoices"
              value="History"
              sub="Past payments"
              color="bg-orange-500"
              href="/tenant-admin/billing/invoices"
            />
          </div>

          {/* Quick actions */}
          <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 p-6">
            <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">Quick actions</h2>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {[
                { href: '/tenant-admin/billing/agent-slots', label: 'Adjust agent slots', desc: 'Increase or decrease AI agent seats', icon: '🤖' },
                { href: '/tenant-admin/billing/crm-seats', label: 'Manage CRM seats', desc: 'Add or remove CRM user slots', icon: '🗂️' },
              ].map((a) => (
                <Link
                  key={a.href}
                  href={a.href}
                  className="flex items-center gap-4 p-4 rounded-lg border border-gray-100 dark:border-gray-800 hover:border-violet-200 dark:hover:border-violet-700 hover:bg-violet-50/50 dark:hover:bg-violet-900/10 transition-colors group"
                >
                  <span className="text-2xl">{a.icon}</span>
                  <div>
                    <p className="text-sm font-medium text-gray-900 dark:text-white group-hover:text-violet-700 dark:group-hover:text-violet-300 transition-colors">
                      {a.label}
                    </p>
                    <p className="text-xs text-gray-500">{a.desc}</p>
                  </div>
                </Link>
              ))}
            </div>
          </div>
        </>
      )}
    </div>
  )
}
