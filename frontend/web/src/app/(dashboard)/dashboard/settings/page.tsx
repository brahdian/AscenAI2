'use client'

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useForm } from 'react-hook-form'
import { tenantApi, complianceApi } from '@/lib/api'
import { getPlanDisplayName } from '@/lib/plans'
import toast from 'react-hot-toast'
import { useEffect, useState } from 'react'
import { Shield, Trash2, Phone, ExternalLink, Copy, CheckCircle } from 'lucide-react'

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

  const { register, handleSubmit, reset } = useForm({
    defaultValues: {
      name: '',
      business_name: '',
      phone: '',
      timezone: 'UTC',
    },
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
    if (tenant) {
      reset({
        name: tenant.name,
        business_name: tenant.business_name,
        phone: tenant.phone || '',
        timezone: tenant.timezone || 'UTC',
      })
    }
  }, [tenant, reset])

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

  const mutation = useMutation({
    mutationFn: (data: Record<string, unknown>) => tenantApi.updateMe(data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['tenant'] })
      toast.success('Settings saved')
    },
    onError: () => toast.error('Failed to save settings'),
  })

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

      {/* Plan info */}
      <div className="bg-gradient-to-r from-violet-50 to-blue-50 dark:from-violet-900/20 dark:to-blue-900/20 rounded-xl border border-violet-100 dark:border-violet-800 p-5 mb-6">
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
      </div>

      {/* Business details */}
      <form
        onSubmit={handleSubmit((d) => mutation.mutate(d as Record<string, unknown>))}
        className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 p-6 space-y-4"
      >
        <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-300 border-b border-gray-100 dark:border-gray-800 pb-3">
          Business information
        </h2>

        {[
          { name: 'name', label: 'Account name' },
          { name: 'business_name', label: 'Business name' },
          { name: 'phone', label: 'Phone number' },
        ].map((f) => (
          <div key={f.name}>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1.5">
              {f.label}
            </label>
            <input
              {...register(f.name as 'name' | 'business_name' | 'phone')}
              className="w-full px-3 py-2.5 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm focus:outline-none focus:ring-1 focus:ring-violet-500"
            />
          </div>
        ))}

        <div>
          <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1.5">
            Timezone
          </label>
          <select
            {...register('timezone')}
            className="w-full px-3 py-2.5 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm focus:outline-none focus:ring-1 focus:ring-violet-500"
          >
            {['UTC', 'America/New_York', 'America/Chicago', 'America/Los_Angeles', 'Europe/London', 'Europe/Paris'].map((tz) => (
              <option key={tz} value={tz}>{tz}</option>
            ))}
          </select>
        </div>

        <button
          type="submit"
          disabled={mutation.isPending}
          className="px-5 py-2.5 rounded-lg bg-violet-600 text-white text-sm font-medium hover:bg-violet-700 disabled:opacity-50 transition-colors"
        >
          {mutation.isPending ? 'Saving…' : 'Save changes'}
        </button>
      </form>

      {/* PIPEDA / Privacy Compliance */}
      <div className="mt-8">
        <div className="flex items-center gap-2 mb-4">
          <Shield size={18} className="text-violet-500" />
          <h2 className="text-base font-semibold text-gray-900 dark:text-white">Privacy & Compliance (PIPEDA)</h2>
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

      {/* Voice Channels - Twilio Setup Guide */}
      <div className="mt-8">
        <div className="flex items-center gap-2 mb-4">
          <Phone size={18} className="text-blue-500" />
          <h2 className="text-base font-semibold text-gray-900 dark:text-white">Voice Channels (Twilio)</h2>
        </div>
        <p className="text-sm text-gray-500 mb-4">
          Set up Twilio to enable voice capabilities for your AI agents. This allows customers to call and speak with your AI agents directly.
        </p>

        <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 p-6 mb-6">
          <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-4 border-b border-gray-100 dark:border-gray-800 pb-2">
            What is Twilio and why do I need it?
          </h3>
          <p className="text-sm text-gray-600 dark:text-gray-400 mb-3">
            Twilio is a cloud communications platform that provides phone numbers and voice call capabilities. 
            AscenAI uses Twilio to connect incoming phone calls to your AI agents.
          </p>
          <p className="text-sm text-gray-600 dark:text-gray-400">
            <strong>You need your own Twilio account</strong> because:
          </p>
          <ul className="list-disc list-inside text-sm text-gray-600 dark:text-gray-400 mt-2 space-y-1">
            <li>Twilio charges per-minute fees for voice calls</li>
            <li>Phone numbers have monthly costs (typically ~$1-15/month depending on type)</li>
            <li>You maintain control over your Twilio billing and usage</li>
          </ul>
        </div>

        <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 p-6 mb-6">
          <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-4 border-b border-gray-100 dark:border-gray-800 pb-2">
            Step-by-Step Setup Guide
          </h3>

          <div className="space-y-6">
            <div>
              <div className="flex items-center gap-2 mb-2">
                <span className="flex items-center justify-center w-6 h-6 rounded-full bg-blue-600 text-white text-xs font-bold">1</span>
                <h4 className="text-sm font-medium text-gray-900 dark:text-white">Create a Twilio Account</h4>
              </div>
              <p className="text-sm text-gray-600 dark:text-gray-400 ml-8">
                Go to <a href="https://www.twilio.com" target="_blank" rel="noopener noreferrer" className="text-blue-600 hover:underline inline-flex items-center gap-1">
                  twilio.com <ExternalLink size={12} />
                </a> and sign up for a free trial account. You'll need to verify your email and phone number.
              </p>
            </div>

            <div>
              <div className="flex items-center gap-2 mb-2">
                <span className="flex items-center justify-center w-6 h-6 rounded-full bg-blue-600 text-white text-xs font-bold">2</span>
                <h4 className="text-sm font-medium text-gray-900 dark:text-white">Get Your Account SID and Auth Token</h4>
              </div>
              <p className="text-sm text-gray-600 dark:text-gray-400 ml-8 mb-2">
                After logging in to the Twilio Console, find your Account SID (starts with <code className="bg-gray-100 dark:bg-gray-800 px-1 rounded">AC</code>) 
                and Auth Token. These credentials are needed to connect AscenAI to your Twilio account.
              </p>
              <div className="ml-8 p-3 bg-blue-50 dark:bg-blue-900/20 rounded-lg">
                <p className="text-xs text-blue-700 dark:text-blue-300">
                  <strong>Important:</strong> Keep your Auth Token secure! Never share it publicly. You'll need both the Account SID and Auth Token to configure voice in AscenAI.
                </p>
              </div>
            </div>

            <div>
              <div className="flex items-center gap-2 mb-2">
                <span className="flex items-center justify-center w-6 h-6 rounded-full bg-blue-600 text-white text-xs font-bold">3</span>
                <h4 className="text-sm font-medium text-gray-900 dark:text-white">Buy a Phone Number</h4>
              </div>
              <p className="text-sm text-gray-600 dark:text-gray-400 ml-8">
                In the Twilio Console, go to Phone Numbers → Buy a Number. Search for a number in your desired area code/region. 
                Voice-enabled numbers typically cost $1-15/month. Click "Buy" to purchase.
              </p>
            </div>

            <div>
              <div className="flex items-center gap-2 mb-2">
                <span className="flex items-center justify-center w-6 h-6 rounded-full bg-blue-600 text-white text-xs font-bold">4</span>
                <h4 className="text-sm font-medium text-gray-900 dark:text-white">Configure in AscenAI</h4>
              </div>
              <p className="text-sm text-gray-600 dark:text-gray-400 ml-8">
                Add your Twilio credentials (Account SID, Auth Token, and Phone Number) in the Channels or Voice settings section. 
                Once configured, incoming calls to your Twilio number will be routed to your AI agents.
              </p>
            </div>
          </div>
        </div>

        <div className="bg-yellow-50 dark:bg-yellow-900/20 rounded-xl border border-yellow-200 dark:border-yellow-800 p-4">
          <div className="flex items-start gap-3">
            <CheckCircle className="w-5 h-5 text-yellow-600 dark:text-yellow-500 mt-0.5 flex-shrink-0" />
            <div>
              <p className="text-sm font-medium text-yellow-800 dark:text-yellow-300">Voice Support Add-on Available</p>
              <p className="text-sm text-yellow-700 dark:text-yellow-400 mt-1">
                For $15/month, AscenAI provides technical support and configuration assistance for your voice channel setup. 
                This includes help with Twilio configuration, troubleshooting, and optimizing voice agent flows. 
                Enable the add-on in the <a href="/billing" className="underline font-medium">Billing page</a>.
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
