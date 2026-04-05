'use client'

import { useQuery } from '@tanstack/react-query'
import { tenantApi, agentsApi, sessionsApi } from '@/lib/api'
import { getPlanDisplayName } from '@/lib/plans'
import { useAuthStore } from '@/store/auth'
import { Bot, MessageSquare, Zap, TrendingUp, AlertCircle } from 'lucide-react'

function StatCard({
  icon: Icon,
  label,
  value,
  sub,
  color,
}: {
  icon: React.ElementType
  label: string
  value: string | number
  sub?: string
  color: string
}) {
  return (
    <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 p-5">
      <div className="flex items-center justify-between mb-3">
        <span className="text-sm text-gray-500 dark:text-gray-400">{label}</span>
        <div className={`w-8 h-8 rounded-lg ${color} flex items-center justify-center`}>
          <Icon size={16} className="text-white" />
        </div>
      </div>
      <p className="text-2xl font-bold text-gray-900 dark:text-white">{value}</p>
      {sub && <p className="text-xs text-gray-500 mt-1">{sub}</p>}
    </div>
  )
}

export default function DashboardPage() {
  const { user } = useAuthStore()

  const { data: usage } = useQuery({
    queryKey: ['usage'],
    queryFn: () => tenantApi.getUsage(),
  })

  const { data: agents } = useQuery({
    queryKey: ['agents'],
    queryFn: () => agentsApi.list(),
  })

  const { data: tenant } = useQuery({
    queryKey: ['tenant'],
    queryFn: () => tenantApi.getMe(),
  })

  return (
    <div className="p-8">
      {/* Header */}
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-gray-900 dark:text-white">
          Good day, {user?.full_name?.split(' ')[0] || 'there'} 👋
        </h1>
        <p className="text-gray-500 dark:text-gray-400 mt-1">
          Here&apos;s an overview of your AI agents this month.
        </p>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
        <StatCard
          icon={MessageSquare}
          label="Sessions"
          value={usage?.current_month_sessions ?? '—'}
          sub="Total conversations"
          color="bg-blue-500"
        />
        <StatCard
          icon={Bot}
          label="Chat Equivalents"
          value={usage?.current_month_chat_units ?? '—'}
          sub="10 turns = 1 chat"
          color="bg-violet-500"
        />
        <StatCard
          icon={Zap}
          label="Voice Minutes"
          value={usage?.current_month_voice_minutes !== undefined ? usage.current_month_voice_minutes.toFixed(1) + 'm' : '—'}
          sub="AI-user calls"
          color="bg-orange-500"
        />
        <StatCard
          icon={TrendingUp}
          label="Active agents"
          value={Array.isArray(agents) ? agents.length : 0}
          sub="Manage assistants"
          color="bg-emerald-500"
        />
      </div>

      {/* Quick actions */}
      <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 p-6">
        <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
          Quick actions
        </h2>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          {[
            {
              href: '/dashboard/agents/new',
              label: 'Create agent',
              desc: 'Set up a new AI assistant',
              icon: '🤖',
            },
            {
              href: '/dashboard/api-keys',
              label: 'API keys',
              desc: 'Manage developer access',
              icon: '🔑',
            },
            {
              href: '/dashboard/sessions',
              label: 'View sessions',
              desc: 'Recent conversations',
              icon: '💬',
            },
          ].map((action) => (
            <a
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
            </a>
          ))}
        </div>
      </div>
    </div>
  )
}
