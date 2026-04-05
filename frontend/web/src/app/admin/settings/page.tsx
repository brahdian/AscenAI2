'use client'

import { useEffect, useState } from 'react'
import { platformSettingsApi } from '@/lib/api'
import { Save, RefreshCw, AlertCircle, CheckCircle2, Globe, MessageSquare, Terminal } from 'lucide-react'

interface Setting {
  key: string
  value: any
  description: string
  updated_at: string
}

export default function PlatformSettingsPage() {
  const [settings, setSettings] = useState<Setting[]>([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState<string | null>(null)

  useEffect(() => {
    fetchSettings()
  }, [])

  const fetchSettings = async () => {
    try {
      setLoading(true)
      const data = await platformSettingsApi.list()
      setSettings(data)
    } catch (err) {
      setError('Failed to load platform settings.')
    } finally {
      setLoading(false)
    }
  }

  const handleUpdate = async (key: string, newValue: any) => {
    try {
      setSaving(key)
      setError(null)
      await platformSettingsApi.update(key, newValue)
      setSuccess(`Updated ${key} successfully`)
      setTimeout(() => setSuccess(null), 3000)
    } catch (err) {
      setError(`Failed to update ${key}`)
    } finally {
      setSaving(null)
    }
  }

  if (loading) {
    return (
      <div className="p-8 flex items-center justify-center">
        <RefreshCw className="w-6 h-6 animate-spin text-violet-600" />
      </div>
    )
  }

  return (
    <div className="p-8 max-w-5xl mx-auto">
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Platform Settings</h1>
          <p className="text-gray-500 dark:text-gray-400">Manage platform configuration and preferences.</p>
        </div>
      </div>

      {error && (
        <div className="mb-6 p-4 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-xl flex items-center gap-3 text-red-700 dark:text-red-400">
          <AlertCircle size={18} />
          <p className="text-sm">{error}</p>
        </div>
      )}

      {success && (
        <div className="mb-6 p-4 bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800 rounded-xl flex items-center gap-3 text-green-700 dark:text-green-400">
          <CheckCircle2 size={18} />
          <p className="text-sm">{success}</p>
        </div>
      )}

      <div className="space-y-6">
        {settings
          .filter((setting) => {
            const key = setting.key.toLowerCase()
            return !key.includes('voice') && !key.includes('messaging') && !key.includes('sms') && !key.includes('call') && !key.includes('tts') && !key.includes('stt') && !key.includes('speech') && !key.includes('whisper') && !key.includes('elevenlabs') && !key.includes('twilio')
          })
          .map((setting) => (
          <div key={setting.key} className="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-2xl overflow-hidden shadow-sm">
            <div className="px-6 py-4 border-b border-gray-100 dark:border-gray-800 flex items-center justify-between bg-gray-50/50 dark:bg-gray-800/50">
              <div className="flex items-center gap-3">
                <div className="w-8 h-8 rounded-lg bg-violet-100 dark:bg-violet-900/30 flex items-center justify-center text-violet-600">
                  {setting.key.includes('greeting') ? <Globe size={18} /> : 
                   setting.key.includes('protocol') ? <Terminal size={18} /> : 
                   <MessageSquare size={18} />}
                </div>
                <div>
                  <h3 className="font-semibold text-gray-900 dark:text-white">{setting.key}</h3>
                  <p className="text-xs text-gray-500">{setting.description}</p>
                </div>
              </div>
              <button
                onClick={() => handleUpdate(setting.key, setting.value)}
                disabled={saving === setting.key}
                className="flex items-center gap-2 px-4 py-2 bg-violet-600 hover:bg-violet-700 disabled:opacity-50 text-white rounded-lg text-sm font-medium transition-all shadow-sm shadow-violet-200 dark:shadow-none"
              >
                {saving === setting.key ? <RefreshCw size={16} className="animate-spin" /> : <Save size={16} />}
                Save Changes
              </button>
            </div>
            <div className="p-6">
              {typeof setting.value === 'object' ? (
                <div className="space-y-4">
                  {Object.entries(setting.value).map(([lang, phrase]: [string, any]) => (
                    <div key={lang} className="flex flex-col gap-1.5">
                      <label className="text-xs font-medium text-gray-400 uppercase tracking-wider">{lang}</label>
                      <textarea
                        className="w-full p-3 bg-gray-50 dark:bg-gray-950 border border-gray-200 dark:border-gray-800 rounded-xl text-sm focus:ring-2 focus:ring-violet-500 transition-all outline-none"
                        rows={setting.key.includes('template') ? 10 : 2}
                        defaultValue={typeof phrase === 'string' ? phrase : JSON.stringify(phrase)}
                        onChange={(e) => {
                          const val = e.target.value
                          const newSettings = [...settings]
                          const target = newSettings.find(s => s.key === setting.key)
                          if (target) {
                            target.value = { ...target.value, [lang]: val }
                            setSettings(newSettings)
                          }
                        }}
                      />
                    </div>
                  ))}
                </div>
              ) : (
                <textarea
                  className="w-full p-4 bg-gray-50 dark:bg-gray-950 border border-gray-200 dark:border-gray-800 rounded-xl text-sm font-mono focus:ring-2 focus:ring-violet-500 transition-all outline-none"
                  rows={10}
                  value={setting.value}
                  onChange={(e) => {
                    const newSettings = [...settings]
                    const target = newSettings.find(s => s.key === setting.key)
                    if (target) {
                      target.value = e.target.value
                      setSettings(newSettings)
                    }
                  }}
                />
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
