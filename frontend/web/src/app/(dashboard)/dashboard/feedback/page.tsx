'use client'

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { feedbackApi, agentsApi } from '@/lib/api'
import {
  ThumbsUp,
  ThumbsDown,
  Download,
  Filter,
  Tag,
  MessageSquare,
  TrendingUp,
} from 'lucide-react'
import { formatDistanceToNow } from 'date-fns'

function SummaryCard({
  label,
  value,
  sub,
  icon: Icon,
  color,
}: {
  label: string
  value: string | number
  sub?: string
  icon: any
  color: string
}) {
  const colors: Record<string, string> = {
    green: 'bg-green-50 text-green-600 dark:bg-green-900/20 dark:text-green-400',
    red: 'bg-red-50 text-red-600 dark:bg-red-900/20 dark:text-red-400',
    violet: 'bg-violet-50 text-violet-600 dark:bg-violet-900/20 dark:text-violet-400',
  }
  return (
    <div className="bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-800 p-5">
      <div className="flex items-start justify-between mb-3">
        <p className="text-sm text-gray-500 dark:text-gray-400">{label}</p>
        <div className={`w-9 h-9 rounded-xl flex items-center justify-center ${colors[color]}`}>
          <Icon size={18} />
        </div>
      </div>
      <p className="text-2xl font-bold text-gray-900 dark:text-white">{value}</p>
      {sub && <p className="text-xs text-gray-400 mt-1">{sub}</p>}
    </div>
  )
}

