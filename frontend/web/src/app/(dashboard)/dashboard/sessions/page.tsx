'use client'

import { useState, useRef, useEffect } from 'react'
import { useSearchParams } from 'next/navigation'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { sessionsApi, agentsApi, feedbackApi, playbooksApi } from '@/lib/api'
import { maskSensitivePII } from '@/lib/pii-mask'
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
  Zap,
  BookOpen,
  ScrollText,
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

// ── Types for correction state ────────────────────────────────────────────────
type ToolCorrectionState = {
  tool_name: string
  was_correct: boolean
  correct_tool: string
  reason: string
}

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
  const qc = useQueryClient()

  // ── Scroll-to-correction on open ────────────────────────────────────────────
  useEffect(() => {
    if (focusCorrection && correctionRef.current) {
      correctionRef.current.scrollIntoView({ behavior: 'smooth', block: 'center' })
      correctionRef.current.focus()
    }
  }, [focusCorrection])

  // ── Basic feedback state ─────────────────────────────────────────────────────
  const [rating, setRating] = useState<'positive' | 'negative' | null>(
    message.feedback?.rating ?? null
  )
  const [labels, setLabels] = useState<string[]>(message.feedback?.labels ?? [])
  const [comment, setComment] = useState(message.feedback?.comment ?? '')
  const [idealResponse, setIdealResponse] = useState(message.feedback?.ideal_response ?? '')
  const [correctionReason, setCorrectionReason] = useState(message.feedback?.correction_reason ?? '')

  // ── Tool corrections state ───────────────────────────────────────────────────
  const rawToolCalls: Array<{ tool_name?: string; name?: string }> = Array.isArray(message.tool_calls)
    ? message.tool_calls
    : message.tool_calls
      ? [message.tool_calls]
      : []

  const [toolCorrections, setToolCorrections] = useState<ToolCorrectionState[]>(() => {
    const existing: Record<string, any> = {}
    for (const tc of message.feedback?.tool_corrections ?? []) {
      existing[tc.tool_name] = tc
    }
    return rawToolCalls.map((tc) => {
      const name = tc.tool_name ?? tc.name ?? 'unknown'
      return existing[name] ?? { tool_name: name, was_correct: true, correct_tool: '', reason: '' }
    })
  })

  const updateToolCorrection = (idx: number, patch: Partial<ToolCorrectionState>) => {
    setToolCorrections((prev) => prev.map((t, i) => i === idx ? { ...t, ...patch } : t))
  }

  // ── Playbook correction state ────────────────────────────────────────────────
  const { data: playbooks = [] } = useQuery({
    queryKey: ['playbooks', agentId],
    queryFn: () => playbooksApi.list(agentId),
    staleTime: 60_000,
  })

  const [selectedPlaybookId, setSelectedPlaybookId] = useState<string>(
    message.feedback?.playbook_correction?.correct_playbook_id ?? ''
  )

  // ── Submit ──────────────────────────────────────────────────────────────────
  const submit = useMutation({
    mutationFn: () => {
      const playbookCorrection = selectedPlaybookId
        ? {
            correct_playbook_id: selectedPlaybookId,
            correct_playbook_name: (playbooks as any[]).find((p: any) => p.id === selectedPlaybookId)?.name ?? '',
          }
        : null

      const filteredToolCorrections = toolCorrections.map((tc) => ({
        tool_name: tc.tool_name,
        was_correct: tc.was_correct,
        correct_tool: tc.correct_tool || undefined,
        reason: tc.reason || undefined,
      }))

      return feedbackApi.submit({
        message_id: message.id,
        session_id: sessionId,
        agent_id: agentId,
        rating: rating || undefined,
        labels: labels.length > 0 ? labels : undefined,
        comment: comment || undefined,
        ideal_response: idealResponse || undefined,
        correction_reason: correctionReason || undefined,
        feedback_source: 'operator',
        playbook_correction: playbookCorrection,
        tool_corrections: filteredToolCorrections,
      })
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['session-detail'] })
      onSubmitted()
      onClose()
    },
  })

  const availableLabels = rating === 'positive' ? POSITIVE_LABELS : NEGATIVE_LABELS

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm p-4">
      <div className="bg-white dark:bg-gray-900 rounded-2xl shadow-xl w-full max-w-lg max-h-[90vh] overflow-y-auto p-6 relative">
        <button
          onClick={onClose}
          className="absolute top-4 right-4 text-gray-400 hover:text-gray-600 dark:hover:text-gray-200"
        >
          <X size={18} />
        </button>
        <h3 className="text-base font-semibold text-gray-900 dark:text-white mb-4">
          Review this response
        </h3>

        {/* Message preview */}
        <p className="text-sm text-gray-600 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 rounded-lg p-3 mb-5 line-clamp-3">
          {maskSensitivePII(message.content)}
        </p>

        {/* ── Rating ─────────────────────────────────────────────────────── */}
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

        {/* ── Labels ─────────────────────────────────────────────────────── */}
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

        {/* ── Tool-call corrections ───────────────────────────────────────── */}
        {toolCorrections.length > 0 && (
          <div className="mb-5">
            <p className="text-xs font-medium text-gray-500 uppercase tracking-wider mb-2">
              Tool calls — were these correct?
            </p>
            <div className="space-y-3">
              {toolCorrections.map((tc, idx) => (
                <div
                  key={idx}
                  className={`rounded-xl border p-3 text-sm transition-colors ${
                    tc.was_correct
                      ? 'border-gray-200 dark:border-gray-700'
                      : 'border-red-200 dark:border-red-800 bg-red-50/40 dark:bg-red-900/10'
                  }`}
                >
                  <div className="flex items-center justify-between mb-2">
                    <span className="font-mono text-xs bg-gray-100 dark:bg-gray-800 px-2 py-0.5 rounded text-gray-700 dark:text-gray-300">
                      {tc.tool_name}
                    </span>
                    <div className="flex gap-2">
                      <button
                        onClick={() => updateToolCorrection(idx, { was_correct: true })}
                        className={`text-xs px-2.5 py-1 rounded-full border transition-all ${
                          tc.was_correct
                            ? 'border-green-500 bg-green-50 text-green-700 dark:bg-green-900/30'
                            : 'border-gray-200 dark:border-gray-700 text-gray-500 hover:border-green-400'
                        }`}
                      >
                        Correct
                      </button>
                      <button
                        onClick={() => updateToolCorrection(idx, { was_correct: false })}
                        className={`text-xs px-2.5 py-1 rounded-full border transition-all ${
                          !tc.was_correct
                            ? 'border-red-500 bg-red-50 text-red-700 dark:bg-red-900/30'
                            : 'border-gray-200 dark:border-gray-700 text-gray-500 hover:border-red-400'
                        }`}
                      >
                        Wrong
                      </button>
                    </div>
                  </div>
                  {!tc.was_correct && (
                    <div className="space-y-1.5 mt-2">
                      <input
                        type="text"
                        value={tc.correct_tool}
                        onChange={(e) => updateToolCorrection(idx, { correct_tool: e.target.value })}
                        placeholder="Correct tool name (leave blank if none)"
                        className="w-full text-xs rounded-lg border border-gray-200 dark:border-gray-700 bg-transparent px-2.5 py-1.5 text-gray-900 dark:text-white placeholder-gray-400 focus:outline-none focus:ring-1 focus:ring-violet-400"
                      />
                      <input
                        type="text"
                        value={tc.reason}
                        onChange={(e) => updateToolCorrection(idx, { reason: e.target.value })}
                        placeholder="Why was it wrong? (optional)"
                        className="w-full text-xs rounded-lg border border-gray-200 dark:border-gray-700 bg-transparent px-2.5 py-1.5 text-gray-900 dark:text-white placeholder-gray-400 focus:outline-none focus:ring-1 focus:ring-violet-400"
                      />
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* ── Playbook correction ─────────────────────────────────────────── */}
        {(playbooks as any[]).length > 0 && (
          <div className="mb-5">
            <label className="text-xs font-medium text-gray-500 uppercase tracking-wider block mb-1.5">
              Playbook that should have handled this
              <span className="normal-case text-gray-400 ml-1">(optional)</span>
            </label>
            <select
              value={selectedPlaybookId}
              onChange={(e) => setSelectedPlaybookId(e.target.value)}
              className="w-full text-sm rounded-xl border border-gray-200 dark:border-gray-700 bg-transparent px-3 py-2 text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-violet-400"
            >
              <option value="">— No change / not applicable —</option>
              {(playbooks as any[]).map((p: any) => (
                <option key={p.id} value={p.id}>{p.name}</option>
              ))}
            </select>
          </div>
        )}

        {/* ── Ideal response ─────────────────────────────────────────────── */}
        <div className="mb-4">
          <label className="text-xs font-medium text-gray-500 uppercase tracking-wider block mb-1.5">
            What should it have said?
            <span className="normal-case text-gray-400 ml-1">(trains the bot)</span>
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

        {/* ── Correction reason ───────────────────────────────────────────── */}
        <div className="mb-4">
          <label className="text-xs font-medium text-gray-500 uppercase tracking-wider block mb-1.5">
            Why was it wrong?
            <span className="normal-case text-gray-400 ml-1">(optional)</span>
          </label>
          <input
            type="text"
            value={correctionReason}
            onChange={(e) => setCorrectionReason(e.target.value)}
            placeholder="e.g. wrong price, missed context, tone too formal…"
            className="w-full text-sm rounded-xl border border-gray-200 dark:border-gray-700 bg-transparent px-3 py-2 text-gray-900 dark:text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-violet-400"
          />
        </div>

        {/* ── Comment ────────────────────────────────────────────────────── */}
        <textarea
          value={comment}
          onChange={(e) => setComment(e.target.value)}
          placeholder="Any other notes…"
          rows={2}
          className="w-full text-sm rounded-xl border border-gray-200 dark:border-gray-700 bg-transparent px-3 py-2 text-gray-900 dark:text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-violet-400 mb-4 resize-none"
        />

        <button
          disabled={!rating && !idealResponse}
          onClick={() => submit.mutate()}
          className="w-full py-2.5 rounded-xl bg-violet-600 hover:bg-violet-700 disabled:opacity-40 text-white text-sm font-medium transition-colors"
        >
          {submit.isPending ? 'Saving…' : idealResponse ? 'Save Correction' : 'Save & Learn'}
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
            {maskSensitivePII(message.content)}
            
            {/* Metadata enrichment: Playbook, Tools, Rerieval */}
            {(message.playbook_name || message.tool_calls || (message.sources && message.sources.length > 0)) && (
              <div className="mt-3 pt-3 border-t border-gray-200/50 dark:border-gray-700/50 flex flex-col gap-2">
                {/* Active Playbook */}
                {message.playbook_name && (
                  <div className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wider text-violet-600 dark:text-violet-400 bg-violet-50 dark:bg-violet-900/20 px-2 py-0.5 rounded-md w-fit">
                    <ScrollText size={10} />
                    Playbook: {message.playbook_name}
                  </div>
                )}

                {/* Tools Invoked */}
                {message.tool_calls && (
                  <div className="flex flex-wrap gap-1.5">
                    {Array.isArray(message.tool_calls) ? (
                      message.tool_calls.map((tc: any, i: number) => (
                        <div key={i} className="flex items-center gap-1 text-[10px] bg-amber-50 dark:bg-amber-900/20 text-amber-700 dark:text-amber-400 px-1.5 py-0.5 rounded border border-amber-200/50 dark:border-amber-800/50">
                          <Zap size={10} />
                          {tc.tool_name || tc.name || 'tool'}
                        </div>
                      ))
                    ) : (
                      <div className="flex items-center gap-1 text-[10px] bg-amber-50 dark:bg-amber-900/20 text-amber-700 dark:text-amber-400 px-1.5 py-0.5 rounded border border-amber-200/50 dark:border-amber-800/50">
                        <Zap size={10} />
                        {(message.tool_calls as any).tool_name || (message.tool_calls as any).name || 'tool'}
                      </div>
                    )}
                  </div>
                )}

                {/* RAG Sources */}
                {message.sources && message.sources.length > 0 && (
                  <div className="space-y-1.5">
                    <div className="flex items-center gap-1 text-[10px] text-gray-500 dark:text-gray-400 font-medium">
                      <BookOpen size={10} />
                      Sources ({message.sources.length})
                    </div>
                    <div className="flex flex-col gap-1">
                      {message.sources.slice(0, 3).map((src: any, i: number) => (
                        <div key={i} className="text-[10px] bg-white/50 dark:bg-gray-900/30 p-1.5 rounded border border-gray-200/50 dark:border-gray-700/50 text-gray-600 dark:text-gray-400 break-words">
                          <span className="font-bold block mb-0.5 text-gray-800 dark:text-gray-200">{src.title || 'Untitled Document'}</span>
                          <span className="line-clamp-2 italic">"{src.content || src.text || '...'}"</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
          <div className="flex items-center gap-2">
            <span className="text-xs text-gray-400">
              {message.created_at ? format(new Date(message.created_at), 'HH:mm') : ''}
            </span>
            {(() => {
              let turnInfo = null
              const hasTool = message.tool_calls && (Array.isArray(message.tool_calls) ? message.tool_calls.length > 0 : true)
              const hasPlaybook = message.playbook_name
              const hasSources = message.sources && message.sources.length > 0
              if (hasTool) {
                const toolNames = Array.isArray(message.tool_calls) 
                  ? message.tool_calls.map((tc: any) => tc.tool_name || tc.name || 'tool').join(', ')
                  : (message.tool_calls?.tool_name || message.tool_calls?.name || 'tool')
                turnInfo = <span key="tool" className="text-xs text-amber-600 dark:text-amber-400">{toolNames}</span>
              } else if (hasPlaybook) {
                turnInfo = <span key="playbook" className="text-xs text-violet-600 dark:text-violet-400">{message.playbook_name}</span>
              } else if (hasSources) {
                const docNames = message.sources.slice(0, 2).map((s: any) => s.title || 'Doc').join(', ')
                turnInfo = <span key="sources" className="text-xs text-blue-600 dark:text-blue-400">{docNames}</span>
              }
              return turnInfo
            })()}
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

function SessionRow({ session, agentName, initialExpanded = false }: { session: any; agentName: string; initialExpanded?: boolean }) {
  const [expanded, setExpanded] = useState(initialExpanded)

  const { data: detail, isLoading } = useQuery({
    queryKey: ['session-detail', session.id],
    queryFn: () => sessionsApi.get(session.id, true),
    enabled: expanded,
    staleTime: 30_000,
  })

  return (
    <div id={`session-${session.id}`} className="border border-gray-200 dark:border-gray-800 rounded-xl overflow-hidden mb-3">
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
  const searchParams = useSearchParams()
  const highlightId = searchParams.get('highlight')

  useEffect(() => {
    if (highlightId) {
      const element = document.getElementById(`session-${highlightId}`)
      if (element) {
        element.scrollIntoView({ behavior: 'smooth', block: 'center' })
      }
    }
  }, [highlightId])

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
              initialExpanded={highlightId === sess.id}
            />
          ))}
        </div>
      )}
    </div>
  )
}
