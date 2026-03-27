import Link from 'next/link'
import { Check, Zap, X } from 'lucide-react'

const tiers = [
  {
    name: 'Professional',
    price: 99,
    description: 'Perfect for salons, restaurants, clinics and small businesses.',
    badge: null,
    color: 'border-white/10',
    highlight: false,
    limits: {
      chat_messages: '5,000 / month',
      voice_minutes: '200 min / month',
      playbooks: '5 per agent',
      rag_documents: '25 documents',
      team_seats: '3 seats',
      api_access: true,
      webhooks: true,
      guardrails: true,
      analytics: 'Standard',
      support: 'Email',
    },
    overage: {
      chat: '$0.015 / message',
      voice: '$0.15 / min',
    },
    cta: 'Get started',
  },
  {
    name: 'Business',
    price: 299,
    description: 'For growing businesses with high call and chat volume.',
    badge: 'Most popular',
    color: 'border-violet-500/50',
    highlight: true,
    limits: {
      chat_messages: '25,000 / month',
      voice_minutes: '1,000 min / month',
      playbooks: 'Unlimited',
      rag_documents: '200 documents',
      team_seats: '10 seats',
      api_access: true,
      webhooks: true,
      guardrails: true,
      analytics: 'Advanced + exports',
      support: 'Priority email (24h)',
    },
    overage: {
      chat: '$0.012 / message',
      voice: '$0.12 / min',
    },
    cta: 'Get started',
  },
]

const featureRows = [
  { label: 'Chat messages / month', key: 'chat_messages' },
  { label: 'Voice minutes / month', key: 'voice_minutes' },
  { label: 'Playbooks per agent', key: 'playbooks' },
  { label: 'RAG knowledge base', key: 'rag_documents' },
  { label: 'Team seats', key: 'team_seats' },
  { label: 'API access & embed widget', key: 'api_access', bool: true },
  { label: 'Webhook events', key: 'webhooks', bool: true },
  { label: 'Guardrails & content filtering', key: 'guardrails', bool: true },
  { label: 'Analytics', key: 'analytics' },
  { label: 'Support', key: 'support' },
]

const faqs = [
  {
    q: 'Is there a free trial or setup fee?',
    a: 'No setup fees, no free trial. Unlike platforms that charge $30,000+ in onboarding fees (Ada, Intercom), AscenAI is fully self-serve. Sign up and have an agent live in minutes.',
  },
  {
    q: 'What counts as a chat message?',
    a: 'Each user message sent to an agent counts as one message. AI responses do not count separately.',
  },
  {
    q: 'What counts as a voice minute?',
    a: 'Billed per minute, rounded up. Includes STT (transcription), AI response time, and TTS (speech synthesis). A 90-second call = 2 minutes.',
  },
  {
    q: 'What happens when I exceed my limits?',
    a: 'Your agent keeps running — we never cut off an active conversation. Overage is billed at the per-unit rate shown in your plan and appears on your next invoice.',
  },
  {
    q: 'Which AI model powers the agents?',
    a: 'All plans run on Gemini 2.5 Flash Lite — Google\'s fastest multimodal model optimised for real-time voice and chat. It handles both audio transcription and text responses in a single model, keeping costs low and latency under 200ms.',
  },
  {
    q: 'How does this compare to Ada or Intercom Fin?',
    a: 'Ada charges $30,000+ in setup fees before you deploy a single agent. Intercom Fin bills $0.99 per resolution — a busy support team can easily hit $5,000+/month. AscenAI is flat-rate, self-serve, and includes voice out of the box.',
  },
  {
    q: 'Can I have multiple agents on one account?',
    a: 'Yes. Each agent is billed separately. You could run a booking agent, a support agent, and a sales agent for $297/month on Professional — or $897/month on Business.',
  },
  {
    q: 'What is included in Enterprise?',
    a: 'Unlimited messages and voice minutes, dedicated infrastructure, custom Gemini model selection (Flash, Pro, or future Gemini 3.x), white-label branding, SLA, HIPAA/SOC2 compliance, and a named account manager.',
  },
]

