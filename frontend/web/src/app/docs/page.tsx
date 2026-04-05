'use client'

import { useState } from 'react'
import Link from 'next/link'
import {
  Rocket,
  Settings,
  BookOpen,
  Wrench,
  PhoneCall,
  Users,
  CreditCard,
  Shield,
  Search,
  ArrowRight,
  ChevronRight,
  Sparkles,
  ExternalLink
} from 'lucide-react'

const guides = [
  {
    id: 'quick-start',
    title: 'Quick Start Guide',
    description: 'Get up and running with AscenAI in minutes. Create your first AI agent and make your first call.',
    href: '/docs/quick-start',
    icon: Rocket,
    color: 'text-orange-500',
    bg: 'bg-orange-50 dark:bg-orange-900/10'
  },
  {
    id: 'agent-configuration',
    title: 'Agent Configuration',
    description: 'Learn how to configure AI agents, set personalities, and define behavior patterns.',
    href: '/docs/agent-setup',
    icon: Settings,
    color: 'text-blue-500',
    bg: 'bg-blue-50 dark:bg-blue-900/10'
  },
  {
    id: 'playbooks',
    title: 'Playbooks',
    description: 'Create conversation flows, define decision trees, and automate complex interactions.',
    href: '/docs/playbooks',
    icon: BookOpen,
    color: 'text-violet-500',
    bg: 'bg-violet-50 dark:bg-violet-900/10'
  },
  {
    id: 'tools-integrations',
    title: 'Tools & Integrations',
    description: 'Connect external APIs, databases, and services to extend your agent capabilities.',
    href: '/docs/tools',
    icon: Wrench,
    color: 'text-emerald-500',
    bg: 'bg-emerald-50 dark:bg-emerald-900/10'
  },
  {
    id: 'voice-setup',
    title: 'Voice Setup',
    description: 'Configure Twilio to enable voice capabilities for your AI agents with step-by-step instructions.',
    href: '/docs/voice-setup',
    icon: PhoneCall,
    color: 'text-indigo-500',
    bg: 'bg-indigo-50 dark:bg-indigo-900/10'
  },
  {
    id: 'team-permissions',
    title: 'Team & Permissions',
    description: 'Manage team members, roles, and access controls for collaborative agent management.',
    href: '/docs/team',
    icon: Users,
    color: 'text-cyan-500',
    bg: 'bg-cyan-50 dark:bg-cyan-900/10'
  },
  {
    id: 'billing-usage',
    title: 'Billing & Usage',
    description: 'Understand pricing tiers, monitor usage, and manage your subscription and billing.',
    href: '/docs/billing',
    icon: CreditCard,
    color: 'text-amber-500',
    bg: 'bg-amber-50 dark:bg-amber-900/10'
  },
  {
    id: 'compliance-privacy',
    title: 'Compliance & Privacy',
    description: 'Learn about data protection, PCI compliance, and privacy best practices.',
    href: '/docs/compliance',
    icon: Shield,
    color: 'text-rose-500',
    bg: 'bg-rose-50 dark:bg-rose-900/10'
  },
]

