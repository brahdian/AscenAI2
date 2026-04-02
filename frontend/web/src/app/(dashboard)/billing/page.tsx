'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { getPlanDisplayName } from '@/lib/plans'
import { CheckCircle, XCircle, Loader2, CreditCard, Zap, Phone, Calendar, ChevronRight, Sparkles, ArrowUp, ArrowDown, X, MessageSquare, Bot } from 'lucide-react'

interface BillingOverview {
  plan: string
  plan_display_name: string
  price_per_agent: number
  agent_count: number
  limits: {
    chat_messages: number
    voice_minutes: number
    team_seats: number
  }
  usage: {
    sessions: number
    messages: number
    tokens: number
    voice_minutes: number
    messages_pct: number
    voice_pct: number
    chats: number
    chat_overage: number
    voice_overage: number
  }
  estimated_bill: {
    base: number
    chat_overage: number
    voice_overage: number
    overage: number
    total: number
  }
  billing_period: {
    start: string
    end: string
  }
  portal_url?: string
}

const PLANS = {
  starter: {
    display_name: "Starter",
    price_per_agent: 49.00,
    chat_equivalents_included: 20_000,
    voice_minutes_included: 0,
    voice_enabled: false,
  },
  voice_growth: {
    display_name: "Growth",
    price_per_agent: 99.00,
    chat_equivalents_included: 80_000,
    voice_minutes_included: 1500,
    voice_enabled: true,
  },
  voice_business: {
    display_name: "Business",
    price_per_agent: 199.00,
    chat_equivalents_included: 170_000,
    voice_minutes_included: 3500,
    voice_enabled: true,
  },
  enterprise: {
    display_name: "Enterprise",
    price_per_agent: null,
    chat_equivalents_included: null,
    voice_minutes_included: null,
    voice_enabled: true,
  },
}

const PLAN_ORDER = ['starter', 'voice_growth', 'voice_business', 'enterprise']
const TWILIO_ADDON_COST = 15.00

