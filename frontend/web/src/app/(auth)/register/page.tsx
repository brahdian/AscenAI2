'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import Link from 'next/link'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import toast from 'react-hot-toast'
import { authApi } from '@/lib/api'
import { useAuthStore } from '@/store/auth'

const schema = z.object({
  full_name: z.string().min(1, 'Full name required'),
  email: z.string().email('Invalid email'),
  password: z.string().min(8, 'Minimum 8 characters'),
  business_name: z.string().min(1, 'Business name required'),
  business_type: z.enum(['pizza_shop', 'clinic', 'salon', 'other']),
})

type FormData = z.infer<typeof schema>

export default function RegisterPage() {
  const router = useRouter()
  const { setTokens, setUser } = useAuthStore()
  const [loading, setLoading] = useState(false)

  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<FormData>({
    resolver: zodResolver(schema),
    defaultValues: { business_type: 'other' },
  })

  const onSubmit = async (data: FormData) => {
    setLoading(true)
    try {
      const res = await authApi.register(data)
      setTokens(res.access_token, res.refresh_token)
      setUser(res.user, res.tenant_id)
      toast.success('Account created! Welcome to AscenAI.')
      router.push('/dashboard')
    } catch (err: any) {
      toast.error(err?.response?.data?.detail || 'Registration failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-[#0f0728] via-[#1a1040] to-[#0c1e4a] px-4 py-12">
      <div className="w-full max-w-md">
        <div className="text-center mb-8">
          <Link href="/" className="inline-flex items-center gap-2">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-violet-500 to-blue-500 flex items-center justify-center text-white font-bold">
              A
            </div>
            <span className="text-2xl font-bold text-white">AscenAI</span>
          </Link>
          <p className="text-gray-400 mt-3">Start your free 14-day trial</p>
        </div>

        <div className="bg-white/[0.03] border border-white/10 rounded-2xl p-8 backdrop-blur-sm">
          <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
            {[
              { name: 'full_name', label: 'Full name', type: 'text', placeholder: 'Alex Johnson' },
              { name: 'email', label: 'Work email', type: 'email', placeholder: 'alex@business.com' },
              { name: 'password', label: 'Password', type: 'password', placeholder: '8+ characters' },
              { name: 'business_name', label: 'Business name', type: 'text', placeholder: "Joe's Pizza" },
            ].map((f) => (
              <div key={f.name}>
                <label className="block text-sm text-gray-300 mb-1.5">{f.label}</label>
                <input
                  {...register(f.name as keyof FormData)}
                  type={f.type}
                  placeholder={f.placeholder}
                  className="w-full px-4 py-3 rounded-lg bg-white/5 border border-white/10 text-white placeholder-gray-500 focus:outline-none focus:border-violet-500 focus:ring-1 focus:ring-violet-500 transition-colors"
                />
                {errors[f.name as keyof FormData] && (
                  <p className="text-red-400 text-xs mt-1">
                    {errors[f.name as keyof FormData]?.message}
                  </p>
                )}
              </div>
            ))}

            <div>
              <label className="block text-sm text-gray-300 mb-1.5">Business type</label>
              <select
                {...register('business_type')}
                className="w-full px-4 py-3 rounded-lg bg-white/5 border border-white/10 text-white focus:outline-none focus:border-violet-500 focus:ring-1 focus:ring-violet-500 transition-colors"
              >
                <option value="other">Other</option>
                <option value="pizza_shop">Pizza / Restaurant</option>
                <option value="clinic">Medical Clinic</option>
                <option value="salon">Salon / Spa</option>
              </select>
            </div>

            <button
              type="submit"
              disabled={loading}
              className="w-full py-3 rounded-lg bg-gradient-to-r from-violet-600 to-blue-600 text-white font-semibold hover:opacity-90 transition-opacity disabled:opacity-50 disabled:cursor-not-allowed mt-2"
            >
              {loading ? 'Creating account…' : 'Create account — Free'}
            </button>
          </form>

          <p className="text-center text-gray-400 text-sm mt-6">
            Already have an account?{' '}
            <Link href="/login" className="text-violet-400 hover:text-violet-300 transition-colors">
              Sign in
            </Link>
          </p>
        </div>
      </div>
    </div>
  )
}