export default function DocsPage() {
  const [searchQuery, setSearchQuery] = useState('')

  const filteredGuides = guides.filter(
    (guide) =>
      guide.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
      guide.description.toLowerCase().includes(searchQuery.toLowerCase())
  )

  return (
    <main className="min-h-screen bg-gray-50 dark:bg-gray-950 text-gray-900 dark:text-white">
      {/* Navbar — Simplified & Modern */}
      <nav className="border-b border-gray-200 dark:border-gray-800 bg-white/80 dark:bg-gray-900/80 backdrop-blur-md sticky top-0 z-20">
        <div className="flex items-center justify-between px-8 py-4 max-w-7xl mx-auto">
          <Link href="/" className="flex items-center gap-2 group">
            <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-violet-600 to-blue-600 flex items-center justify-center text-white font-bold text-sm shadow-md">
              A
            </div>
            <span className="text-xl font-bold text-gray-900 dark:text-white tracking-tight">AscenAI<span className="text-violet-600">Docs</span></span>
          </Link>
          <div className="hidden md:flex items-center gap-6">
            <Link href="/pricing" className="text-gray-500 hover:text-violet-600 dark:hover:text-violet-400 transition-colors text-sm font-medium">
              Pricing
            </Link>
            <Link href="/login" className="text-gray-500 hover:text-violet-600 dark:hover:text-violet-400 transition-colors text-sm font-medium">
              Dashboard
            </Link>
            <Link
              href="/register"
              className="px-4 py-2 rounded-lg bg-violet-600 text-white text-sm font-medium hover:bg-violet-700 transition-colors shadow-sm"
            >
              Get Started
            </Link>
          </div>
        </div>
      </nav>

      {/* Hero Section */}
      <div className="relative overflow-hidden bg-white dark:bg-gray-950 border-b border-gray-200 dark:border-gray-800">
        <div className="absolute inset-0 bg-grid-slate-100 [mask-image:linear-gradient(0deg,white,rgba(255,255,255,0.6))] dark:bg-grid-slate-900/50 dark:[mask-image:linear-gradient(0deg,rgba(0,0,0,0.1),rgba(0,0,0,0.5))]"></div>
        <div className="max-w-7xl mx-auto px-8 pt-20 pb-16 relative">
          <div className="flex flex-col items-center text-center max-w-3xl mx-auto">
             <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-violet-50 dark:bg-violet-900/20 border border-violet-100 dark:border-violet-800 text-violet-600 dark:text-violet-400 text-xs font-bold mb-6 uppercase tracking-wider">
               <Sparkles size={12} />
               Developers Knowledge Base
             </div>
             <h1 className="text-4xl md:text-6xl font-extrabold text-gray-900 dark:text-white mb-6 tracking-tight leading-tight">
               Build something <span className="text-transparent bg-clip-text bg-gradient-to-r from-violet-600 to-blue-600">intelligent</span>.
             </h1>
             <p className="text-gray-500 dark:text-gray-400 text-lg mb-10 max-w-2xl">
               Comprehensive guides and references to help you build, deploy, and scale AI-powered voice and chat agents for your business.
             </p>
             
             {/* Integrated Search */}
             <div className="w-full max-w-2xl relative group">
                <Search className="absolute left-4 top-1/2 -translate-y-1/2 w-5 h-5 text-gray-400 group-focus-within:text-violet-500 transition-colors" />
                <input
                  type="text"
                  placeholder="Search documentation, guides, and API reference..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="w-full pl-12 pr-4 py-4 rounded-2xl bg-gray-50 dark:bg-gray-900 border border-gray-200 dark:border-gray-800 text-gray-900 dark:text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-violet-500/20 focus:border-violet-500 transition-all shadow-sm"
                />
             </div>
          </div>
        </div>
      </div>

      {/* Documentation Grid */}
      <div className="max-w-7xl mx-auto px-8 py-16">
        <div className="flex flex-col md:flex-row gap-12">
            {/* Sidebar Navigation - Quick Links */}
            <aside className="w-full md:w-64 flex-shrink-0 space-y-8">
                <div>
                   <h4 className="text-xs font-bold text-gray-400 dark:text-gray-500 uppercase tracking-widest mb-4">Core Guides</h4>
                   <nav className="space-y-1">
                      {guides.slice(0, 4).map(g => (
                         <Link key={g.id} href={g.href} className="flex items-center gap-2 px-3 py-2 text-sm text-gray-600 dark:text-gray-400 hover:text-violet-600 dark:hover:text-violet-400 hover:bg-gray-100 dark:hover:bg-gray-800 rounded-lg transition-all">
                            {g.title}
                         </Link>
                      ))}
                   </nav>
                </div>
                <div>
                   <h4 className="text-xs font-bold text-gray-400 dark:text-gray-500 uppercase tracking-widest mb-4">Advanced</h4>
                   <nav className="space-y-1">
                      {guides.slice(4).map(g => (
                         <Link key={g.id} href={g.href} className="flex items-center gap-2 px-3 py-2 text-sm text-gray-600 dark:text-gray-400 hover:text-violet-600 dark:hover:text-violet-400 hover:bg-gray-100 dark:hover:bg-gray-800 rounded-lg transition-all">
                            {g.title}
                         </Link>
                      ))}
                   </nav>
                </div>
                <div className="p-5 rounded-2xl bg-gradient-to-br from-violet-600 to-blue-700 text-white shadow-xl shadow-violet-500/10">
                   <p className="text-xs font-bold uppercase tracking-widest opacity-80 mb-2">Need help?</p>
                   <p className="text-sm font-medium mb-4">Can&apos;t find what you&apos;re looking for?</p>
                   <a href="mailto:support@ascenai.com" className="flex items-center justify-center gap-2 py-2 px-4 bg-white/20 hover:bg-white/30 rounded-lg text-xs font-bold transition-colors">
                      Contact Support <ExternalLink size={12} />
                   </a>
                </div>
            </aside>

            {/* Main Grid */}
            <div className="flex-1">
                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                  {filteredGuides.map((guide) => (
                    <Link
                      key={guide.id}
                      href={guide.href}
                      className="group flex flex-col p-6 bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-2xl hover:border-violet-300 dark:hover:border-violet-700 hover:shadow-xl hover:shadow-violet-500/5 transition-all duration-300 overflow-hidden relative"
                    >
                      <div className="flex items-center justify-between mb-4">
                        <div className={`w-12 h-12 rounded-xl ${guide.bg} flex items-center justify-center ${guide.color} group-hover:scale-110 transition-transform duration-500`}>
                          <guide.icon size={24} />
                        </div>
                        <ChevronRight className="w-5 h-5 text-gray-300 group-hover:text-violet-500 dark:group-hover:text-violet-400 group-hover:translate-x-1 transition-all" />
                      </div>
                      <div className="flex-1">
                        <h3 className="text-lg font-bold text-gray-900 dark:text-white mb-2 decoration-violet-500 group-hover:text-violet-600 transition-colors">
                          {guide.title}
                        </h3>
                        <p className="text-gray-500 dark:text-gray-400 text-sm leading-relaxed line-clamp-2">
                          {guide.description}
                        </p>
                      </div>
                      <div className="mt-6 flex items-center gap-2 text-xs font-bold text-gray-300 dark:text-gray-600 group-hover:text-violet-400 transition-colors">
                         READ DOCUMENTATION <ArrowRight size={14} />
                      </div>
                      
                      {/* Subtle Glow Overlay */}
                      <div className="absolute -bottom-10 -right-10 w-24 h-24 bg-violet-500/5 blur-3xl opacity-0 group-hover:opacity-100 transition-opacity"></div>
                    </Link>
                  ))}
                </div>

                {filteredGuides.length === 0 && (
                  <div className="text-center py-20 bg-gray-50 dark:bg-gray-900 rounded-3xl border-2 border-dashed border-gray-200 dark:border-gray-800">
                    <Search className="w-12 h-12 text-gray-300 mx-auto mb-4" />
                    <p className="text-gray-900 dark:text-white font-bold text-xl mb-2">No matching guides</p>
                    <p className="text-gray-500 max-w-sm mx-auto mb-6">We couldn&apos;t find any documentation matching &apos;{searchQuery}&apos;. Try using different keywords or check our navigation.</p>
                    <button
                      onClick={() => setSearchQuery('')}
                      className="px-6 py-2 bg-violet-600 text-white rounded-xl text-sm font-bold hover:bg-violet-700 transition-colors"
                    >
                      Clear search query
                    </button>
                  </div>
                )}
            </div>
        </div>
      </div>

      {/* Footer */}
      <footer className="border-t border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-950 py-12">
        <div className="max-w-7xl mx-auto px-8 flex flex-col md:flex-row items-center justify-between gap-6">
            <div className="flex items-center gap-2">
                <div className="w-8 h-8 rounded-lg bg-gray-100 dark:bg-gray-800 flex items-center justify-center text-gray-500 font-bold text-sm">
                    A
                </div>
                <span className="text-sm font-bold text-gray-900 dark:text-white">&copy; {new Date().getFullYear()} AscenAI</span>
            </div>
            <div className="flex items-center gap-8 text-sm text-gray-500 font-medium">
                <Link href="/" className="hover:text-violet-600 transition-colors">Home</Link>
                <Link href="/pricing" className="hover:text-violet-600 transition-colors">Pricing</Link>
                <Link href="/login" className="hover:text-violet-600 transition-colors">Dashboard</Link>
            </div>
            <p className="text-xs text-gray-400">
                Built with FastAPI, Next.js, and Gemini.
            </p>
        </div>
      </footer>
    </main>
  )
}
