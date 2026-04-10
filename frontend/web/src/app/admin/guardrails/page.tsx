'use client'

import { useEffect, useState } from 'react'
import { adminApi } from '@/lib/api'
import {
  ShieldCheck,
  ShieldAlert,
  Lock,
  Unlock,
  RefreshCw,
  AlertTriangle,
  CheckCircle2,
  Info,
} from 'lucide-react'

interface Guardrail {
  id: string
  name: string
  description: string
  category: string
  enabled: boolean
  severity: 'critical' | 'high' | 'medium' | 'low'
  toggleable: boolean
}

const CATEGORY_LABELS: Record<string, string> = {
  security: 'Security',
  privacy: 'Privacy & PII',
  safety: 'Safety',
  compliance: 'Compliance',
  quality: 'Quality',
  reliability: 'Reliability',
}

const SEVERITY_STYLES: Record<string, string> = {
  critical: 'bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-300',
  high:     'bg-orange-100 dark:bg-orange-900/30 text-orange-700 dark:text-orange-300',
  medium:   'bg-yellow-100 dark:bg-yellow-900/30 text-yellow-700 dark:text-yellow-300',
  low:      'bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-300',
}

const CATEGORY_STYLES: Record<string, string> = {
  security:    'bg-violet-50 dark:bg-violet-900/20 text-violet-700 dark:text-violet-300',
  privacy:     'bg-blue-50 dark:bg-blue-900/20 text-blue-700 dark:text-blue-300',
  safety:      'bg-red-50 dark:bg-red-900/20 text-red-700 dark:text-red-300',
  compliance:  'bg-emerald-50 dark:bg-emerald-900/20 text-emerald-700 dark:text-emerald-300',
  quality:     'bg-indigo-50 dark:bg-indigo-900/20 text-indigo-700 dark:text-indigo-300',
  reliability: 'bg-slate-50 dark:bg-slate-800/50 text-slate-700 dark:text-slate-300',
}

