'use client'

import { useEffect } from 'react'
import { useRouter } from 'next/navigation'

export default function PaymentSuccessPage() {
  const router = useRouter()

  useEffect(() => {
    const timer = setTimeout(() => {
      router.push('/login')
    }, 3000)

    return () => clearTimeout(timer)
  }, [router])

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-[#0f0728] via-[#1a1040] to-[#0c1e4a] px-4 py-12">
      <div className="w-full max-w-md">
        <div className="bg-white/[0.03] border border-white/10 rounded-2xl p-8 backdrop-blur-sm text-center">
          <div className="w-16 h-16 rounded-full bg-green-500/20 flex items-center justify-center mx-auto mb-6">
            <svg className="w-8 h-8 text-green-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
            </svg>
          </div>

          <h1 className="text-2xl font-bold text-white mb-3">Payment successful!</h1>
          <p className="text-gray-400 mb-6">Your account is being activated. Redirecting to login...</p>

          <div className="flex justify-center">
            <div className="w-16 h-1 bg-white/10 rounded-full overflow-hidden">
              <div className="h-full bg-gradient-to-r from-violet-500 to-blue-500 animate-pulse rounded-full" />
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
