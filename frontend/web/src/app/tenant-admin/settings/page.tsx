'use client'

import { useEffect, useState } from 'react'
import { Settings, Save } from 'lucide-react'
import toast from 'react-hot-toast'

interface OrgSettings {
  id: string
  name: string
  business_name: string
  business_type: string
  email: string
  phone: string
  timezone: string
  slug: string
}

export default function OrgSettingsPage() {
  const [settings, setSettings] = useState<Partial<OrgSettings>>({})
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    fetch('/api/v1/tenant-admin/settings', { credentials: 'include' })
      .then((r) => (r.ok ? r.json() : {}))
      .then(setSettings)
      .finally(() => setLoading(false))
  }, [])

  const handleSave = async () => {
    setSaving(true)
    try {
      const res = await fetch('/api/v1/tenant-admin/settings', {
        method: 'PATCH',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          business_name: settings.business_name,
          business_type: settings.business_type,
          phone: settings.phone,
          timezone: settings.timezone,
        }),
      })
      if (!res.ok) throw new Error()
      toast.success('Settings saved')
    } catch {
      toast.error('Failed to save settings')
    } finally {
      setSaving(false)
    }
  }

  const field = (label: string, key: keyof OrgSettings, type = 'text', readOnly = false) => (
    <div>
      <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1.5">{label}</label>
      <input
        type={type}
        value={(settings[key] as string) || ''}
        readOnly={readOnly}
        onChange={(e) => !readOnly && setSettings((s) => ({ ...s, [key]: e.target.value }))}
        className={`w-full px-3 py-2 text-sm border border-gray-200 dark:border-gray-700 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-violet-500 ${readOnly ? 'opacity-60 cursor-not-allowed' : ''}`}
      />
    </div>
  )

  return (
    <div className="p-8 max-w-2xl">
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-gray-900 dark:text-white flex items-center gap-2">
          <Settings size={24} className="text-violet-500" />
          Organization Settings
        </h1>
        <p className="text-gray-500 dark:text-gray-400 mt-1">Manage your organization profile and preferences.</p>
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-20">
          <div className="animate-spin rounded-full h-8 w-8 border-t-2 border-b-2 border-violet-500" />
        </div>
      ) : (
        <div className="space-y-6">
          <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 p-6 space-y-5">
            <p className="text-xs font-semibold text-gray-400 uppercase tracking-wider">Business Info</p>
            {field('Organization slug', 'slug', 'text', true)}
            {field('Business name', 'business_name')}
            {field('Business type', 'business_type')}
            {field('Contact email', 'email', 'email', true)}
            {field('Phone', 'phone', 'tel')}
            {field('Timezone', 'timezone')}
          </div>

          <button
            onClick={handleSave}
            disabled={saving}
            className="flex items-center gap-2 px-5 py-2.5 bg-violet-600 hover:bg-violet-700 disabled:opacity-50 text-white text-sm font-medium rounded-lg transition-colors"
          >
            <Save size={16} />
            {saving ? 'Saving…' : 'Save changes'}
          </button>
        </div>
      )}
    </div>
  )
}
