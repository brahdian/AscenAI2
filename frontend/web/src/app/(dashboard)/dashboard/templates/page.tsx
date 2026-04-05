'use client'

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useRouter } from 'next/navigation'
import { templatesApi } from '@/lib/api'
import Link from 'next/link'
import {
  Sparkles,
  Bot,
  Building2,
  Stethoscope,
  Scissors,
  ShoppingCart,
  MessageCircle,
  PhoneCall,
  TrendingUp,
  MapPin,
  RefreshCw,
  GitBranch,
  Search,
  ArrowRight,
  BookOpen,
  Wrench,
  CheckCircle2,
} from 'lucide-react'

// Map category → icon + gradient color
const CATEGORY_META: Record<string, { icon: any; gradient: string; badge: string }> = {
  sales:     { icon: TrendingUp,    gradient: 'from-violet-500/10 to-blue-500/10',   badge: 'bg-violet-100 dark:bg-violet-900/30 text-violet-700 dark:text-violet-300' },
  booking:   { icon: Building2,     gradient: 'from-blue-500/10 to-cyan-500/10',     badge: 'bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300' },
  support:   { icon: MessageCircle, gradient: 'from-emerald-500/10 to-teal-500/10',  badge: 'bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-300' },
  ecommerce: { icon: ShoppingCart,  gradient: 'from-orange-500/10 to-amber-500/10',  badge: 'bg-orange-100 dark:bg-orange-900/30 text-orange-700 dark:text-orange-300' },
  service:   { icon: Scissors,      gradient: 'from-pink-500/10 to-rose-500/10',     badge: 'bg-pink-100 dark:bg-pink-900/30 text-pink-700 dark:text-pink-300' },
  medical:   { icon: Stethoscope,   gradient: 'from-green-500/10 to-emerald-500/10', badge: 'bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-300' },
  routing:   { icon: PhoneCall,     gradient: 'from-indigo-500/10 to-violet-500/10', badge: 'bg-indigo-100 dark:bg-indigo-900/30 text-indigo-700 dark:text-indigo-300' },
  local:     { icon: MapPin,        gradient: 'from-yellow-500/10 to-orange-500/10', badge: 'bg-yellow-100 dark:bg-yellow-900/30 text-yellow-700 dark:text-yellow-300' },
  retention: { icon: RefreshCw,     gradient: 'from-cyan-500/10 to-blue-500/10',     badge: 'bg-cyan-100 dark:bg-cyan-900/30 text-cyan-700 dark:text-cyan-300' },
  workflow:  { icon: GitBranch,     gradient: 'from-slate-500/10 to-gray-500/10',    badge: 'bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300' },
  general:   { icon: Bot,           gradient: 'from-gray-500/10 to-slate-500/10',    badge: 'bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300' },
}

// Human-readable category labels
const CATEGORY_LABELS: Record<string, string> = {
  sales: 'Sales',
  booking: 'Appointments',
  support: 'Support',
  ecommerce: 'E-Commerce',
  service: 'Service',
  medical: 'Medical',
  routing: 'Routing',
  local: 'Local Business',
  retention: 'Retention',
  workflow: 'Workflow',
  general: 'General',
}

// Template key → friendly tagline (fallback enrichment for templates without tagline field)
const TAGLINES: Record<string, string> = {
  lead_capture:       'Qualify inbound traffic and pass leads to your CRM automatically.',
  appointment_booking:'Let customers self-book and confirm appointments 24/7.',
  customer_support:   'Answer FAQs and resolve common issues with zero wait time.',
  order_checkout:     'Guide customers through a conversational order flow.',
  quote_generator:    'Collect requirements and instantly generate quotes.',
  triage_routing:     'Classify intent and route callers to the right department.',
  sales_assistant:    'Consultative selling — handle objections and close deals.',
  local_business:     'Answer hours, location, pricing for brick-and-mortar shops.',
  follow_up:          'Re-engage cold leads and drive return visits automatically.',
  strict_workflow:    'Enforce a multi-step compliance process end-to-end.',
}

const ALL_CATEGORIES = Object.keys(CATEGORY_LABELS)

