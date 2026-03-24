'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { agentsApi } from '@/lib/api'
import toast from 'react-hot-toast'
import Link from 'next/link'
import { ArrowLeft } from 'lucide-react'

const schema = z.object({
  name: z.string().min(1, 'Name required'),
  description: z.string().optional(),
  business_type: z.enum(['pizza_shop', 'clinic', 'salon', 'generic']),
  language: z.string().default('en'),
  voice_enabled: z.boolean().default(true),
  system_prompt: z.string().optional(),
  personality: z.string().optional(),
})

type FormData = z.infer<typeof schema>

export default function NewAgentPage() {
  const router = useRouter()
  const qc = useQueryClient()

  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<FormData>({
    resolver: zodResolver(schema),
    defaultValues: { business_type: 'generic', language: 'en', voice_enabled: true },
  })

  const mutation = useMutation({
    mutationFn: (data: FormData) => agentsApi.create(data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['agents'] })
      toast.success('Agent created!')
      router.push('/dashboard/agents')
    },
    onError: (err: any) =>
      toast.error(err?.response?.data?.detail || 'Failed to create agent'),
  })

  return (
    <div className="p-8 max-w-2xl">
      <Link
        href="/dashboard/agents"
        className="inline-flex items-center gap-2 text-sm text-gray-500 hover:text-gray-900 dark:hover:text-white mb-6 transition-colors"
      >
        <ArrowLeft size={16} /> Back to agents
      </Link>

      <h1 className="text-2xl font-bold text-gray-900 dark:text-white mb-6">
        Create new agent
      </h1>

      <form
        onSubmit={handleSubmit((d) => mutation.mutate(d))}
        className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 p-6 space-y-5"
      >
        <div>
          <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1.5">
            Agent name *
          </label>
          <input
            {...register('name')}
            placeholder="e.g. Pizza Ordering Bot"
            className="w-full px-3 py-2.5 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm focus:outline-none focus:ring-1 focus:ring-violet-500"
          />
          {errors.name && <p className="text-red-500 text-xs mt-1">{errors.name.message}</p>}
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1.5">
            Description
          </label>
          <input
            {...register('description')}
            placeholder="Optional description"
            className="w-full px-3 py-2.5 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm focus:outline-none focus:ring-1 focus:ring-violet-500"
          />
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1.5">
              Business type
            </label>
            <select
              {...register('business_type')}
              className="w-full px-3 py-2.5 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm focus:outline-none focus:ring-1 focus:ring-violet-500"
            >
              <option value="generic">Generic</option>
              <option value="pizza_shop">Pizza / Restaurant</option>
              <option value="clinic">Medical Clinic</option>
              <option value="salon">Salon / Spa</option>
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1.5">
              Language
            </label>
            <select
              {...register('language')}
              className="w-full px-3 py-2.5 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm focus:outline-none focus:ring-1 focus:ring-violet-500"
            >
              <option value="en">English</option>
              <option value="es">Spanish</option>
              <option value="fr">French</option>
              <option value="de">German</option>
              <option value="pt">Portuguese</option>
            </select>
          </div>
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1.5">
            System prompt
          </label>
          <textarea
            {...register('system_prompt')}
            rows={4}
            placeholder="You are a helpful assistant for {business_name}. You help customers with orders and questions..."
            className="w-full px-3 py-2.5 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm focus:outline-none focus:ring-1 focus:ring-violet-500 resize-none"
          />
        </div>

        <div className="flex items-center gap-3">
          <input
            {...register('voice_enabled')}
            type="checkbox"
            id="voice_enabled"
            className="w-4 h-4 accent-violet-600"
          />
          <label htmlFor="voice_enabled" className="text-sm text-gray-700 dark:text-gray-300">
            Enable voice (STT/TTS)
          </label>
        </div>

        <div className="flex gap-3 pt-2">
          <button
            type="submit"
            disabled={mutation.isPending}
            className="px-5 py-2.5 rounded-lg bg-gradient-to-r from-violet-600 to-blue-600 text-white text-sm font-medium hover:opacity-90 disabled:opacity-50 transition-opacity"
          >
            {mutation.isPending ? 'Creating…' : 'Create agent'}
          </button>
          <Link
            href="/dashboard/agents"
            className="px-5 py-2.5 rounded-lg border border-gray-200 dark:border-gray-700 text-sm text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors"
          >
            Cancel
          </Link>
        </div>
      </form>
    </div>
  )
}