export default function BillingPage() {
  const router = useRouter()
  const [loading, setLoading] = useState(true)
  const [overview, setOverview] = useState<BillingOverview | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [voiceAddon, setVoiceAddon] = useState(false)
  const [changingPlan, setChangingPlan] = useState(false)
  const [cancelling, setCancelling] = useState(false)

  useEffect(() => {
    fetchOverview()
  }, [])

  const fetchOverview = async () => {
    try {
      const token = localStorage.getItem('access_token')
      const response = await fetch('/api/v1/billing/overview', {
        headers: {
          'Authorization': `Bearer ${token}`,
        },
      })
      if (!response.ok) throw new Error('Failed to fetch billing overview')
      const data = await response.json()
      setOverview(data)
    } catch (err) {
      setError('Failed to load billing information')
    } finally {
      setLoading(false)
    }
  }

  const handleUpgrade = async (newPlan: string) => {
    setChangingPlan(true)
    try {
      const token = localStorage.getItem('access_token')
      const response = await fetch('/api/v1/billing/create-checkout-session', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ plan: newPlan }),
      })
      if (!response.ok) throw new Error('Failed to create checkout session')
      const data = await response.json()
      if (data.checkout_url) {
        window.location.href = data.checkout_url
      }
    } catch (err) {
      setError('Failed to start plan change')
      setChangingPlan(false)
    }
  }

  const handleCancel = async () => {
    if (!confirm('Are you sure you want to cancel your plan? You will be moved to Free Tier.')) return
    setCancelling(true)
    try {
      const token = localStorage.getItem('access_token')
      const response = await fetch('/api/v1/billing/cancel', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
      })
      if (!response.ok) throw new Error('Failed to cancel plan')
      await fetchOverview()
    } catch (err) {
      setError('Failed to cancel plan')
    } finally {
      setCancelling(false)
    }
  }

  const handleVoiceToggle = async () => {
    try {
      const token = localStorage.getItem('access_token')
      const response = await fetch('/api/v1/billing/voice-addon', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ enabled: !voiceAddon }),
      })
      if (!response.ok) throw new Error('Failed to toggle voice addon')
      setVoiceAddon(!voiceAddon)
    } catch (err) {
      setError('Failed to update voice addon')
    }
  }

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50 dark:bg-gray-900">
        <Loader2 className="w-8 h-8 animate-spin text-violet-600" />
      </div>
    )
  }

  if (error && !overview) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50 dark:bg-gray-900 p-4">
        <div className="max-w-md w-full bg-white dark:bg-gray-800 rounded-2xl border border-gray-200 dark:border-gray-700 p-8 text-center">
          <div className="w-16 h-16 rounded-full bg-red-100 dark:bg-red-900/30 flex items-center justify-center mx-auto mb-6">
            <XCircle className="w-8 h-8 text-red-600" />
          </div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white mb-2">
            Error Loading Billing
          </h1>
          <p className="text-gray-500 dark:text-gray-400 mb-6">{error}</p>
          <button
            onClick={() => router.push('/dashboard')}
            className="px-5 py-2.5 rounded-xl border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300 font-medium hover:bg-gray-50 dark:hover:bg-gray-700"
          >
            Back to Dashboard
          </button>
        </div>
      </div>
    )
  }

  const currentPlanKey = overview?.plan || 'free'
  const planData = PLANS[currentPlanKey as keyof typeof PLANS] || null
  const isFreeTier = !overview?.plan || overview?.plan === 'free' || overview?.price_per_agent === null || overview?.price_per_agent === 0

  const displayPlanName = isFreeTier ? 'Free Tier' : (overview?.plan_display_name || planData?.display_name || getPlanDisplayName(currentPlanKey))
  const displayPrice = isFreeTier ? '$0.00' : `$${(overview?.price_per_agent || planData?.price_per_agent || 0).toFixed(2)}/month`
  const displayAgents = overview?.agent_count || 1
  const totalMonthlyCost = overview?.estimated_bill?.total || 0

  const currentPlanIndex = PLAN_ORDER.indexOf(currentPlanKey)
  if (currentPlanIndex === -1) {
    // Fallback for legacy keys or unknown plans
    if (currentPlanKey === 'starter') PLAN_ORDER.indexOf('text_growth')
    else if (currentPlanKey === 'growth' || currentPlanKey === 'professional') PLAN_ORDER.indexOf('voice_growth')
    else if (currentPlanKey === 'business') PLAN_ORDER.indexOf('voice_business')
  }
  const planStatus = isFreeTier ? 'Free Tier' : 'Active'

  // Format dates for display
  const formatDate = (dateStr: string) => {
    if (!dateStr) return 'N/A'
    try {
      const d = new Date(dateStr)
      return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
    } catch {
      return dateStr
    }
  }

  // Calculate renewal date (end of billing period)
  const renewalDate = overview?.billing_period?.end ? formatDate(overview.billing_period.end) : 'N/A'

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-900 py-8">
      <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="mb-8">
          <h1 className="text-3xl font-bold text-gray-900 dark:text-white">Billing & Subscription</h1>
          <p className="mt-2 text-gray-600 dark:text-gray-400">Manage your subscription and view usage</p>
        </div>

        {error && (
          <div className="mb-6 p-4 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-xl text-red-700 dark:text-red-400">
            {error}
          </div>
        )}

        <div className="grid gap-6">
          {/* Current Plan Section */}
          <div className="bg-white dark:bg-gray-800 rounded-2xl border border-gray-200 dark:border-gray-700 p-6">
            <div className="flex items-center justify-between mb-6">
              <div>
                <h2 className="text-lg font-semibold text-gray-900 dark:text-white">Current Plan</h2>
                <p className="text-sm text-gray-500 dark:text-gray-400">Your active subscription</p>
              </div>
              {isFreeTier ? (
                <span className="inline-flex items-center px-3 py-1 rounded-full text-sm font-medium bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-300">
                  Free Tier
                </span>
              ) : (
                <span className="inline-flex items-center px-3 py-1 rounded-full text-sm font-medium bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400">
                  <CheckCircle className="w-4 h-4 mr-1" />
                  Active
                </span>
              )}
            </div>

            <div className="grid md:grid-cols-4 gap-4">
              <div className="p-4 bg-gray-50 dark:bg-gray-700/50 rounded-xl">
                <p className="text-sm text-gray-500 dark:text-gray-400 mb-1">Plan</p>
                <p className="text-xl font-bold text-gray-900 dark:text-white">{displayPlanName}</p>
              </div>
              <div className="p-4 bg-gray-50 dark:bg-gray-700/50 rounded-xl">
                <p className="text-sm text-gray-500 dark:text-gray-400 mb-1">Price</p>
                <p className="text-xl font-bold text-gray-900 dark:text-white">
                  {displayPrice}
                  {!isFreeTier && <span className="text-sm font-normal text-gray-500 dark:text-gray-400"> per agent</span>}
                </p>
              </div>
              <div className="p-4 bg-gray-50 dark:bg-gray-700/50 rounded-xl">
                <p className="text-sm text-gray-500 dark:text-gray-400 mb-1">Agents</p>
                <p className="text-xl font-bold text-gray-900 dark:text-white">{displayAgents}</p>
              </div>
              <div className="p-4 bg-gray-50 dark:bg-gray-700/50 rounded-xl">
                <p className="text-sm text-gray-500 dark:text-gray-400 mb-1">Billing Period</p>
                <p className="text-lg font-bold text-gray-900 dark:text-white">
                  {overview?.billing_period?.start ? formatDate(overview.billing_period.start) : 'N/A'}
                </p>
                <p className="text-xs text-gray-500 dark:text-gray-400">
                  to {overview?.billing_period?.end ? formatDate(overview.billing_period.end) : 'N/A'}
                </p>
                {!isFreeTier && overview?.billing_period?.end && (
                  <p className="text-xs text-violet-600 dark:text-violet-400 mt-1">
                    Renews on {formatDate(overview.billing_period.end)}
                  </p>
                )}
              </div>
            </div>
          </div>

          {/* View Invoices Button */}
          {!isFreeTier && overview?.portal_url && (
            <div className="bg-white dark:bg-gray-800 rounded-2xl border border-gray-200 dark:border-gray-700 p-6">
              <div className="flex items-center justify-between">
                <div>
                  <h2 className="text-lg font-semibold text-gray-900 dark:text-white">Invoices & Payments</h2>
                  <p className="text-sm text-gray-500 dark:text-gray-400">View and download your billing history</p>
                </div>
                <a
                  href={overview.portal_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="px-4 py-2 rounded-lg font-medium text-violet-600 border border-violet-200 dark:border-violet-800 hover:bg-violet-50 dark:hover:bg-violet-900/20 flex items-center gap-2"
                >
                  <CreditCard className="w-4 h-4" />
                  View Invoices
                </a>
              </div>
            </div>
          )}

          {/* Per-Agent Breakdown */}
          {!isFreeTier && (
            <div className="bg-white dark:bg-gray-800 rounded-2xl border border-gray-200 dark:border-gray-700 p-6">
              <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-6">Per-Agent Breakdown</h2>
              <div className="grid md:grid-cols-3 gap-4">
                <div className="p-4 bg-gray-50 dark:bg-gray-700/50 rounded-xl">
                  <p className="text-sm text-gray-500 dark:text-gray-400 mb-1">Number of Agents</p>
                  <p className="text-2xl font-bold text-gray-900 dark:text-white">{displayAgents}</p>
                </div>
                <div className="p-4 bg-gray-50 dark:bg-gray-700/50 rounded-xl">
                  <p className="text-sm text-gray-500 dark:text-gray-400 mb-1">Cost per Agent</p>
                  <p className="text-2xl font-bold text-gray-900 dark:text-white">${overview?.price_per_agent || planData?.price_per_agent || 0}</p>
                </div>
                <div className="p-4 bg-violet-50 dark:bg-violet-900/20 rounded-xl">
                  <p className="text-sm text-violet-600 dark:text-violet-400 mb-1">Total Monthly Cost</p>
                  <p className="text-2xl font-bold text-violet-600">${totalMonthlyCost.toFixed(2)}</p>
                </div>
              </div>
            </div>
          )}

          {/* Usage Section */}
          <div className="bg-white dark:bg-gray-800 rounded-2xl border border-gray-200 dark:border-gray-700 p-6">
            <div className="flex items-center justify-between mb-6">
              <div>
                <h2 className="text-lg font-semibold text-gray-900 dark:text-white">Current Usage</h2>
                <p className="text-sm text-gray-500 dark:text-gray-400">This billing period</p>
              </div>
              <div className="flex items-center text-sm text-gray-500 dark:text-gray-400">
                <Calendar className="w-4 h-4 mr-1" />
                {overview?.billing_period?.start ? formatDate(overview.billing_period.start) : ''} - {overview?.billing_period?.end ? formatDate(overview.billing_period.end) : ''}
              </div>
            </div>

            <div className="space-y-6">
              {/* Chat Equivalents */}
              <div>
                <div className="flex justify-between text-sm mb-2">
                  <span className="text-gray-600 dark:text-gray-400">Chat Equivalents</span>
                  <span className="font-medium text-gray-900 dark:text-white">
                    {(overview?.usage?.chats || 0).toLocaleString()} / {overview?.limits?.chat_messages ? overview.limits.chat_messages.toLocaleString() : 'N/A'}
                  </span>
                </div>
                <div className="w-full bg-gray-200 dark:bg-gray-700 rounded-full h-3">
                  <div
                    className="bg-violet-600 h-3 rounded-full transition-all"
                    style={{ width: `${Math.min(overview?.usage?.messages_pct || 0, 100)}%` }}
                  />
                </div>
                <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">{(overview?.usage?.messages_pct || 0).toFixed(1)}% used</p>
              </div>

              {/* Voice Minutes */}
              <div>
                <div className="flex justify-between text-sm mb-2">
                  <span className="text-gray-600 dark:text-gray-400">Voice Minutes</span>
                  <span className="font-medium text-gray-900 dark:text-white">
                    {overview?.limits?.voice_minutes !== undefined && overview?.limits?.voice_minutes !== null && overview?.limits?.voice_minutes > 0
                      ? `${(overview?.usage?.voice_minutes || 0).toLocaleString()} / ${overview.limits.voice_minutes.toLocaleString()}`
                      : isFreeTier
                        ? 'N/A'
                        : 'Custom'}
                  </span>
                </div>
                {overview?.limits?.voice_minutes !== undefined && overview?.limits?.voice_minutes !== null && overview?.limits?.voice_minutes > 0 && (
                  <div className="w-full bg-gray-200 dark:bg-gray-700 rounded-full h-3">
                    <div
                      className="bg-blue-600 h-3 rounded-full transition-all"
                      style={{ width: `${Math.min(overview?.usage?.voice_pct || 0, 100)}%` }}
                    />
                  </div>
                )}
                {overview?.limits?.voice_minutes !== undefined && overview?.limits?.voice_minutes !== null && overview?.limits?.voice_minutes > 0 && (
                  <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">{(overview?.usage?.voice_pct || 0).toFixed(1)}% used</p>
                )}
              </div>

              <div className="grid md:grid-cols-2 lg:grid-cols-4 gap-4">
                <div className="p-4 bg-gray-50 dark:bg-gray-700/50 rounded-xl">
                  <div className="flex items-center text-sm text-gray-500 dark:text-gray-400 mb-1">
                    <Sparkles className="w-4 h-4 mr-1" />
                    Sessions
                  </div>
                  <p className="text-lg font-bold text-gray-900 dark:text-white">{(overview?.usage?.sessions || 0).toLocaleString()}</p>
                  <p className="text-xs text-gray-500 dark:text-gray-400">Total conversations</p>
                </div>
                <div className="p-4 bg-gray-50 dark:bg-gray-700/50 rounded-xl">
                  <div className="flex items-center text-sm text-gray-500 dark:text-gray-400 mb-1">
                    <MessageSquare className="w-4 h-4 mr-1" />
                    Chats
                  </div>
                  <p className="text-lg font-bold text-gray-900 dark:text-white">{(overview?.usage?.chats || 0).toLocaleString()}</p>
                  <p className="text-xs text-gray-500 dark:text-gray-400">
                    Inbound + Outbound
                  </p>
                  {(overview?.usage?.chat_overage || 0) > 0 && (
                    <p className="text-xs text-orange-600 dark:text-orange-400 mt-1">
                      +{(overview?.usage?.chat_overage || 0).toLocaleString()} overage
                    </p>
                  )}
                </div>
                <div className="p-4 bg-gray-50 dark:bg-gray-700/50 rounded-xl">
                  <div className="flex items-center text-sm text-gray-500 dark:text-gray-400 mb-1">
                    <Zap className="w-4 h-4 mr-1" />
                    Tokens Used
                  </div>
                  <p className="text-lg font-bold text-gray-900 dark:text-white">
                    {overview?.usage?.tokens 
                      ? (overview.usage.tokens / 1000).toFixed(1) + 'k'
                      : '0'}
                  </p>
                  <p className="text-xs text-gray-500 dark:text-gray-400">Total LLM throughput</p>
                </div>
                <div className="p-4 bg-gray-50 dark:bg-gray-700/50 rounded-xl">
                  <div className="flex items-center text-sm text-gray-500 dark:text-gray-400 mb-1">
                    <Phone className="w-4 h-4 mr-1" />
                    Voice Minutes
                  </div>
                  <p className="text-lg font-bold text-gray-900 dark:text-white">{(overview?.usage?.voice_minutes || 0).toFixed(1)}m</p>
                  <p className="text-xs text-gray-500 dark:text-gray-400">AI-user calls</p>
                  {(overview?.usage?.voice_overage || 0) > 0 && (
                    <p className="text-xs text-orange-600 dark:text-orange-400 mt-1">
                      +{(overview?.usage?.voice_overage || 0).toLocaleString()} overage
                    </p>
                  )}
                </div>
              </div>
            </div>
          </div>

          {/* Estimated Bill */}
          {!isFreeTier && (
            <div className="bg-white dark:bg-gray-800 rounded-2xl border border-gray-200 dark:border-gray-700 p-6">
              <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-6">Cost Breakdown</h2>
              <div className="space-y-3">
                <div className="flex justify-between">
                  <span className="text-gray-600 dark:text-gray-400">Base plan ({displayAgents} agent{displayAgents > 1 ? 's' : ''})</span>
                  <span className="font-medium text-gray-900 dark:text-white">${(overview?.estimated_bill?.base || 0).toFixed(2)}</span>
                </div>
                {(overview?.estimated_bill?.chat_overage || 0) > 0 && (
                  <div className="flex justify-between">
                    <span className="text-gray-600 dark:text-gray-400">Chat overage</span>
                    <span className="font-medium text-orange-600">${(overview?.estimated_bill?.chat_overage || 0).toFixed(2)}</span>
                  </div>
                )}
                {(overview?.estimated_bill?.voice_overage || 0) > 0 && (
                  <div className="flex justify-between">
                    <span className="text-gray-600 dark:text-gray-400">Voice overage</span>
                    <span className="font-medium text-orange-600">${(overview?.estimated_bill?.voice_overage || 0).toFixed(2)}</span>
                  </div>
                )}
                <div className="border-t border-gray-200 dark:border-gray-700 pt-3 flex justify-between">
                  <span className="font-semibold text-gray-900 dark:text-white">Total to Pay</span>
                  <span className="font-bold text-xl text-violet-600">${(overview?.estimated_bill?.total || 0).toFixed(2)}</span>
                </div>
              </div>
            </div>
          )}

          {/* Voice Add-on */}
          {planData && planData.voice_enabled && (
            <div className="bg-white dark:bg-gray-800 rounded-2xl border border-gray-200 dark:border-gray-700 p-6">
              <div className="flex items-center justify-between">
                <div className="flex items-center">
                  <div className="p-2 bg-blue-100 dark:bg-blue-900/30 rounded-lg mr-4">
                    <Phone className="w-5 h-5 text-blue-600" />
                  </div>
                  <div>
                    <h3 className="font-semibold text-gray-900 dark:text-white">Voice Support Add-on</h3>
                    <p className="text-sm text-gray-500 dark:text-gray-400">Technical support & configuration help</p>
                  </div>
                </div>
                <div className="flex items-center gap-4">
                  <span className="text-lg font-bold text-gray-900 dark:text-white">${TWILIO_ADDON_COST}/mo</span>
                  <span className="text-xs text-gray-500 dark:text-gray-400 max-w-[200px]">
                    Requires your own Twilio account
                  </span>
                  <button
                    onClick={handleVoiceToggle}
                    className={`px-4 py-2 rounded-lg font-medium transition-colors ${voiceAddon
                      ? 'bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400'
                      : 'bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-600'
                      }`}
                  >
                    {voiceAddon ? 'Enabled' : 'Enable'}
                  </button>
                </div>
              </div>
            </div>
          )}

          {/* Available Plans - Upgrade/Downgrade */}
          <div className="bg-white dark:bg-gray-800 rounded-2xl border border-gray-200 dark:border-gray-700 p-6">
            <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-6">Available Plans</h2>
            <div className="grid md:grid-cols-4 gap-4">
              {Object.entries(PLANS).map(([key, plan]) => {
                const isCurrentPlan = key === currentPlanKey
                const planIndex = PLAN_ORDER.indexOf(key)
                const isUpgrade = !isFreeTier && planIndex > currentPlanIndex
                const isDowngrade = !isFreeTier && planIndex < currentPlanIndex && !isFreeTier

                return (
                  <div
                    key={key}
                    className={`p-4 rounded-xl border-2 transition-all ${isCurrentPlan
                      ? 'border-violet-500 bg-violet-50 dark:bg-violet-900/20'
                      : 'border-gray-200 dark:border-gray-700 hover:border-violet-300'
                      }`}
                  >
                    <h3 className="font-semibold text-gray-900 dark:text-white mb-1">{plan.display_name}</h3>
                    <p className="text-2xl font-bold text-gray-900 dark:text-white mb-2">
                      {plan.price_per_agent ? `$${plan.price_per_agent}` : 'Custom'}
                      {plan.price_per_agent && <span className="text-sm font-normal text-gray-500">/mo</span>}
                    </p>
                    <p className="text-sm text-gray-500 dark:text-gray-400 mb-3">
                      {plan.chat_equivalents_included
                        ? `${(plan.chat_equivalents_included / 1000).toFixed(1)}K chat equiv`
                        : 'N/A'}
                    </p>
                    {plan.voice_minutes_included !== null && (
                      <p className="text-xs text-gray-500 dark:text-gray-400 mb-3">
                        {plan.voice_minutes_included > 0 ? `${plan.voice_minutes_included} min voice` : 'No voice'}
                      </p>
                    )}
                    {isCurrentPlan ? (
                      <span className="block w-full text-center py-2 text-sm font-medium text-violet-600 bg-violet-100 dark:bg-violet-900/30 rounded-lg">
                        Current
                      </span>
                    ) : (
                      <button
                        onClick={() => handleUpgrade(key)}
                        disabled={changingPlan}
                        className="w-full py-2 text-sm font-medium text-white bg-violet-600 hover:bg-violet-700 rounded-lg disabled:opacity-50 flex items-center justify-center gap-1"
                      >
                        {changingPlan ? (
                          <Loader2 className="w-4 h-4 animate-spin" />
                        ) : (
                          <>
                            {isUpgrade && <ArrowUp className="w-3 h-3" />}
                            {isDowngrade && <ArrowDown className="w-3 h-3" />}
                            {isUpgrade ? 'Upgrade' : isDowngrade ? 'Downgrade' : 'Select Plan'}
                          </>
                        )}
                      </button>
                    )}
                  </div>
                )
              })}
            </div>

            {/* Cancel Plan */}
            {!isFreeTier && (
              <div className="mt-6 pt-6 border-t border-gray-200 dark:border-gray-700">
                <div className="flex items-center justify-between">
                  <div>
                    <h3 className="font-medium text-gray-900 dark:text-white">Cancel Subscription</h3>
                    <p className="text-sm text-gray-500 dark:text-gray-400">You will be moved to Free Tier at the end of your billing period</p>
                  </div>
                  <button
                    onClick={handleCancel}
                    disabled={cancelling}
                    className="px-4 py-2 rounded-lg font-medium text-red-600 border border-red-200 dark:border-red-800 hover:bg-red-50 dark:hover:bg-red-900/20 disabled:opacity-50 flex items-center gap-1"
                  >
                    {cancelling ? (
                      <Loader2 className="w-4 h-4 animate-spin" />
                    ) : (
                      <>
                        <X className="w-3 h-3" />
                        Cancel Plan
                      </>
                    )}
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
