'use client'

import { useState, Suspense } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import Link from 'next/link'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import toast from 'react-hot-toast'
import { authApi } from '@/lib/api'

const schema = z.object({
  new_password: z.string().min(8, 'Password must be at least 8 characters'),
  confirm_password: z.string(),
}).refine((data) => data.new_password === data.confirm_password, {
  message: "Passwords don't match",
  path: ['confirm_password'],
})

type FormData = z.infer<typeof schema>

function ResetPasswordForm() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const token = searchParams.get('token')
  const [loading, setLoading] = useState(false)

  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<FormData>({ resolver: zodResolver(schema) })

  const onSubmit = async (data: FormData) => {
    if (!token) {
      toast.error('Invalid reset token')
      return
    }
    setLoading(true)
    try {
      await authApi.resetPassword({ token, new_password: data.new_password })
      toast.success('Password reset successfully')
      router.push('/login')
    } catch (err: any) {
      const detail = err?.response?.data?.detail
      toast.error(detail || 'Failed to reset password')
    } finally {
      setLoading(false)
    }
  }

  if (!token) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-[#0f0728] via-[#1a1040] to-[#0c1e4a] px-4">
        <div className="w-full max-w-md text-center">
          <div className="bg-white/[0.03] border border-white/10 rounded-2xl p-8 backdrop-blur-sm">
            <h2 className="text-xl font-bold text-white mb-2">Invalid Link</h2>
            <p className="text-gray-400 text-sm mb-6">
              This password reset link is invalid or has expired.
            </p>
            <Link href="/forgot-password" className="text-violet-400 hover:text-violet-300 text-sm">
              Request a new reset link
            </Link>
          </div>
        </div>
      </div>
    )
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
          <p className="text-gray-400 mt-3">Create a new password</p>
        </div>

        <div className="bg-white/[0.03] border border-white/10 rounded-2xl p-8 backdrop-blur-sm">
          <form onSubmit={handleSubmit(onSubmit)} className="space-y-5">
            <div>
              <label className="block text-sm text-gray-300 mb-1.5">New Password</label>
              <input
                {...register('new_password')}
                type="password"
                placeholder="••••••••"
                className="w-full px-4 py-3 rounded-lg bg-white/5 border border-white/10 text-white placeholder-gray-500 focus:outline-none focus:border-violet-500 focus:ring-1 focus:ring-violet-500 transition-colors"
              />
              {errors.new_password && (
                <p className="text-red-400 text-xs mt-1">{errors.new_password.message}</p>
              )}
            </div>

            <div>
              <label className="block text-sm text-gray-300 mb-1.5">Confirm Password</label>
              <input
                {...register('confirm_password')}
                type="password"
                placeholder="••••••••"
                className="w-full px-4 py-3 rounded-lg bg-white/5 border border-white/10 text-white placeholder-gray-500 focus:outline-none focus:border-violet-500 focus:ring-1 focus:ring-violet-500 transition-colors"
              />
              {errors.confirm_password && (
                <p className="text-red-400 text-xs mt-1">{errors.confirm_password.message}</p>
              )}
            </div>

            <button
              type="submit"
              disabled={loading}
              className="w-full py-3 rounded-lg bg-gradient-to-r from-violet-600 to-blue-600 text-white font-semibold hover:opacity-90 transition-opacity disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {loading ? 'Resetting...' : 'Reset password'}
            </button>
          </form>

          <p className="text-center text-gray-400 text-sm mt-6">
            Remember your password?{' '}
            <Link href="/login" className="text-violet-400 hover:text-violet-300 transition-colors">
              Sign in
            </Link>
          </p>
        </div>
      </div>
    </div>
  )
}

export default function ResetPasswordPage() {
  return (
    <Suspense fallback={
      <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-[#0f0728] via-[#1a1040] to-[#0c1e4a] px-4">
        <div className="text-white">Loading...</div>
      </div>
    }>
      <ResetPasswordForm />
    </Suspense>
  )
}
