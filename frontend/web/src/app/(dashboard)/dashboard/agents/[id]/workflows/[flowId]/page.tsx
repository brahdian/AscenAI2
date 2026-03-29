'use client'

import { useParams, useRouter } from 'next/navigation'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { flowsApi } from '@/lib/api'
import toast from 'react-hot-toast'
import { useCallback, useEffect, useRef, useState } from 'react'
import {
  ArrowLeft,
  Save,
  Plus,
  X,
  ChevronRight,
  Play,
  ZoomIn,
  ZoomOut,
  Maximize2,
} from 'lucide-react'
import Link from 'next/link'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type StepType = 'wait_input' | 'llm' | 'tool' | 'condition' | 'deterministic' | 'goto' | 'end'

interface Step {
  id: string
  type: StepType
  // wait_input
  prompt_to_user?: string
  variable_to_store?: string
  validation_regex?: string
  error_message?: string
  next_step_id?: string
  // llm
  prompt_template?: string
  output_variable?: string
  temperature?: number
  max_tokens?: number
  extract_json?: boolean
  // tool
  tool_name?: string
  argument_mapping?: Record<string, string>
  on_error?: string
  retry_count?: number
  // condition
  expression?: string
  then_step_id?: string
  else_step_id?: string
  // deterministic
  action?: string
  params?: Record<string, unknown>
  // goto
  target_step_id?: string
  // end
  status?: string
  final_message_template?: string
}

interface UiPos { x: number; y: number }
type Layout = Record<string, UiPos>

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

// ---------------------------------------------------------------------------
// Auto-layout: BFS topological sort
// ---------------------------------------------------------------------------

function autoLayout(steps: Record<string, Step>, initialStepId?: string): Layout {
  const layout: Layout = {}
  const visited = new Set<string>()
  const queue: Array<{ id: string; col: number; row: number }> = []

  const startId = initialStepId || Object.keys(steps)[0]
  if (!startId) return layout

  queue.push({ id: startId, col: 0, row: 0 })
  const colCounts: Record<number, number> = {}

  while (queue.length) {
    const { id, col } = queue.shift()!
    if (visited.has(id)) continue
    visited.add(id)

    colCounts[col] = (colCounts[col] || 0)
    const row = colCounts[col]!
    colCounts[col]++

    layout[id] = { x: col * 280 + 80, y: row * 140 + 80 }

    const step = steps[id]
    if (!step) continue
    const nexts: string[] = []
    if (step.next_step_id) nexts.push(step.next_step_id)
    if (step.then_step_id) nexts.push(step.then_step_id)
    if (step.else_step_id) nexts.push(step.else_step_id)
    if (step.target_step_id) nexts.push(step.target_step_id)
    nexts.forEach((nid) => {
      if (!visited.has(nid) && steps[nid]) {
        queue.push({ id: nid, col: col + 1, row: 0 })
      }
    })
  }

  // Place any orphaned nodes
  let orphanY = 80
  Object.keys(steps).forEach((id) => {
    if (!layout[id]) {
      layout[id] = { x: 80, y: orphanY }
      orphanY += 140
    }
  })

  return layout
}

// ---------------------------------------------------------------------------
// SVG bezier arrow
// ---------------------------------------------------------------------------

function Arrow({
  from,
  to,
  label,
  color = '#6366f1',
}: {
  from: UiPos
  to: UiPos
  label?: string
  color?: string
}) {
  const x1 = from.x + NODE_W
  const y1 = from.y + NODE_H / 2
  const x2 = to.x
  const y2 = to.y + NODE_H / 2
  const cx1 = x1 + 60
  const cx2 = x2 - 60
  const mid = { x: (x1 + x2) / 2, y: (y1 + y2) / 2 }

  return (
    <g>
      <path
        d={`M${x1},${y1} C${cx1},${y1} ${cx2},${y2} ${x2},${y2}`}
        fill="none"
        stroke={color}
        strokeWidth={1.5}
        strokeDasharray={label === 'else' ? '4,3' : undefined}
        markerEnd={`url(#arrowhead-${color.replace('#', '')})`}
        opacity={0.75}
      />
      {label && (
        <text
          x={mid.x}
          y={mid.y - 6}
          textAnchor="middle"
          fontSize={10}
          fill={color}
          opacity={0.9}
        >
          {label}
        </text>
      )}
    </g>
  )
}

// ---------------------------------------------------------------------------
// Step node
// ---------------------------------------------------------------------------

