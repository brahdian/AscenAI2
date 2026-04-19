'use client'

import { useState } from 'react'
import Link from 'next/link'
import { useQuery } from '@tanstack/react-query'
import { billingApi } from '@/lib/api'
import { Check, Zap, X, RefreshCw } from 'lucide-react'

export default function PricingPage() {
  const [isYearly, setIsYearly] = useState(false)

  const { data: plansData, isLoading } = useQuery({
    queryKey: ['public-plans'],
    queryFn: () => billingApi.listPlans(),
  })

  if (isLoading || !plansData) {
    return (
      <div className="min-h-screen bg-[#0f0728] flex items-center justify-center">
        <RefreshCw className="animate-spin text-white/20" size={32} />
      </div>
    )
  }

  // Convert Record<string, Plan> to sorted array for the grid
  // We want Starter -> Growth -> Business order
  const order = ['starter', 'growth', 'business']
  const plans = order.map(key => ({
    key,
    ...plansData[key]
  })).filter(p => p.display_name)

  const featureRows = [
    { label: 'Usage (chat equivalents)', key: 'chat_equivalents_included', format: (v: any) => `${(v || 0).toLocaleString()} / month` },
    { label: 'Voice minutes', key: 'voice_minutes_included', format: (v: any) => v ? `${v.toLocaleString()} mins included` : 'None' },
    { label: 'Playbooks per agent', key: 'playbooks_per_agent', format: (v: any) => v ? `${v} per agent` : 'Unlimited' },
    { label: 'RAG knowledge base', key: 'rag_documents', format: (v: any) => `${v} documents` },
    { label: 'Team seats', key: 'team_seats', format: (v: any) => `${v} seats` },
    { label: 'API access & embed widget', key: 'api_access', bool: true, defaultValue: true },
    { label: 'Webhook events', key: 'webhooks', bool: true, defaultValue: true },
    { label: 'Guardrails & filtering', key: 'guardrails', bool: true, defaultValue: true },
    { label: 'Analytics', key: 'analytics', format: () => 'Advanced' },
    { label: 'Support', key: 'support', format: () => 'Priority email' },
  ]

  const faqs = [
    {
      q: 'How does the "chat equivalents" model work?',
      a: 'Each plan gives you a pool of "chat equivalents" you can use any way you want. 1 voice minute = 100 chat equivalents. For example, on the Growth plan you get 80,000 chat equivalents — you could use all 80,000 as chats, or 800 voice minutes, or any combination — like 400 mins + 40,000 chats.',
    },
    {
      q: 'What is a chat equivalent?',
      a: 'A chat equivalent is our unified unit of usage. 1 chat = 1 chat equivalent. 1 voice minute = 100 chat equivalents. This lets you use your plan allowance flexibly across both chat and voice.',
    },
    {
      q: 'How are voice minutes calculated?',
      a: 'Billed per minute, rounded up. Each voice minute includes STT (transcription), AI response time, and TTS (speech synthesis). A 90-second call = 2 voice minutes = 200 chat equivalents.',
    },
    {
      q: 'What happens when I exceed my limits?',
      a: 'Your agent keeps running — we never cut off an active conversation. Overage is billed at the rates specified in your plan and appears on your next invoice.',
    },
    {
      q: 'Do I need my own Twilio or Telnyx account?',
      a: 'Yes. You bring your own Twilio or Telnyx account for telephony. This means you only pay us for the AI layer (STT, LLM, and TTS) — not for carrier costs. That\'s how we can offer significantly more voice minutes at lower prices compared to competitors who bundle telephony.',
    },
    {
      q: 'Can I switch between plans?',
      a: 'Yes, you can upgrade or downgrade your plan at any time. Changes take effect on your next billing cycle, and we\'ll prorate any differences.',
    },
    {
      q: 'Which AI model powers the agents?',
      a: 'All plans run on Gemini 2.5 Flash Lite — Google\'s fastest multimodal model optimised for real-time voice and chat. It handles both audio transcription and text responses in a single model, keeping costs low and latency under 200ms.',
    },
  ]

  return (
    <main className="min-h-screen bg-gradient-to-br from-[#0f0728] via-[#1a1040] to-[#0c1e4a] text-white">
      {/* Navbar */}
      <nav className="flex items-center justify-between px-8 py-5 max-w-7xl mx-auto">
        <Link href="/" className="flex items-center gap-2">
          <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-violet-500 to-blue-500 flex items-center justify-center text-white font-bold text-sm">
            A
          </div>
          <span className="text-xl font-bold text-white">AscenAI</span>
        </Link>
        <div className="flex items-center gap-4">
          <Link href="/login" className="text-gray-300 hover:text-white transition-colors text-sm">
            Sign in
          </Link>
          <Link
            href="/register"
            className="px-4 py-2 rounded-lg bg-gradient-to-r from-violet-600 to-blue-600 text-white text-sm font-medium hover:opacity-90 transition-opacity"
          >
            Get Started
          </Link>
        </div>
      </nav>

      {/* Header */}
      <section className="max-w-4xl mx-auto px-8 pt-16 pb-8 text-center">
        <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full bg-violet-500/10 border border-violet-500/20 text-violet-300 text-sm mb-6">
          No setup fees · No per-resolution billing · Cancel anytime
        </div>
        <h1 className="text-5xl font-bold mb-4">Simple pricing, no surprises</h1>
        <p className="text-gray-400 text-lg max-w-2xl mx-auto">
          Flat monthly rate per agent. Choose Chat-only or add Voice. While others charge 
          $30,000+ in setup fees, AscenAI is fully self-serve — live in minutes.
        </p>
        <p className="mt-3 text-sm text-violet-300">
          Powered by Gemini 2.5 Flash Lite · Google Cloud TTS · BYO Twilio/Telnyx
        </p>

        {/* Billing Toggle */}
        <div className="mt-8 flex items-center justify-center gap-4">
          <span className={`text-sm ${!isYearly ? 'text-white font-medium' : 'text-gray-400'}`}>
            Monthly
          </span>
          <button
            onClick={() => setIsYearly(!isYearly)}
            className={`relative w-14 h-7 rounded-full transition-colors ${
              isYearly ? 'bg-violet-600' : 'bg-gray-600'
            }`}
          >
            <div
              className={`absolute top-1 w-5 h-5 rounded-full bg-white transition-transform ${
                isYearly ? 'translate-x-8' : 'translate-x-1'
              }`}
            />
          </button>
          <span className={`text-sm ${isYearly ? 'text-white font-medium' : 'text-gray-400'}`}>
            Yearly
          </span>
          {isYearly && (
            <span className="ml-2 px-2 py-0.5 rounded-full bg-green-500/20 text-green-400 text-xs font-medium">
              Save 20%
            </span>
          )}
        </div>
      </section>

      {/* Plans Grid */}
      <section className="max-w-6xl mx-auto px-8 pb-16">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          {plans.map((plan) => (
            <div
              key={plan.key}
              className={`relative rounded-2xl border ${plan.color || 'border-white/10'} bg-white/[0.03] backdrop-blur-sm p-7 flex flex-col ${
                plan.highlight ? 'shadow-[0_0_60px_rgba(124,58,237,0.2)]' : ''
              }`}
            >
              {plan.badge && (
                <div className="absolute -top-3 left-1/2 -translate-x-1/2 px-3 py-1 rounded-full bg-violet-600 text-white text-xs font-semibold whitespace-nowrap">
                  {plan.badge}
                </div>
              )}

              <div className="mb-6">
                <div className="flex items-center gap-2 mb-2">
                  <span className="px-2 py-1 rounded-md bg-violet-500/20 text-violet-300 text-xs font-medium">
                    {plan.display_name}
                  </span>
                </div>
                <p className="text-gray-400 text-sm mb-4 h-10 line-clamp-2">{plan.description}</p>
                <div className="flex items-end gap-1">
                  <span className="text-5xl font-bold text-white">
                    ${isYearly 
                      ? (plan.price_per_agent_yearly || Math.round((plan.price_per_agent || 0) * 12 * 0.8)) 
                      : (plan.price_per_agent || 0)
                    }
                  </span>
                  <span className="text-gray-400 mb-1.5">/ agent / {isYearly ? 'year' : 'month'}</span>
                </div>
                {isYearly && (
                  <p className="text-sm text-gray-500 mt-1">
                    (${plan.price_per_agent}/month billed annually)
                  </p>
                )}
                <div className="mt-3 space-y-1">
                   <p className="text-violet-300 text-sm font-medium">
                     {(plan.chat_equivalents_included || 0).toLocaleString()} chats/month
                   </p>
                </div>
              </div>

              <Link
                href="/register"
                className={`block text-center py-3 rounded-xl text-sm font-semibold mb-6 transition-all ${
                  plan.highlight
                    ? 'bg-gradient-to-r from-violet-600 to-blue-600 text-white hover:opacity-90'
                    : 'border border-white/20 text-white hover:bg-white/5'
                }`}
              >
                Get Started
              </Link>

              <div className="space-y-3 flex-1">
                {featureRows.map((row) => {
                  const val = plan[row.key as keyof typeof plan]
                  const displayVal = row.format ? row.format(val) : (row.bool ? (val ?? row.defaultValue) : String(val))
                  const isEnabled = row.bool ? (val ?? row.defaultValue) : true

                  return (
                    <div key={row.key} className="flex items-start gap-2.5 text-sm">
                      {row.bool ? (
                        isEnabled ? (
                          <Check size={15} className="text-violet-400 shrink-0 mt-0.5" />
                        ) : (
                          <X size={15} className="text-gray-600 shrink-0 mt-0.5" />
                        )
                      ) : (
                        <Check size={15} className="text-violet-400 shrink-0 mt-0.5" />
                      )}
                      <span className={`${row.bool && !isEnabled ? 'text-gray-600' : 'text-gray-300'}`}>
                        <span className="text-gray-500 mr-1">{row.label}:</span>
                        {row.bool ? (isEnabled ? 'Included' : 'Not included') : displayVal}
                      </span>
                    </div>
                  )
                })}
              </div>

              <div className="mt-6 pt-5 border-t border-white/5 text-xs text-gray-500 space-y-1">
                <p className="font-medium text-gray-400 mb-1.5">Overage:</p>
                <p>Chat: ${plan.overage_per_chat_equivalent} per chat</p>
                {plan.overage_per_voice_minute > 0 && (
                  <p>Voice: ${plan.overage_per_voice_minute}/min</p>
                )}
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* Enterprise */}
      <section className="max-w-3xl mx-auto px-8 pb-16">
        <div className="rounded-2xl border border-white/10 bg-white/[0.02] p-6 flex flex-col md:flex-row items-center justify-between gap-4">
          <div>
            <div className="flex items-center gap-2 mb-1">
              <Zap size={16} className="text-yellow-400" />
              <h3 className="font-semibold text-white">Enterprise</h3>
            </div>
            <p className="text-gray-400 text-sm">
              High volume (contact for custom limits) · Custom Gemini model (Flash, Pro, Gemini 3.x) ·
              Dedicated infrastructure · White-label · SLA 99.9% · HIPAA/SOC2 · Named account manager
            </p>
          </div>
          <a
            href="mailto:sales@ascenai.com"
            className="shrink-0 px-5 py-2.5 rounded-xl border border-white/20 text-white text-sm font-medium hover:bg-white/5 transition-colors whitespace-nowrap"
          >
            Talk to sales →
          </a>
        </div>
      </section>

      {/* FAQ */}
      <section className="max-w-2xl mx-auto px-8 pb-20">
        <h2 className="text-2xl font-bold text-center mb-8">Frequently asked questions</h2>
        <div className="space-y-6">
          {faqs.map(({ q, a }) => (
            <div key={q}>
              <p className="font-semibold text-white mb-1.5">{q}</p>
              <p className="text-gray-400 text-sm leading-relaxed">{a}</p>
            </div>
          ))}
        </div>
      </section>

      <footer className="border-t border-white/5 py-8 text-center text-gray-500 text-sm">
        © {new Date().getFullYear()} AscenAI · Canada{' '}
        <span className="mx-2">·</span>
        <a href="mailto:billing@ascenai.com" className="hover:text-gray-300 transition-colors">
          billing@ascenai.com
        </a>
        <span className="mx-2">·</span>
        <a href="mailto:sales@ascenai.com" className="hover:text-gray-300 transition-colors">
          sales@ascenai.com
        </a>
      </footer>
    </main>
  )
}
