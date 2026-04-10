'use client'

import { useState } from 'react'
import Link from 'next/link'
import toast from 'react-hot-toast'
import { authApi } from '@/lib/api'

export default function PaymentCancelPage() {
  const [retrying, setRetrying] = useState(false)
  const email = typeof window !== 'undefined' ? sessionStorage.getItem('pending_payment_email') : null
  const plan = typeof window !== 'undefined' ? sessionStorage.getItem('pending_payment_plan') : null

  const handleRetry = async () => {
    if (!email || !plan) {
      toast.error('Payment session expired. Please register again.')
      return
    }

    setRetrying(true)
    try {
      const subscribeRes = await authApi.subscribe({ email, plan })
      if (subscribeRes.payment_url) {
        window.location.href = subscribeRes.payment_url
      }
    } catch (err: any) {
      toast.error(err?.response?.data?.detail || 'Failed to retry payment')
    } finally {
      setRetrying(false)
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
        </div>

        <div className="bg-white/[0.03] border border-white/10 rounded-2xl p-8 backdrop-blur-sm text-center">
          <div className="w-16 h-16 rounded-full bg-yellow-500/20 flex items-center justify-center mx-auto mb-6">
            <svg className="w-8 h-8 text-yellow-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </div>

          <h1 className="text-2xl font-bold text-white mb-3">Payment cancelled</h1>
          <p className="text-gray-400 mb-8">Your account is still pending. Complete your payment to activate all features.</p>

          <div className="space-y-3">
            <button
              onClick={handleRetry}
              disabled={retrying}
              className="w-full py-3 rounded-lg bg-gradient-to-r from-violet-600 to-blue-600 text-white font-semibold hover:opacity-90 transition-opacity disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {retrying ? 'Redirecting...' : 'Retry payment'}
            </button>

            <Link
              href="/login"
              className="block w-full py-3 rounded-lg border border-white/10 text-gray-400 hover:text-white hover:border-white/20 transition-colors text-sm"
            >
              Back to login
            </Link>
          </div>
        </div>
      </div>
    </div>
  )
}