function StepNode({
  step,
  pos,
  selected,
  onSelect,
  onDragStart,
  isInitial,
}: {
  step: Step
  pos: UiPos
  selected: boolean
  onSelect: () => void
  onDragStart: (e: React.MouseEvent) => void
  isInitial: boolean
}) {
  const colors = STEP_COLORS[step.type]

  return (
    <div
      className={`absolute select-none cursor-pointer rounded-xl border-2 shadow-sm transition-shadow ${colors.bg} ${
        selected ? 'border-violet-500 shadow-lg ring-2 ring-violet-200 dark:ring-violet-800' : colors.border
      }`}
      style={{ left: pos.x, top: pos.y, width: NODE_W, height: NODE_H }}
      onMouseDown={(e) => {
        onSelect()
        onDragStart(e)
      }}
    >
      {isInitial && (
        <div className="absolute -top-2 -left-1 text-[9px] font-bold px-1.5 py-0.5 bg-violet-600 text-white rounded">
          START
        </div>
      )}
      <div className="px-3 py-2 h-full flex flex-col justify-center">
        <div className="flex items-center gap-2">
          <span className={`w-2 h-2 rounded-full flex-shrink-0 ${colors.dot}`} />
          <span className={`text-[10px] font-bold uppercase tracking-wider ${colors.text}`}>
            {STEP_LABELS[step.type]}
          </span>
        </div>
        <p className="text-xs text-gray-700 dark:text-gray-300 mt-1 truncate font-medium">
          {step.id}
        </p>
        <p className="text-[11px] text-gray-500 dark:text-gray-400 truncate">
          {getStepSummary(step)}
        </p>
      </div>
    </div>
  )
}

function getStepSummary(step: Step): string {
  switch (step.type) {
    case 'wait_input': return step.prompt_to_user?.slice(0, 40) || '(no prompt)'
    case 'llm': return step.prompt_template?.slice(0, 40) || '(no template)'
    case 'tool': return step.tool_name || '(no tool)'
    case 'condition': return step.expression?.slice(0, 40) || '(no expression)'
    case 'deterministic': return step.action || '(no action)'
    case 'goto': return `→ ${step.target_step_id || '?'}`
    case 'end': return step.final_message_template?.slice(0, 40) || '(end)'
    default: return ''
  }
}

// ---------------------------------------------------------------------------
// Step property editor
// ---------------------------------------------------------------------------

