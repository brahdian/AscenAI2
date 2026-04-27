'use client'

import { useQuery } from '@tanstack/react-query'
import { billingApi } from '@/lib/api'

export function DynamicHeroPrice({ format }: { format: 'banner' | 'button' }) {
  const { data: plansData, isLoading } = useQuery({
    queryKey: ['public-plans'],
    queryFn: () => billingApi.listPlans(),
  })

  // Fallback price if API is loading or fails
  let minPrice = 39

  if (plansData) {
    const prices = Object.values(plansData)
      .filter((p: any) => p.price_per_agent !== null && p.price_per_agent !== undefined)
      .map((p: any) => p.price_per_agent)
    
    if (prices.length > 0) {
      minPrice = Math.min(...prices)
    }
  }

  if (isLoading) {
    return (
      <span className="opacity-50 animate-pulse">
        {format === 'banner' ? 'Loading pricing...' : 'Get started'}
      </span>
    )
  }

  if (format === 'banner') {
    return <>From ${minPrice}/agent/month</>
  }

  return <>Get started — from ${minPrice}/agent/month</>
}
