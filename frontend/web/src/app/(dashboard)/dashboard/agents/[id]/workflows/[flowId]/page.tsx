'use client'

import { useState, useEffect } from 'react'
import { useParams, useRouter } from 'next/navigation'
import Link from 'next/link'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { workflowsApi, variablesApi, toolsApi, documentsApi } from '@/lib/api'
import toast from 'react-hot-toast'
import {
  ChevronLeft,
  Save,
  Zap,
  Play,
  Pause,
  Plus,
  Trash2,
  ChevronDown,
  ChevronRight,
  Loader2,
  Clock,
  Webhook,
  Radio,
  GitBranch,
  CheckCircle2,
  XCircle,
  AlertCircle,
  Copy,
  Info,
  X,
  Settings,
  Activity,
  Code,
  ArrowRight,
} from 'lucide-react'
import { PlaybookMentionsEditor } from '@/components/PlaybookMentionsEditor'

// ─── Types ────────────────────────────────────────────────────────────────────

type TriggerType = 'none' | 'cron' | 'webhook' | 'event'

type NodeType =
  | 'INPUT' | 'SET_VARIABLE' | 'VALIDATION' | 'CONDITION' | 'SWITCH'
  | 'FOR_EACH' | 'TOOL_CALL' | 'LLM_CALL' | 'ACTION' | 'SEND_SMS'
  | 'DELAY' | 'HUMAN_HANDOFF' | 'END'

interface WorkflowNode {
  id: string
  type: NodeType
  label: string
  config: Record<string, unknown>
}

interface WorkflowEdge {
  id: string
  source: string
  target: string
  source_handle?: string
}

interface WorkflowDefinition {
  nodes: WorkflowNode[]
  edges: WorkflowEdge[]
  entry_node_id: string
  variables: Record<string, unknown>
}

interface Flow {
  id: string
  name: string
  description: string
  is_active: boolean
  trigger_type: TriggerType
  trigger_config: Record<string, unknown>
  tags: string[]
  version: number
  definition: WorkflowDefinition
  input_schema: Record<string, unknown>
  output_schema: Record<string, unknown>
  created_at: string
  updated_at: string
}

interface Execution {
  id: string
  status: string
  trigger_source: string
  current_node_id: string | null
  error_message: string | null
  created_at: string
  updated_at: string
}

// ─── Node type meta ───────────────────────────────────────────────────────────

