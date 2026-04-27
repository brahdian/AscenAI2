'use client'

import { useEffect, useState } from 'react'
import { useAuthStore } from '@/store/auth'
import {
  Bot, Database, Users, CreditCard, TrendingUp,
  Zap, ExternalLink, ArrowRight, CheckCircle, Clock,
} from 'lucide-react'
import Link from 'next/link'

interface Overview {
  tenant: {
    name: string
    plan_display_name: string
    subscription_status: string
  }
  products: {
    agents: { enabled: boolean; agent_slots_purchased: number }
    crm: {
      enabled: boolean
      workspace_count: number
      total_crm_seats: number
      crm_members_count: number
    }
  }
  team: { total_members: number }
}

function StatCard({
  icon: Icon,
  label,
  value,
  sub,
  color,
  href,
}: {
  icon: React.ElementType
  label: string
  value: string | number
  sub?: string
  color: string
  href?: string
}) {
  const inner = (
    <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 p-5 hover:border-violet-200 dark:hover:border-violet-700 transition-colors group">
      <div className="flex items-center justify-between mb-3">
        <span className="text-sm text-gray-500 dark:text-gray-400">{label}</span>
        <div className={`w-8 h-8 rounded-lg ${color} flex items-center justify-center`}>
          <Icon size={16} className="text-white" />
        </div>
      </div>
      <p className="text-2xl font-bold text-gray-900 dark:text-white">{value}</p>
      {sub && <p className="text-xs text-gray-500 mt-1">{sub}</p>}
      {href && (
        <div className="mt-3 flex items-center gap-1 text-xs text-violet-600 dark:text-violet-400 opacity-0 group-hover:opacity-100 transition-opacity">
          Manage <ArrowRight size={12} />
        </div>
      )}
    </div>
  )
  return href ? <Link href={href}>{inner}</Link> : inner
}

function ProductCard({
  icon: Icon,
  title,
  description,
  enabled,
  href,
  externalHref,
  badge,
}: {
  icon: React.ElementType
  title: string
  description: string
  enabled: boolean
  href?: string
  externalHref?: string
  badge?: string
}) {
  return (
    <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 p-6">
      <div className="flex items-start justify-between mb-4">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-violet-500 to-blue-500 flex items-center justify-center text-white">
            <Icon size={20} />
          </div>
          <div>
            <h3 className="text-sm font-semibold text-gray-900 dark:text-white">{title}</h3>
            {badge && (
              <span className="text-[10px] font-bold uppercase tracking-wider text-violet-600 dark:text-violet-400">
                {badge}
              </span>
            )}
          </div>
        </div>
        <span className={`flex items-center gap-1 text-xs font-medium px-2 py-0.5 rounded-full ${
          enabled
            ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-900/20 dark:text-emerald-400'
            : 'bg-gray-100 text-gray-500 dark:bg-gray-800 dark:text-gray-500'
        }`}>
          {enabled ? <CheckCircle size={12} /> : <Clock size={12} />}
          {enabled ? 'Active' : 'Not set up'}
        </span>
      </div>
      <p className="text-sm text-gray-500 dark:text-gray-400 mb-4">{description}</p>
      <div className="flex items-center gap-2">
        {href && (
          <Link
            href={href}
            className="text-xs font-medium text-violet-600 dark:text-violet-400 hover:underline"
          >
            Manage →
          </Link>
        )}
        {externalHref && (
          <a
            href={externalHref}
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-1 text-xs text-gray-500 hover:text-gray-700 dark:hover:text-gray-200"
          >
            Open <ExternalLink size={11} />
          </a>
        )}
      </div>
    </div>
  )
}

