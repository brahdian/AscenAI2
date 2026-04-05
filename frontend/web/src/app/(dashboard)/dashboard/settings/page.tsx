'use client'

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useForm } from 'react-hook-form'
import { tenantApi, complianceApi } from '@/lib/api'
import { getPlanDisplayName } from '@/lib/plans'
import toast from 'react-hot-toast'
import { useEffect, useState } from 'react'
import { Shield, Trash2, ExternalLink } from 'lucide-react'

export default function SettingsPage() {
  const qc = useQueryClient()
  const [erasureContact, setErasureContact] = useState('')
  const [erasureReason, setErasureReason] = useState('customer_request')
  const [erasureSubmitting, setErasureSubmitting] = useState(false)

  const { data: tenant, isLoading } = useQuery({
    queryKey: ['tenant'],
    queryFn: tenantApi.getMe,
  })

  const { data: compliance } = useQuery({
    queryKey: ['compliance-settings'],
    queryFn: complianceApi.getSettings,
  })

  const {
    register: regCompliance,
    handleSubmit: handleComplianceSubmit,
    reset: resetCompliance,
  } = useForm({
    defaultValues: {
      data_retention_days: 365,
      session_retention_days: 90,
      auto_anonymize_after_days: 730,
      collect_consent_enabled: false,
      consent_message: 'By chatting, you agree to our privacy policy.',
      privacy_policy_url: '',
      data_residency: 'Canada',
    },
  })

  useEffect(() => {
    if (compliance) {
      resetCompliance({
        data_retention_days: compliance.data_retention_days ?? 365,
        session_retention_days: compliance.session_retention_days ?? 90,
        auto_anonymize_after_days: compliance.auto_anonymize_after_days ?? 730,
        collect_consent_enabled: compliance.collect_consent_enabled ?? false,
        consent_message: compliance.consent_message ?? 'By chatting, you agree to our privacy policy.',
        privacy_policy_url: compliance.privacy_policy_url ?? '',
        data_residency: compliance.data_residency ?? 'Canada',
      })
    }
  }, [compliance, resetCompliance])

  const complianceMutation = useMutation({
    mutationFn: (data: Record<string, unknown>) => complianceApi.updateSettings(data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['compliance-settings'] })
      toast.success('Compliance settings saved')
    },
    onError: () => toast.error('Failed to save compliance settings'),
  })

  const handleErasureRequest = async () => {
    if (!erasureContact.trim()) {
      toast.error('Enter an email or customer ID')
      return
    }
    setErasureSubmitting(true)
    try {
      const res = await complianceApi.requestErasure({
        contact_identifier: erasureContact,
        reason: erasureReason,
      })
      toast.success(`Erasure request submitted — ID: ${res.request_id.slice(0, 8)}…`)
      setErasureContact('')
    } catch {
      toast.error('Failed to submit erasure request')
    } finally {
      setErasureSubmitting(false)
    }
  }

  if (isLoading) return <div className="p-8 animate-pulse">Loading…</div>

  return (
    <div className="p-8 w-full">
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Settings</h1>
        <p className="text-gray-500 dark:text-gray-400 mt-1">
          Manage your account and business information.
        </p>
      </div>

      {/* Section 2: Plan & Billing */}
      <div className="mb-8">
        <h2 className="text-lg font-bold text-gray-900 dark:text-white mb-4">Plan & Billing</h2>

        <div className="bg-gradient-to-r from-violet-50 to-blue-50 dark:from-violet-900/20 dark:to-blue-900/20 rounded-xl border border-violet-100 dark:border-violet-800 p-5">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium text-gray-700 dark:text-gray-300">Current plan</p>
              <p className="text-xl font-bold text-violet-700 dark:text-violet-300">
                {tenant ? getPlanDisplayName(tenant.plan) : ''}
              </p>
            </div>
            <div className="text-right">
              <p className="text-xs text-gray-500">Tenant ID</p>
              <p className="text-xs font-mono text-gray-600 dark:text-gray-400">{tenant?.id?.slice(0, 16)}…</p>
            </div>
          </div>
          <div className="mt-4 pt-4 border-t border-violet-200 dark:border-violet-700">
            <a href="/dashboard/billing" className="text-sm text-violet-600 dark:text-violet-400 hover:underline font-medium">
              Manage billing & upgrade plan →
            </a>
          </div>
        </div>
      </div>

      {/* Section 4: Privacy & Compliance (PIPEDA) */}
      <div className="mb-8">
        <div className="flex items-center gap-2 mb-4">
          <Shield size={18} className="text-violet-500" />
          <h2 className="text-lg font-bold text-gray-900 dark:text-white">Privacy & Compliance (PIPEDA)</h2>
        </div>
        <p className="text-sm text-gray-500 mb-4">
          Configure data retention, consent, and privacy settings to comply with PIPEDA (Canadian Privacy Law)
          and related clinic/healthcare requirements.
        </p>

        <form
          onSubmit={handleComplianceSubmit((d) => complianceMutation.mutate(d as Record<string, unknown>))}
          className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 p-6 space-y-5 mb-6"
        >
          <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-300 border-b border-gray-100 dark:border-gray-800 pb-3">
            Data retention
          </h3>

          <div className="grid grid-cols-3 gap-4">
            {[
              { name: 'data_retention_days', label: 'Raw data (days)', min: 30, max: 3650 },
              { name: 'session_retention_days', label: 'Session records (days)', min: 7, max: 3650 },
              { name: 'auto_anonymize_after_days', label: 'Auto-anonymize after (days)', min: 30, max: 3650 },
            ].map((f) => (
              <div key={f.name}>
                <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
                  {f.label}
                </label>
                <input
                  type="number"
                  min={f.min}
                  max={f.max}
                  {...regCompliance(f.name as any, { valueAsNumber: true })}
                  className="w-full px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm focus:outline-none focus:ring-1 focus:ring-violet-500"
                />
              </div>
            ))}
          </div>

          <div>
            <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
              Data residency
            </label>
            <select
              {...regCompliance('data_residency')}
              className="w-full px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm focus:outline-none focus:ring-1 focus:ring-violet-500"
            >
              <option value="Canada">Canada</option>
              <option value="US">United States</option>
              <option value="EU">European Union</option>
            </select>
          </div>

          <div className="pt-2 border-t border-gray-100 dark:border-gray-800">
            <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-4">Consent</h3>
            <div className="flex items-center gap-3 mb-4">
              <input
                type="checkbox"
                id="collect_consent_enabled"
                {...regCompliance('collect_consent_enabled')}
                className="w-4 h-4 accent-violet-600"
              />
              <label htmlFor="collect_consent_enabled" className="text-sm text-gray-700 dark:text-gray-300">
                Show consent notice before first chat message
              </label>
            </div>
            <div className="mb-4">
              <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
                Consent message
              </label>
              <input
                type="text"
                {...regCompliance('consent_message')}
                className="w-full px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm focus:outline-none focus:ring-1 focus:ring-violet-500"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
                Privacy policy URL
              </label>
              <input
                type="url"
                placeholder="https://yoursite.com/privacy"
                {...regCompliance('privacy_policy_url')}
                className="w-full px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm focus:outline-none focus:ring-1 focus:ring-violet-500"
              />
            </div>
          </div>

          <button
            type="submit"
            disabled={complianceMutation.isPending}
            className="px-5 py-2.5 rounded-lg bg-violet-600 text-white text-sm font-medium hover:bg-violet-700 disabled:opacity-50 transition-colors"
          >
            {complianceMutation.isPending ? 'Saving…' : 'Save compliance settings'}
          </button>
        </form>

        {/* Right to erasure */}
        <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 p-6">
          <div className="flex items-center gap-2 mb-1">
            <Trash2 size={15} className="text-red-500" />
            <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-300">Right to Erasure</h3>
          </div>
          <p className="text-xs text-gray-500 mb-4">
            PIPEDA grants individuals the right to request deletion of their personal data.
            Submit a request below — all sessions, messages, and PII for that contact will be
            permanently deleted within 30 days.
          </p>
          <div className="flex gap-3">
            <input
              type="text"
              value={erasureContact}
              onChange={(e) => setErasureContact(e.target.value)}
              placeholder="customer@email.com or customer ID"
              className="flex-1 px-3 py-2.5 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-sm text-gray-900 dark:text-white focus:outline-none focus:ring-1 focus:ring-red-500"
            />
            <select
              value={erasureReason}
              onChange={(e) => setErasureReason(e.target.value)}
              className="px-3 py-2.5 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-sm text-gray-900 dark:text-white focus:outline-none"
            >
              <option value="customer_request">Customer request</option>
              <option value="legal_obligation">Legal obligation</option>
              <option value="data_minimization">Data minimization</option>
            </select>
            <button
              onClick={handleErasureRequest}
              disabled={erasureSubmitting || !erasureContact.trim()}
              className="px-4 py-2.5 rounded-lg bg-red-600 text-white text-sm font-medium hover:bg-red-700 disabled:opacity-50 transition-colors whitespace-nowrap"
            >
              {erasureSubmitting ? 'Submitting…' : 'Submit request'}
            </button>
          </div>
          <p className="text-xs text-gray-400 mt-2">
            All erasure requests are logged for your audit trail. Contact{' '}
            <a href="mailto:privacy@ascenai.com" className="text-violet-600 hover:underline">
              privacy@ascenai.com
            </a>{' '}
            if you need assistance.
          </p>
        </div>
      </div>

      {/* Section 5: Data Management */}
      <div className="mb-8">
        <h2 className="text-lg font-bold text-gray-900 dark:text-white mb-4">Data Management</h2>

        <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 p-6 space-y-6">
          <div className="flex items-center justify-between pb-4 border-b border-gray-100 dark:border-gray-800">
            <div>
              <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-300">Export Data</h3>
              <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                Download all your account data, including agents, sessions, and settings.
              </p>
            </div>
            <button
              type="button"
              className="px-4 py-2 rounded-lg border border-gray-200 dark:border-gray-700 text-gray-700 dark:text-gray-300 text-sm font-medium hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors"
            >
              Export
            </button>
          </div>

          <div className="flex items-center justify-between">
            <div>
              <h3 className="text-sm font-semibold text-red-600 dark:text-red-400">Delete Account</h3>
              <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                Permanently delete your account and all associated data. This action cannot be undone.
              </p>
            </div>
            <button
              type="button"
              className="px-4 py-2 rounded-lg bg-red-600 text-white text-sm font-medium hover:bg-red-700 transition-colors"
            >
              Delete Account
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
