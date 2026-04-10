'use client'

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useForm } from 'react-hook-form'
import { useRouter } from 'next/navigation'
import { tenantApi, agentsApi, complianceApi } from '@/lib/api'
import { useAuthStore } from '@/store/auth'
import { getPlanDisplayName } from '@/lib/plans'
import toast from 'react-hot-toast'
import { useEffect, useState } from 'react'
import { Shield, Trash2, Download, AlertTriangle, X } from 'lucide-react'

export default function SettingsPage() {
  const qc = useQueryClient()
  const router = useRouter()
  const { user, logout } = useAuthStore()

  // Erasure state
  const [erasureContact, setErasureContact] = useState('')
  const [erasureReason, setErasureReason] = useState('customer_request')
  const [erasureSubmitting, setErasureSubmitting] = useState(false)

  // Export state
  const [exporting, setExporting] = useState(false)

  // Delete account modal state
  const [showDeleteModal, setShowDeleteModal] = useState(false)
  const [deleteConfirm, setDeleteConfirm] = useState('')
  const [deleting, setDeleting] = useState(false)

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

  async function handleExport() {
    setExporting(true)
    try {
      const [tenantData, agentsData, usageData] = await Promise.all([
        tenantApi.getMe(),
        agentsApi.list(),
        tenantApi.getUsage(),
      ])
      const payload = {
        exported_at: new Date().toISOString(),
        tenant: tenantData,
        usage: usageData,
        agents: agentsData,
      }
      const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `ascenai-export-${new Date().toISOString().split('T')[0]}.json`
      a.click()
      URL.revokeObjectURL(url)
      toast.success('Export downloaded')
    } catch {
      toast.error('Failed to export data')
    } finally {
      setExporting(false)
    }
  }

  async function handleDeleteAccount() {
    if (deleteConfirm !== 'DELETE') return
    setDeleting(true)
    try {
      await complianceApi.requestErasure({
        contact_identifier: user?.email || '',
        reason: 'customer_request',
      })
      toast.success('Account deletion requested — signing you out.')
      setTimeout(() => {
        logout()
        router.push('/login')
      }, 2000)
    } catch {
      toast.error('Failed to submit account deletion request')
      setDeleting(false)
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
                Download all your account data, including agents, usage stats, and settings as JSON.
              </p>
            </div>
            <button
              type="button"
              onClick={handleExport}
              disabled={exporting}
              className="flex items-center gap-2 px-4 py-2 rounded-lg border border-gray-200 dark:border-gray-700 text-gray-700 dark:text-gray-300 text-sm font-medium hover:bg-gray-50 dark:hover:bg-gray-800 disabled:opacity-50 transition-colors"
            >
              {exporting ? (
                <div className="w-4 h-4 border-2 border-gray-400/30 border-t-gray-400 rounded-full animate-spin" />
              ) : (
                <Download size={14} />
              )}
              {exporting ? 'Exporting…' : 'Export'}
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
              onClick={() => { setDeleteConfirm(''); setShowDeleteModal(true) }}
              className="px-4 py-2 rounded-lg bg-red-600 text-white text-sm font-medium hover:bg-red-700 transition-colors"
            >
              Delete Account
            </button>
          </div>
        </div>
      </div>

      {/* Delete Account Confirmation Modal */}
      {showDeleteModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 shadow-xl w-full max-w-md p-6">
            <div className="flex items-start justify-between mb-4">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-full bg-red-100 dark:bg-red-900/30 flex items-center justify-center flex-shrink-0">
                  <AlertTriangle size={18} className="text-red-600 dark:text-red-400" />
                </div>
                <div>
                  <h3 className="text-base font-semibold text-gray-900 dark:text-white">Delete Account</h3>
                  <p className="text-xs text-gray-500 mt-0.5">This action is permanent and cannot be reversed.</p>
                </div>
              </div>
              <button
                onClick={() => setShowDeleteModal(false)}
                className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 transition-colors"
              >
                <X size={18} />
              </button>
            </div>

            <p className="text-sm text-gray-600 dark:text-gray-400 mb-4">
              All your agents, sessions, API keys, and data will be permanently deleted within 30 days.
              You will be immediately signed out.
            </p>

            <div className="mb-5">
              <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1.5">
                Type <span className="font-mono font-bold text-red-600">DELETE</span> to confirm
              </label>
              <input
                type="text"
                value={deleteConfirm}
                onChange={(e) => setDeleteConfirm(e.target.value)}
                placeholder="DELETE"
                className="w-full px-3 py-2.5 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-sm text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-red-500/30 focus:border-red-400 transition-colors"
                autoFocus
              />
            </div>

            <div className="flex justify-end gap-3">
              <button
                type="button"
                onClick={() => setShowDeleteModal(false)}
                className="px-4 py-2 rounded-lg border border-gray-200 dark:border-gray-700 text-gray-700 dark:text-gray-300 text-sm font-medium hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleDeleteAccount}
                disabled={deleteConfirm !== 'DELETE' || deleting}
                className="flex items-center gap-2 px-4 py-2 rounded-lg bg-red-600 text-white text-sm font-medium hover:bg-red-700 disabled:opacity-50 transition-colors"
              >
                {deleting ? (
                  <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                ) : (
                  <Trash2 size={14} />
                )}
                {deleting ? 'Deleting…' : 'Delete my account'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