export default function FeedbackPage() {
  const [agentFilter, setAgentFilter] = useState('')
  const [ratingFilter, setRatingFilter] = useState('')
  const [page, setPage] = useState(0)
  const PAGE_SIZE = 20

  const { data: agents } = useQuery({
    queryKey: ['agents'],
    queryFn: () => agentsApi.list(),
  })

  const { data: summary, isLoading: summaryLoading } = useQuery({
    queryKey: ['feedback-summary', agentFilter],
    queryFn: () => feedbackApi.summary({ agent_id: agentFilter || undefined }),
    staleTime: 30_000,
  })

  const { data: feedbackList, isLoading: listLoading } = useQuery({
    queryKey: ['feedback-list', agentFilter, ratingFilter, page],
    queryFn: () =>
      feedbackApi.list({
        agent_id: agentFilter || undefined,
        rating: ratingFilter || undefined,
        limit: PAGE_SIZE,
        offset: page * PAGE_SIZE,
      }),
    staleTime: 30_000,
  })

  const agentMap: Record<string, string> = {}
  for (const a of agents || []) {
    agentMap[a.id] = a.name
  }

  function handleExport(format: 'jsonl' | 'csv') {
    const params = new URLSearchParams({
      format,
      ...(agentFilter && { agent_id: agentFilter }),
      ...(ratingFilter && { rating: ratingFilter }),
    })
    // Download via hidden link — HttpOnly auth cookie is sent automatically
    const url = `/api/v1/proxy/feedback/export?${params}`
    fetch(url, { credentials: 'include' })
      .then((r) => r.blob())
      .then((blob) => {
        const a = document.createElement('a')
        a.href = URL.createObjectURL(blob)
        a.download = `feedback_export.${format === 'jsonl' ? 'jsonl' : 'csv'}`
        a.click()
      })
  }

  return (
    <div className="p-8">
      <div className="flex items-start justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Feedback & Training</h1>
          <p className="text-gray-500 dark:text-gray-400 mt-1">
            Review user ratings, apply labels, and export training data.
          </p>
        </div>
        {/* Export buttons */}
        <div className="flex gap-2">
          <button
            onClick={() => handleExport('csv')}
            className="flex items-center gap-2 px-4 py-2 rounded-xl border border-gray-200 dark:border-gray-700 text-sm text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors"
          >
            <Download size={14} />
            CSV
          </button>
          <button
            onClick={() => handleExport('jsonl')}
            className="flex items-center gap-2 px-4 py-2 rounded-xl bg-violet-600 hover:bg-violet-700 text-white text-sm transition-colors"
          >
            <Download size={14} />
            JSONL (Fine-tune)
          </button>
        </div>
      </div>

      {/* Summary cards */}
      {!summaryLoading && summary && (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
          <SummaryCard
            label="Total Feedback"
            value={summary.total}
            icon={MessageSquare}
            color="violet"
          />
          <SummaryCard
            label="Positive"
            value={summary.positive}
            sub={`${summary.positive_pct}% of total`}
            icon={ThumbsUp}
            color="green"
          />
          <SummaryCard
            label="Negative"
            value={summary.negative}
            icon={ThumbsDown}
            color="red"
          />
          <SummaryCard
            label="Positive Rate"
            value={`${summary.positive_pct}%`}
            icon={TrendingUp}
            color={summary.positive_pct >= 70 ? 'green' : summary.positive_pct >= 40 ? 'violet' : 'red'}
          />
        </div>
      )}

      {/* Top labels */}
      {summary && (summary.top_positive_labels.length > 0 || summary.top_negative_labels.length > 0) && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-8">
          <div className="bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-800 p-5">
            <div className="flex items-center gap-2 mb-3">
              <Tag size={14} className="text-green-500" />
              <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-300">Top Positive Labels</h3>
            </div>
            <div className="space-y-2">
              {summary.top_positive_labels.map((l: any) => (
                <div key={l.label} className="flex items-center justify-between">
                  <span className="text-sm text-gray-600 dark:text-gray-400">{l.label}</span>
                  <div className="flex items-center gap-2">
                    <div className="w-24 h-1.5 bg-gray-100 dark:bg-gray-800 rounded-full overflow-hidden">
                      <div
                        className="h-full bg-green-400 rounded-full"
                        style={{ width: `${Math.min(100, (l.count / (summary.top_positive_labels[0]?.count || 1)) * 100)}%` }}
                      />
                    </div>
                    <span className="text-xs text-gray-400 w-6 text-right">{l.count}</span>
                  </div>
                </div>
              ))}
              {summary.top_positive_labels.length === 0 && (
                <p className="text-sm text-gray-400">No labels yet</p>
              )}
            </div>
          </div>

          <div className="bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-800 p-5">
            <div className="flex items-center gap-2 mb-3">
              <Tag size={14} className="text-red-500" />
              <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-300">Top Negative Labels</h3>
            </div>
            <div className="space-y-2">
              {summary.top_negative_labels.map((l: any) => (
                <div key={l.label} className="flex items-center justify-between">
                  <span className="text-sm text-gray-600 dark:text-gray-400">{l.label}</span>
                  <div className="flex items-center gap-2">
                    <div className="w-24 h-1.5 bg-gray-100 dark:bg-gray-800 rounded-full overflow-hidden">
                      <div
                        className="h-full bg-red-400 rounded-full"
                        style={{ width: `${Math.min(100, (l.count / (summary.top_negative_labels[0]?.count || 1)) * 100)}%` }}
                      />
                    </div>
                    <span className="text-xs text-gray-400 w-6 text-right">{l.count}</span>
                  </div>
                </div>
              ))}
              {summary.top_negative_labels.length === 0 && (
                <p className="text-sm text-gray-400">No labels yet</p>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Per-agent breakdown */}
      {summary?.by_agent?.length > 0 && (
        <div className="bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-800 overflow-hidden mb-8">
          <div className="px-5 py-4 border-b border-gray-100 dark:border-gray-800">
            <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-300">Feedback by Agent</h3>
          </div>
          <table className="w-full text-sm">
            <thead className="bg-gray-50 dark:bg-gray-800/50">
              <tr>
                {['Agent', 'Total', 'Positive', 'Negative', 'Positive %'].map((h) => (
                  <th key={h} className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wider">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50 dark:divide-gray-800">
              {summary.by_agent.map((a: any) => (
                <tr key={a.agent_id} className="hover:bg-gray-50 dark:hover:bg-gray-800/30">
                  <td className="px-4 py-3 font-medium text-gray-900 dark:text-white">
                    {a.agent_name}
                  </td>
                  <td className="px-4 py-3 text-gray-600 dark:text-gray-400">{a.total}</td>
                  <td className="px-4 py-3 text-green-600 dark:text-green-400">{a.positive}</td>
                  <td className="px-4 py-3 text-red-500 dark:text-red-400">{a.negative}</td>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      <div className="w-20 h-1.5 bg-gray-100 dark:bg-gray-800 rounded-full overflow-hidden">
                        <div
                          className={`h-full rounded-full ${a.positive_pct >= 70 ? 'bg-green-400' : a.positive_pct >= 40 ? 'bg-amber-400' : 'bg-red-400'}`}
                          style={{ width: `${a.positive_pct}%` }}
                        />
                      </div>
                      <span className={`font-medium text-xs ${a.positive_pct >= 70 ? 'text-green-600' : a.positive_pct >= 40 ? 'text-amber-500' : 'text-red-500'}`}>
                        {a.positive_pct}%
                      </span>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Filters */}
      <div className="flex gap-3 mb-4">
        <div className="flex items-center gap-2 bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 rounded-xl px-3 py-2">
          <Filter size={14} className="text-gray-400" />
          <select
            value={agentFilter}
            onChange={(e) => { setAgentFilter(e.target.value); setPage(0) }}
            className="text-sm bg-transparent text-gray-700 dark:text-gray-300 focus:outline-none"
          >
            <option value="">All agents</option>
            {(agents || []).map((a: any) => (
              <option key={a.id} value={a.id}>{a.name}</option>
            ))}
          </select>
        </div>
        <div className="flex items-center gap-2 bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 rounded-xl px-3 py-2">
          <select
            value={ratingFilter}
            onChange={(e) => { setRatingFilter(e.target.value); setPage(0) }}
            className="text-sm bg-transparent text-gray-700 dark:text-gray-300 focus:outline-none"
          >
            <option value="">All ratings</option>
            <option value="positive">Positive</option>
            <option value="negative">Negative</option>
          </select>
        </div>
      </div>

      {/* Feedback list */}
      {listLoading ? (
        <div className="space-y-2">
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-20 rounded-xl bg-gray-100 dark:bg-gray-800 animate-pulse" />
          ))}
        </div>
      ) : feedbackList?.length === 0 ? (
        <div className="text-center py-12 bg-white dark:bg-gray-900 rounded-xl border border-dashed border-gray-200 dark:border-gray-700">
          <ThumbsUp size={36} className="mx-auto text-gray-300 dark:text-gray-600 mb-3" />
          <p className="text-gray-500">No feedback yet. Rate responses in Chat History to get started.</p>
        </div>
      ) : (
        <>
          <div className="space-y-2">
            {(feedbackList || []).map((fb: any) => (
              <div
                key={fb.id}
                className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 px-5 py-4"
              >
                <div className="flex items-start gap-3">
                  <div className={`mt-0.5 flex-shrink-0 ${fb.rating === 'positive' ? 'text-green-500' : 'text-red-500'}`}>
                    {fb.rating === 'positive' ? <ThumbsUp size={16} /> : <ThumbsDown size={16} />}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex flex-wrap items-center gap-2 mb-1">
                      <span className="text-xs font-medium text-gray-500">
                        {agentMap[fb.agent_id] || 'Unknown Agent'}
                      </span>
                      <span className="text-gray-300 dark:text-gray-700">·</span>
                      <span className="text-xs text-gray-400">
                        {fb.created_at ? formatDistanceToNow(new Date(fb.created_at), { addSuffix: true }) : ''}
                      </span>
                      {fb.labels?.map((l: string) => (
                        <span key={l} className={`px-2 py-0.5 rounded-full text-xs font-medium ${
                          fb.rating === 'positive'
                            ? 'bg-green-100 text-green-700 dark:bg-green-900/20 dark:text-green-400'
                            : 'bg-red-100 text-red-700 dark:bg-red-900/20 dark:text-red-400'
                        }`}>
                          {l}
                        </span>
                      ))}
                    </div>
                    <p className="text-sm text-gray-700 dark:text-gray-300 truncate">
                      Message: <span className="text-gray-500">{fb.message_id.slice(0, 12)}…</span>
                    </p>
                    {fb.comment && (
                      <p className="text-sm text-gray-500 dark:text-gray-400 mt-1 italic">
                        "{fb.comment}"
                      </p>
                    )}
                  </div>
                  <span className={`flex-shrink-0 text-xs px-2 py-0.5 rounded-full font-medium ${
                    fb.feedback_source === 'operator'
                      ? 'bg-violet-100 text-violet-700 dark:bg-violet-900/20 dark:text-violet-400'
                      : 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400'
                  }`}>
                    {fb.feedback_source}
                  </span>
                </div>
              </div>
            ))}
          </div>

          {/* Pagination */}
          <div className="flex items-center justify-between mt-4">
            <button
              disabled={page === 0}
              onClick={() => setPage((p) => p - 1)}
              className="px-4 py-2 text-sm rounded-xl border border-gray-200 dark:border-gray-700 disabled:opacity-40 hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors"
            >
              Previous
            </button>
            <span className="text-sm text-gray-500">Page {page + 1}</span>
            <button
              disabled={(feedbackList?.length ?? 0) < PAGE_SIZE}
              onClick={() => setPage((p) => p + 1)}
              className="px-4 py-2 text-sm rounded-xl border border-gray-200 dark:border-gray-700 disabled:opacity-40 hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors"
            >
              Next
            </button>
          </div>
        </>
      )}
    </div>
  )
}
