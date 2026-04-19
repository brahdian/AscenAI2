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
  full_name: z.string().min(1, 'Full name required'),
  password: z.string().min(8, 'Password must be at least 8 characters'),
  confirm_password: z.string().min(8, 'Please confirm your password'),
}).refine((data) => data.password === data.confirm_password, {
  message: "Passwords don't match",
  path: ["confirm_password"],
})

type FormData = z.infer<typeof schema>

function AcceptInviteForm() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const token = searchParams.get('token')
  const { setUser } = useAuthStore()
  const [loading, setLoading] = useState(false)

  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<FormData>({ resolver: zodResolver(schema) })

  const onSubmit = async (data: FormData) => {
    if (!token) {
      toast.error('Invalid invitation link')
      return
    }
    setLoading(true)
    try {
      const res = await authApi.acceptInvite({
        token,
        full_name: data.full_name,
        password: data.password,
      })
      
      setUser(res.user, res.tenant_id)
      toast.success('Welcome to the team!')
      router.push('/dashboard')
    } catch (err: any) {
      toast.error(err?.response?.data?.detail || 'Failed to accept invitation')
    } finally {
      setLoading(false)
    }
  }

  if (!token) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-[#0f0728] via-[#1a1040] to-[#0c1e4a] px-4">
        <div className="bg-white/5 border border-white/10 p-8 rounded-2xl text-center max-w-sm">
          <h2 className="text-xl font-bold text-white mb-4">Invalid Link</h2>
          <p className="text-gray-400 mb-6">This invitation link is invalid or has expired.</p>
          <Link href="/login" className="text-violet-400 hover:underline">Back to Login</Link>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-[#0f0728] via-[#1a1040] to-[#0c1e4a] px-4">
      <div className="w-full max-w-md">
        <div className="text-center mb-8">
          <div className="inline-flex items-center gap-2 mb-4">
            <div className="w-12 h-12 rounded-2xl bg-gradient-to-br from-violet-500 to-blue-500 flex items-center justify-center text-white text-xl font-bold shadow-lg shadow-violet-500/20">
              A
            </div>
            <span className="text-2xl font-bold text-white">AscenAI</span>
          </div>
          <h1 className="text-3xl font-bold text-white">Join the Team</h1>
          <p className="text-gray-400 mt-3">Finish setting up your account to get started.</p>
        </div>

        <div className="bg-white/[0.03] border border-white/10 rounded-3xl p-8 backdrop-blur-md shadow-2xl">
          <form onSubmit={handleSubmit(onSubmit)} className="space-y-5">
            <div>
              <label className="block text-sm font-medium text-gray-300 mb-1.5">Full Name</label>
              <input
                {...register('full_name')}
                type="text"
                placeholder="Jane Smith"
                className="w-full px-4 py-3 rounded-xl bg-white/5 border border-white/10 text-white placeholder-gray-500 focus:outline-none focus:border-violet-500 focus:ring-2 focus:ring-violet-500/20 transition-all"
              />
              {errors.full_name && (
                <p className="text-red-400 text-xs mt-1">{errors.full_name.message}</p>
              )}
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-300 mb-1.5">Create Password</label>
              <input
                {...register('password')}
                type="password"
                placeholder="••••••••"
                className="w-full px-4 py-3 rounded-xl bg-white/5 border border-white/10 text-white placeholder-gray-500 focus:outline-none focus:border-violet-500 focus:ring-2 focus:ring-violet-500/20 transition-all"
              />
              {errors.password && (
                <p className="text-red-400 text-xs mt-1">{errors.password.message}</p>
              )}
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-300 mb-1.5">Confirm Password</label>
              <input
                {...register('confirm_password')}
                type="password"
                placeholder="••••••••"
                className="w-full px-4 py-3 rounded-xl bg-white/5 border border-white/10 text-white placeholder-gray-500 focus:outline-none focus:border-violet-500 focus:ring-2 focus:ring-violet-500/20 transition-all"
              />
              {errors.confirm_password && (
                <p className="text-red-400 text-xs mt-1">{errors.confirm_password.message}</p>
              )}
            </div>

            <button
              type="submit"
              disabled={loading}
              className="w-full py-3.5 rounded-xl bg-gradient-to-r from-violet-600 to-indigo-600 text-white font-bold hover:from-violet-500 hover:to-indigo-500 transition-all disabled:opacity-50 disabled:cursor-not-allowed shadow-lg shadow-violet-600/20 mt-4"
            >
              {loading ? 'Joining Team…' : 'Accept Invitation & Join'}
            </button>
          </form>

          <p className="text-center text-gray-500 text-xs mt-8">
            By joining, you agree to our Terms of Service and Privacy Policy.
          </p>
        </div>
      </div>
    </div>
  )
}

export default function AcceptInvitePage() {
  return (
    <Suspense fallback={
      <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-[#0f0728] via-[#1a1040] to-[#0c1e4a]">
        <div className="text-white">Loading invitation details...</div>
      </div>
    }>
      <AcceptInviteForm />
    </Suspense>
  )
}
