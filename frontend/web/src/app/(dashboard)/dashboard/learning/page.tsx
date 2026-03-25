'use client'

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { learningApi, agentsApi } from '@/lib/api'
import Link from 'next/link'
import {
  BrainCircuit, BookOpen, AlertTriangle, Shield, ThumbsDown, ThumbsUp,
  ChevronRight, MessageSquare, Lightbulb, Info,
} from 'lucide-react'

// ─── Helpers ─────────────────────────────────────────────────────────────────

function truncate(s: string, n = 120) {
  return s.length > n ? s.slice(0, n) + '…' : s
}

function timeAgo(iso: string) {
  const d = new Date(iso)
  const diff = (Date.now() - d.getTime()) / 1000
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
  return `${Math.floor(diff / 86400)}d ago`
}

// ─── Sub-components ───────────────────────────────────────────────────────────

function StatCard({
  icon: Icon,
  label,
  value,
  color,
}: {
  icon: React.ElementType
  label: string
  value: number
  color: string
}) {
  return (
    <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 p-5 flex items-center gap-4">
      <div className={`w-10 h-10 rounded-lg flex items-center justify-center ${color}`}>
        <Icon size={20} />
      </div>
      <div>
        <p className="text-2xl font-bold text-gray-900 dark:text-white">{value}</p>
        <p className="text-sm text-gray-500">{label}</p>
      </div>
    </div>
  )
}

function EmptyState({ label }: { label: string }) {
  return (
    <div className="py-10 text-center text-gray-400 text-sm">
      <Lightbulb size={28} className="mx-auto mb-2 opacity-40" />
      {label}
    </div>
  )
}

// ─── Tabs ────────────────────────────────────────────────────────────────────

type Tab = 'gaps' | 'negatives' | 'triggers' | 'suggested'

const TABS: { id: Tab; label: string; icon: React.ElementType; color: string }[] = [
  { id: 'gaps', label: 'Knowledge Gaps', icon: BookOpen, color: 'text-blue-500' },
  { id: 'negatives', label: 'Unreviewed Negatives', icon: ThumbsDown, color: 'text-red-500' },
  { id: 'triggers', label: 'Guardrail Triggers', icon: Shield, color: 'text-orange-500' },
  { id: 'suggested', label: 'Suggested Pairs', icon: ThumbsUp, color: 'text-green-500' },
]

// ─── Page ────────────────────────────────────────────────────────────────────