export default function PlatformGuardrailsPage() {
  const [guardrails, setGuardrails] = useState<Guardrail[]>([])
  const [loading, setLoading] = useState(true)
  const [toggling, setToggling] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState<string | null>(null)

  const fetchGuardrails = async () => {
    setLoading(true)
    try {
      const data = await adminApi.listGuardrails()
      setGuardrails(data.guardrails || [])
      setError(null)
    } catch (err) {
      setError('Failed to load platform guardrails.')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchGuardrails()
  }, [])

  const handleToggle = async (guardrail: Guardrail) => {
    if (!guardrail.toggleable) return
    const newValue = !guardrail.enabled
    setToggling(guardrail.id)
    setError(null)
    try {
      await adminApi.updateGuardrail(guardrail.id, newValue)
      setGuardrails((prev) =>
        prev.map((g) => (g.id === guardrail.id ? { ...g, enabled: newValue } : g))
      )
      setSuccess(
        `${guardrail.id} ${newValue ? 'enabled' : 'disabled'} — change is live for all new requests.`
      )
      setTimeout(() => setSuccess(null), 4000)
    } catch (err: any) {
      setError(err?.response?.data?.detail || `Failed to update ${guardrail.id}.`)
    } finally {
      setToggling(null)
    }
  }

  const categories = Array.from(new Set(guardrails.map((g) => g.category)))
  const enabledCount = guardrails.filter((g) => g.enabled).length
  const criticalDisabled = guardrails.filter(
    (g) => g.severity === 'critical' && !g.enabled
  ).length

  return (
    <div className="p-8 max-w-5xl mx-auto">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-start justify-between gap-6 mb-8">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white flex items-center gap-2">
            <ShieldCheck className="text-violet-500" size={24} />
            Platform Guardrails
          </h1>
          <p className="text-sm text-gray-500 mt-1 max-w-xl">
            Global enforcement rules applied to every agent on the platform, regardless of tenant
            configuration. Critical rules cannot be disabled.
          </p>
        </div>
        <div className="flex items-center gap-3 shrink-0">
          <div className="px-3 py-1.5 rounded-lg bg-emerald-50 dark:bg-emerald-900/20 border border-emerald-200 dark:border-emerald-800 text-emerald-700 dark:text-emerald-300 text-xs font-bold">
            {enabledCount}/{guardrails.length} active
          </div>
          {criticalDisabled > 0 && (
            <div className="px-3 py-1.5 rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 text-red-700 dark:text-red-300 text-xs font-bold flex items-center gap-1">
              <AlertTriangle size={12} />
              {criticalDisabled} critical disabled
            </div>
          )}
        </div>
      </div>

      {/* Alerts */}
      {error && (
        <div className="mb-6 p-4 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-xl flex items-center gap-3 text-red-700 dark:text-red-400 text-sm">
          <AlertTriangle size={16} />
          {error}
        </div>
      )}
      {success && (
        <div className="mb-6 p-4 bg-emerald-50 dark:bg-emerald-900/20 border border-emerald-200 dark:border-emerald-800 rounded-xl flex items-center gap-3 text-emerald-700 dark:text-emerald-400 text-sm">
          <CheckCircle2 size={16} />
          {success}
        </div>
      )}

      {/* Warning banner if any guardrail is disabled */}
      {guardrails.some((g) => !g.enabled) && (
        <div className="mb-6 p-4 bg-amber-50 dark:bg-amber-900/10 border border-amber-200 dark:border-amber-800 rounded-xl flex items-start gap-3">
          <AlertTriangle className="text-amber-500 shrink-0 mt-0.5" size={16} />
          <div>
            <p className="text-sm font-semibold text-amber-800 dark:text-amber-300">Guardrails disabled</p>
            <p className="text-xs text-amber-700 dark:text-amber-400 mt-0.5">
              One or more platform guardrails are disabled. This may increase regulatory and safety
              risk. Re-enable rules before production traffic.
            </p>
          </div>
        </div>
      )}

      {/* Info callout */}
      <div className="mb-8 p-4 bg-blue-50 dark:bg-blue-900/10 border border-blue-200 dark:border-blue-800 rounded-xl flex items-start gap-3">
        <Info className="text-blue-500 shrink-0 mt-0.5" size={16} />
        <p className="text-xs text-blue-700 dark:text-blue-300 leading-relaxed">
          <strong>Non-toggleable rules</strong> (marked with a lock icon) are enforced in code and
          cannot be bypassed through this interface. Changes to toggleable rules take effect
          immediately for all new requests — no restart required.
        </p>
      </div>

      {loading ? (
        <div className="space-y-4 animate-pulse">
          {[...Array(8)].map((_, i) => (
            <div key={i} className="h-20 bg-gray-100 dark:bg-gray-800 rounded-xl" />
          ))}
        </div>
      ) : (
        <div className="space-y-8">
          {categories.map((cat) => (
            <div key={cat}>
              <h2 className="text-xs font-bold uppercase tracking-widest text-gray-400 dark:text-gray-500 mb-3">
                {CATEGORY_LABELS[cat] || cat}
              </h2>
              <div className="space-y-3">
                {guardrails
                  .filter((g) => g.category === cat)
                  .map((guardrail) => (
                    <div
                      key={guardrail.id}
                      className={`flex items-center justify-between gap-4 p-5 rounded-xl border transition-all ${
                        guardrail.enabled
                          ? 'bg-white dark:bg-gray-900 border-gray-200 dark:border-gray-800'
                          : 'bg-gray-50 dark:bg-gray-900/50 border-gray-200 dark:border-gray-700 opacity-70'
                      }`}
                    >
                      <div className="flex items-start gap-3 flex-1 min-w-0">
                        <div
                          className={`shrink-0 w-9 h-9 rounded-lg flex items-center justify-center ${
                            guardrail.enabled
                              ? 'bg-emerald-100 dark:bg-emerald-900/30 text-emerald-600 dark:text-emerald-400'
                              : 'bg-gray-100 dark:bg-gray-800 text-gray-400'
                          }`}
                        >
                          {guardrail.enabled ? <ShieldCheck size={18} /> : <ShieldAlert size={18} />}
                        </div>
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2 flex-wrap mb-1">
                            <span className="text-sm font-semibold text-gray-900 dark:text-white">
                              {guardrail.name}
                            </span>
                            <span className="font-mono text-[10px] text-gray-400 dark:text-gray-500">
                              {guardrail.id}
                            </span>
                            <span
                              className={`text-[10px] font-bold uppercase tracking-wide px-2 py-0.5 rounded-full ${
                                SEVERITY_STYLES[guardrail.severity]
                              }`}
                            >
                              {guardrail.severity}
                            </span>
                            <span
                              className={`text-[10px] font-bold uppercase tracking-wide px-2 py-0.5 rounded-full ${
                                CATEGORY_STYLES[guardrail.category]
                              }`}
                            >
                              {CATEGORY_LABELS[guardrail.category] || guardrail.category}
                            </span>
                          </div>
                          <p className="text-xs text-gray-500 dark:text-gray-400 leading-relaxed">
                            {guardrail.description}
                          </p>
                        </div>
                      </div>

                      {/* Toggle */}
                      <div className="shrink-0">
                        {!guardrail.toggleable ? (
                          <div className="flex items-center gap-1.5 text-xs font-semibold text-gray-400 dark:text-gray-500">
                            <Lock size={13} />
                            Immutable
                          </div>
                        ) : (
                          <button
                            onClick={() => handleToggle(guardrail)}
                            disabled={toggling === guardrail.id}
                            title={guardrail.enabled ? 'Disable guardrail' : 'Enable guardrail'}
                            className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors focus:outline-none focus:ring-2 focus:ring-violet-500 focus:ring-offset-2 disabled:opacity-50 ${
                              guardrail.enabled
                                ? 'bg-emerald-500'
                                : 'bg-gray-300 dark:bg-gray-700'
                            }`}
                          >
                            {toggling === guardrail.id ? (
                              <RefreshCw
                                size={12}
                                className="absolute left-1/2 -translate-x-1/2 animate-spin text-white"
                              />
                            ) : (
                              <span
                                className={`inline-block h-4 w-4 transform rounded-full bg-white shadow-sm transition-transform ${
                                  guardrail.enabled ? 'translate-x-6' : 'translate-x-1'
                                }`}
                              />
                            )}
                          </button>
                        )}
                      </div>
                    </div>
                  ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
