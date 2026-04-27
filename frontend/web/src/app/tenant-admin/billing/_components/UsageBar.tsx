// Shared billing component — usage progress bar
import { AlertCircle } from 'lucide-react'

const fmtNum = (n: number) => n.toLocaleString()
const fmtLimit = (n: number | null) => (n == null ? 'Unlimited' : fmtNum(n))

export function UsageBar({
  label,
  desc,
  used,
  limit,
  pct,
}: {
  label: string
  desc: string
  used: number
  limit: number | null
  pct: number | null
}) {
  const p = pct || 0
  return (
    <div className="space-y-3">
      <div className="flex justify-between items-end">
        <div>
          <p className="text-sm font-bold text-gray-900 dark:text-white">{label}</p>
          <p className="text-[10px] text-gray-500 mt-0.5">{desc}</p>
        </div>
        <p className="text-sm font-mono font-bold text-gray-900 dark:text-white">
          {fmtNum(Math.round(used))}{' '}
          <span className="text-gray-400 font-normal">/ {fmtLimit(limit)}</span>
        </p>
      </div>
      <div className="h-2.5 bg-gray-100 dark:bg-gray-800 rounded-full overflow-hidden">
        <div
          className={`h-full transition-all duration-700 ease-out rounded-full ${
            p > 100
              ? 'bg-red-500 shadow-[0_0_8px_rgba(239,68,68,0.4)]'
              : p > 85
              ? 'bg-amber-500'
              : 'bg-violet-600'
          }`}
          style={{ width: `${Math.min(p, 100)}%` }}
        />
      </div>
      <div className="flex justify-between text-[10px]">
        <span className={p > 100 ? 'text-red-500 font-bold' : 'text-gray-400'}>
          {p > 100 ? 'Overage Applied' : `${Math.round(p)}% of limit used`}
        </span>
        {p > 85 && (
          <span className="flex items-center gap-1 text-amber-600 dark:text-amber-400 font-medium">
            <AlertCircle size={10} />
            Approaching limit
          </span>
        )}
      </div>
    </div>
  )
}