function StepEditor({
  step,
  allStepIds,
  onChange,
  onClose,
  onDelete,
}: {
  step: Step
  allStepIds: string[]
  onChange: (updated: Step) => void
  onClose: () => void
  onDelete: () => void
}) {
  const [local, setLocal] = useState<Step>({ ...step })

  useEffect(() => { setLocal({ ...step }) }, [step.id])

  const set = (field: keyof Step, val: unknown) =>
    setLocal((s) => ({ ...s, [field]: val }))

  const save = () => onChange(local)

  const otherIds = allStepIds.filter((id) => id !== step.id)

  return (
    <div className="w-80 bg-white dark:bg-gray-900 border-l border-gray-200 dark:border-gray-800 flex flex-col h-full overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-gray-100 dark:border-gray-800">
        <div className="flex items-center gap-2">
          <span className={`w-2.5 h-2.5 rounded-full ${STEP_COLORS[local.type].dot}`} />
          <span className="text-sm font-semibold text-gray-900 dark:text-white">
            {STEP_LABELS[local.type]}
          </span>
        </div>
        <button onClick={onClose} className="text-gray-400 hover:text-gray-600 p-1">
          <X size={16} />
        </button>
      </div>

      {/* Fields */}
      <div className="flex-1 overflow-y-auto p-4 space-y-3">
        {/* Step ID */}
        <div>
          <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
            Step ID
          </label>
          <input
            value={local.id}
            readOnly
            className="w-full px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 text-gray-500 text-xs font-mono"
          />
        </div>

        {/* Type-specific fields */}
        {local.type === 'wait_input' && (
          <>
            <Field label="Prompt to user" multiline value={local.prompt_to_user || ''} onChange={(v) => set('prompt_to_user', v)} />
            <Field label="Variable to store" value={local.variable_to_store || ''} onChange={(v) => set('variable_to_store', v)} placeholder="e.g. user_name" />
            <Field label="Validation regex" value={local.validation_regex || ''} onChange={(v) => set('validation_regex', v)} placeholder="e.g. ^[\\w.-]+@[\\w.-]+$" />
            <Field label="Error message" value={local.error_message || ''} onChange={(v) => set('error_message', v)} />
            <SelectField label="Next step" value={local.next_step_id || ''} options={otherIds} onChange={(v) => set('next_step_id', v)} />
          </>
        )}

        {local.type === 'llm' && (
          <>
            <Field label="Prompt template" multiline value={local.prompt_template || ''} onChange={(v) => set('prompt_template', v)} placeholder="You are a helpful assistant. User said: {{user_input}}" />
            <Field label="Output variable" value={local.output_variable || ''} onChange={(v) => set('output_variable', v)} placeholder="llm_response" />
            <div className="grid grid-cols-2 gap-2">
              <Field label="Temperature" value={String(local.temperature ?? 0.7)} onChange={(v) => set('temperature', parseFloat(v) || 0.7)} />
              <Field label="Max tokens" value={String(local.max_tokens ?? 500)} onChange={(v) => set('max_tokens', parseInt(v) || 500)} />
            </div>
            <CheckField label="Extract JSON" checked={local.extract_json ?? false} onChange={(v) => set('extract_json', v)} />
            <SelectField label="Next step" value={local.next_step_id || ''} options={otherIds} onChange={(v) => set('next_step_id', v)} />
          </>
        )}

        {local.type === 'tool' && (
          <>
            <Field label="Tool name" value={local.tool_name || ''} onChange={(v) => set('tool_name', v)} placeholder="e.g. search_knowledge_base" />
            <Field label="Output variable" value={local.output_variable || ''} onChange={(v) => set('output_variable', v)} placeholder="tool_result" />
            <Field label="On error" value={local.on_error || ''} onChange={(v) => set('on_error', v)} placeholder="continue | fail | retry" />
            <Field label="Retry count" value={String(local.retry_count ?? 0)} onChange={(v) => set('retry_count', parseInt(v) || 0)} />
            <SelectField label="Next step" value={local.next_step_id || ''} options={otherIds} onChange={(v) => set('next_step_id', v)} />
          </>
        )}

        {local.type === 'condition' && (
          <>
            <Field label="Expression" multiline value={local.expression || ''} onChange={(v) => set('expression', v)} placeholder="variables.get('confirmed') == 'yes'" />
            <SelectField label="Then (true) →" value={local.then_step_id || ''} options={otherIds} onChange={(v) => set('then_step_id', v)} />
            <SelectField label="Else (false) →" value={local.else_step_id || ''} options={otherIds} onChange={(v) => set('else_step_id', v)} />
          </>
        )}

        {local.type === 'deterministic' && (
          <>
            <Field label="Action" value={local.action || ''} onChange={(v) => set('action', v)} placeholder="e.g. set_variable, send_email" />
            <SelectField label="Next step" value={local.next_step_id || ''} options={otherIds} onChange={(v) => set('next_step_id', v)} />
          </>
        )}

        {local.type === 'goto' && (
          <SelectField label="Target step" value={local.target_step_id || ''} options={otherIds} onChange={(v) => set('target_step_id', v)} />
        )}

        {local.type === 'end' && (
          <>
            <div>
              <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">Status</label>
              <select
                value={local.status || 'completed'}
                onChange={(e) => set('status', e.target.value)}
                className="w-full px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm focus:outline-none focus:ring-1 focus:ring-violet-500"
              >
                <option value="completed">Completed</option>
                <option value="escalated">Escalated</option>
                <option value="failed">Failed</option>
                <option value="abandoned">Abandoned</option>
              </select>
            </div>
            <Field label="Final message" multiline value={local.final_message_template || ''} onChange={(v) => set('final_message_template', v)} />
          </>
        )}
      </div>

      {/* Footer */}
      <div className="px-4 py-3 border-t border-gray-100 dark:border-gray-800 flex items-center justify-between">
        <button
          onClick={onDelete}
          className="text-xs text-red-500 hover:text-red-700 font-medium"
        >
          Delete step
        </button>
        <button
          onClick={save}
          className="px-4 py-2 rounded-lg bg-violet-600 text-white text-xs font-medium hover:bg-violet-700 transition-colors"
        >
          Apply
        </button>
      </div>
    </div>
  )
}

