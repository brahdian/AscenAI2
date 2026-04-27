'use client'

import { useEffect, useState } from 'react'
import { useRouter, usePathname } from 'next/navigation'
import Link from 'next/link'
import { useAuthStore } from '@/store/auth'
import {
  LayoutDashboard,
  Users,
  CreditCard,
  Database,
  Settings,
  LogOut,
  Bot,
  ChevronRight,
  ExternalLink,
  Building2,
  ShieldCheck,
  Terminal,
  BarChart2,
  Zap,
} from 'lucide-react'

const AGENTS_URL =
  typeof window !== 'undefined'
    ? `${window.location.protocol}//${process.env.NEXT_PUBLIC_AGENTS_SUBDOMAIN || window.location.host.replace(/^admin\./, 'agents.')}`
    : `http://${process.env.NEXT_PUBLIC_AGENTS_SUBDOMAIN || 'agents.lvh.me:3000'}`

const navItems = [
  { href: '/tenant-admin', icon: LayoutDashboard, label: 'Overview', exact: true },
  { href: '/tenant-admin/members', icon: Users, label: 'Members & RBAC' },
  { href: '/tenant-admin/billing', icon: CreditCard, label: 'Billing' },
  { href: '/tenant-admin/crm', icon: Database, label: 'CRM Workspaces' },
  { href: '/tenant-admin/settings', icon: Settings, label: 'Settings' },
]

const SEGMENT_LABELS: Record<string, string> = {
  'tenant-admin': 'Admin',
  members: 'Members',
  invite: 'Invite',
  billing: 'Billing',
  analytics: 'Analytics',
  'agent-slots': 'Agent Slots',
  'crm-seats': 'CRM Seats',
  crm: 'CRM Workspaces',
  settings: 'Settings',
}

function Breadcrumbs({ pathname }: { pathname: string }) {
  if (pathname === '/tenant-admin') return null
  const segments = pathname.replace(/^\/tenant-admin\/?/, '').split('/').filter(Boolean)
  if (!segments.length) return null

  const crumbs: { label: string; href: string }[] = [
    { label: 'Admin', href: '/tenant-admin' },
  ]
  let path = '/tenant-admin'
  for (const seg of segments) {
    path += `/${seg}`
    crumbs.push({
      label: SEGMENT_LABELS[seg] || seg.charAt(0).toUpperCase() + seg.slice(1),
      href: path,
    })
  }

  return (
    <div className="flex items-center gap-1.5 px-8 pt-4 pb-0 text-xs text-gray-500 dark:text-gray-400">
      {crumbs.map((crumb, i) => (
        <span key={crumb.href} className="flex items-center gap-1.5">
          {i > 0 && <ChevronRight size={12} className="text-gray-400" />}
          {i < crumbs.length - 1 ? (
            <Link href={crumb.href} className="hover:text-gray-700 dark:hover:text-gray-200 transition-colors">
              {crumb.label}
            </Link>
          ) : (
            <span className="text-gray-700 dark:text-gray-200 font-medium">{crumb.label}</span>
          )}
        </span>
      ))}
    </div>
  )
}

export default function TenantAdminLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter()
  const pathname = usePathname()
  const { isAuthenticated, _hasHydrated, user, logout } = useAuthStore()
  const [agentsUrl, setAgentsUrl] = useState('')

  useEffect(() => {
    if (typeof window !== 'undefined') {
      const proto = window.location.protocol
      const host = process.env.NEXT_PUBLIC_AGENTS_SUBDOMAIN || window.location.host.replace(/^admin\./, 'agents.')
      setAgentsUrl(`${proto}//${host}`)
    }
  }, [])

  useEffect(() => {
    if (_hasHydrated && !isAuthenticated) {
      router.replace('/login')
    }
  }, [isAuthenticated, _hasHydrated, router])

  if (!_hasHydrated) return null

  return (
    <div className="flex h-screen bg-gray-50 dark:bg-gray-950">
      {/* Sidebar — matches dashboard exactly, just different nav items */}
      <aside className="fixed md:relative z-30 h-screen w-64 bg-white dark:bg-gray-900 border-r border-gray-200 dark:border-gray-800 flex flex-col">
        {/* Brand — same gradient mark as dashboard, ADMIN badge below */}
        <div className="px-6 py-5 border-b border-gray-100 dark:border-gray-800">
          <Link href="/tenant-admin" className="flex items-center gap-2">
            <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-violet-500 to-blue-500 flex items-center justify-center text-white font-bold text-sm">
              A
            </div>
            <span className="text-lg font-bold text-gray-900 dark:text-white">AscenAI</span>
          </Link>
          <p className="mt-1 text-[10px] font-semibold uppercase tracking-widest text-violet-500 dark:text-violet-400">
            Admin Portal
          </p>
        </div>

        {/* Nav */}
        <nav className="flex-1 px-3 py-4 overflow-y-auto space-y-1">
          {navItems.map((item) => {
            const active = item.exact
              ? pathname === item.href
              : pathname === item.href || pathname.startsWith(item.href + '/')
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors ${
                  active
                    ? 'bg-violet-50 text-violet-700 dark:bg-violet-900/20 dark:text-violet-300'
                    : 'text-gray-600 hover:bg-gray-100 dark:text-gray-400 dark:hover:bg-gray-800'
                }`}
              >
                <item.icon size={18} />
                {item.label}
              </Link>
            )
          })}

          {/* Divider + Switch to Products */}
          <div className="pt-3 mt-2 border-t border-gray-100 dark:border-gray-800">
            <p className="px-3 py-1 text-xs font-semibold text-gray-400 dark:text-gray-500 uppercase tracking-wider">
              Products
            </p>
            <a
              href={agentsUrl || 'http://agents.lvh.me:3000'}
              className="flex items-center gap-3 px-3 py-2 rounded-lg text-sm text-gray-500 hover:bg-gray-100 dark:text-gray-400 dark:hover:bg-gray-800 transition-colors"
            >
              <Bot size={18} />
              AI Agents
              <ExternalLink size={12} className="ml-auto opacity-40" />
            </a>
          </div>
        </nav>

        {/* User — identical to dashboard */}
        <div className="p-4 border-t border-gray-100 dark:border-gray-800">
          <div className="flex items-center gap-2">
            <div className="flex items-center gap-3 flex-1 min-w-0 rounded-lg p-1 -m-1">
              <div className="w-8 h-8 rounded-full bg-gradient-to-br from-violet-400 to-blue-400 flex items-center justify-center text-white text-xs font-bold flex-shrink-0">
                {user?.full_name?.charAt(0) || 'U'}
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-gray-900 dark:text-white truncate">
                  {user?.full_name || 'User'}
                </p>
                <p className="text-xs text-gray-500 truncate">{user?.email}</p>
              </div>
            </div>
            <button
              onClick={() => { logout(); router.push('/login') }}
              className="p-1.5 text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 transition-colors"
              title="Sign out"
            >
              <LogOut size={16} />
            </button>
          </div>
        </div>
      </aside>

      {/* Main */}
      <main className="flex-1 overflow-auto min-w-0">
        <Breadcrumbs pathname={pathname} />
        {children}
      </main>
    </div>
  )
}
