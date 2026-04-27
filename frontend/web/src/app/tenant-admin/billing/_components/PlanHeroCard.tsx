// Shared billing component — plan hero card (gradient banner)
import { Clock, TrendingUp } from 'lucide-react'

const fmt = (n: number) =>
  `$${n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`

export function PlanHeroCard({
  planDisplayName,
  subscriptionStatus,
  pricePerAgent,
  estimatedBill,
  billingPeriodEnd,
  agentCount,
  isSubscribed,
  onManageBilling,
}: {
  planDisplayName: string
  subscriptionStatus?: string
  pricePerAgent: number
  estimatedBill: { base: number; overage: number; total: number }
  billingPeriodEnd: string
  agentCount: number
  isSubscribed: boolean
  onManageBilling: () => void
}) {
  const isOverage = estimatedBill.overage > 0

  return (
    <div className="bg-gradient-to-br from-violet-600 to-indigo-700 rounded-2xl p-6 text-white shadow-lg shadow-violet-500/20 relative overflow-hidden">
      <div className="absolute top-0 right-0 p-8 opacity-10">
        <TrendingUp size={120} />
      </div>
      <div className="relative z-10">
        <div className="flex justify-between items-start">
          <div>
            <div className="flex items-center gap-3 mb-3">
              <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold bg-white/20">
                Current Plan
              </span>
              {subscriptionStatus && (
                <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider ${
                  subscriptionStatus === 'active'
                    ? 'bg-emerald-400/20 text-emerald-100 border border-emerald-400/30'
                    : 'bg-amber-400/20 text-amber-100 border border-amber-400/30'
                }`}>
                  {subscriptionStatus}
                </span>
              )}
            </div>
            <p className="text-3xl font-bold mb-1">{planDisplayName || 'Not Subscribed'}</p>
            <p className="text-violet-100 text-sm opacity-80">{fmt(pricePerAgent)} per active agent / month</p>
          </div>
          <div className="text-right">
            <p className="text-violet-100 text-xs font-medium uppercase tracking-wider mb-1">Estimated Cost</p>
            <p className="text-4xl font-black">{fmt(estimatedBill.total)}</p>
            <div className="mt-2 flex items-center justify-end gap-1.5 text-xs text-violet-200">
              <Clock size={12} />
              <span>Period ends {billingPeriodEnd}</span>
            </div>
          </div>
        </div>

        <div className="mt-8 pt-6 border-t border-white/10 flex items-center justify-between">
          <div className="flex gap-6">
            <div>
              <p className="text-xs text-violet-200 mb-0.5">Active Agent Slots</p>
              <p className="text-lg font-bold">{agentCount}</p>
            </div>
            {isSubscribed && (
              <>
                <div>
                  <p className="text-xs text-violet-200 mb-0.5">Base Fee</p>
                  <p className="text-lg font-bold">{fmt(estimatedBill.base)}</p>
                </div>
                {isOverage && (
                  <div>
                    <p className="text-xs text-violet-200 mb-0.5">Overage</p>
                    <p className="text-lg font-bold text-amber-300">{fmt(estimatedBill.overage)}</p>
                  </div>
                )}
              </>
            )}
          </div>
          <button
            onClick={onManageBilling}
            className="px-4 py-2 bg-white text-violet-600 rounded-xl text-sm font-bold hover:bg-violet-50 transition-colors shadow-sm"
          >
            {isSubscribed ? 'Change Plan' : 'Choose Plan'}
          </button>
        </div>
      </div>
    </div>
  )
}
