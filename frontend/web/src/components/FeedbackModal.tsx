'use client'

import { useState, useRef, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { feedbackApi, playbooksApi } from '@/lib/api'
import { X, ThumbsUp, ThumbsDown } from 'lucide-react'

const POSITIVE_LABELS = ['helpful', 'accurate', 'fast', 'clear', 'complete']
const NEGATIVE_LABELS = ['wrong', 'off-topic', 'inappropriate', 'slow', 'incomplete', 'confusing']

type ToolCorrectionState = {
  tool_name: string
  was_correct: boolean
  correct_tool: string
  reason: string
}

export function FeedbackModal({
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

  const { data: playbooks = [] } = useQuery({
    queryKey: ['playbooks', agentId],
    queryFn: () => playbooksApi.list(agentId),
    staleTime: 60_000,
  })

  const [selectedPlaybookId, setSelectedPlaybookId] = useState<string>(
    message.feedback?.playbook_correction?.correct_playbook_id ?? ''
  )

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
      qc.invalidateQueries({ queryKey: ['session-detail', sessionId] })
      qc.invalidateQueries({ queryKey: ['corrections'] })
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

        <p className="text-sm text-gray-600 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 rounded-lg p-3 mb-5 line-clamp-3">
          {message.content}
        </p>

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

        <div className="mb-4">
          <label className="text-xs font-medium text-gray-500 uppercase tracking-wider block mb-1.5 flex items-center justify-between">
            <span>What should it have said?</span>
            <span className="normal-case text-gray-400">(trains the bot)</span>
          </label>
          <textarea
            ref={correctionRef}
            value={idealResponse}
            onChange={(e) => setIdealResponse(e.target.value)}
            placeholder="Write the ideal response here — it will be used as a training example for future conversations…"
            rows={4}
            className="w-full text-sm rounded-xl border border-violet-200 dark:border-violet-800 bg-violet-50/40 dark:bg-violet-900/10 px-3 py-2 text-gray-900 dark:text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-violet-400 resize-none"
          />
          <div className="mt-2 flex items-start gap-2 px-1">
            <div className="mt-0.5 text-amber-500 dark:text-amber-400">
               <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" className="w-3 h-3"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><path d="M12 9v4"/><path d="M12 17h.01"/></svg>
            </div>
            <p className="text-[10px] text-gray-500 dark:text-gray-400 leading-tight">
              <span className="font-semibold text-amber-600 dark:text-amber-400">Compliance Check:</span> Please ensure corrections do not contain raw PII (names, phone numbers, or emails). Use generic labels like [PERSON] or [PHONE] instead.
            </p>
          </div>
        </div>

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
