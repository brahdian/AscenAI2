'use client'

import { useState, useRef, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { sessionsApi, agentsApi, feedbackApi } from '@/lib/api'
import Link from 'next/link'
import {
  MessageSquare,
  Clock,
  ChevronDown,
  ChevronUp,
  ChevronRight,
  ThumbsUp,
  ThumbsDown,
  User,
  Bot,
  Wrench,
  X,
  Filter,
  PenLine,
} from 'lucide-react'
import { formatDistanceToNow, format } from 'date-fns'

function statusColor(status: string) {
  switch (status) {
    case 'active': return 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-300'
    case 'ended': return 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400'
    default: return 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-300'
  }
}

const POSITIVE_LABELS = ['helpful', 'accurate', 'fast', 'clear', 'complete']
const NEGATIVE_LABELS = ['wrong', 'off-topic', 'inappropriate', 'slow', 'incomplete', 'confusing']

function FeedbackModal({
  message,
  agentId,
  sessionId,
  focusCorrection = false,
  onClose,
  onSubmitted,
}: {
  message: any
  agentId: string
  sessionId: string
  focusCorrection?: boolean
  onClose: () => void
  onSubmitted: () => void
}) {
  const correctionRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    if (focusCorrection && correctionRef.current) {
      correctionRef.current.scrollIntoView({ behavior: 'smooth', block: 'center' })
      correctionRef.current.focus()
    }
  }, [focusCorrection])

  const [rating, setRating] = useState<'positive' | 'negative' | null>(
    message.feedback?.rating ?? null
  )
  const [labels, setLabels] = useState<string[]>(message.feedback?.labels ?? [])
  const [comment, setComment] = useState(message.feedback?.comment ?? '')
  const [idealResponse, setIdealResponse] = useState(message.feedback?.ideal_response ?? '')
  const [correctionReason, setCorrectionReason] = useState(message.feedback?.correction_reason ?? '')
  const qc = useQueryClient()

  const submit = useMutation({
    mutationFn: () =>
      feedbackApi.submit({
        message_id: message.id,
        session_id: sessionId,
        agent_id: agentId,
        rating: rating!,
        labels,
        comment: comment || undefined,
        ideal_response: idealResponse || undefined,
        correction_reason: correctionReason || undefined,
        feedback_source: 'operator',
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['session-detail'] })
      onSubmitted()
      onClose()
    },
  })

  const availableLabels = rating === 'positive' ? POSITIVE_LABELS : NEGATIVE_LABELS

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm">
      <div className="bg-white dark:bg-gray-900 rounded-2xl shadow-xl w-full max-w-md p-6 relative">
        <button
          onClick={onClose}
          className="absolute top-4 right-4 text-gray-400 hover:text-gray-600 dark:hover:text-gray-200"
        >
          <X size={18} />
        </button>
        <h3 className="text-base font-semibold text-gray-900 dark:text-white mb-4">
          Rate this response
        </h3>

        {/* Message preview */}
        <p className="text-sm text-gray-600 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 rounded-lg p-3 mb-5 line-clamp-3">
          {message.content}
        </p>

        {/* Rating */}
        <div className="flex gap-3 mb-5">
          <button
            onClick={() => { setRating('positive'); setLabels([]) }}
            className={`flex-1 flex items-center justify-center gap-2 py-2.5 rounded-xl border-2 text-sm font-medium transition-all ${
              rating === 'positive'
                ? 'border-green-500 bg-green-50 text-green-700 dark:bg-green-900/30 dark:text-green-300'
                : 'border-gray-200 dark:border-gray-700 text-gray-600 dark:text-gray-400 hover:border-green-400'
            }`}
          >
            <ThumbsUp size={16} />
            Positive
          </button>
          <button
            onClick={() => { setRating('negative'); setLabels([]) }}
            className={`flex-1 flex items-center justify-center gap-2 py-2.5 rounded-xl border-2 text-sm font-medium transition-all ${
              rating === 'negative'
                ? 'border-red-500 bg-red-50 text-red-700 dark:bg-red-900/30 dark:text-red-300'
                : 'border-gray-200 dark:border-gray-700 text-gray-600 dark:text-gray-400 hover:border-red-400'
            }`}
          >
            <ThumbsDown size={16} />
            Negative
          </button>
        </div>

        {/* Labels */}
        {rating && (
          <div className="mb-5">
            <p className="text-xs font-medium text-gray-500 uppercase tracking-wider mb-2">Labels</p>
            <div className="flex flex-wrap gap-2">
              {availableLabels.map((l) => (
                <button
                  key={l}
                  onClick={() =>
                    setLabels((prev) =>
                      prev.includes(l) ? prev.filter((x) => x !== l) : [...prev, l]
                    )
                  }
                  className={`px-3 py-1 rounded-full text-xs border transition-all ${
                    labels.includes(l)
                      ? 'bg-violet-100 border-violet-400 text-violet-700 dark:bg-violet-900/30 dark:text-violet-300'
                      : 'border-gray-200 dark:border-gray-700 text-gray-500 hover:border-violet-300'
                  }`}
                >
                  {l}
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Ideal response — shown for negative or when operator wants to correct */}
        <div className="mb-4">
          <label className="text-xs font-medium text-gray-500 uppercase tracking-wider block mb-1.5">
            What should it have said? <span className="normal-case text-gray-400">(trains the bot)</span>
          </label>
          <textarea
            ref={correctionRef}
            value={idealResponse}
            onChange={(e) => setIdealResponse(e.target.value)}
            placeholder="Write the ideal response here — it will be used as a training example for future conversations…"
            rows={4}
            className="w-full text-sm rounded-xl border border-violet-200 dark:border-violet-800 bg-violet-50/40 dark:bg-violet-900/10 px-3 py-2 text-gray-900 dark:text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-violet-400 resize-none"
          />
        </div>

        {/* Correction reason */}
        <div className="mb-4">
          <label className="text-xs font-medium text-gray-500 uppercase tracking-wider block mb-1.5">
            Why was it wrong? <span className="normal-case text-gray-400">(optional)</span>
          </label>
          <input
            type="text"
            value={correctionReason}
            onChange={(e) => setCorrectionReason(e.target.value)}
            placeholder="e.g. wrong price, missed context, tone too formal…"
            className="w-full text-sm rounded-xl border border-gray-200 dark:border-gray-700 bg-transparent px-3 py-2 text-gray-900 dark:text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-violet-400"
          />
        </div>

        {/* Comment */}
        <textarea
          value={comment}
          onChange={(e) => setComment(e.target.value)}
          placeholder="Any other notes…"
          rows={2}
          className="w-full text-sm rounded-xl border border-gray-200 dark:border-gray-700 bg-transparent px-3 py-2 text-gray-900 dark:text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-violet-400 mb-4 resize-none"
        />

        <button
          disabled={!rating || submit.isPending}
          onClick={() => submit.mutate()}
          className="w-full py-2.5 rounded-xl bg-violet-600 hover:bg-violet-700 disabled:opacity-40 text-white text-sm font-medium transition-colors"
        >
          {submit.isPending ? 'Saving…' : 'Save Feedback'}
        </button>
      </div>
    </div>
  )
}

function MessageBubble({
  message,
  agentId,
  sessionId,
}: {
  message: any
  agentId: string
  sessionId: string
}) {
  const [showFeedback, setShowFeedback] = useState(false)
  const [focusCorrection, setFocusCorrection] = useState(false)
  const qc = useQueryClient()

  const openRate = () => { setFocusCorrection(false); setShowFeedback(true) }
  const openCorrect = () => { setFocusCorrection(true); setShowFeedback(true) }
  const isUser = message.role === 'user'
  const isAssistant = message.role === 'assistant'

  return (
    <>
      <div className={`flex gap-3 ${isUser ? 'flex-row-reverse' : 'flex-row'}`}>
        {/* Avatar */}
        <div className={`w-7 h-7 rounded-full flex-shrink-0 flex items-center justify-center text-white text-xs ${
          isUser ? 'bg-blue-500' : isAssistant ? 'bg-violet-500' : 'bg-gray-400'
        }`}>
          {isUser ? <User size={14} /> : isAssistant ? <Bot size={14} /> : <Wrench size={14} />}
        </div>

        {/* Content */}
        <div className={`max-w-[75%] ${isUser ? 'items-end' : 'items-start'} flex flex-col gap-1`}>
          <div className={`px-4 py-2.5 rounded-2xl text-sm leading-relaxed whitespace-pre-wrap ${
            isUser
              ? 'bg-blue-500 text-white rounded-tr-sm'
              : 'bg-gray-100 dark:bg-gray-800 text-gray-900 dark:text-white rounded-tl-sm'
          }`}>
            {message.content}
          </div>
          <div className="flex items-center gap-2">
            <span className="text-xs text-gray-400">
              {message.created_at ? format(new Date(message.created_at), 'HH:mm') : ''}
            </span>
            {message.tokens_used > 0 && (
              <span className="text-xs text-gray-400">{message.tokens_used} tok</span>
            )}
            {message.latency_ms > 0 && (
              <span className="text-xs text-gray-400">{message.latency_ms}ms</span>
            )}

            {/* Feedback / correction actions for assistant messages */}
            {isAssistant && (
              <div className="flex items-center gap-1.5 ml-1">
                {message.feedback ? (
                  <>
                    {/* Existing feedback badge */}
                    <button
                      onClick={openRate}
                      title="Click to edit feedback"
                      className={`flex items-center gap-1 text-xs px-2 py-0.5 rounded-full transition-opacity hover:opacity-80 ${
                        message.feedback.rating === 'positive'
                          ? 'bg-green-100 text-green-600 dark:bg-green-900/30'
                          : 'bg-red-100 text-red-600 dark:bg-red-900/30'
                      }`}>
                      {message.feedback.rating === 'positive' ? <ThumbsUp size={11} /> : <ThumbsDown size={11} />}
                      {message.feedback.labels?.join(', ') || message.feedback.rating}
                    </button>
                    {/* Correction indicator / edit button */}
                    <button
                      onClick={openCorrect}
                      title={message.feedback.ideal_response ? 'Correction added — click to edit' : 'Add a correction the bot will learn from'}
                      className={`flex items-center gap-1 text-xs px-2 py-0.5 rounded-full transition-colors ${
                        message.feedback.ideal_response
                          ? 'bg-violet-100 text-violet-600 dark:bg-violet-900/30 dark:text-violet-300'
                          : 'text-gray-400 hover:text-violet-500 hover:bg-violet-50 dark:hover:bg-violet-900/20'
                      }`}>
                      <PenLine size={11} />
                      {message.feedback.ideal_response ? 'Corrected' : 'Add correction'}
                    </button>
                  </>
                ) : (
                  <>
                    <button
                      onClick={openRate}
                      className="text-xs text-gray-400 hover:text-green-600 transition-colors flex items-center gap-1"
                      title="Rate this response"
                    >
                      <ThumbsUp size={11} />
                      Rate
                    </button>
                    <button
                      onClick={openCorrect}
                      className="text-xs text-gray-400 hover:text-violet-500 transition-colors flex items-center gap-1"
                      title="Add a correction the bot will learn from"
                    >
                      <PenLine size={11} />
                      Correct
                    </button>
                  </>
                )}
              </div>
            )}
          </div>
        </div>
      </div>

      {showFeedback && (
        <FeedbackModal
          message={message}
          agentId={agentId}
          sessionId={sessionId}
          focusCorrection={focusCorrection}
          onClose={() => setShowFeedback(false)}
          onSubmitted={() => qc.invalidateQueries({ queryKey: ['session-detail', sessionId] })}
        />
      )}
    </>
  )
}

function SessionRow({ session, agentName }: { session: any; agentName: string }) {
  const [expanded, setExpanded] = useState(false)

  const { data: detail, isLoading } = useQuery({
    queryKey: ['session-detail', session.id],
    queryFn: () => sessionsApi.get(session.id, true),
    enabled: expanded,
    staleTime: 30_000,
  })

  return (
    <div className="border border-gray-200 dark:border-gray-800 rounded-xl overflow-hidden mb-3">
      {/* Header row */}
      <button
        className="w-full flex items-center gap-4 px-4 py-3 bg-white dark:bg-gray-900 hover:bg-gray-50 dark:hover:bg-gray-800/50 transition-colors text-left"
        onClick={() => setExpanded((v) => !v)}
      >
        <div className="flex-1 min-w-0 grid grid-cols-5 gap-2 items-center">
          <span className="font-mono text-xs text-gray-500 truncate">
            {session.id.slice(0, 8)}…
          </span>
          <span className="text-sm text-gray-700 dark:text-gray-300 capitalize truncate">
            {agentName}
          </span>
          <span className="capitalize text-sm text-gray-600 dark:text-gray-400">
            {session.channel}
          </span>
          <span className="text-sm text-gray-500 truncate">
            {session.customer_identifier || '—'}
          </span>
          <div className="flex items-center gap-2">
            <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${statusColor(session.status)}`}>
              {session.status}
            </span>
            <span className="text-xs text-gray-400">
              {session.started_at
                ? formatDistanceToNow(new Date(session.started_at), { addSuffix: true })
                : '—'}
            </span>
          </div>
        </div>
        {expanded ? <ChevronUp size={16} className="text-gray-400 flex-shrink-0" /> : <ChevronDown size={16} className="text-gray-400 flex-shrink-0" />}
      </button>

      {/* Expanded message thread */}
      {expanded && (
        <div className="border-t border-gray-100 dark:border-gray-800 bg-gray-50 dark:bg-gray-950 px-6 py-5">
          {isLoading ? (
            <div className="space-y-3">
              {[1, 2, 3].map((i) => (
                <div key={i} className="h-10 rounded-xl bg-gray-200 dark:bg-gray-800 animate-pulse" />
              ))}
            </div>
          ) : !detail?.messages?.length ? (
            <p className="text-sm text-gray-400 text-center py-4">No messages in this session.</p>
          ) : (
            <div className="space-y-4">
              {detail.messages.map((msg: any) => (
                <MessageBubble
                  key={msg.id}
                  message={msg}
                  agentId={session.agent_id}
                  sessionId={session.id}
                />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export default function SessionsPage() {
  const [agentFilter, setAgentFilter] = useState('')
  const [statusFilter, setStatusFilter] = useState('')

  const { data: agents } = useQuery({
    queryKey: ['agents'],
    queryFn: () => agentsApi.list(),
  })

  const { data: sessions, isLoading } = useQuery({
    queryKey: ['sessions', agentFilter, statusFilter],
    queryFn: () => sessionsApi.list({
      limit: 100,
      agent_id: agentFilter || undefined,
      status: statusFilter || undefined,
    }),
  })

  const agentMap: Record<string, string> = {}
  for (const a of agents || []) {
    agentMap[a.id] = a.name
  }

  return (
    <div className="p-8">
      <div className="mb-6">
        <nav className="flex items-center gap-1.5 text-sm text-gray-400 mb-3">
          <Link href="/dashboard" className="hover:text-gray-600 dark:hover:text-gray-200 transition-colors">Dashboard</Link>
          <ChevronRight size={13} />
          <span className="text-gray-600 dark:text-gray-300">Chat History</span>
        </nav>
        <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Chat History</h1>
        <p className="text-gray-500 dark:text-gray-400 mt-1">
          Browse conversations, expand a session to review messages, and click any bot reply to rate it or add a correction the bot will learn from.
        </p>
      </div>

      {/* Filters */}
      <div className="flex gap-3 mb-6">
        <div className="flex items-center gap-2 bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 rounded-xl px-3 py-2">
          <Filter size={14} className="text-gray-400" />
          <select
            value={agentFilter}
            onChange={(e) => setAgentFilter(e.target.value)}
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
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="text-sm bg-transparent text-gray-700 dark:text-gray-300 focus:outline-none"
          >
            <option value="">All statuses</option>
            <option value="active">Active</option>
            <option value="ended">Ended</option>
          </select>
        </div>
        <span className="ml-auto text-sm text-gray-500 flex items-center">
          {sessions?.length ?? 0} sessions
        </span>
      </div>

      {/* Column headers */}
      {sessions && sessions.length > 0 && (
        <div className="grid grid-cols-5 gap-2 px-4 mb-2 text-xs font-medium text-gray-400 uppercase tracking-wider">
          <span>Session</span>
          <span>Agent</span>
          <span>Channel</span>
          <span>Customer</span>
          <span>Status / Time</span>
        </div>
      )}

      {isLoading ? (
        <div className="space-y-3">
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="h-14 rounded-xl bg-gray-100 dark:bg-gray-800 animate-pulse" />
          ))}
        </div>
      ) : sessions?.length === 0 ? (
        <div className="text-center py-16 bg-white dark:bg-gray-900 rounded-xl border border-dashed border-gray-200 dark:border-gray-700">
          <MessageSquare size={40} className="mx-auto text-gray-300 dark:text-gray-600 mb-3" />
          <p className="text-gray-500">No sessions yet. Start a conversation with one of your agents.</p>
        </div>
      ) : (
        <div>
          {sessions?.map((sess: any) => (
            <SessionRow
              key={sess.id}
              session={sess}
              agentName={agentMap[sess.agent_id] || 'Unknown Agent'}
            />
          ))}
        </div>
      )}
    </div>
  )
}