export default function TemplatesMarketplacePage() {
  const router = useRouter()
  const [search, setSearch] = useState('')
  const [activeCategory, setActiveCategory] = useState<string>('all')

  const { data: templates = [], isLoading } = useQuery({
    queryKey: ['templates'],
    queryFn: templatesApi.list,
  })

  // Filter
  const filtered = templates.filter((t: any) => {
    const matchesSearch =
      !search ||
      t.name.toLowerCase().includes(search.toLowerCase()) ||
      (t.description || '').toLowerCase().includes(search.toLowerCase())
    const matchesCategory =
      activeCategory === 'all' || t.category === activeCategory

    return matchesSearch && matchesCategory
  })

  // Categories present in data
  const presentCategories = ['all', ...Array.from(new Set<string>(templates.map((t: any) => t.category)))]

  return (
    <div className="p-8 max-w-7xl mx-auto">
      {/* Header */}
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-gray-900 dark:text-white flex items-center gap-2">
          <Sparkles className="text-violet-500" size={28} />
          Agent Templates
        </h1>
        <p className="text-gray-500 mt-2 max-w-2xl">
          Pick a prebuilt template to deploy an AI agent in minutes. Each template ships with
          battle-tested playbooks, system prompts, and tool schemas — fully customizable after
          setup.
        </p>
      </div>

      {/* Search + filters */}
      <div className="flex flex-col sm:flex-row gap-4 mb-8">
        <div className="relative flex-1 max-w-sm">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" size={16} />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search templates…"
            className="w-full pl-9 pr-4 py-2 text-sm rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 text-gray-900 dark:text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-violet-500"
          />
        </div>

        <div className="flex flex-wrap gap-2">
          {presentCategories.map((cat) => (
            <button
              key={cat}
              onClick={() => setActiveCategory(cat)}
              className={`px-3 py-1.5 rounded-full text-xs font-semibold transition-colors ${
                activeCategory === cat
                  ? 'bg-violet-600 text-white'
                  : 'bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-700'
              }`}
            >
              {cat === 'all' ? 'All' : CATEGORY_LABELS[cat] || cat}
            </button>
          ))}
        </div>
      </div>

      {/* Grid */}
      {isLoading ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6 animate-pulse">
          {[...Array(6)].map((_, i) => (
            <div key={i} className="h-64 bg-gray-100 dark:bg-gray-800 rounded-2xl" />
          ))}
        </div>
      ) : filtered.length === 0 ? (
        <div className="text-center py-16 text-gray-400">
          <Bot size={40} className="mx-auto mb-4 opacity-30" />
          <p className="text-sm">No templates match your search.</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {filtered.map((tpl: any) => {
            const meta = CATEGORY_META[tpl.category] || CATEGORY_META.general
            const Icon = meta.icon
            const tagline = TAGLINES[tpl.key] || tpl.description || ''
            const playbookCount = tpl.versions?.[0]?.playbooks?.length ?? 0
            const toolCount = tpl.versions?.[0]?.tools?.length ?? 0
            const variableCount = tpl.variables?.length ?? 0

            return (
              <div
                key={tpl.id}
                className="group flex flex-col bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-800 hover:border-violet-500 hover:shadow-xl hover:shadow-violet-500/10 transition-all overflow-hidden"
              >
                {/* Card body */}
                <div className="p-6 flex-1 flex flex-col">
                  {/* Icon */}
                  <div className={`w-12 h-12 rounded-xl bg-gradient-to-br ${meta.gradient} flex items-center justify-center mb-4`}>
                    <Icon size={22} className="text-violet-600 dark:text-violet-400" />
                  </div>

                  {/* Title + category */}
                  <div className="flex items-start justify-between gap-2 mb-2">
                    <h3 className="text-base font-bold text-gray-900 dark:text-white leading-tight">
                      {tpl.name}
                    </h3>
                    <span className={`shrink-0 text-[10px] font-bold uppercase tracking-wide px-2 py-0.5 rounded-full ${meta.badge}`}>
                      {CATEGORY_LABELS[tpl.category] || tpl.category}
                    </span>
                  </div>

                  <p className="text-sm text-gray-500 leading-relaxed line-clamp-3 flex-1">
                    {tagline}
                  </p>

                  {/* Stats row */}
                  <div className="mt-4 flex items-center gap-3 text-xs text-gray-400">
                    {playbookCount > 0 && (
                      <span className="flex items-center gap-1">
                        <BookOpen size={11} />
                        {playbookCount} playbook{playbookCount !== 1 ? 's' : ''}
                      </span>
                    )}
                    {toolCount > 0 && (
                      <span className="flex items-center gap-1">
                        <Wrench size={11} />
                        {toolCount} tool{toolCount !== 1 ? 's' : ''}
                      </span>
                    )}
                    {variableCount > 0 && (
                      <span className="flex items-center gap-1">
                        <CheckCircle2 size={11} />
                        {variableCount} variable{variableCount !== 1 ? 's' : ''}
                      </span>
                    )}
                  </div>
                </div>

                {/* Action footer */}
                <div className="px-6 pb-6 pt-0">
                  <Link
                    href={`/dashboard/agents/new?template=${tpl.id}`}
                    className="w-full flex items-center justify-center gap-2 px-4 py-2.5 bg-violet-600 hover:bg-violet-700 text-white text-sm font-semibold rounded-xl transition-colors"
                  >
                    Use Template <ArrowRight size={14} />
                  </Link>
                </div>
              </div>
            )
          })}

          {/* Start from Scratch card */}
          <Link
            href="/dashboard/agents/new"
            className="group flex flex-col justify-between p-6 bg-white dark:bg-gray-900 rounded-2xl border-2 border-dashed border-gray-300 dark:border-gray-700 hover:border-violet-500 transition-colors"
          >
            <div>
              <div className="w-12 h-12 rounded-xl bg-gray-100 dark:bg-gray-800 flex items-center justify-center mb-4 group-hover:bg-violet-100 dark:group-hover:bg-violet-900/30 transition-colors">
                <Bot size={22} className="text-gray-400 group-hover:text-violet-600 dark:group-hover:text-violet-400 transition-colors" />
              </div>
              <h3 className="text-base font-bold text-gray-900 dark:text-white">Start from Scratch</h3>
              <p className="text-sm text-gray-500 mt-2 leading-relaxed">
                Build a completely custom agent. Write your own system prompt and define workflows manually.
              </p>
            </div>
            <div className="mt-4 flex items-center gap-1 text-sm font-semibold text-violet-600 dark:text-violet-400 group-hover:gap-2 transition-all">
              Create custom <ArrowRight size={14} />
            </div>
          </Link>
        </div>
      )}
    </div>
  )
}
