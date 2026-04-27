// Shared billing component — invoice list
import { Download, AlertCircle } from 'lucide-react'

export interface Invoice {
  id: string
  amount_due: number
  status: string
  created: number
  invoice_pdf: string
  hosted_invoice_url: string
}

const formatDate = (ts: number) =>
  new Date(ts * 1000).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })

export function InvoiceList({
  invoices,
  onManageBilling,
}: {
  invoices: Invoice[]
  onManageBilling: () => void
}) {
  return (
    <div className="bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-800 p-6 flex flex-col h-full">
      <h2 className="text-base font-bold text-gray-900 dark:text-white mb-4 flex items-center gap-2">
        <Download size={18} className="text-violet-500" />
        Recent Invoices
      </h2>

      {invoices.length === 0 ? (
        <div className="flex-1 flex flex-col items-center justify-center text-center p-8 border-2 border-dashed border-gray-100 dark:border-gray-800 rounded-xl">
          <AlertCircle size={32} className="text-gray-300 mb-2" />
          <p className="text-sm text-gray-500">No invoices found yet.</p>
        </div>
      ) : (
        <div className="space-y-3 flex-1 overflow-y-auto pr-1">
          {invoices.map((inv) => (
            <div
              key={inv.id}
              className="group p-3 rounded-xl border border-gray-100 dark:border-gray-800 hover:border-violet-200 hover:bg-violet-50/30 dark:hover:bg-violet-900/10 transition-all cursor-pointer"
              onClick={() => window.open(inv.hosted_invoice_url, '_blank')}
            >
              <div className="flex justify-between items-start mb-1.5">
                <p className="text-xs font-bold text-gray-900 dark:text-white">{formatDate(inv.created)}</p>
                <span className={`text-[10px] px-1.5 py-0.5 rounded-full font-medium ${inv.status === 'paid' ? 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400' : 'bg-amber-100 text-amber-700'}`}>
                  {inv.status.toUpperCase()}
                </span>
              </div>
              <div className="flex justify-between items-center">
                <p className="text-lg font-black text-gray-900 dark:text-white">
                  ${(inv.amount_due / 100).toFixed(2)}
                </p>
                <a
                  href={inv.invoice_pdf}
                  target="_blank"
                  rel="noreferrer"
                  className="text-gray-400 hover:text-violet-600 transition-colors"
                  onClick={(e) => e.stopPropagation()}
                >
                  <Download size={14} />
                </a>
              </div>
            </div>
          ))}
        </div>
      )}

      <button
        onClick={onManageBilling}
        className="mt-6 w-full py-2.5 text-xs text-gray-500 hover:text-violet-600 font-medium border border-gray-100 dark:border-gray-800 rounded-xl hover:bg-gray-50 dark:hover:bg-gray-800 transition-all"
      >
        See all billing history
      </button>
    </div>
  )
}