const NODE_TYPES: { type: NodeType; label: string; color: string; desc: string }[] = [
  { type: 'INPUT',        label: 'Input',         color: 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300',      desc: 'Collect a value from the user' },
  { type: 'SET_VARIABLE', label: 'Set Variable',  color: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-300',         desc: 'Assign or transform a context variable' },
  { type: 'VALIDATION',   label: 'Validation',    color: 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-300', desc: 'Validate a variable against regex' },
  { type: 'CONDITION',    label: 'Condition',     color: 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300',   desc: 'Branch on a boolean expression' },
  { type: 'SWITCH',       label: 'Switch',        color: 'bg-orange-100 text-orange-700 dark:bg-orange-900/30 dark:text-orange-300', desc: 'N-way branch on a variable value' },
  { type: 'FOR_EACH',     label: 'For Each',      color: 'bg-cyan-100 text-cyan-700 dark:bg-cyan-900/30 dark:text-cyan-300',       desc: 'Iterate over a list in context' },
  { type: 'TOOL_CALL',    label: 'Tool Call',     color: 'bg-indigo-100 text-indigo-700 dark:bg-indigo-900/30 dark:text-indigo-300', desc: 'Call an MCP tool and store result' },
  { type: 'LLM_CALL',     label: 'LLM Call',      color: 'bg-violet-100 text-violet-700 dark:bg-violet-900/30 dark:text-violet-300', desc: 'Run a prompt through the LLM' },
  { type: 'ACTION',       label: 'HTTP Action',   color: 'bg-pink-100 text-pink-700 dark:bg-pink-900/30 dark:text-pink-300',       desc: 'POST/GET to an external endpoint' },
  { type: 'SEND_SMS',     label: 'Send SMS',      color: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300', desc: 'Send an SMS and optionally await reply' },
  { type: 'DELAY',        label: 'Delay',         color: 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300',      desc: 'Pause execution for N seconds' },
  { type: 'HUMAN_HANDOFF', label: 'Handoff',      color: 'bg-rose-100 text-rose-700 dark:bg-rose-900/30 dark:text-rose-300',       desc: 'Escalate to a human agent' },
  { type: 'END',          label: 'End',           color: 'bg-gray-200 text-gray-700 dark:bg-gray-700 dark:text-gray-200',          desc: 'Terminal — emit a final message' },
]

const NODE_META = Object.fromEntries(NODE_TYPES.map((n) => [n.type, n]))

function defaultConfig(type: NodeType): Record<string, unknown> {
  switch (type) {
    case 'INPUT':        return { variable: 'user_input', prompt: 'Please provide your input:' }
    case 'SET_VARIABLE': return { variable: 'result', value: '' }
    case 'VALIDATION':   return { variable: '', regex: '.*' }
    case 'CONDITION':    return { expression: 'True' }
    case 'SWITCH':       return { variable: '', cases: [], default_handle: 'default' }
    case 'FOR_EACH':     return { items_variable: 'items', item_variable: 'item', index_variable: 'loop_index', max_iterations: 50 }
    case 'TOOL_CALL':    return { tool_name: '', output_variable: 'tool_result', argument_mapping: {}, retry_attempts: 1, on_error: 'fail' }
    case 'LLM_CALL':     return { prompt_template: '', output_variable: 'llm_result', extract_json: false }
    case 'ACTION':       return { url: '', method: 'POST', headers: {}, body: {}, output_variable: 'action_result', timeout_seconds: 10 }
    case 'SEND_SMS':     return { to: '{{customer_phone}}', message: '', await_reply: false, reply_ttl_seconds: 900 }
    case 'DELAY':        return { seconds: 60 }
    case 'HUMAN_HANDOFF': return { message: 'Transferring you to a human agent. Please hold.' }
    case 'END':          return { final_message: '' }
    default:             return {}
  }
}

// ─── Node config form fields ──────────────────────────────────────────────────

function NodeConfigForm({
  node,
  onChange,
  tools,
  variables,
  documents,
}: {
  node: WorkflowNode
  onChange: (config: Record<string, unknown>) => void
  tools: any[]
  variables: any[]
  documents: any[]
}) {
  const cfg = node.config
  const set = (key: string, value: unknown) => onChange({ ...cfg, [key]: value })

  const field = (label: string, key: string, type = 'text', placeholder = '') => (
    <div key={key}>
      <label className="block text-xs font-medium text-gray-500 dark:text-gray-400 mb-1">{label}</label>
      <input
        type={type}
        value={String(cfg[key] ?? '')}
        onChange={(e) => set(key, type === 'number' ? Number(e.target.value) : e.target.value)}
        placeholder={placeholder}
        className="w-full px-3 py-1.5 rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 text-sm focus:outline-none focus:ring-1 focus:ring-violet-500"
      />
    </div>
  )

  const textarea = (label: string, key: string, rows = 2, placeholder = '') => (
    <div key={key}>
      <label className="block text-xs font-medium text-gray-500 dark:text-gray-400 mb-1">{label}</label>
      <PlaybookMentionsEditor
        value={String(cfg[key] ?? '')}
        onChange={(val) => set(key, val)}
        tools={tools}
        variables={variables}
        documents={documents}
        placeholder={placeholder}
      />
    </div>
  )

  const checkbox = (label: string, key: string) => (
    <label key={key} className="flex items-center gap-2 text-sm text-gray-700 dark:text-gray-300 cursor-pointer">
      <input
        type="checkbox"
        checked={Boolean(cfg[key])}
        onChange={(e) => set(key, e.target.checked)}
        className="rounded border-gray-300 text-violet-600 focus:ring-violet-500"
      />
      {label}
    </label>
  )

  switch (node.type) {
    case 'INPUT':
      return <div className="space-y-3">{field('Variable name', 'variable', 'text', 'e.g. user_name')}{textarea('Prompt shown to user', 'prompt', 2)}{field('Validation regex (optional)', 'validation_regex', 'text', 'e.g. ^\\d{10}$')}{field('Error message (optional)', 'error_message', 'text')}</div>
    case 'SET_VARIABLE':
      return <div className="space-y-3">{field('Variable name', 'variable', 'text', 'e.g. formatted_date')}{field('Value (supports {{vars}})', 'value', 'text', 'e.g. Hello {{name}}!')}</div>
    case 'VALIDATION':
      return <div className="space-y-3">{field('Variable to validate', 'variable', 'text', 'e.g. email')}{field('Regex pattern', 'regex', 'text', 'e.g. ^[\\w.-]+@[\\w.-]+\\.[a-z]{2,}$')}</div>
    case 'CONDITION':
      return <div className="space-y-3">{field('Boolean expression', 'expression', 'text', 'e.g. balance > 100')}<p className="text-xs text-gray-400">Routes to "yes" or "no" edge based on result.</p></div>
    case 'SWITCH':
      return (
        <div className="space-y-3">
          {field('Variable to match', 'variable', 'text', 'e.g. intent')}
          {field('Default handle', 'default_handle', 'text', 'default')}
          <div>
            <label className="block text-xs font-medium text-gray-500 dark:text-gray-400 mb-1">Cases (JSON array)</label>
            <textarea
              value={JSON.stringify(cfg.cases ?? [], null, 2)}
              onChange={(e) => { try { set('cases', JSON.parse(e.target.value)) } catch {} }}
              rows={4}
              className="w-full px-3 py-1.5 rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 text-xs font-mono resize-none focus:outline-none focus:ring-1 focus:ring-violet-500"
              placeholder='[{"value": "book", "handle": "book", "match": "exact"}]'
            />
          </div>
        </div>
      )
    case 'FOR_EACH':
      return <div className="space-y-3">{field('Items variable (list)', 'items_variable', 'text', 'e.g. appointments')}{field('Current item variable', 'item_variable', 'text', 'item')}{field('Index variable', 'index_variable', 'text', 'loop_index')}{field('Max iterations', 'max_iterations', 'number')}</div>
    case 'TOOL_CALL':
      return (
        <div className="space-y-3">
          {field('Tool name', 'tool_name', 'text', 'e.g. send_sms')}
          {field('Output variable', 'output_variable', 'text', 'tool_result')}
          <div>
            <label className="block text-xs font-medium text-gray-500 dark:text-gray-400 mb-1">Argument mapping (JSON)</label>
            <textarea
              value={JSON.stringify(cfg.argument_mapping ?? {}, null, 2)}
              onChange={(e) => { try { set('argument_mapping', JSON.parse(e.target.value)) } catch {} }}
              rows={3}
              className="w-full px-3 py-1.5 rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 text-xs font-mono resize-none focus:outline-none focus:ring-1 focus:ring-violet-500"
            />
          </div>
          {field('Retry attempts', 'retry_attempts', 'number')}
          <div>
            <label className="block text-xs font-medium text-gray-500 dark:text-gray-400 mb-1">On error</label>
            <select value={String(cfg.on_error ?? 'fail')} onChange={(e) => set('on_error', e.target.value)} className="w-full px-3 py-1.5 rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 text-sm focus:outline-none focus:ring-1 focus:ring-violet-500">
              <option value="fail">Fail the workflow</option>
              <option value="skip">Skip and continue</option>
              <option value="retry">Retry</option>
            </select>
          </div>
        </div>
      )
    case 'LLM_CALL':
      return (
        <div className="space-y-3">
          {textarea('System prompt (optional)', 'system_prompt', 2, 'You are a helpful assistant...')}
          {textarea('Prompt template (supports {{vars}})', 'prompt_template', 3, 'Summarise {{data}} in one sentence.')}
          {field('Output variable', 'output_variable', 'text', 'llm_result')}
          {field('Model override (optional)', 'model', 'text', 'claude-sonnet-4-6')}
          {checkbox('Extract JSON from response', 'extract_json')}
        </div>
      )
    case 'ACTION':
      return (
        <div className="space-y-3">
          {field('URL (supports {{vars}})', 'url', 'text', 'https://api.example.com/endpoint')}
          <div>
            <label className="block text-xs font-medium text-gray-500 dark:text-gray-400 mb-1">Method</label>
            <select value={String(cfg.method ?? 'POST')} onChange={(e) => set('method', e.target.value)} className="w-full px-3 py-1.5 rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 text-sm focus:outline-none">
              {['GET','POST','PUT','PATCH','DELETE'].map((m) => <option key={m}>{m}</option>)}
            </select>
          </div>
          {field('Output variable', 'output_variable', 'text', 'action_result')}
          {field('Timeout (seconds)', 'timeout_seconds', 'number')}
          <div>
            <label className="block text-xs font-medium text-gray-500 dark:text-gray-400 mb-1">Request body (JSON)</label>
            <textarea
              value={JSON.stringify(cfg.body ?? {}, null, 2)}
              onChange={(e) => { try { set('body', JSON.parse(e.target.value)) } catch {} }}
              rows={3}
              className="w-full px-3 py-1.5 rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 text-xs font-mono resize-none focus:outline-none focus:ring-1 focus:ring-violet-500"
            />
          </div>
        </div>
      )
    case 'SEND_SMS':
      return (
        <div className="space-y-3">
          {field('To (E.164 or {{var}})', 'to', 'text', '{{customer_phone}}')}
          {textarea('Message (supports {{vars}})', 'message', 3, 'Hi {{name}}, your appointment is at {{time}}.')}
          {checkbox('Await SMS reply before continuing', 'await_reply')}
          {Boolean(cfg.await_reply) && field('Reply timeout (seconds)', 'reply_ttl_seconds', 'number')}
        </div>
      )
    case 'DELAY':
      return <div className="space-y-3">{field('Delay (seconds)', 'seconds', 'number')}</div>
    case 'HUMAN_HANDOFF':
      return <div className="space-y-3">{textarea('Handoff message', 'message', 2)}</div>
    case 'END':
      return <div className="space-y-3">{textarea('Final message (supports {{vars}})', 'final_message', 2, 'Thank you! Your request has been processed.')}</div>
    default:
      return <p className="text-xs text-gray-400">No configurable fields for this node type.</p>
  }
}

// ─── Node row ─────────────────────────────────────────────────────────────────

function NodeRow({
  node,
  isEntry,
  allNodes,
  edges,
  onUpdate,
  onDelete,
  onSetEntry,
  onEdgeChange,
  onAddEdge,
  onDeleteEdge,
}: {
  node: WorkflowNode
  isEntry: boolean
  allNodes: WorkflowNode[]
  edges: WorkflowEdge[]
  onUpdate: (n: WorkflowNode) => void
  onDelete: () => void
  onSetEntry: () => void
  onEdgeChange: (edgeId: string, field: string, value: string) => void
  onAddEdge: (sourceId: string) => void
  onDeleteEdge: (edgeId: string) => void
  tools: any[]
  variables: any[]
  documents: any[]
}) {
  const [open, setOpen] = useState(false)
  const meta = NODE_META[node.type]
  const outEdges = edges.filter((e) => e.source === node.id)

  return (
    <div className={`rounded-xl border transition-colors ${open ? 'border-violet-300 dark:border-violet-700' : 'border-gray-200 dark:border-gray-800'} bg-white dark:bg-gray-900`}>
      {/* Header row */}
      <div
        className="flex items-center gap-3 p-3 cursor-pointer select-none"
        onClick={() => setOpen(!open)}
      >
        <span className={`text-xs font-semibold px-2 py-0.5 rounded-full shrink-0 ${meta?.color ?? 'bg-gray-100 text-gray-600'}`}>
          {meta?.label ?? node.type}
        </span>
        <span className="text-sm font-medium text-gray-800 dark:text-gray-200 flex-1 truncate">
          {node.label || node.id}
        </span>
        {isEntry && (
          <span className="text-xs text-emerald-700 dark:text-emerald-400 bg-emerald-50 dark:bg-emerald-900/20 px-2 py-0.5 rounded-full shrink-0">
            Entry
          </span>
        )}
        <button
          onClick={(e) => { e.stopPropagation(); onDelete() }}
          className="p-1 rounded text-gray-400 hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-900/20 shrink-0"
        >
          <Trash2 size={13} />
        </button>
        {open ? <ChevronDown size={14} className="text-gray-400 shrink-0" /> : <ChevronRight size={14} className="text-gray-400 shrink-0" />}
      </div>

      {open && (
        <div className="border-t border-gray-100 dark:border-gray-800 p-4 space-y-4">
          {/* Node meta */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-medium text-gray-500 dark:text-gray-400 mb-1">Node ID</label>
              <input
                value={node.id}
                onChange={(e) => onUpdate({ ...node, id: e.target.value })}
                className="w-full px-3 py-1.5 rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 text-sm font-mono focus:outline-none focus:ring-1 focus:ring-violet-500"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-500 dark:text-gray-400 mb-1">Label</label>
              <input
                value={node.label}
                onChange={(e) => onUpdate({ ...node, label: e.target.value })}
                className="w-full px-3 py-1.5 rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 text-sm focus:outline-none focus:ring-1 focus:ring-violet-500"
              />
            </div>
          </div>

          {/* Set as entry */}
          {!isEntry && (
            <button
              onClick={onSetEntry}
              className="text-xs text-violet-600 dark:text-violet-400 hover:underline"
            >
              Set as entry node
            </button>
          )}

          {/* Config fields */}
          <div>
            <p className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-2">Config</p>
            <NodeConfigForm node={node} onChange={(cfg) => onUpdate({ ...node, config: cfg })} tools={tools} variables={variables} documents={documents} />
          </div>

          {/* Outgoing edges */}
          <div>
            <p className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-2">
              Outgoing edges
            </p>
            <div className="space-y-2">
              {outEdges.map((edge) => (
                <div key={edge.id} className="flex items-center gap-2 text-xs">
                  <input
                    value={edge.source_handle ?? 'default'}
                    onChange={(e) => onEdgeChange(edge.id, 'source_handle', e.target.value)}
                    placeholder="handle"
                    className="w-24 px-2 py-1 rounded border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 font-mono focus:outline-none focus:ring-1 focus:ring-violet-500"
                  />
                  <ArrowRight size={12} className="text-gray-400 shrink-0" />
                  <select
                    value={edge.target}
                    onChange={(e) => onEdgeChange(edge.id, 'target', e.target.value)}
                    className="flex-1 px-2 py-1 rounded border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 focus:outline-none focus:ring-1 focus:ring-violet-500"
                  >
                    {allNodes.filter((n) => n.id !== node.id).map((n) => (
                      <option key={n.id} value={n.id}>{n.label || n.id}</option>
                    ))}
                  </select>
                  <button onClick={() => onDeleteEdge(edge.id)} className="p-1 text-gray-400 hover:text-red-500">
                    <X size={12} />
                  </button>
                </div>
              ))}
              <button
                onClick={() => onAddEdge(node.id)}
                className="flex items-center gap-1 text-xs text-violet-600 dark:text-violet-400 hover:underline"
              >
                <Plus size={12} /> Add edge
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

// ─── Tabs ─────────────────────────────────────────────────────────────────────

type Tab = 'settings' | 'nodes' | 'executions' | 'raw'

const TABS: { id: Tab; label: string; icon: React.ElementType }[] = [
  { id: 'settings',   label: 'Settings',    icon: Settings },
  { id: 'nodes',      label: 'Nodes & Edges', icon: GitBranch },
  { id: 'executions', label: 'Executions',  icon: Activity },
  { id: 'raw',        label: 'JSON',        icon: Code },
]

// ─── Trigger config panel ─────────────────────────────────────────────────────

function TriggerConfig({
  type,
  config,
  onChange,
}: {
  type: TriggerType
  config: Record<string, unknown>
  onChange: (v: Record<string, unknown>) => void
}) {
  const set = (k: string, v: unknown) => onChange({ ...config, [k]: v })

  if (type === 'none') return (
    <p className="text-sm text-gray-500 dark:text-gray-400">
      This flow will be invoked as an LLM tool call or via the advance API.
    </p>
  )

  if (type === 'cron') return (
    <div className="space-y-3">
      <div>
        <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Cron schedule</label>
        <input
          value={String(config.schedule ?? '')}
          onChange={(e) => set('schedule', e.target.value)}
          placeholder="e.g. 0 9 * * * (daily at 9 AM)"
          className="w-full px-3 py-2 rounded-xl border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-violet-500"
        />
        <p className="text-xs text-gray-400 mt-1">Standard 5-field cron expression (minute hour day month weekday)</p>
      </div>
      <div>
        <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Timezone</label>
        <input
          value={String(config.timezone ?? 'UTC')}
          onChange={(e) => set('timezone', e.target.value)}
          placeholder="UTC"
          className="w-full px-3 py-2 rounded-xl border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 text-sm focus:outline-none focus:ring-2 focus:ring-violet-500"
        />
      </div>
    </div>
  )

  if (type === 'webhook') return (
    <div className="space-y-3">
      <div>
        <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Webhook secret (optional)</label>
        <input
          type="password"
          value={String(config.webhook_secret ?? '')}
          onChange={(e) => set('webhook_secret', e.target.value)}
          placeholder="whsec_..."
          className="w-full px-3 py-2 rounded-xl border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-violet-500"
        />
        <p className="text-xs text-gray-400 mt-1">If set, incoming requests must include a valid HMAC-SHA256 signature header.</p>
      </div>
    </div>
  )

  if (type === 'event') return (
    <div className="space-y-3">
      <div>
        <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Event name</label>
        <input
          value={String(config.event ?? '')}
          onChange={(e) => set('event', e.target.value)}
          placeholder="e.g. payment.completed"
          className="w-full px-3 py-2 rounded-xl border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-violet-500"
        />
      </div>
      <div>
        <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Filter (JSON, optional)</label>
        <textarea
          value={JSON.stringify(config.filter ?? {}, null, 2)}
          onChange={(e) => { try { set('filter', JSON.parse(e.target.value)) } catch {} }}
          rows={3}
          placeholder='{"status": "paid"}'
          className="w-full px-3 py-2 rounded-xl border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 text-sm font-mono resize-none focus:outline-none focus:ring-2 focus:ring-violet-500"
        />
      </div>
    </div>
  )

  return null
}

// ─── Execution status badge ───────────────────────────────────────────────────

const STATUS_STYLES: Record<string, string> = {
  RUNNING:         'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300',
  COMPLETED:       'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300',
  FAILED:          'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300',
  EXPIRED:         'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400',
  AWAITING_INPUT:  'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300',
  AWAITING_EVENT:  'bg-violet-100 text-violet-700 dark:bg-violet-900/30 dark:text-violet-300',
}

const SOURCE_LABELS: Record<string, string> = {
  llm_tool_call: 'LLM',
  cron: 'Cron',
  webhook: 'Webhook',
  event: 'Event',
  manual_api: 'Manual',
}

// ─── Add node modal ───────────────────────────────────────────────────────────

function AddNodeModal({
  onAdd,
  onClose,
}: {
  onAdd: (type: NodeType) => void
  onClose: () => void
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
      <div className="w-full max-w-lg bg-white dark:bg-gray-900 rounded-2xl shadow-2xl p-6 max-h-[80vh] overflow-y-auto">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-gray-900 dark:text-white">Add node</h2>
          <button onClick={onClose} className="p-1.5 rounded-lg text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800"><X size={16} /></button>
        </div>
        <div className="grid grid-cols-2 gap-2">
          {NODE_TYPES.map((nt) => (
            <button
              key={nt.type}
              onClick={() => { onAdd(nt.type); onClose() }}
              className="text-left p-3 rounded-xl border border-gray-200 dark:border-gray-700 hover:border-violet-400 dark:hover:border-violet-600 hover:bg-violet-50/40 dark:hover:bg-violet-900/10 transition-colors"
            >
              <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${nt.color}`}>{nt.label}</span>
              <p className="text-xs text-gray-500 dark:text-gray-400 mt-1.5 leading-snug">{nt.desc}</p>
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function FlowDetailPage() {
  const { id: agentId, flowId } = useParams<{ id: string; flowId: string }>()
  const router = useRouter()
  const qc = useQueryClient()

  const [tab, setTab] = useState<Tab>('settings')
  const [showAddNode, setShowAddNode] = useState(false)

  // ── Editable state ────
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [tags, setTags] = useState<string[]>([])
  const [tagInput, setTagInput] = useState('')
  const [triggerType, setTriggerType] = useState<TriggerType>('none')
  const [triggerConfig, setTriggerConfig] = useState<Record<string, unknown>>({})
  const [definition, setDefinition] = useState<WorkflowDefinition>({
    nodes: [], edges: [], entry_node_id: '', variables: {},
  })
  const [rawJson, setRawJson] = useState('')
  const [rawError, setRawError] = useState('')
  const [dirty, setDirty] = useState(false)

  // ── Fetch flow ────────
  const { data: flow, isLoading } = useQuery<Flow>({
    queryKey: ['flow', agentId, flowId],
    queryFn: () => workflowsApi.get(agentId, flowId),
  })

  const { data: baseVariables = [] } = useQuery({
    queryKey: ['variables', agentId],
    queryFn: () => variablesApi.list(agentId),
    enabled: !!agentId,
  })
  
  const globalVariables = Array.isArray(baseVariables) ? baseVariables.filter((v: any) => v.scope === 'global') : []

  const { data: tools = [] } = useQuery({
    queryKey: ['tools', agentId],
    queryFn: () => toolsApi.list(agentId),
    enabled: !!agentId,
  })

  const { data: documents = [] } = useQuery({
    queryKey: ['documents', agentId],
    queryFn: () => documentsApi.list(agentId),
    enabled: !!agentId,
  })

  // Hydrate state from server data
  useEffect(() => {
    if (!flow) return
    setName(flow.name)
    setDescription(flow.description)
    setTags(flow.tags ?? [])
    setTriggerType(flow.trigger_type)
    setTriggerConfig(flow.trigger_config ?? {})
    const def = flow.definition ?? { nodes: [], edges: [], entry_node_id: '', variables: {} }
    setDefinition(def)
    setRawJson(JSON.stringify(def, null, 2))
    setDirty(false)
  }, [flow])

  // Sync rawJson when definition changes (from node editor)
  useEffect(() => {
    if (tab === 'raw') return // don't overwrite while user is typing JSON
    setRawJson(JSON.stringify(definition, null, 2))
  }, [definition])

  // ── Executions ───────
  const { data: executions = [], isLoading: execLoading } = useQuery<Execution[]>({
    queryKey: ['flow-executions', agentId, flowId],
    queryFn: () => workflowsApi.listExecutions(agentId, flowId),
    enabled: tab === 'executions',
    refetchInterval: tab === 'executions' ? 5000 : false,
  })

  // ── Save ─────────────
  const saveMutation = useMutation({
    mutationFn: () =>
      workflowsApi.patch(agentId, flowId, {
        name,
        description,
        tags,
        trigger_type: triggerType,
        trigger_config: triggerConfig,
        definition,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['workflows', agentId] })
      qc.invalidateQueries({ queryKey: ['flow', agentId, flowId] })
      toast.success('Workflow saved')
      setDirty(false)
    },
    onError: (e: any) => {
      toast.error(e?.response?.data?.detail || 'Failed to save workflow')
    },
  })

  const toggleMutation = useMutation({
    mutationFn: () => flow?.is_active ? workflowsApi.deactivate(agentId, flowId) : workflowsApi.activate(agentId, flowId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['flow', agentId, flowId] })
      toast.success(flow?.is_active ? 'Workflow deactivated' : 'Workflow activated')
    },
    onError: () => toast.error('Failed to toggle workflow'),
  })

  const deleteMutation = useMutation({
    mutationFn: () => workflowsApi.delete(agentId, flowId),
    onSuccess: () => {
      toast.success('Workflow deleted')
      router.push(`/dashboard/agents/${agentId}/workflows`)
    },
    onError: () => toast.error('Failed to delete workflow'),
  })

  // ── Definition helpers ────────────────────────────────────────────────────

  const mark = () => setDirty(true)

  const addNode = (type: NodeType) => {
    const id = `${type.toLowerCase()}_${Date.now()}`
    const newNode: WorkflowNode = { id, type, label: NODE_META[type]?.label ?? type, config: defaultConfig(type) }
    setDefinition((d) => ({
      ...d,
      nodes: [...d.nodes, newNode],
      entry_node_id: d.entry_node_id || id,
    }))
    mark()
  }

  const updateNode = (idx: number, node: WorkflowNode) => {
    setDefinition((d) => {
      const nodes = [...d.nodes]
      const oldId = nodes[idx].id
      nodes[idx] = node
      // Update edges if node id changed
      const edges = d.edges.map((e) => ({
        ...e,
        source: e.source === oldId ? node.id : e.source,
        target: e.target === oldId ? node.id : e.target,
      }))
      const entry_node_id = d.entry_node_id === oldId ? node.id : d.entry_node_id
      return { ...d, nodes, edges, entry_node_id }
    })
    mark()
  }

  const deleteNode = (idx: number) => {
    setDefinition((d) => {
      const removed = d.nodes[idx].id
      const nodes = d.nodes.filter((_, i) => i !== idx)
      const edges = d.edges.filter((e) => e.source !== removed && e.target !== removed)
      const entry_node_id = d.entry_node_id === removed ? (nodes[0]?.id ?? '') : d.entry_node_id
      return { ...d, nodes, edges, entry_node_id }
    })
    mark()
  }

  const addEdge = (sourceId: string) => {
    const others = definition.nodes.filter((n) => n.id !== sourceId)
    if (!others.length) return
    setDefinition((d) => ({
      ...d,
      edges: [...d.edges, { id: `e_${Date.now()}`, source: sourceId, target: others[0].id, source_handle: 'default' }],
    }))
    mark()
  }

  const updateEdge = (edgeId: string, field: string, value: string) => {
    setDefinition((d) => ({
      ...d,
      edges: d.edges.map((e) => e.id === edgeId ? { ...e, [field]: value } : e),
    }))
    mark()
  }

  const deleteEdge = (edgeId: string) => {
    setDefinition((d) => ({ ...d, edges: d.edges.filter((e) => e.id !== edgeId) }))
    mark()
  }

  const applyRawJson = () => {
    try {
      const parsed = JSON.parse(rawJson)
      setDefinition(parsed)
      setRawError('')
      mark()
    } catch (err: any) {
      setRawError(err.message)
    }
  }

  if (isLoading) {
    return (
      <div className="flex justify-center items-center min-h-screen">
        <Loader2 size={28} className="animate-spin text-violet-500" />
      </div>
    )
  }

  if (!flow) return null

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-950">
      {/* Top bar */}
      <div className="sticky top-0 z-30 bg-white dark:bg-gray-900 border-b border-gray-200 dark:border-gray-800 px-6 py-3 flex items-center gap-4">
        <Link
          href={`/dashboard/agents/${agentId}/workflows`}
          className="flex items-center gap-1.5 text-sm text-gray-500 dark:text-gray-400 hover:text-violet-600 dark:hover:text-violet-400 shrink-0"
        >
          <ChevronLeft size={16} /> Workflows
        </Link>

        <div className="flex-1 min-w-0">
          <h1 className="text-base font-semibold text-gray-900 dark:text-white truncate">{flow.name}</h1>
          <p className="text-xs text-gray-400 dark:text-gray-500">v{flow.version}</p>
        </div>

        <div className="flex items-center gap-2 shrink-0">
          {/* Active badge */}
          {flow.is_active ? (
            <span className="hidden sm:flex items-center gap-1 text-xs font-medium text-emerald-700 dark:text-emerald-400 bg-emerald-50 dark:bg-emerald-900/20 px-2 py-0.5 rounded-full">
              <CheckCircle2 size={11} /> Active
            </span>
          ) : (
            <span className="hidden sm:flex items-center gap-1 text-xs font-medium text-gray-500 bg-gray-100 dark:bg-gray-800 px-2 py-0.5 rounded-full">
              <XCircle size={11} /> Inactive
            </span>
          )}

          {/* Toggle */}
          <button
            onClick={() => toggleMutation.mutate()}
            disabled={toggleMutation.isPending}
            title={flow.is_active ? 'Deactivate' : 'Activate'}
            className="p-1.5 rounded-lg border border-gray-200 dark:border-gray-700 text-gray-500 hover:border-violet-400 hover:text-violet-600 transition-colors"
          >
            {flow.is_active ? <Pause size={15} /> : <Play size={15} />}
          </button>

          {/* Delete */}
          <button
            onClick={() => confirm('Delete this workflow?') && deleteMutation.mutate()}
            className="p-1.5 rounded-lg border border-gray-200 dark:border-gray-700 text-gray-500 hover:border-red-400 hover:text-red-500 transition-colors"
          >
            <Trash2 size={15} />
          </button>

          {/* Save */}
          <button
            onClick={() => saveMutation.mutate()}
            disabled={saveMutation.isPending || !dirty}
            className="flex items-center gap-2 px-4 py-1.5 rounded-lg bg-violet-600 text-white text-sm font-medium disabled:opacity-50 hover:bg-violet-700 transition-colors"
          >
            {saveMutation.isPending ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
            Save
          </button>
        </div>
      </div>

      {/* Tab bar */}
      <div className="bg-white dark:bg-gray-900 border-b border-gray-200 dark:border-gray-800 px-6">
        <div className="flex gap-1">
          {TABS.map((t) => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={`flex items-center gap-1.5 px-3 py-3 text-sm font-medium border-b-2 transition-colors ${
                tab === t.id
                  ? 'border-violet-600 text-violet-600 dark:text-violet-400'
                  : 'border-transparent text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200'
              }`}
            >
              <t.icon size={14} /> {t.label}
            </button>
          ))}
        </div>
      </div>

      {/* Tab content */}
      <div className="p-6 max-w-3xl mx-auto">

        {/* ── SETTINGS ──────────────────────────────────────────────────── */}
        {tab === 'settings' && (
          <div className="space-y-6">
            <div className="bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-800 p-6 space-y-4">
              <h2 className="text-base font-semibold text-gray-900 dark:text-white">General</h2>
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Name</label>
                <input
                  value={name}
                  onChange={(e) => { setName(e.target.value); mark() }}
                  className="w-full px-3 py-2 rounded-xl border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 text-sm focus:outline-none focus:ring-2 focus:ring-violet-500"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Description</label>
                <textarea
                  value={description}
                  onChange={(e) => { setDescription(e.target.value); mark() }}
                  rows={2}
                  className="w-full px-3 py-2 rounded-xl border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 text-sm resize-none focus:outline-none focus:ring-2 focus:ring-violet-500"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Tags</label>
                <div className="flex flex-wrap gap-1.5 p-2 min-h-[44px] rounded-xl border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 focus-within:ring-1 focus-within:ring-violet-500">
                  {tags.map((tag) => (
                    <span key={tag} className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full bg-violet-100 dark:bg-violet-900/40 text-violet-700 dark:text-violet-300 text-xs font-medium">
                      {tag}
                      <button type="button" onClick={() => { setTags(tags.filter((t) => t !== tag)); mark() }} className="hover:text-violet-900"><X size={10} /></button>
                    </span>
                  ))}
                  <input
                    value={tagInput}
                    onChange={(e) => setTagInput(e.target.value)}
                    onKeyDown={(e) => {
                      if ((e.key === 'Enter' || e.key === ',') && tagInput.trim()) {
                        e.preventDefault()
                        const v = tagInput.trim()
                        if (!tags.includes(v)) { setTags([...tags, v]); mark() }
                        setTagInput('')
                      }
                    }}
                    placeholder="Add tag…"
                    className="flex-1 min-w-[80px] bg-transparent text-sm outline-none text-gray-700 dark:text-gray-300 placeholder-gray-400"
                  />
                </div>
              </div>
            </div>

            {/* Trigger section */}
            <div className="bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-800 p-6 space-y-4">
              <h2 className="text-base font-semibold text-gray-900 dark:text-white">Trigger</h2>
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Trigger type</label>
                <select
                  value={triggerType}
                  onChange={(e) => { setTriggerType(e.target.value as TriggerType); setTriggerConfig({}); mark() }}
                  className="w-full px-3 py-2 rounded-xl border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 text-sm focus:outline-none focus:ring-2 focus:ring-violet-500"
                >
                  <option value="none">Manual / LLM tool call</option>
                  <option value="cron">Scheduled (cron)</option>
                  <option value="webhook">Webhook</option>
                  <option value="event">Internal event</option>
                </select>
              </div>
              <TriggerConfig
                type={triggerType}
                config={triggerConfig}
                onChange={(v) => { setTriggerConfig(v); mark() }}
              />
            </div>
          </div>
        )}

        {/* ── NODES & EDGES ──────────────────────────────────────────────── */}
        {tab === 'nodes' && (
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-gray-500 dark:text-gray-400">
                  {definition.nodes.length} nodes · {definition.edges.length} edges
                </p>
              </div>
              <button
                onClick={() => setShowAddNode(true)}
                className="flex items-center gap-2 px-3 py-1.5 bg-violet-600 text-white rounded-xl text-sm font-medium hover:bg-violet-700"
              >
                <Plus size={14} /> Add node
              </button>
            </div>

            {definition.nodes.length === 0 ? (
              <div className="text-center py-16 bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-800">
                <GitBranch size={36} className="text-gray-300 dark:text-gray-700 mx-auto mb-3" />
                <p className="text-sm text-gray-500 dark:text-gray-400 mb-4">No nodes yet. Add your first node to start building.</p>
                <button onClick={() => setShowAddNode(true)} className="inline-flex items-center gap-2 px-4 py-2 bg-violet-600 text-white rounded-xl text-sm font-medium hover:bg-violet-700">
                  <Plus size={14} /> Add node
                </button>
              </div>
            ) : (
              <div className="space-y-2">
                {definition.nodes.map((node, idx) => (
                  <NodeRow
                    key={node.id}
                    node={node}
                    isEntry={definition.entry_node_id === node.id}
                    allNodes={definition.nodes}
                    edges={definition.edges}
                    onUpdate={(n) => updateNode(idx, n)}
                    onDelete={() => deleteNode(idx)}
                    onSetEntry={() => { setDefinition((d) => ({ ...d, entry_node_id: node.id })); mark() }}
                    onEdgeChange={updateEdge}
                    onAddEdge={addEdge}
                    onDeleteEdge={deleteEdge}
                    tools={tools}
                    variables={globalVariables}
                    documents={documents}
                  />
                ))}
              </div>
            )}

            {/* Global variables */}
            <div className="bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-800 p-4">
              <p className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-2">Global variables (JSON)</p>
              <textarea
                value={JSON.stringify(definition.variables ?? {}, null, 2)}
                onChange={(e) => {
                  try { setDefinition((d) => ({ ...d, variables: JSON.parse(e.target.value) })); mark() } catch {}
                }}
                rows={4}
                className="w-full px-3 py-2 rounded-xl border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 text-xs font-mono resize-none focus:outline-none focus:ring-1 focus:ring-violet-500"
                placeholder='{"default_lang": "en"}'
              />
            </div>
          </div>
        )}

        {/* ── EXECUTIONS ─────────────────────────────────────────────────── */}
        {tab === 'executions' && (
          <div className="space-y-3">
            {execLoading ? (
              <div className="flex justify-center py-16"><Loader2 size={24} className="animate-spin text-violet-500" /></div>
            ) : executions.length === 0 ? (
              <div className="text-center py-16 bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-800">
                <Activity size={36} className="text-gray-300 dark:text-gray-700 mx-auto mb-3" />
                <p className="text-sm text-gray-500 dark:text-gray-400">No executions yet.</p>
              </div>
            ) : (
              executions.map((ex) => (
                <div key={ex.id} className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 p-4">
                  <div className="flex items-start justify-between gap-3">
                    <div className="space-y-1">
                      <div className="flex items-center gap-2">
                        <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${STATUS_STYLES[ex.status] ?? 'bg-gray-100 text-gray-600'}`}>
                          {ex.status}
                        </span>
                        <span className="text-xs text-gray-400 dark:text-gray-500">
                          via {SOURCE_LABELS[ex.trigger_source] ?? ex.trigger_source}
                        </span>
                      </div>
                      <p className="text-xs font-mono text-gray-500 dark:text-gray-400">{ex.id}</p>
                      {ex.error_message && (
                        <p className="text-xs text-red-600 dark:text-red-400 flex items-start gap-1">
                          <AlertCircle size={11} className="mt-0.5 shrink-0" /> {ex.error_message}
                        </p>
                      )}
                      {ex.current_node_id && (
                        <p className="text-xs text-gray-400">Current node: <code className="font-mono">{ex.current_node_id}</code></p>
                      )}
                    </div>
                    <div className="text-right shrink-0">
                      <p className="text-xs text-gray-400">{new Date(ex.created_at).toLocaleString()}</p>
                    </div>
                  </div>
                </div>
              ))
            )}
          </div>
        )}

        {/* ── RAW JSON ──────────────────────────────────────────────────── */}
        {tab === 'raw' && (
          <div className="space-y-3">
            <div className="flex items-start gap-2 text-xs text-amber-700 dark:text-amber-400 bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 rounded-xl p-3">
              <Info size={13} className="shrink-0 mt-0.5" />
              Edit the raw workflow definition JSON. Click "Apply" to sync to the node editor, then Save to persist.
            </div>
            <textarea
              value={rawJson}
              onChange={(e) => { setRawJson(e.target.value); setRawError('') }}
              rows={30}
              spellCheck={false}
              className="w-full px-4 py-3 rounded-xl border border-gray-200 dark:border-gray-700 bg-gray-900 text-gray-100 text-xs font-mono resize-none focus:outline-none focus:ring-2 focus:ring-violet-500"
            />
            {rawError && (
              <p className="text-xs text-red-600 dark:text-red-400 flex items-center gap-1">
                <AlertCircle size={12} /> {rawError}
              </p>
            )}
            <button
              onClick={applyRawJson}
              className="px-4 py-2 bg-violet-600 text-white rounded-xl text-sm font-medium hover:bg-violet-700"
            >
              Apply JSON
            </button>
          </div>
        )}
      </div>

      {showAddNode && <AddNodeModal onAdd={addNode} onClose={() => setShowAddNode(false)} />}
    </div>
  )
}