export default function PricingPage() {
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
      <section className="max-w-4xl mx-auto px-8 pt-16 pb-12 text-center">
        <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full bg-violet-500/10 border border-violet-500/20 text-violet-300 text-sm mb-6">
          No setup fees · No per-resolution billing · Cancel anytime
        </div>
        <h1 className="text-5xl font-bold mb-4">Simple pricing, no surprises</h1>
        <p className="text-gray-400 text-lg max-w-2xl mx-auto">
          Flat monthly rate per agent. While others charge $30,000+ in setup fees,
          AscenAI is fully self-serve — live in minutes.
        </p>
        <p className="mt-3 text-sm text-violet-300">
          Powered by Gemini 2.5 Flash Lite · Google Cloud TTS · Twilio voice
        </p>
      </section>

      {/* Tier cards */}
      <section className="max-w-4xl mx-auto px-8 pb-16">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6 max-w-3xl mx-auto">
          {tiers.map((tier) => (
            <div
              key={tier.name}
              className={`relative rounded-2xl border ${tier.color} bg-white/[0.03] backdrop-blur-sm p-7 flex flex-col ${
                tier.highlight ? 'shadow-[0_0_60px_rgba(124,58,237,0.2)]' : ''
              }`}
            >
              {tier.badge && (
                <div className="absolute -top-3 left-1/2 -translate-x-1/2 px-3 py-1 rounded-full bg-violet-600 text-white text-xs font-semibold">
                  {tier.badge}
                </div>
              )}

              <div className="mb-6">
                <h2 className="text-lg font-semibold text-white mb-1">{tier.name}</h2>
                <p className="text-gray-400 text-sm mb-4">{tier.description}</p>
                <div className="flex items-end gap-1">
                  <span className="text-5xl font-bold text-white">${tier.price}</span>
                  <span className="text-gray-400 mb-1.5">/ agent / month</span>
                </div>
              </div>

              <Link
                href="/register"
                className={`block text-center py-3 rounded-xl text-sm font-semibold mb-6 transition-all ${
                  tier.highlight
                    ? 'bg-gradient-to-r from-violet-600 to-blue-600 text-white hover:opacity-90'
                    : 'border border-white/20 text-white hover:bg-white/5'
                }`}
              >
                {tier.cta}
              </Link>

              <div className="space-y-3 flex-1">
                {featureRows.map((row) => {
                  const val = tier.limits[row.key as keyof typeof tier.limits]
                  return (
                    <div key={row.key} className="flex items-start gap-2.5 text-sm">
                      {row.bool ? (
                        val ? (
                          <Check size={15} className="text-violet-400 shrink-0 mt-0.5" />
                        ) : (
                          <X size={15} className="text-gray-600 shrink-0 mt-0.5" />
                        )
                      ) : (
                        <Check size={15} className="text-violet-400 shrink-0 mt-0.5" />
                      )}
                      <span className={`${row.bool && !val ? 'text-gray-600' : 'text-gray-300'}`}>
                        <span className="text-gray-500 mr-1">{row.label}:</span>
                        {row.bool ? (val ? '' : 'Not included') : String(val)}
                      </span>
                    </div>
                  )
                })}
              </div>

              <div className="mt-6 pt-5 border-t border-white/5 text-xs text-gray-500 space-y-1">
                <p className="font-medium text-gray-400 mb-1.5">Overage (agents never go offline):</p>
                <p>Chat: {tier.overage.chat}</p>
                <p>Voice: {tier.overage.voice}</p>
              </div>
            </div>
          ))}
        </div>

        {/* Enterprise */}
        <div className="mt-6 max-w-3xl mx-auto rounded-2xl border border-white/10 bg-white/[0.02] p-6 flex flex-col md:flex-row items-center justify-between gap-4">
          <div>
            <div className="flex items-center gap-2 mb-1">
              <Zap size={16} className="text-yellow-400" />
              <h3 className="font-semibold text-white">Enterprise</h3>
            </div>
            <p className="text-gray-400 text-sm">
              Unlimited messages & voice · Custom Gemini model (Flash, Pro, Gemini 3.x) ·
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

      {/* Comparison vs competitors */}
      <section className="max-w-3xl mx-auto px-8 pb-20">
        <h2 className="text-2xl font-bold text-center mb-2">How we compare</h2>
        <p className="text-gray-400 text-sm text-center mb-8">Same outcome, fraction of the cost</p>
        <div className="rounded-2xl border border-white/10 bg-white/[0.02] overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-white/5">
                <th className="text-left px-5 py-3 text-gray-400 font-medium">Platform</th>
                <th className="text-right px-5 py-3 text-gray-400 font-medium">Setup fee</th>
                <th className="text-right px-5 py-3 text-gray-400 font-medium">Monthly cost</th>
                <th className="text-right px-5 py-3 text-gray-400 font-medium">Voice included</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/5">
              {[
                ['Ada', '$30,000+', 'Custom', 'Extra'],
                ['Intercom Fin', 'None', '$0.99/resolution', 'No'],
                ['Bland.ai', 'None', '$0.09/min voice only', 'Yes'],
                ['VAPI', 'None', '$0.05–0.10/min', 'Yes, no chat'],
                ['AscenAI Professional', 'None', '$99/agent flat', 'Yes — included'],
                ['AscenAI Business', 'None', '$299/agent flat', 'Yes — included'],
              ].map(([platform, setup, monthly, voice], i) => (
                <tr key={platform} className={i >= 4 ? 'bg-violet-500/5' : ''}>
                  <td className={`px-5 py-3 ${i >= 4 ? 'text-violet-300 font-medium' : 'text-gray-300'}`}>
                    {platform}
                  </td>
                  <td className="px-5 py-3 text-right text-gray-400">{setup}</td>
                  <td className={`px-5 py-3 text-right font-mono ${i >= 4 ? 'text-violet-300 font-semibold' : 'text-gray-400'}`}>
                    {monthly}
                  </td>
                  <td className="px-5 py-3 text-right text-gray-400">{voice}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="text-xs text-gray-600 text-center mt-3">
          Competitor pricing sourced from public pricing pages. Actual costs vary.
        </p>
      </section>

      {/* Example calculation */}
      <section className="max-w-3xl mx-auto px-8 pb-20">
        <div className="rounded-2xl border border-white/10 bg-white/[0.02] p-6">
          <h3 className="font-semibold text-white mb-1">Example: Multi-location salon group</h3>
          <p className="text-gray-400 text-sm mb-4">
            3 locations, each with a booking + support agent
          </p>
          <div className="space-y-2 text-sm">
            {[
              ['3 agents × $299/month (Business plan)', '$897'],
              ['Overage: 200 extra voice minutes @ $0.12', '$24'],
              ['Total / month', '$921'],
              ['vs. 1 part-time receptionist (Canada avg)', '$2,200+'],
            ].map(([label, amount], i) => (
              <div
                key={label}
                className={`flex justify-between ${
                  i === 3
                    ? 'pt-3 mt-1 border-t border-white/5 text-gray-500 line-through'
                    : i === 2
                    ? 'pt-3 mt-1 border-t border-white/5 font-semibold text-white'
                    : 'text-gray-300'
                }`}
              >
                <span>{label}</span>
                <span className="font-mono">{amount}</span>
              </div>
            ))}
          </div>
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
