'use client'

import { useParams, useRouter, useSearchParams } from 'next/navigation'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { flowsApi, sessionsApi } from '@/lib/api'
import { useEffect, useRef, useState } from 'react'
import { ArrowLeft, RefreshCw, Activity, CheckCircle2, XCircle, Clock, Play } from 'lucide-react'
import Link from 'next/link'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type StepType = 'wait_input' | 'llm' | 'tool' | 'condition' | 'deterministic' | 'goto' | 'end'

interface Step {
  id: string
  type: StepType
  prompt_to_user?: string
  prompt_template?: string
  tool_name?: string
  expression?: string
  action?: string
  target_step_id?: string
  final_message_template?: string
  next_step_id?: string
  then_step_id?: string
  else_step_id?: string
  status?: string
}

interface UiPos { x: number; y: number }
type Layout = Record<string, UiPos>

interface ExecutionState {
  status: string
  current_step_id: string | null
  variables: Record<string, unknown>
  history: Array<{ step_id: string; type: string; timestamp?: string; result?: unknown }>
  step_count: number
  error_message?: string | null
  source: string
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const STEP_COLORS: Record<StepType, { bg: string; border: string; text: string; dot: string }> = {
  wait_input:    { bg: 'bg-indigo-50 dark:bg-indigo-900/20',   border: 'border-indigo-200 dark:border-indigo-700',   text: 'text-indigo-700 dark:text-indigo-300',   dot: 'bg-indigo-500' },
  llm:           { bg: 'bg-purple-50 dark:bg-purple-900/20',   border: 'border-purple-200 dark:border-purple-700',   text: 'text-purple-700 dark:text-purple-300',   dot: 'bg-purple-500' },
  tool:          { bg: 'bg-orange-50 dark:bg-orange-900/20',   border: 'border-orange-200 dark:border-orange-700',   text: 'text-orange-700 dark:text-orange-300',   dot: 'bg-orange-500' },
  condition:     { bg: 'bg-amber-50 dark:bg-amber-900/20',     border: 'border-amber-200 dark:border-amber-700',     text: 'text-amber-700 dark:text-amber-300',     dot: 'bg-amber-500' },
  deterministic: { bg: 'bg-slate-50 dark:bg-slate-900/20',    border: 'border-slate-200 dark:border-slate-700',    text: 'text-slate-700 dark:text-slate-300',    dot: 'bg-slate-500' },
  goto:          { bg: 'bg-teal-50 dark:bg-teal-900/20',      border: 'border-teal-200 dark:border-teal-700',      text: 'text-teal-700 dark:text-teal-300',      dot: 'bg-teal-500' },
  end:           { bg: 'bg-emerald-50 dark:bg-emerald-900/20', border: 'border-emerald-200 dark:border-emerald-700', text: 'text-emerald-700 dark:text-emerald-300', dot: 'bg-emerald-500' },
}

const STEP_LABELS: Record<StepType, string> = {
  wait_input: 'Wait Input',
  llm: 'LLM',
  tool: 'Tool Call',
  condition: 'Condition',
  deterministic: 'Action',
  goto: 'Go To',
  end: 'End',
}

const NODE_W = 200
const NODE_H = 72

const STATUS_COLORS: Record<string, string> = {
  active: 'text-blue-600 bg-blue-50 border-blue-200',
  awaiting_input: 'text-amber-600 bg-amber-50 border-amber-200',
  completed: 'text-emerald-600 bg-emerald-50 border-emerald-200',
  failed: 'text-red-600 bg-red-50 border-red-200',
  escalated: 'text-purple-600 bg-purple-50 border-purple-200',
  not_started: 'text-gray-500 bg-gray-50 border-gray-200',
}

// ---------------------------------------------------------------------------
// Mini step node (read-only)
// ---------------------------------------------------------------------------

function ReadonlyNode({
  step,
  pos,
  isCurrent,
  isCompleted,
}: {
  step: Step
  pos: UiPos
  isCurrent: boolean
  isCompleted: boolean
}) {
  const colors = STEP_COLORS[step.type]

  return (
    <div
      className={`absolute select-none rounded-xl border-2 transition-all ${colors.bg} ${
        isCurrent
          ? 'border-violet-500 shadow-xl ring-4 ring-violet-200/50 dark:ring-violet-800/50 animate-pulse'
          : isCompleted
          ? 'border-emerald-400 opacity-70'
          : colors.border
      }`}
      style={{ left: pos.x, top: pos.y, width: NODE_W, height: NODE_H }}
    >
      {isCurrent && (
        <div className="absolute -top-2.5 left-1/2 -translate-x-1/2">
          <span className="text-[9px] font-bold px-2 py-0.5 bg-violet-600 text-white rounded-full whitespace-nowrap">
            CURRENT
          </span>
        </div>
      )}
      {isCompleted && !isCurrent && (
        <div className="absolute -top-2 -right-1">
          <CheckCircle2 size={14} className="text-emerald-500" />
        </div>
      )}
      <div className="px-3 py-2 h-full flex flex-col justify-center">
        <div className="flex items-center gap-2">
          <span className={`w-2 h-2 rounded-full flex-shrink-0 ${colors.dot}`} />
          <span className={`text-[10px] font-bold uppercase tracking-wider ${colors.text}`}>
            {STEP_LABELS[step.type]}
          </span>
        </div>
        <p className="text-xs text-gray-700 dark:text-gray-300 mt-0.5 truncate font-medium">
          {step.id}
        </p>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// SVG arrow
// ---------------------------------------------------------------------------

function Arrow({ from, to, color = '#6366f1' }: { from: UiPos; to: UiPos; color?: string }) {
  const x1 = from.x + NODE_W
  const y1 = from.y + NODE_H / 2
  const x2 = to.x
  const y2 = to.y + NODE_H / 2
  return (
    <path
      d={`M${x1},${y1} C${x1 + 60},${y1} ${x2 - 60},${y2} ${x2},${y2}`}
      fill="none"
      stroke={color}
      strokeWidth={1.5}
      opacity={0.5}
      markerEnd={`url(#ah)`}
    />
  )
}

// ---------------------------------------------------------------------------
// Auto layout (BFS)
// ---------------------------------------------------------------------------

function autoLayout(steps: Record<string, Step>, initialStepId?: string): Layout {
  const layout: Layout = {}
  const visited = new Set<string>()
  const queue: Array<{ id: string; col: number }> = []
  const startId = initialStepId || Object.keys(steps)[0]
  if (!startId) return layout
  queue.push({ id: startId, col: 0 })
  const colCounts: Record<number, number> = {}
  while (queue.length) {
    const { id, col } = queue.shift()!
    if (visited.has(id)) continue
    visited.add(id)
    colCounts[col] = colCounts[col] || 0
    layout[id] = { x: col * 270 + 60, y: (colCounts[col]!) * 130 + 60 }
    colCounts[col]++
    const step = steps[id]
    if (!step) continue
    const nexts: string[] = []
    if (step.next_step_id) nexts.push(step.next_step_id)
    if (step.then_step_id) nexts.push(step.then_step_id)
    if (step.else_step_id) nexts.push(step.else_step_id)
    if (step.target_step_id) nexts.push(step.target_step_id)
    nexts.forEach((nid) => {
      if (!visited.has(nid) && steps[nid]) queue.push({ id: nid, col: col + 1 })
    })
  }
  let orphanY = 60
  Object.keys(steps).forEach((id) => {
    if (!layout[id]) { layout[id] = { x: 60, y: orphanY }; orphanY += 130 }
  })
  return layout
}

// ---------------------------------------------------------------------------
// Main execution page
// ---------------------------------------------------------------------------

export default function ExecutionPage() {
  const { id: agentId, flowId } = useParams<{ id: string; flowId: string }>()
  const searchParams = useSearchParams()
  const [sessionId, setSessionId] = useState(searchParams.get('session') || '')
  const [sessionInput, setSessionInput] = useState(searchParams.get('session') || '')
  const [autoRefresh, setAutoRefresh] = useState(false)
  const intervalRef = useRef<NodeJS.Timeout | null>(null)

  const { data: flowData } = useQuery({
    queryKey: ['flow', agentId, flowId],
    queryFn: () => flowsApi.get(agentId, flowId),
  })

  const {
    data: execState,
    isLoading: execLoading,
    refetch,
    dataUpdatedAt,
  } = useQuery<ExecutionState>({
    queryKey: ['flow-exec', agentId, flowId, sessionId],
    queryFn: () => flowsApi.getExecution(agentId, flowId, sessionId),
    enabled: !!sessionId,
    refetchInterval: autoRefresh ? 2000 : false,
  })

  const steps: Record<string, Step> = flowData?.steps || {}
  const rawLayout: Layout = flowData?.ui_layout || {}
  const layout = Object.keys(rawLayout).length > 0 ? rawLayout : autoLayout(steps, flowData?.initial_step_id)

  const completedIds = new Set((execState?.history || []).map((h) => h.step_id))
  const currentId = execState?.current_step_id

  const canvasW = Math.max(900, ...Object.values(layout).map((p) => p.x + NODE_W + 60))
  const canvasH = Math.max(600, ...Object.values(layout).map((p) => p.y + NODE_H + 60))

  // Arrows
  const arrows: Array<{ from: UiPos; to: UiPos }> = []
  Object.values(steps).forEach((step) => {
    const fromPos = layout[step.id]
    if (!fromPos) return
    const nexts = [step.next_step_id, step.then_step_id, step.else_step_id, step.target_step_id].filter(Boolean) as string[]
    nexts.forEach((nid) => {
      if (layout[nid]) arrows.push({ from: fromPos, to: layout[nid] })
    })
  })

  const statusColor = execState ? (STATUS_COLORS[execState.status] || STATUS_COLORS.not_started) : STATUS_COLORS.not_started

  return (
    <div className="flex flex-col h-screen bg-gray-50 dark:bg-gray-950">
      {/* Header */}
      <div className="flex items-center gap-3 px-4 py-2.5 bg-white dark:bg-gray-900 border-b border-gray-200 dark:border-gray-800">
        <Link
          href={`/dashboard/agents/${agentId}/workflows/${flowId}`}
          className="p-1.5 text-gray-500 hover:text-gray-900 dark:hover:text-white"
        >
          <ArrowLeft size={18} />
        </Link>
        <div>
          <p className="text-sm font-semibold text-gray-900 dark:text-white">
            {flowData?.name || 'Flow'} — Live Execution
          </p>
          {execState && (
            <p className="text-xs text-gray-400">
              Last updated {new Date(dataUpdatedAt).toLocaleTimeString()}
            </p>
          )}
        </div>
        <div className="flex-1" />
        <label className="flex items-center gap-2 text-xs text-gray-600 dark:text-gray-400 cursor-pointer">
          <input
            type="checkbox"
            checked={autoRefresh}
            onChange={(e) => setAutoRefresh(e.target.checked)}
            className="accent-violet-600"
          />
          Auto-refresh (2s)
        </label>
        <button
          onClick={() => refetch()}
          disabled={!sessionId}
          className="p-2 text-gray-500 hover:text-gray-900 dark:hover:text-white disabled:opacity-40"
        >
          <RefreshCw size={15} />
        </button>
      </div>

      <div className="flex flex-1 overflow-hidden">
        {/* Canvas */}
        <div className="flex-1 overflow-auto bg-[#f8f8fc] dark:bg-gray-950">
          {!sessionId ? (
            <div className="flex items-center justify-center h-full">
              <div className="text-center max-w-sm">
                <Activity size={40} className="mx-auto mb-3 text-gray-300 dark:text-gray-600" />
                <p className="text-gray-500 font-medium mb-4">Enter a session ID to view live execution</p>
                <div className="flex gap-2">
                  <input
                    value={sessionInput}
                    onChange={(e) => setSessionInput(e.target.value)}
                    placeholder="Session ID"
                    className="flex-1 px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-sm text-gray-900 dark:text-white focus:outline-none focus:ring-1 focus:ring-violet-500"
                    onKeyDown={(e) => { if (e.key === 'Enter') setSessionId(sessionInput.trim()) }}
                  />
                  <button
                    onClick={() => setSessionId(sessionInput.trim())}
                    disabled={!sessionInput.trim()}
                    className="px-4 py-2 rounded-lg bg-violet-600 text-white text-sm font-medium hover:bg-violet-700 disabled:opacity-50"
                  >
                    <Play size={14} />
                  </button>
                </div>
              </div>
            </div>
          ) : (
            <div style={{ position: 'relative', width: canvasW, height: canvasH }}>
              <svg
                style={{ position: 'absolute', top: 0, left: 0, pointerEvents: 'none', overflow: 'visible' }}
                width={canvasW}
                height={canvasH}
              >
                <defs>
                  <marker id="ah" markerWidth="8" markerHeight="6" refX="6" refY="3" orient="auto">
                    <polygon points="0 0, 8 3, 0 6" fill="#6366f1" opacity={0.5} />
                  </marker>
                </defs>
                {arrows.map((a, i) => (
                  <Arrow key={i} from={a.from} to={a.to} />
                ))}
              </svg>

              {Object.values(steps).map((step) => {
                const pos = layout[step.id] || { x: 60, y: 60 }
                return (
                  <ReadonlyNode
                    key={step.id}
                    step={step}
                    pos={pos}
                    isCurrent={step.id === currentId}
                    isCompleted={completedIds.has(step.id) && step.id !== currentId}
                  />
                )
              })}
            </div>
          )}
        </div>

        {/* Right panel */}
        <div className="w-72 bg-white dark:bg-gray-900 border-l border-gray-200 dark:border-gray-800 flex flex-col overflow-hidden">
          {/* Session input */}
          <div className="p-4 border-b border-gray-100 dark:border-gray-800">
            <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1.5">
              Session ID
            </label>
            <div className="flex gap-2">
              <input
                value={sessionInput}
                onChange={(e) => setSessionInput(e.target.value)}
                placeholder="Paste session ID…"
                className="flex-1 px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-xs text-gray-900 dark:text-white focus:outline-none focus:ring-1 focus:ring-violet-500"
                onKeyDown={(e) => { if (e.key === 'Enter') setSessionId(sessionInput.trim()) }}
              />
              <button
                onClick={() => setSessionId(sessionInput.trim())}
                disabled={!sessionInput.trim()}
                className="p-2 rounded-lg bg-violet-600 text-white hover:bg-violet-700 disabled:opacity-50"
              >
                <Play size={13} />
              </button>
            </div>
          </div>

          {execLoading && sessionId && (
            <div className="p-4 text-xs text-gray-400 animate-pulse">Loading execution state…</div>
          )}

          {execState && (
            <>
              {/* Status */}
              <div className="p-4 border-b border-gray-100 dark:border-gray-800">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-xs font-semibold text-gray-700 dark:text-gray-300">Status</span>
                  <span className={`text-xs px-2.5 py-1 rounded-full border font-medium capitalize ${statusColor}`}>
                    {execState.status.replace('_', ' ')}
                  </span>
                </div>
                <div className="grid grid-cols-2 gap-2 text-xs text-gray-500">
                  <div>
                    <span className="font-medium text-gray-700 dark:text-gray-300">Steps run</span>
                    <p>{execState.step_count}</p>
                  </div>
                  <div>
                    <span className="font-medium text-gray-700 dark:text-gray-300">Current step</span>
                    <p className="font-mono truncate">{execState.current_step_id || '—'}</p>
                  </div>
                  <div>
                    <span className="font-medium text-gray-700 dark:text-gray-300">Source</span>
                    <p>{execState.source}</p>
                  </div>
                </div>
                {execState.error_message && (
                  <div className="mt-2 p-2 rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800">
                    <p className="text-xs text-red-600 dark:text-red-300">{execState.error_message}</p>
                  </div>
                )}
              </div>

              {/* Variables */}
              <div className="p-4 border-b border-gray-100 dark:border-gray-800 flex-shrink-0">
                <h3 className="text-xs font-semibold text-gray-700 dark:text-gray-300 mb-2">
                  Variables ({Object.keys(execState.variables || {}).length})
                </h3>
                {Object.keys(execState.variables || {}).length === 0 ? (
                  <p className="text-xs text-gray-400">No variables yet</p>
                ) : (
                  <div className="space-y-1 max-h-32 overflow-y-auto">
                    {Object.entries(execState.variables).map(([k, v]) => (
                      <div key={k} className="flex gap-2 text-xs">
                        <span className="font-mono text-violet-600 dark:text-violet-400 font-medium flex-shrink-0">{k}</span>
                        <span className="text-gray-600 dark:text-gray-400 truncate">
                          {typeof v === 'object' ? JSON.stringify(v) : String(v)}
                        </span>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* History */}
              <div className="p-4 flex-1 overflow-y-auto">
                <h3 className="text-xs font-semibold text-gray-700 dark:text-gray-300 mb-2">
                  History ({execState.history?.length || 0} steps)
                </h3>
                <div className="space-y-2">
                  {(execState.history || []).map((h, i) => (
                    <div
                      key={i}
                      className="flex items-start gap-2 text-xs"
                    >
                      <div className="mt-0.5 flex-shrink-0">
                        {h.step_id === currentId ? (
                          <Activity size={12} className="text-violet-500" />
                        ) : (
                          <CheckCircle2 size={12} className="text-emerald-500" />
                        )}
                      </div>
                      <div className="min-w-0">
                        <p className="font-mono text-gray-700 dark:text-gray-300 truncate">{h.step_id}</p>
                        <p className="text-gray-400">{h.type}</p>
                        {h.timestamp && (
                          <p className="text-gray-300 dark:text-gray-600 text-[10px]">
                            {new Date(h.timestamp).toLocaleTimeString()}
                          </p>
                        )}
                      </div>
                    </div>
                  ))}
                  {!execState.history?.length && (
                    <p className="text-xs text-gray-400">No steps executed yet</p>
                  )}
                </div>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
