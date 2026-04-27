'use client'

import { useEffect } from 'react'
import { CreditCard, ArrowRight } from 'lucide-react'

// Billing has moved to the Admin Portal.
// This page auto-redirects after a brief notice.
export default function BillingRedirectPage() {
  useEffect(() => {
    const adminHost =
      typeof window !== 'undefined'
        ? (process.env.NEXT_PUBLIC_TENANT_ADMIN_SUBDOMAIN || window.location.host.replace(/^agents\./, 'admin.'))
        : 'admin.lvh.me:3000'
    const timer = setTimeout(() => {
      window.location.href = `${window.location.protocol}//${adminHost}/billing`
    }, 2500)
    return () => clearTimeout(timer)
  }, [])

  const adminUrl =
    typeof window !== 'undefined'
      ? `${window.location.protocol}//${process.env.NEXT_PUBLIC_TENANT_ADMIN_SUBDOMAIN || window.location.host.replace(/^agents\./, 'admin.')}/billing`
      : `http://${process.env.NEXT_PUBLIC_TENANT_ADMIN_SUBDOMAIN || 'admin.lvh.me:3000'}/billing`

  return (
    <div className="p-8 flex items-center justify-center min-h-[60vh]">
      <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 p-8 max-w-md w-full text-center">
        <div className="w-14 h-14 rounded-xl bg-violet-100 dark:bg-violet-900/30 flex items-center justify-center mx-auto mb-4">
          <CreditCard size={28} className="text-violet-600 dark:text-violet-400" />
        </div>
        <h2 className="text-lg font-bold text-gray-900 dark:text-white mb-2">Billing has moved</h2>
        <p className="text-sm text-gray-500 dark:text-gray-400 mb-6">
          Billing is now managed centrally in the{' '}
          <span className="font-semibold text-violet-600 dark:text-violet-400">Admin Portal</span>.
          You'll be redirected automatically.
        </p>
        <a
          href={adminUrl}
          className="inline-flex items-center gap-2 px-5 py-2.5 bg-violet-600 hover:bg-violet-700 text-white text-sm font-medium rounded-lg transition-colors"
        >
          Go to Admin Portal <ArrowRight size={16} />
        </a>
        <p className="mt-4 text-xs text-gray-400">Redirecting in 2.5 seconds…</p>
      </div>
    </div>
  )
}
