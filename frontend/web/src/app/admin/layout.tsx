'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { useAuthStore } from '@/store/auth'
import { api } from '@/lib/api'
import {
  Settings,
  LogOut,
  ShieldCheck,
  LayoutDashboard,
  ExternalLink,
  Zap,
  Users,
  Building2,
  BarChart3,
  Home,
} from 'lucide-react'

const ROOT_DOMAIN = process.env.NEXT_PUBLIC_ROOT_DOMAIN || 'localhost:3000'
const APP_NAME = process.env.NEXT_PUBLIC_APP_NAME || 'AscenAI'

function getMainOrigin(): string {
  if (typeof window !== 'undefined') {
    const host = window.location.host.replace(/^admin\./, '')
    return `${window.location.protocol}//${host}`
  }
  return `http://${ROOT_DOMAIN}`
}

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname()
  const { isAuthenticated, _hasHydrated, user, logout } = useAuthStore()
  const [platformUrl, setPlatformUrl] = useState<string>('')

  useEffect(() => {
    setPlatformUrl(getMainOrigin())
  }, [])

  useEffect(() => {
    if (!_hasHydrated) return

    if (!isAuthenticated) {
      window.location.href = `${platformUrl || getMainOrigin()}/login`
    } else if (user?.role !== 'super_admin') {
      window.location.href = `${platformUrl || getMainOrigin()}/dashboard`
    }
  }, [isAuthenticated, _hasHydrated, user, platformUrl])

  if (!_hasHydrated || !isAuthenticated || user?.role !== 'super_admin') {
    return (
      <div className="flex h-screen w-full items-center justify-center bg-gray-50 dark:bg-gray-950">
        <div className="animate-spin rounded-full h-8 w-8 border-t-2 border-b-2 border-violet-500"></div>
      </div>
    )
  }

  const navItems = [
    { label: 'Overview', href: '/admin/dashboard', icon: Home },
    { label: 'Platform Economics', href: '/admin/analytics', icon: BarChart3 },
    { label: 'Infrastructure', href: '/admin/tenants', icon: Building2 },
    { label: 'Identity Directory', href: '/admin/users', icon: Users },
  ]

  const configItems = [
    { label: 'Billing & Plans', href: '/admin/settings/plans', icon: Zap },
    { label: 'Global Settings', href: '/admin/settings', icon: Settings },
  ]

  return (
    <div className="flex h-screen bg-gray-50 dark:bg-gray-950 overflow-hidden">
      {/* Admin Sidebar */}
      <aside className="w-64 bg-white dark:bg-gray-900 border-r border-gray-100 dark:border-gray-800 flex flex-col z-50">
        {/* Brand */}
        <div className="px-6 py-5 border-b border-gray-50 dark:border-gray-800 bg-gray-50/50 dark:bg-gray-800/20">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-xl bg-gradient-to-br from-violet-600 to-blue-600 flex items-center justify-center text-white font-bold text-sm shadow-lg shadow-violet-500/20">
              <ShieldCheck size={18} />
            </div>
            <span className="text-lg font-bold tracking-tight text-gray-900 dark:text-white">Super Admin</span>
          </div>
          <p className="mt-1.5 text-[10px] uppercase font-bold tracking-widest text-gray-400 dark:text-gray-500 group-hover:text-violet-500 transition-colors">
            {APP_NAME} Control Center
          </p>
        </div>

        {/* Global Navigation */}
        <nav className="flex-1 px-4 py-8 overflow-y-auto space-y-8 scrollbar-hide">
          <div className="space-y-1">
            <p className="px-3 mb-2 text-[10px] font-bold uppercase tracking-widest text-gray-400 dark:text-gray-600">
               Core Operations
            </p>
            {navItems.map((item) => (
              <Link
                key={item.href}
                href={item.href}
                className={`flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-bold transition-all duration-300 group ${
                  pathname === item.href
                    ? 'bg-violet-50 text-violet-600 dark:bg-violet-900/10 dark:text-violet-400 border border-violet-100 dark:border-violet-900/40 shadow-sm'
                    : 'text-gray-500 hover:text-gray-900 dark:text-gray-400 dark:hover:text-white hover:bg-gray-50 dark:hover:bg-gray-800 border border-transparent'
                }`}
              >
                <item.icon size={18} className={`${pathname === item.href ? 'text-violet-600 dark:text-violet-400 font-bold' : 'text-gray-400 group-hover:text-gray-600 dark:group-hover:text-gray-200'} transition-colors`} />
                {item.label}
              </Link>
            ))}
          </div>

          <div className="space-y-1">
            <p className="px-3 mb-2 text-[10px] font-bold uppercase tracking-widest text-gray-400 dark:text-gray-600">
               Platform Configuration
            </p>
            {configItems.map((item) => (
              <Link
                key={item.href}
                href={item.href}
                className={`flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-bold transition-all duration-300 group ${
                  pathname === item.href
                    ? 'bg-violet-50 text-violet-600 dark:bg-violet-900/10 dark:text-violet-400 border border-violet-100 dark:border-violet-900/40 shadow-sm'
                    : 'text-gray-500 hover:text-gray-900 dark:text-gray-400 dark:hover:text-white hover:bg-gray-50 dark:hover:bg-gray-800 border border-transparent'
                }`}
              >
                <item.icon size={18} className={`${pathname === item.href ? 'text-violet-600 dark:text-violet-400' : 'text-gray-400 group-hover:text-gray-600 dark:group-hover:text-gray-200'} transition-colors`} />
                {item.label}
              </Link>
            ))}
          </div>
          
          <div className="pt-4 border-t border-gray-100 dark:border-gray-800">
             <a
               href={`${platformUrl}/dashboard`}
               className="flex items-center gap-3 px-3 py-2.5 rounded-xl text-xs font-bold text-gray-400 hover:text-gray-900 dark:hover:text-white hover:bg-gray-50 dark:hover:bg-gray-800 transition-all border border-transparent"
             >
               <LayoutDashboard size={16} />
               Exit to Application
               <ExternalLink size={12} className="ml-auto opacity-30" />
             </a>
          </div>
        </nav>

        {/* User Card */}
        <div className="p-4 bg-gray-50/50 dark:bg-gray-800/10 border-t border-gray-100 dark:border-gray-800">
          <div className="flex items-center gap-3 p-3 bg-white dark:bg-gray-900 rounded-2xl border border-gray-100 dark:border-gray-800 shadow-sm">
            <div className="w-9 h-9 rounded-full bg-gradient-to-br from-violet-500 to-blue-500 flex items-center justify-center text-white text-xs font-black shadow-md border-2 border-white dark:border-gray-800">
              {user?.full_name?.charAt(0)?.toUpperCase() || 'A'}
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-xs font-black text-gray-900 dark:text-white truncate">
                {user?.full_name || 'Admin'}
              </p>
              <p className="text-[9px] font-bold text-violet-600 dark:text-violet-400 uppercase tracking-widest flex items-center gap-1">
                 <ShieldCheck size={10} /> Root
              </p>
            </div>
            <button
              onClick={async () => {
                try {
                  await api.post('/auth/logout')
                } catch (e) {
                  // ignore
                } finally {
                  logout()
                  window.location.href = `${platformUrl || getMainOrigin()}/login`
                }
              }}
              className="p-1.5 text-gray-300 hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-950/20 rounded-lg transition-all active:scale-90"
              title="Terminate Global Session"
            >
              <LogOut size={16} />
            </button>
          </div>
        </div>
      </aside>

      {/* Primary Workspace */}
      <main className="flex-1 overflow-auto bg-gray-50 dark:bg-gray-950 selection:bg-violet-500/20">
        <div className="max-w-7xl mx-auto px-10 py-10">
          {children}
        </div>
      </main>
    </div>
  )
}
