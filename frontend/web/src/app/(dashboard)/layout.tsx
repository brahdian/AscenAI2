'use client'

import { useEffect } from 'react'
import { useRouter } from 'next/navigation'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { useAuthStore } from '@/store/auth'
import {
  LayoutDashboard,
  Bot,
  MessageSquare,
  Key,
  Settings,
  LogOut,
  BarChart2,
  ThumbsUp,
  BrainCircuit,
  Code2,
  Users,
  CreditCard,
  BookOpen,
  FileText,
  Shield,
  Wrench,
  PhoneCall,
  Mic,
  ChevronLeft,
} from 'lucide-react'

const navItems = [
  { href: '/dashboard', icon: LayoutDashboard, label: 'Overview' },
  { href: '/dashboard/agents', icon: Bot, label: 'Agents' },
  { href: '/dashboard/sessions', icon: MessageSquare, label: 'Chat History' },
  { href: '/dashboard/analytics', icon: BarChart2, label: 'Analytics' },
  { href: '/dashboard/feedback', icon: ThumbsUp, label: 'Feedback' },
  { href: '/dashboard/learning', icon: BrainCircuit, label: 'Learning' },
  { href: '/dashboard/api-keys', icon: Key, label: 'API Keys' },
  { href: '/dashboard/team', icon: Users, label: 'Team' },
  { href: '/dashboard/billing', icon: CreditCard, label: 'Billing' },
  { href: '/dashboard/embed', icon: Code2, label: 'Embed & SDK' },
  { href: '/dashboard/settings', icon: Settings, label: 'Settings' },
]

const agentSubNav = [
  { slug: '',            icon: Bot,          label: 'Overview' },
  { slug: 'playbooks',   icon: BookOpen,     label: 'Playbooks' },
  { slug: 'documents',   icon: FileText,     label: 'Documents' },
  { slug: 'guardrails',  icon: Shield,       label: 'Guardrails' },
  { slug: 'tools',       icon: Wrench,       label: 'Tools' },
  { slug: 'escalation',  icon: PhoneCall,    label: 'Escalation' },
  { slug: 'greeting',    icon: Mic,          label: 'Greeting & Language' },
]

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter()
  const pathname = usePathname()
  const { isAuthenticated, _hasHydrated, user, logout } = useAuthStore()

  useEffect(() => {
    if (_hasHydrated && !isAuthenticated) {
      router.replace('/login')
    }
  }, [isAuthenticated, _hasHydrated, router])

  if (!_hasHydrated) return null

  // Detect if we're on an agent detail page: /dashboard/agents/[id] or /dashboard/agents/[id]/subpage
  const agentMatch = pathname.match(/^\/dashboard\/agents\/([^/]+)(\/.*)?$/)
  const agentId = agentMatch?.[1]
  const isAgentPage = !!agentId && agentId !== 'new'

  return (
    <div className="flex h-screen bg-gray-50 dark:bg-gray-950">
      {/* Sidebar */}
      <aside className="w-64 bg-white dark:bg-gray-900 border-r border-gray-200 dark:border-gray-800 flex flex-col">
        {/* Brand */}
        <div className="px-6 py-5 border-b border-gray-100 dark:border-gray-800">
          <Link href="/dashboard" className="flex items-center gap-2">
            <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-violet-500 to-blue-500 flex items-center justify-center text-white font-bold text-sm">
              A
            </div>
            <span className="text-lg font-bold text-gray-900 dark:text-white">AscenAI</span>
          </Link>
        </div>

        {/* Nav */}
        <nav className="flex-1 px-3 py-4 overflow-y-auto space-y-1">
          {isAgentPage ? (
            <>
              {/* Back to agents list */}
              <Link
                href="/dashboard/agents"
                className="flex items-center gap-2 px-3 py-2 mb-2 text-xs font-medium text-gray-500 hover:text-violet-600 dark:hover:text-violet-400 transition-colors"
              >
                <ChevronLeft size={14} />
                All Agents
              </Link>

              <p className="px-3 py-1 text-xs font-semibold text-gray-400 dark:text-gray-500 uppercase tracking-wider">
                Agent Settings
              </p>

              {agentSubNav.map((item) => {
                const href = item.slug
                  ? `/dashboard/agents/${agentId}/${item.slug}`
                  : `/dashboard/agents/${agentId}`
                const active = item.slug
                  ? pathname === href || pathname.startsWith(href + '/')
                  : pathname === href
                return (
                  <Link
                    key={href}
                    href={href}
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

              <div className="pt-3 mt-2 border-t border-gray-100 dark:border-gray-800 space-y-1">
                <p className="px-3 py-1 text-xs font-semibold text-gray-400 dark:text-gray-500 uppercase tracking-wider">
                  Main Menu
                </p>
                {navItems.map((item) => {
                  const active = pathname === item.href
                  return (
                    <Link
                      key={item.href}
                      href={item.href}
                      className={`flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors ${
                        active
                          ? 'bg-violet-50 text-violet-700 dark:bg-violet-900/20 dark:text-violet-300'
                          : 'text-gray-500 hover:bg-gray-100 dark:text-gray-500 dark:hover:bg-gray-800'
                      }`}
                    >
                      <item.icon size={16} />
                      {item.label}
                    </Link>
                  )
                })}
              </div>
            </>
          ) : (
            navItems.map((item) => {
              const active = pathname === item.href || (item.href !== '/dashboard' && pathname.startsWith(item.href))
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
            })
          )}
        </nav>

        {/* User */}
        <div className="p-4 border-t border-gray-100 dark:border-gray-800">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-full bg-gradient-to-br from-violet-400 to-blue-400 flex items-center justify-center text-white text-xs font-bold">
              {user?.full_name?.charAt(0) || 'U'}
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium text-gray-900 dark:text-white truncate">
                {user?.full_name || 'User'}
              </p>
              <p className="text-xs text-gray-500 truncate">{user?.email}</p>
            </div>
            <button
              onClick={() => {
                logout()
                router.push('/login')
              }}
              className="p-1.5 text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 transition-colors"
              title="Sign out"
            >
              <LogOut size={16} />
            </button>
          </div>
        </div>
      </aside>

      {/* Main */}
      <main className="flex-1 overflow-auto">
        {children}
      </main>
    </div>
  )
}
