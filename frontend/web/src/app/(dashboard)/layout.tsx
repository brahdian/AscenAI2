'use client'

import { useEffect, useState } from 'react'
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
  CheckCircle,
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
  ChevronRight,
  GitBranch,
  ShieldCheck,
  Terminal,
  Menu,
  X,
  User,
} from 'lucide-react'
import { agentsApi } from '@/lib/api'

const navItems = [
  { href: '/dashboard', icon: LayoutDashboard, label: 'Overview' },
  { href: '/dashboard/agents', icon: Bot, label: 'Agents' },
  { href: '/dashboard/sessions', icon: MessageSquare, label: 'Chat History' },
  { href: '/dashboard/analytics', icon: BarChart2, label: 'Analytics' },
  { href: '/dashboard/feedback', icon: ThumbsUp, label: 'Feedback' },
  { href: '/dashboard/learning', icon: CheckCircle, label: 'Corrections' },
  { href: '/dashboard/api-keys', icon: Key, label: 'API Keys' },
  { href: '/dashboard/team', icon: Users, label: 'Team' },
  { href: '/dashboard/billing', icon: CreditCard, label: 'Billing' },
  { href: '/dashboard/embed', icon: Code2, label: 'Embed & SDK' },
  { href: '/dashboard/settings', icon: Settings, label: 'Settings' },
]

const agentSubNav = [
  // Agent Configuration
  { slug: '', icon: Bot, label: 'Overview' },
  { slug: 'greeting', icon: Mic, label: 'Greeting & Voice' },
  { slug: 'playbooks', icon: BookOpen, label: 'Playbooks' },
  // Knowledge & Tools
  { slug: 'documents', icon: FileText, label: 'Documents' },
  { slug: 'tools', icon: Wrench, label: 'Tools' },
  { slug: 'variables', icon: Code2, label: 'Variables' },
  // Safety & Operations
  { slug: 'guardrails', icon: Shield, label: 'Guardrails' },
  { slug: 'escalation', icon: PhoneCall, label: 'Escalation' },
  // Automation
  { slug: 'flows', icon: GitBranch, label: 'Flows' },
]