function Field({
  label,
  value,
  onChange,
  placeholder,
  multiline,
}: {
  label: string
  value: string
  onChange: (v: string) => void
  placeholder?: string
  multiline?: boolean
}) {
  const cls =
    'w-full px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-xs focus:outline-none focus:ring-1 focus:ring-violet-500'
  return (
    <div>
      <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">{label}</label>
      {multiline ? (
        <textarea
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          rows={3}
          className={`${cls} resize-none`}
        />
      ) : (
        <input value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} className={cls} />
      )}
    </div>
  )
}

function SelectField({
  label,
  value,
  options,
  onChange,
}: {
  label: string
  value: string
  options: string[]
  onChange: (v: string) => void
}) {
  return (
    <div>
      <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">{label}</label>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-xs focus:outline-none focus:ring-1 focus:ring-violet-500"
      >
        <option value="">(none)</option>
        {options.map((o) => (
          <option key={o} value={o}>{o}</option>
        ))}
      </select>
    </div>
  )
}

function CheckField({
  label,
  checked,
  onChange,
}: {
  label: string
  checked: boolean
  onChange: (v: boolean) => void
}) {
  return (
    <label className="flex items-center gap-2 cursor-pointer">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="w-4 h-4 accent-violet-600"
      />
      <span className="text-xs text-gray-700 dark:text-gray-300">{label}</span>
    </label>
  )
}

// ---------------------------------------------------------------------------
// Arrow colours per edge type
// ---------------------------------------------------------------------------

const ARROW_COLORS: Record<string, string> = {
  next: '#6366f1',
  then: '#10b981',
  else: '#f59e0b',
  target: '#14b8a6',
}

// ---------------------------------------------------------------------------
// Main flow builder page
// ---------------------------------------------------------------------------