export default function TenantAdminHubPage() {
  const { user } = useAuthStore()
  const [overview, setOverview] = useState<Overview | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetch('/api/v1/tenant-admin/overview', { credentials: 'include' })
      .then((r) => r.ok ? r.json() : null)
      .then((d) => setOverview(d))
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  const crmUrl = typeof window !== 'undefined'
    ? `${window.location.protocol}//${process.env.NEXT_PUBLIC_CRM_SUBDOMAIN || window.location.host.replace(/^admin\./, 'crm.')}`
    : `http://${process.env.NEXT_PUBLIC_CRM_SUBDOMAIN || 'crm.lvh.me:3001'}`

  return (
    <div className="p-8">
      {/* Header */}
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-gray-900 dark:text-white">
          Good day, {user?.full_name?.split(' ')[0] || 'there'} 👋
        </h1>
        <p className="text-gray-500 dark:text-gray-400 mt-1">
          Manage your team, billing, and products from one place.
        </p>
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-20">
          <div className="animate-spin rounded-full h-8 w-8 border-t-2 border-b-2 border-violet-500" />
        </div>
      ) : (
        <>
          {/* Stats row — same pattern as dashboard StatCard */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
            <StatCard
              icon={Bot}
              label="Agent Slots"
              value={overview?.products.agents.agent_slots_purchased ?? 0}
              sub="Purchased seats"
              color="bg-violet-500"
              href="/tenant-admin/billing/agent-slots"
            />
            <StatCard
              icon={Database}
              label="CRM Seats"
              value={overview?.products.crm.total_crm_seats ?? 0}
              sub="Across all workspaces"
              color="bg-blue-500"
              href="/tenant-admin/billing/crm-seats"
            />
            <StatCard
              icon={Users}
              label="Team Members"
              value={overview?.team.total_members ?? 0}
              sub="Active members"
              color="bg-emerald-500"
              href="/tenant-admin/members"
            />
            <StatCard
              icon={TrendingUp}
              label="Plan"
              value={overview?.tenant.plan_display_name ?? '—'}
              sub={overview?.tenant.subscription_status ?? ''}
              color="bg-orange-500"
              href="/tenant-admin/billing"
            />
          </div>

          {/* Products */}
          <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 p-6 mb-6">
            <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">Products</h2>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <ProductCard
                icon={Bot}
                title="AI Agents"
                description="Build and deploy AI voice & chat agents for your business."
                enabled={true}
                href="/tenant-admin/billing/agent-slots"
                externalHref={
                  typeof window !== 'undefined'
                    ? `${window.location.protocol}//${window.location.host.replace(/^admin\./, 'agents.')}`
                    : undefined
                }
                badge="Core Product"
              />
              <ProductCard
                icon={Database}
                title="CRM"
                description="Manage your contacts, pipeline, and customer relationships."
                enabled={!!overview?.products.crm.enabled}
                href="/tenant-admin/crm"
                externalHref={overview?.products.crm.enabled ? crmUrl : undefined}
                badge={overview?.products.crm.enabled ? `${overview.products.crm.workspace_count} workspace${overview.products.crm.workspace_count !== 1 ? 's' : ''}` : 'Add-on'}
              />
            </div>
          </div>

          {/* Quick actions — same card style */}
          <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 p-6">
            <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">Quick actions</h2>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
              {[
                { href: '/tenant-admin/members/invite', label: 'Invite member', desc: 'Add someone to your team', icon: '👥' },
                { href: '/tenant-admin/billing/agent-slots', label: 'Manage agent slots', desc: 'Increase or decrease seats', icon: '🤖' },
                { href: '/tenant-admin/crm', label: 'CRM workspaces', desc: 'Configure CRM access', icon: '🗂️' },
              ].map((action) => (
                <Link
                  key={action.href}
                  href={action.href}
                  className="flex items-center gap-4 p-4 rounded-lg border border-gray-100 dark:border-gray-800 hover:border-violet-200 dark:hover:border-violet-700 hover:bg-violet-50/50 dark:hover:bg-violet-900/10 transition-colors group"
                >
                  <span className="text-2xl">{action.icon}</span>
                  <div>
                    <p className="text-sm font-medium text-gray-900 dark:text-white group-hover:text-violet-700 dark:group-hover:text-violet-300 transition-colors">
                      {action.label}
                    </p>
                    <p className="text-xs text-gray-500">{action.desc}</p>
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