// Breadcrumb segment labels
const SEGMENT_LABELS: Record<string, string> = {
  dashboard: 'Dashboard',
  agents: 'Agents',
  playbooks: 'Playbooks',
  documents: 'Documents',
  guardrails: 'Guardrails',
  tools: 'Tools',
  variables: 'Variables',
  escalation: 'Escalation',
  flows: 'Flows',
  greeting: 'Greeting & Voice',
  sessions: 'Chat History',
  analytics: 'Analytics',
  feedback: 'Feedback',
  learning: 'Corrections',
  'api-keys': 'API Keys',
  team: 'Team',
  billing: 'Billing',
  embed: 'Embed & SDK',
  settings: 'Settings',
  profile: 'Profile',
}

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter()
  const pathname = usePathname()
  const { isAuthenticated, _hasHydrated, user, logout } = useAuthStore()
  const [sidebarOpen, setSidebarOpen] = useState(false)

  useEffect(() => {
    if (_hasHydrated && !isAuthenticated) {
      router.replace('/login')
    }
  }, [isAuthenticated, _hasHydrated, router])

  // Close sidebar on route change (mobile)
  useEffect(() => {
    setSidebarOpen(false)
  }, [pathname])

  // Wait for store to hydrate from localStorage before deciding to redirect.
  // Without this, the layout briefly sees isAuthenticated=false on every page
  // load and immediately redirects to /login even for logged-in users.
  if (!_hasHydrated) return null

  // Detect if we're on an agent detail page: /dashboard/agents/[id] or /dashboard/agents/[id]/subpage
  const agentMatch = pathname.match(/^\/dashboard\/agents\/([^/]+)(\/.*)?$/)
  const agentId = agentMatch?.[1]
  const isAgentPage = !!agentId && agentId !== 'new'

  return (
    <div className="flex h-screen bg-gray-50 dark:bg-gray-950">
      {/* Mobile overlay */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 z-20 bg-black/40 md:hidden"
          onClick={() => setSidebarOpen(false)}
        />
      )}

      {/* Sidebar */}
      <aside className={`fixed md:relative z-30 h-screen w-64 transition-transform duration-200 ease-in-out ${sidebarOpen ? 'translate-x-0' : '-translate-x-full md:translate-x-0'} bg-white dark:bg-gray-900 border-r border-gray-200 dark:border-gray-800 flex flex-col`}>
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
                    className={`flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors ${active
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
                      className={`flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors ${active
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
            <>
              {navItems.map((item) => {
                const active = pathname === item.href || (item.href !== '/dashboard' && pathname.startsWith(item.href))
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    className={`flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors ${active
                        ? 'bg-violet-50 text-violet-700 dark:bg-violet-900/20 dark:text-violet-300'
                        : 'text-gray-600 hover:bg-gray-100 dark:text-gray-400 dark:hover:bg-gray-800'
                      }`}
                  >
                    <item.icon size={18} />
                    {item.label}
                  </Link>
                )
              })}
            </>
          )}


        </nav>

        {/* User */}
        <div className="p-4 border-t border-gray-100 dark:border-gray-800">
          <div className="flex items-center gap-2">
            <Link
              href="/dashboard/profile"
              className="flex items-center gap-3 flex-1 min-w-0 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-800 p-1 -m-1 transition-colors"
              title="View profile"
            >
              <div className="w-8 h-8 rounded-full bg-gradient-to-br from-violet-400 to-blue-400 flex items-center justify-center text-white text-xs font-bold flex-shrink-0">
                {user?.full_name?.charAt(0) || 'U'}
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-gray-900 dark:text-white truncate">
                  {user?.full_name || 'User'}
                </p>
                <p className="text-xs text-gray-500 truncate">{user?.email}</p>
              </div>
            </Link>
            {/* Console link — discreet, not in main nav */}
            <Link
              href="/console"
              className="p-1.5 text-gray-300 hover:text-gray-600 dark:text-gray-600 dark:hover:text-gray-300 transition-colors"
              title="Activity Console"
            >
              <Terminal size={15} />
            </Link>
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
      <main className="flex-1 overflow-auto min-w-0">
        {/* Mobile header with hamburger */}
        <div className="md:hidden flex items-center gap-3 px-4 py-3 border-b border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900">
          <button
            onClick={() => setSidebarOpen(true)}
            className="p-1.5 text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800 rounded-lg transition-colors"
            aria-label="Open menu"
          >
            <Menu size={20} />
          </button>
          <span className="text-sm font-semibold text-gray-900 dark:text-white">AscenAI</span>
        </div>
        <Breadcrumbs pathname={pathname} />
        {children}
      </main>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Breadcrumbs component
// ---------------------------------------------------------------------------
function Breadcrumbs({ pathname }: { pathname: string }) {
  // Don't show breadcrumbs on the root dashboard page or flow builder
  if (pathname === '/dashboard' || pathname.includes('/workflows/')) return null

  const segments = pathname.replace(/^\/dashboard\/?/, '').split('/').filter(Boolean)
  if (segments.length === 0) return null

  const crumbs: { label: string; href: string }[] = [
    { label: 'Dashboard', href: '/dashboard' },
  ]

  let path = '/dashboard'
  for (let i = 0; i < segments.length; i++) {
    const seg = segments[i]
    path += `/${seg}`
    // Skip UUID segments that are agent IDs — they'll be resolved by the parent label
    const isUuid = /^[0-9a-f]{8}-/.test(seg)
    if (isUuid) {
      crumbs.push({ label: 'Agent', href: path })
    } else {
      const label = SEGMENT_LABELS[seg] || seg.charAt(0).toUpperCase() + seg.slice(1)
      crumbs.push({ label, href: path })
    }
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
