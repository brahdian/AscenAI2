'use client'

import { useEffect, useState } from 'react'
import { billingApi } from '@/lib/api'
import { Download, AlertCircle, ArrowLeft, ExternalLink } from 'lucide-react'
import Link from 'next/link'
import toast from 'react-hot-toast'

interface Invoice {
  id: string
  amount_due: number
  amount_paid: number
  status: string
  created: number
  invoice_pdf: string
  hosted_invoice_url: string
}

const formatDate = (ts: number) =>
  new Date(ts * 1000).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })

export default function InvoicesPage() {
  const [invoices, setInvoices] = useState<Invoice[]>([])
  const [loading, setLoading] = useState(true)
  const [portalLoading, setPortalLoading] = useState(false)

  useEffect(() => {
    billingApi
      .getInvoices()
      .then((r) => setInvoices(r.invoices ?? []))
      .catch(() => toast.error('Failed to load invoices'))
      .finally(() => setLoading(false))
  }, [])

  const handlePortal = async () => {
    setPortalLoading(true)
    try {
      const { portal_url } = await billingApi.createPortalSession()
      window.open(portal_url, '_blank')
    } catch {
      toast.error('Failed to open billing portal')
    } finally {
      setPortalLoading(false)
    }
  }

  const statusColor: Record<string, string> = {
    paid: 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400',
    open: 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400',
    void: 'bg-gray-100 text-gray-500 dark:bg-gray-800 dark:text-gray-500',
    uncollectible: 'bg-red-100 text-red-600 dark:bg-red-900/30 dark:text-red-400',
  }

  return (
    <div className="p-8 max-w-3xl mx-auto">
      <Link
        href="/tenant-admin/billing"
        className="flex items-center gap-1.5 text-sm text-gray-500 hover:text-violet-600 dark:hover:text-violet-400 mb-6 transition-colors"
      >
        <ArrowLeft size={14} /> Back to Billing
      </Link>

      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white flex items-center gap-2">
            <Download size={24} className="text-violet-500" />
            Invoice History
          </h1>
          <p className="text-gray-500 dark:text-gray-400 mt-1">All past invoices for your subscription.</p>
        </div>
        <button
          onClick={handlePortal}
          disabled={portalLoading}
          className="flex items-center gap-2 px-4 py-2 bg-gray-100 dark:bg-gray-800 hover:bg-gray-200 dark:hover:bg-gray-700 text-gray-700 dark:text-gray-200 rounded-lg text-sm font-medium transition-colors disabled:opacity-50"
        >
          <ExternalLink size={15} />
          {portalLoading ? 'Opening…' : 'Stripe Portal'}
        </button>
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-20">
          <div className="animate-spin rounded-full h-8 w-8 border-t-2 border-b-2 border-violet-500" />
        </div>
      ) : invoices.length === 0 ? (
        <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 p-12 text-center">
          <AlertCircle size={40} className="mx-auto mb-4 text-gray-300 dark:text-gray-600" />
          <p className="text-sm text-gray-500">No invoices found yet.</p>
        </div>
      ) : (
        <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 overflow-hidden">
          {/* Table header */}
          <div className="grid grid-cols-12 gap-4 px-6 py-3 border-b border-gray-100 dark:border-gray-800 bg-gray-50/50 dark:bg-gray-800/20 text-xs font-semibold text-gray-400 uppercase tracking-wider">
            <span className="col-span-4">Date</span>
            <span className="col-span-2">Status</span>
            <span className="col-span-3 text-right">Amount</span>
            <span className="col-span-3 text-right">Actions</span>
          </div>
          <div className="divide-y divide-gray-100 dark:divide-gray-800">
            {invoices.map((inv) => (
              <div
                key={inv.id}
                className="grid grid-cols-12 gap-4 px-6 py-4 items-center hover:bg-gray-50/50 dark:hover:bg-gray-800/20 transition-colors"
              >
                <span className="col-span-4 text-sm font-medium text-gray-900 dark:text-white">
                  {formatDate(inv.created)}
                </span>
                <span className="col-span-2">
                  <span
                    className={`text-[10px] px-2 py-0.5 rounded-full font-bold uppercase ${statusColor[inv.status] ?? 'bg-gray-100 text-gray-500'}`}
                  >
                    {inv.status}
                  </span>
                </span>
                <span className="col-span-3 text-right font-bold text-gray-900 dark:text-white">
                  ${(inv.amount_due / 100).toFixed(2)}
                </span>
                <div className="col-span-3 flex items-center justify-end gap-2">
                  <a
                    href={inv.invoice_pdf}
                    target="_blank"
                    rel="noreferrer"
                    className="p-1.5 text-gray-400 hover:text-violet-600 dark:hover:text-violet-400 transition-colors"
                    title="Download PDF"
                  >
                    <Download size={15} />
                  </a>
                  <a
                    href={inv.hosted_invoice_url}
                    target="_blank"
                    rel="noreferrer"
                    className="p-1.5 text-gray-400 hover:text-violet-600 dark:hover:text-violet-400 transition-colors"
                    title="View invoice"
                  >
                    <ExternalLink size={15} />
                  </a>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