export default function FlowBuilderPage() {
  const { id: agentId, flowId } = useParams<{ id: string; flowId: string }>()
  const router = useRouter()
  const qc = useQueryClient()

  const { data: flowData, isLoading } = useQuery({
    queryKey: ['flow', agentId, flowId],
    queryFn: () => flowsApi.get(agentId, flowId),
  })

  const [steps, setSteps] = useState<Record<string, Step>>({})
  const [layout, setLayout] = useState<Layout>({})
  const [flowName, setFlowName] = useState('Untitled Flow')
  const [initialStepId, setInitialStepId] = useState<string>('')
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [zoom, setZoom] = useState(1)
  const [dirty, setDirty] = useState(false)

  const canvasRef = useRef<HTMLDivElement>(null)
  const dragging = useRef<{ id: string; startX: number; startY: number; startPosX: number; startPosY: number } | null>(null)

  // Load flow data
  useEffect(() => {
    if (flowData) {
      setSteps(flowData.steps || {})
      setLayout(flowData.ui_layout || {})
      setFlowName(flowData.name || 'Untitled Flow')
      setInitialStepId(flowData.initial_step_id || '')
      setDirty(false)
    }
  }, [flowData])

  // Save mutation
  const saveMutation = useMutation({
    mutationFn: () =>
      flowsApi.update(agentId, flowId, {
        name: flowName,
        description: flowData?.description,
        trigger_keywords: flowData?.trigger_keywords || [],
        initial_step_id: initialStepId,
        steps,
        ui_layout: layout,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['flow', agentId, flowId] })
      toast.success('Flow saved')
      setDirty(false)
    },
    onError: () => toast.error('Failed to save flow'),
  })

  // Drag logic
  const handleDragStart = useCallback(
    (stepId: string) => (e: React.MouseEvent) => {
      e.preventDefault()
      const pos = layout[stepId] || { x: 0, y: 0 }
      dragging.current = {
        id: stepId,
        startX: e.clientX,
        startY: e.clientY,
        startPosX: pos.x,
        startPosY: pos.y,
      }
    },
    [layout]
  )

  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      if (!dragging.current) return
      const { id, startX, startY, startPosX, startPosY } = dragging.current
      const dx = (e.clientX - startX) / zoom
      const dy = (e.clientY - startY) / zoom
      setLayout((prev) => ({
        ...prev,
        [id]: { x: Math.max(0, startPosX + dx), y: Math.max(0, startPosY + dy) },
      }))
      setDirty(true)
    }
    const onUp = () => { dragging.current = null }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
    return () => {
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
    }
  }, [zoom])

  // Add step
  const addStep = (type: StepType) => {
    const id = `${type}_${Date.now().toString(36)}`
    const newStep: Step = { id, type }
    if (type === 'end') { newStep.status = 'completed'; newStep.final_message_template = 'Thank you!' }
    setSteps((prev) => ({ ...prev, [id]: newStep }))
    const maxX = Math.max(80, ...Object.values(layout).map((p) => p.x))
    setLayout((prev) => ({ ...prev, [id]: { x: maxX + 260, y: 120 } }))
    setSelectedId(id)
    setDirty(true)
  }

  // Delete step
  const deleteStep = (id: string) => {
    setSteps((prev) => {
      const next = { ...prev }
      delete next[id]
      return next
    })
    setLayout((prev) => {
      const next = { ...prev }
      delete next[id]
      return next
    })
    setSelectedId(null)
    setDirty(true)
  }

  // Update step
  const updateStep = (updated: Step) => {
    setSteps((prev) => ({ ...prev, [updated.id]: updated }))
    setDirty(true)
  }

  // Auto layout
  const runAutoLayout = () => {
    const newLayout = autoLayout(steps, initialStepId)
    setLayout(newLayout)
    setDirty(true)
  }

  // Canvas size
  const canvasW = Math.max(1200, ...Object.values(layout).map((p) => p.x + NODE_W + 100))
  const canvasH = Math.max(800, ...Object.values(layout).map((p) => p.y + NODE_H + 100))

  // Build arrows
  const arrows: Array<{ from: UiPos; to: UiPos; label?: string; color?: string }> = []
  Object.values(steps).forEach((step) => {
    const fromPos = layout[step.id]
    if (!fromPos) return
    const addArrow = (targetId: string | undefined, label: string, color: string) => {
      if (!targetId || !layout[targetId]) return
      arrows.push({ from: fromPos, to: layout[targetId], label, color })
    }
    if (step.type === 'condition') {
      addArrow(step.then_step_id, 'then', ARROW_COLORS.then)
      addArrow(step.else_step_id, 'else', ARROW_COLORS.else)
    } else if (step.type === 'goto') {
      addArrow(step.target_step_id, '', ARROW_COLORS.target)
    } else {
      addArrow(step.next_step_id, '', ARROW_COLORS.next)
    }
  })

  const stepIds = Object.keys(steps)
  const selectedStep = selectedId ? steps[selectedId] : null

  if (isLoading) return <div className="p-8 animate-pulse text-gray-400">Loading flow…</div>

  return (
    <div className="flex flex-col h-screen bg-gray-50 dark:bg-gray-950">
      {/* Top toolbar */}
      <div className="flex items-center gap-3 px-4 py-2.5 bg-white dark:bg-gray-900 border-b border-gray-200 dark:border-gray-800 z-10">
        <Link
          href={`/dashboard/agents/${agentId}/workflows`}
          className="p-1.5 text-gray-500 hover:text-gray-900 dark:hover:text-white transition-colors"
        >
          <ArrowLeft size={18} />
        </Link>

        <input
          value={flowName}
          onChange={(e) => { setFlowName(e.target.value); setDirty(true) }}
          className="text-sm font-medium bg-transparent border-none outline-none text-gray-900 dark:text-white w-48"
        />

        {dirty && <span className="text-xs text-amber-500">Unsaved changes</span>}

        <div className="flex-1" />

        {/* Step type palette */}
        <div className="flex items-center gap-1 mr-2">
          {(Object.entries(STEP_LABELS) as [StepType, string][]).map(([type, label]) => {
            const colors = STEP_COLORS[type]
            return (
              <button
                key={type}
                onClick={() => addStep(type)}
                className={`inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-xs font-medium border transition-colors hover:opacity-90 ${colors.bg} ${colors.border} ${colors.text}`}
                title={`Add ${label} step`}
              >
                <Plus size={11} /> {label}
              </button>
            )
          })}
        </div>

        {/* Auto-layout */}
        <button
          onClick={runAutoLayout}
          className="px-3 py-1.5 rounded-lg text-xs font-medium border border-gray-200 dark:border-gray-700 text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
          title="Auto layout"
        >
          <Maximize2 size={13} />
        </button>

        {/* Zoom */}
        <div className="flex items-center gap-1">
          <button
            onClick={() => setZoom((z) => Math.max(0.3, z - 0.1))}
            className="p-1.5 text-gray-500 hover:text-gray-900 dark:hover:text-white"
          >
            <ZoomOut size={15} />
          </button>
          <span className="text-xs text-gray-500 w-10 text-center">{Math.round(zoom * 100)}%</span>
          <button
            onClick={() => setZoom((z) => Math.min(2, z + 0.1))}
            className="p-1.5 text-gray-500 hover:text-gray-900 dark:hover:text-white"
          >
            <ZoomIn size={15} />
          </button>
        </div>

        {/* Live view */}
        <Link
          href={`/dashboard/agents/${agentId}/workflows/${flowId}/execution`}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-emerald-50 dark:bg-emerald-900/20 text-emerald-700 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-700 hover:bg-emerald-100 transition-colors"
        >
          <Play size={12} /> Live View
        </Link>

        {/* Save */}
        <button
          onClick={() => saveMutation.mutate()}
          disabled={saveMutation.isPending || !dirty}
          className="inline-flex items-center gap-1.5 px-4 py-1.5 rounded-lg bg-violet-600 text-white text-xs font-medium hover:bg-violet-700 disabled:opacity-50 transition-colors"
        >
          <Save size={13} /> {saveMutation.isPending ? 'Saving…' : 'Save'}
        </button>
      </div>

      {/* Canvas + editor */}
      <div className="flex flex-1 overflow-hidden">
        {/* Canvas */}
        <div className="flex-1 overflow-auto bg-[#f8f8fc] dark:bg-gray-950">
          <div
            ref={canvasRef}
            style={{
              transform: `scale(${zoom})`,
              transformOrigin: '0 0',
              width: canvasW,
              height: canvasH,
              position: 'relative',
            }}
          >
            {/* SVG arrows layer */}
            <svg
              style={{ position: 'absolute', top: 0, left: 0, pointerEvents: 'none', overflow: 'visible' }}
              width={canvasW}
              height={canvasH}
            >
              <defs>
                {Object.entries(ARROW_COLORS).map(([key, color]) => (
                  <marker
                    key={key}
                    id={`arrowhead-${color.replace('#', '')}`}
                    markerWidth="8"
                    markerHeight="6"
                    refX="6"
                    refY="3"
                    orient="auto"
                  >
                    <polygon points="0 0, 8 3, 0 6" fill={color} opacity={0.75} />
                  </marker>
                ))}
              </defs>
              {arrows.map((a, i) => (
                <Arrow key={i} from={a.from} to={a.to} label={a.label} color={a.color} />
              ))}
            </svg>

            {/* Step nodes */}
            {Object.values(steps).map((step) => {
              const pos = layout[step.id] || { x: 80, y: 80 }
              return (
                <StepNode
                  key={step.id}
                  step={step}
                  pos={pos}
                  selected={selectedId === step.id}
                  onSelect={() => setSelectedId(step.id)}
                  onDragStart={handleDragStart(step.id)}
                  isInitial={step.id === initialStepId}
                />
              )
            })}

            {/* Empty state */}
            {stepIds.length === 0 && (
              <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
                <div className="text-center">
                  <p className="text-gray-300 dark:text-gray-600 text-lg font-medium">Empty canvas</p>
                  <p className="text-gray-300 dark:text-gray-600 text-sm mt-1">
                    Click a step type in the toolbar to add nodes
                  </p>
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Right panel — step editor */}
        {selectedStep && (
          <StepEditor
            step={selectedStep}
            allStepIds={stepIds}
            onChange={updateStep}
            onClose={() => setSelectedId(null)}
            onDelete={() => deleteStep(selectedStep.id)}
          />
        )}

        {/* Initial step selector — bottom status bar */}
        {!selectedStep && stepIds.length > 0 && (
          <div className="w-64 bg-white dark:bg-gray-900 border-l border-gray-200 dark:border-gray-800 p-4">
            <h3 className="text-xs font-semibold text-gray-700 dark:text-gray-300 mb-3">Flow Settings</h3>
            <div>
              <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
                Initial step
              </label>
              <select
                value={initialStepId}
                onChange={(e) => { setInitialStepId(e.target.value); setDirty(true) }}
                className="w-full px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-xs focus:outline-none focus:ring-1 focus:ring-violet-500"
              >
                <option value="">(none)</option>
                {stepIds.map((id) => (
                  <option key={id} value={id}>{id}</option>
                ))}
              </select>
            </div>
            <p className="text-xs text-gray-400 mt-4">
              Click a node to edit its properties.
            </p>
            <p className="text-xs text-gray-400 mt-2">
              Drag nodes to reposition them.
            </p>
          </div>
        )}
      </div>
    </div>
  )
}
