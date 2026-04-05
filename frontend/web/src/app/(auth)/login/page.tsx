'use client'

import { useState, Suspense } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import Link from 'next/link'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import toast from 'react-hot-toast'
import { authApi } from '@/lib/api'
import { useAuthStore } from '@/store/auth'

const schema = z.object({
  email: z.string().email('Invalid email'),
  password: z.string().min(1, 'Password required'),
})

type FormData = z.infer<typeof schema>

function LoginForm() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const redirect = searchParams.get('redirect')
  const { setUser } = useAuthStore()
  const [loading, setLoading] = useState(false)

  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<FormData>({ resolver: zodResolver(schema) })

  const onSubmit = async (data: FormData) => {
    setLoading(true)
    try {
      const res = await authApi.login(data)
      console.log('[LOGIN] Response:', {
        hasUser: !!res.user,
        hasToken: !!res.access_token,
        tenantId: res.tenant_id,
        tokenLength: res.access_token?.length,
      })
      
      // Clear old cached session store to avoid hydration mismatches
      localStorage.removeItem('ascenai-auth')
      setUser(res.user, res.tenant_id)
      
      console.log('[LOGIN] Successful login, HttpOnly cookies set.')
      
      toast.success('Welcome back!')
      
      const hostname = typeof window !== 'undefined' ? window.location.hostname : ''
      const isAdminPortal = hostname === (process.env.NEXT_PUBLIC_ADMIN_SUBDOMAIN?.split(':')[0] || 'admin.lvh.me')
      
      if (redirect) {
        router.push(redirect)
      } else if (isAdminPortal) {
        router.push('/settings')
      } else {
        router.push('/dashboard')
      }
    } catch (err: any) {
      console.error('[LOGIN] Error:', {
        status: err?.response?.status,
        detail: err?.response?.data?.detail,
        action: err?.response?.headers?.['x-action'],
        message: err?.message,
      })
      const detail = err?.response?.data?.detail
      const action = err?.response?.headers?.['x-action']
      
      if (action === 'verify_email' || detail?.includes('verify') || detail?.includes('Email not verified')) {
        toast.error('Please verify your email first. Check your inbox for the verification code.')
        router.push('/verify-email')
      } else if (detail?.includes('inactive') || detail?.includes('Subscription required')) {
        toast.error('Account is not active. Please complete payment to activate your account.')
        router.push('/pricing')
      } else {
        toast.error(detail || 'Login failed')
      }
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-[#0f0728] via-[#1a1040] to-[#0c1e4a] px-4">
      <div className="w-full max-w-md">
        <div className="text-center mb-8">
          <Link href="/" className="inline-flex items-center gap-2">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-violet-500 to-blue-500 flex items-center justify-center text-white font-bold">
              A
            </div>
            <span className="text-2xl font-bold text-white">AscenAI</span>
          </Link>
          <p className="text-gray-400 mt-3">Sign in to your account</p>
        </div>

        <div className="bg-white/[0.03] border border-white/10 rounded-2xl p-8 backdrop-blur-sm">
          <form onSubmit={handleSubmit(onSubmit)} className="space-y-5">
            <div>
              <label className="block text-sm text-gray-300 mb-1.5">Email</label>
              <input
                {...register('email')}
                type="email"
                placeholder="you@business.com"
                className="w-full px-4 py-3 rounded-lg bg-white/5 border border-white/10 text-white placeholder-gray-500 focus:outline-none focus:border-violet-500 focus:ring-1 focus:ring-violet-500 transition-colors"
              />
              {errors.email && (
                <p className="text-red-400 text-xs mt-1">{errors.email.message}</p>
              )}
            </div>

            <div>
              <label className="block text-sm text-gray-300 mb-1.5">Password</label>
              <input
                {...register('password')}
                type="password"
                placeholder="••••••••"
                className="w-full px-4 py-3 rounded-lg bg-white/5 border border-white/10 text-white placeholder-gray-500 focus:outline-none focus:border-violet-500 focus:ring-1 focus:ring-violet-500 transition-colors"
              />
              {errors.password && (
                <p className="text-red-400 text-xs mt-1">{errors.password.message}</p>
              )}
            </div>

            <button
              type="submit"
              disabled={loading}
              className="w-full py-3 rounded-lg bg-gradient-to-r from-violet-600 to-blue-600 text-white font-semibold hover:opacity-90 transition-opacity disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {loading ? 'Signing in…' : 'Sign in'}
            </button>
          </form>

          <div className="text-center mt-4">
            <Link href="/forgot-password" className="text-sm text-gray-400 hover:text-violet-400 transition-colors">
              Forgot password?
            </Link>
          </div>

          <p className="text-center text-gray-400 text-sm mt-6">
            No account?{' '}
            <Link href="/register" className="text-violet-400 hover:text-violet-300 transition-colors">
              Sign up
            </Link>
          </p>
        </div>
      </div>
    </div>
  )
}

export default function LoginPage() {
  return (
    <Suspense fallback={
      <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-[#0f0728] via-[#1a1040] to-[#0c1e4a] px-4">
        <div className="text-white">Loading...</div>
      </div>
    }>
      <LoginForm />
    </Suspense>
  )
}
