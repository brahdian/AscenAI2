'use client'

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useForm } from 'react-hook-form'
import { tenantApi } from '@/lib/api'
import toast from 'react-hot-toast'
import { useEffect } from 'react'

export default function SettingsPage() {
  const qc = useQueryClient()
  const { data: tenant, isLoading } = useQuery({
    queryKey: ['tenant'],
    queryFn: tenantApi.getMe,
  })

  const { register, handleSubmit, reset } = useForm({
    defaultValues: {
      name: '',
      business_name: '',
      phone: '',
      timezone: 'UTC',
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

  const mutation = useMutation({
    mutationFn: (data: Record<string, unknown>) => tenantApi.updateMe(data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['tenant'] })
      toast.success('Settings saved')
    },
    onError: () => toast.error('Failed to save settings'),
  })

  if (isLoading) return <div className="p-8 animate-pulse">Loading…</div>

  return (
    <div className="p-8 max-w-2xl">
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
            <p className="text-xl font-bold text-violet-700 dark:text-violet-300 capitalize">
              {tenant?.plan}
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
    </div>
  )
}