export default function LearningPage() {
  const [selectedAgent, setSelectedAgent] = useState<string>('')
  const [activeTab, setActiveTab] = useState<Tab>('gaps')

  const { data: agents } = useQuery({
    queryKey: ['agents'],
    queryFn: agentsApi.list,
  })

  const agentId = selectedAgent || agents?.[0]?.id || ''

  const { data: insights, isLoading } = useQuery({
    queryKey: ['learning', agentId],
    queryFn: () => learningApi.getInsights(agentId),
    enabled: !!agentId,
  })

  return (
    <div className="p-8">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white flex items-center gap-2">
            <BrainCircuit size={24} className="text-violet-500" />
            Conversational Learning
          </h1>
          <p className="text-gray-500 dark:text-gray-400 mt-1">
            Surface knowledge gaps, unreviewed negatives, and training opportunities
          </p>
        </div>

        {/* Agent selector */}
        <select
          value={selectedAgent}
          onChange={(e) => setSelectedAgent(e.target.value)}
          className="px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 text-sm text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-violet-500"
        >
          {agents?.map((a: any) => (
            <option key={a.id} value={a.id}>
              {a.name}
            </option>
          ))}
        </select>
      </div>

      {/* Stat cards */}
      {insights && (
        <div className="grid grid-cols-4 gap-4 mb-6">
          <StatCard
            icon={BookOpen}
            label="Knowledge gaps"
            value={insights.total_gaps}
            color="bg-blue-50 dark:bg-blue-900/20 text-blue-600"
          />
          <StatCard
            icon={ThumbsDown}
            label="Unreviewed negatives"
            value={insights.total_unreviewed}
            color="bg-red-50 dark:bg-red-900/20 text-red-600"
          />
          <StatCard
            icon={Shield}
            label="Guardrail triggers"
            value={insights.total_triggers}
            color="bg-orange-50 dark:bg-orange-900/20 text-orange-600"
          />
          <StatCard
            icon={ThumbsUp}
            label="Suggested pairs"
            value={insights.suggested_training_pairs?.length ?? 0}
            color="bg-green-50 dark:bg-green-900/20 text-green-600"
          />
        </div>
      )}

      {/* Info banner */}
      <div className="flex items-start gap-2 bg-violet-50 dark:bg-violet-900/10 border border-violet-200 dark:border-violet-800 rounded-xl p-4 mb-6 text-sm text-violet-700 dark:text-violet-300">
        <Info size={16} className="mt-0.5 shrink-0" />
        <div>
          <strong>How this works:</strong> Knowledge gaps are auto-detected when the agent uses a
          fallback or uncertainty response. Guardrail triggers show blocked user messages — useful for
          updating your allowed-topics list. Suggested pairs are positive-rated exchanges worth
          adding to the playbook or knowledge base. Review negatives via the{' '}
          <Link href="/dashboard/sessions" className="underline">
            Chat History
          </Link>{' '}
          page to add ideal responses.
        </div>
      </div>

      {/* Tab bar */}
      <div className="flex gap-1 bg-gray-100 dark:bg-gray-800 rounded-xl p-1 mb-5 w-fit">
        {TABS.map((tab) => {
          const count =
            tab.id === 'gaps'
              ? insights?.total_gaps
              : tab.id === 'negatives'
              ? insights?.total_unreviewed
              : tab.id === 'triggers'
              ? insights?.total_triggers
              : insights?.suggested_training_pairs?.length
          return (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
                activeTab === tab.id
                  ? 'bg-white dark:bg-gray-900 text-gray-900 dark:text-white shadow-sm'
                  : 'text-gray-500 hover:text-gray-700 dark:hover:text-gray-300'
              }`}
            >
              <tab.icon size={15} className={activeTab === tab.id ? tab.color : ''} />
              {tab.label}
              {count != null && count > 0 && (
                <span
                  className={`text-xs px-1.5 py-0.5 rounded-full font-medium ${
                    activeTab === tab.id
                      ? 'bg-violet-100 dark:bg-violet-900/30 text-violet-700 dark:text-violet-300'
                      : 'bg-gray-200 dark:bg-gray-700 text-gray-600 dark:text-gray-400'
                  }`}
                >
                  {count}
                </span>
              )}
            </button>
          )
        })}
      </div>

      {/* Content */}
      <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800">
        {isLoading ? (
          <div className="space-y-3 p-6">
            {[1, 2, 3].map((i) => (
              <div key={i} className="h-20 rounded-lg bg-gray-100 dark:bg-gray-800 animate-pulse" />
            ))}
          </div>
        ) : !agentId ? (
          <EmptyState label="Select an agent above to view learning insights" />
        ) : activeTab === 'gaps' ? (
          <KnowledgeGapsList items={insights?.knowledge_gaps ?? []} agentId={agentId} />
        ) : activeTab === 'negatives' ? (
          <UnreviewedNegativesList items={insights?.unreviewed_negatives ?? []} />
        ) : activeTab === 'triggers' ? (
          <GuardrailTriggersList items={insights?.guardrail_triggers ?? []} agentId={agentId} />
        ) : (
          <SuggestedPairsList items={insights?.suggested_training_pairs ?? []} agentId={agentId} />
        )}
      </div>
    </div>
  )
}

// ─── Knowledge Gaps ───────────────────────────────────────────────────────────

function KnowledgeGapsList({
  items,
  agentId,
}: {
  items: any[]
  agentId: string
}) {
  if (!items.length) {
    return <EmptyState label="No knowledge gaps detected — the agent has been confidently answering questions" />
  }
  return (
    <div className="divide-y divide-gray-100 dark:divide-gray-800">
      {items.map((item) => (
        <div key={item.message_id} className="p-5 hover:bg-gray-50 dark:hover:bg-gray-800/50 transition-colors">
          <div className="flex items-start justify-between gap-4">
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 mb-2">
                <span className="text-xs font-medium px-2 py-0.5 rounded-full bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300">
                  Gap
                </span>
                <span className="text-xs text-gray-400">{timeAgo(item.created_at)}</span>
              </div>
              <p className="text-sm font-medium text-gray-900 dark:text-white mb-1">
                User asked:
              </p>
              <p className="text-sm text-gray-600 dark:text-gray-400 mb-3 italic">
                "{truncate(item.user_message)}"
              </p>
              <p className="text-sm font-medium text-gray-900 dark:text-white mb-1">
                Agent responded:
              </p>
              <p className="text-sm text-gray-500 dark:text-gray-400 italic">
                "{truncate(item.agent_response)}"
              </p>
            </div>
            <div className="flex flex-col gap-2 shrink-0">
              <Link
                href={`/dashboard/sessions?highlight=${item.session_id}`}
                className="flex items-center gap-1 text-xs text-violet-600 dark:text-violet-400 hover:underline"
              >
                <MessageSquare size={12} />
                Review session
              </Link>
              <Link
                href={`/dashboard/agents/${agentId}/playbook`}
                className="flex items-center gap-1 text-xs text-blue-600 dark:text-blue-400 hover:underline"
              >
                <BookOpen size={12} />
                Add to playbook
              </Link>
            </div>
          </div>
        </div>
      ))}
    </div>
  )
}

// ─── Unreviewed Negatives ─────────────────────────────────────────────────────

function UnreviewedNegativesList({ items }: { items: any[] }) {
  if (!items.length) {
    return <EmptyState label="No unreviewed negative feedback — great job!" />
  }
  return (
    <div className="divide-y divide-gray-100 dark:divide-gray-800">
      {items.map((item) => (
        <div key={item.feedback_id} className="p-5 hover:bg-gray-50 dark:hover:bg-gray-800/50 transition-colors">
          <div className="flex items-start justify-between gap-4">
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 mb-2">
                <span className="text-xs font-medium px-2 py-0.5 rounded-full bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-300">
                  Negative
                </span>
                {item.labels?.map((l: string) => (
                  <span
                    key={l}
                    className="text-xs px-2 py-0.5 rounded-full bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-400"
                  >
                    {l}
                  </span>
                ))}
                <span className="text-xs text-gray-400">{timeAgo(item.created_at)}</span>
              </div>
              <p className="text-sm text-gray-700 dark:text-gray-300 italic mb-2">
                "{truncate(item.agent_response)}"
              </p>
              {item.comment && (
                <p className="text-xs text-gray-500 mt-1">
                  <span className="font-medium">Comment:</span> {item.comment}
                </p>
              )}
            </div>
            <Link
              href={`/dashboard/sessions?highlight=${item.session_id}`}
              className="flex items-center gap-1 text-xs text-violet-600 dark:text-violet-400 hover:underline shrink-0"
            >
              <MessageSquare size={12} />
              Add ideal response
              <ChevronRight size={12} />
            </Link>
          </div>
        </div>
      ))}
    </div>
  )
}

// ─── Guardrail Triggers ───────────────────────────────────────────────────────

function GuardrailTriggersList({
  items,
  agentId,
}: {
  items: any[]
  agentId: string
}) {
  if (!items.length) {
    return <EmptyState label="No guardrail triggers — no messages have been blocked" />
  }

  // Group by trigger reason for pattern detection
  const grouped = items.reduce<Record<string, any[]>>((acc, item) => {
    const key = item.trigger_reason.split(':')[0] || 'other'
    acc[key] = acc[key] || []
    acc[key].push(item)
    return acc
  }, {})

  return (
    <div>
      {/* Pattern summary */}
      <div className="p-4 border-b border-gray-100 dark:border-gray-800 bg-orange-50/50 dark:bg-orange-900/5">
        <p className="text-xs font-medium text-gray-500 uppercase tracking-wider mb-2">
          Trigger patterns
        </p>
        <div className="flex flex-wrap gap-2">
          {Object.entries(grouped).map(([reason, msgs]) => (
            <span
              key={reason}
              className="inline-flex items-center gap-1 text-xs px-2.5 py-1 rounded-full bg-orange-100 dark:bg-orange-900/30 text-orange-700 dark:text-orange-300"
            >
              <Shield size={10} />
              {reason} ({msgs.length})
            </span>
          ))}
        </div>
      </div>

      <div className="divide-y divide-gray-100 dark:divide-gray-800">
        {items.map((item) => (
          <div key={item.message_id} className="p-5 hover:bg-gray-50 dark:hover:bg-gray-800/50 transition-colors">
            <div className="flex items-start justify-between gap-4">
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-2">
                  <span className="text-xs font-medium px-2 py-0.5 rounded-full bg-orange-100 dark:bg-orange-900/30 text-orange-700 dark:text-orange-300">
                    {item.trigger_reason}
                  </span>
                  <span className="text-xs text-gray-400">{timeAgo(item.created_at)}</span>
                </div>
                <p className="text-sm text-gray-700 dark:text-gray-300 italic">
                  "{truncate(item.user_message)}"
                </p>
              </div>
              <Link
                href={`/dashboard/agents/${agentId}/guardrails`}
                className="flex items-center gap-1 text-xs text-orange-600 dark:text-orange-400 hover:underline shrink-0"
              >
                <Shield size={12} />
                Edit guardrails
              </Link>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

// ─── Suggested Training Pairs ─────────────────────────────────────────────────

function SuggestedPairsList({
  items,
  agentId,
}: {
  items: any[]
  agentId: string
}) {
  if (!items.length) {
    return (
      <EmptyState label="No suggested pairs yet — positively-rated exchanges will appear here" />
    )
  }
  return (
    <div>
      <div className="p-4 border-b border-gray-100 dark:border-gray-800 bg-green-50/50 dark:bg-green-900/5">
        <p className="text-sm text-green-700 dark:text-green-400 flex items-center gap-1.5">
          <ThumbsUp size={14} />
          These are positively-rated responses. Add them to your playbook scenarios or knowledge base
          to reinforce what the agent does well.
        </p>
      </div>
      <div className="divide-y divide-gray-100 dark:divide-gray-800">
        {items.map((item) => (
          <div key={item.feedback_id} className="p-5 hover:bg-gray-50 dark:hover:bg-gray-800/50 transition-colors">
            <div className="flex items-start justify-between gap-4">
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-2">
                  <span className="text-xs font-medium px-2 py-0.5 rounded-full bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-300">
                    Suggested
                  </span>
                  {item.labels?.map((l: string) => (
                    <span
                      key={l}
                      className="text-xs px-2 py-0.5 rounded-full bg-gray-100 dark:bg-gray-800 text-gray-500"
                    >
                      {l}
                    </span>
                  ))}
                  <span className="text-xs text-gray-400">{timeAgo(item.created_at)}</span>
                </div>
                <p className="text-xs text-gray-500 mb-1 font-medium">User:</p>
                <p className="text-sm text-gray-700 dark:text-gray-300 italic mb-2">
                  "{truncate(item.user_message, 200)}"
                </p>
                <p className="text-xs text-gray-500 mb-1 font-medium">Agent:</p>
                <p className="text-sm text-gray-600 dark:text-gray-400 italic">
                  "{truncate(item.agent_response, 200)}"
                </p>
              </div>
              <div className="flex flex-col gap-2 shrink-0">
                <Link
                  href={`/dashboard/agents/${agentId}/playbook`}
                  className="flex items-center gap-1 text-xs text-green-600 dark:text-green-400 hover:underline"
                >
                  <BookOpen size={12} />
                  Add to playbook
                </Link>
                <Link
                  href={`/dashboard/sessions?highlight=${item.session_id}`}
                  className="flex items-center gap-1 text-xs text-violet-600 dark:text-violet-400 hover:underline"
                >
                  <MessageSquare size={12} />
                  View session
                </Link>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
