import Link from 'next/link'
import { Check, Zap, X } from 'lucide-react'

const tiers = [
  {
    name: 'Starter',
    price: 49,
    description: 'Chat-only agents for small teams.',
    badge: null,
    color: 'border-white/10',
    highlight: false,
    limits: {
      chat_messages: '2,000 / month',
      voice_minutes: 'Not included',
      playbooks: '2 per agent',
      rag_documents: '10 documents',
      team_seats: '1 seat',
      api_access: true,
      webhooks: false,
      guardrails: true,
      analytics: 'Basic',
      support: 'Community',
    },
    overage: {
      chat: '$0.02 / message',
      voice: '—',
    },
    cta: 'Get started',
  },
  {
    name: 'Professional',
    price: 149,
    description: 'Chat + voice agents for growing businesses.',
    badge: 'Most popular',
    color: 'border-violet-500/50',
    highlight: true,
    limits: {
      chat_messages: '10,000 / month',
      voice_minutes: '300 min / month',
      playbooks: '10 per agent',
      rag_documents: '100 documents',
      team_seats: '5 seats',
      api_access: true,
      webhooks: true,
      guardrails: true,
      analytics: 'Full + exports',
      support: 'Email (48h)',
    },
    overage: {
      chat: '$0.02 / message',
      voice: '$0.20 / min',
    },
    cta: 'Get started',
  },
  {
    name: 'Business',
    price: 399,
    description: 'High-volume deployments with priority support.',
    badge: null,
    color: 'border-white/10',
    highlight: false,
    limits: {
      chat_messages: '50,000 / month',
      voice_minutes: '2,000 min / month',
      playbooks: 'Unlimited',
      rag_documents: '500 documents',
      team_seats: '20 seats',
      api_access: true,
      webhooks: true,
      guardrails: true,
      analytics: 'Full + custom reports',
      support: 'Priority (24h)',
    },
    overage: {
      chat: '$0.015 / message',
      voice: '$0.18 / min',
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
    q: 'Is there a free trial?',
    a: 'No. AscenAI is a professional platform. Contact us to discuss your use case before signing up.',
  },
  {
    q: 'What counts as a chat message?',
    a: 'Each user message sent to an agent counts as one message. AI responses do not count separately.',
  },
  {
    q: 'What counts as a voice minute?',
    a: 'Billed in 1-minute increments. A 90-second call = 2 minutes. Includes STT (transcription) + TTS (speech synthesis) + AI response time.',
  },
  {
    q: 'What happens when I exceed limits?',
    a: 'Your agent keeps running — we never hard-stop you mid-conversation. Overage is billed at the per-unit rate shown in each plan and appears on your next invoice.',
  },
  {
    q: 'Which AI model powers the agents?',
    a: 'All plans run on Gemini 2.5 Flash Lite by default — the most cost-efficient multimodal model for real-time voice and chat. Higher Gemini models (Flash, Pro, or future Gemini 3.x releases) are available as an add-on on Business and Enterprise plans.',
  },
  {
    q: 'Do I pay per seat or per agent?',
    a: 'Per agent. Seats (team members who access the dashboard) are included up to the plan limit. Additional seats are $10/seat/month.',
  },
  {
    q: 'Can I mix plans across agents?',
    a: 'Not currently — all agents under an account share the same plan. Enterprise accounts can negotiate per-agent plans.',
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
        <h1 className="text-5xl font-bold mb-4">Transparent, usage-based pricing</h1>
        <p className="text-gray-400 text-lg max-w-2xl mx-auto">
          Flat monthly rate per agent with clear message and voice limits.
          Overage billing keeps agents running — you never get cut off mid-conversation.
        </p>
        <p className="mt-4 text-sm text-violet-300">
          All plans powered by Gemini 2.5 Flash Lite · Google Cloud TTS Neural2 · Twilio voice
        </p>
      </section>

      {/* Tier cards */}
      <section className="max-w-6xl mx-auto px-8 pb-16">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
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
                <p className="font-medium text-gray-400 mb-1.5">Overage rates:</p>
                <p>Chat: {tier.overage.chat}</p>
                <p>Voice: {tier.overage.voice}</p>
              </div>
            </div>
          ))}
        </div>

        {/* Enterprise */}
        <div className="mt-6 rounded-2xl border border-white/10 bg-white/[0.02] p-6 flex flex-col md:flex-row items-center justify-between gap-4">
          <div>
            <div className="flex items-center gap-2 mb-1">
              <Zap size={16} className="text-yellow-400" />
              <h3 className="font-semibold text-white">Enterprise</h3>
            </div>
            <p className="text-gray-400 text-sm">
              Unlimited messages & voice · Bring your own API keys · Dedicated infrastructure ·
              Gemini Pro / future Gemini 3.x models · SLA 99.9% · HIPAA/SOC2 · Custom contracts
            </p>
          </div>
          <a
            href="mailto:sales@ascenai.com"
            className="shrink-0 px-5 py-2.5 rounded-xl border border-white/20 text-white text-sm font-medium hover:bg-white/5 transition-colors"
          >
            Contact sales →
          </a>
        </div>
      </section>

      {/* Cost breakdown — transparent */}
      <section className="max-w-3xl mx-auto px-8 pb-20">
        <h2 className="text-2xl font-bold text-center mb-2">What your $149 pays for</h2>
        <p className="text-gray-400 text-center text-sm mb-8">
          Professional plan cost breakdown for 10,000 messages + 300 voice minutes
        </p>
        <div className="rounded-2xl border border-white/10 bg-white/[0.02] overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-white/5">
                <th className="text-left px-5 py-3 text-gray-400 font-medium">Component</th>
                <th className="text-right px-5 py-3 text-gray-400 font-medium">Est. cost</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/5">
              {[
                ['Gemini 2.5 Flash Lite — chat LLM', '$11.25'],
                ['Gemini 2.5 Flash Lite — voice LLM', '$1.01'],
                ['Gemini audio STT (300 min)', '$0.58'],
                ['Google Cloud TTS Neural2 (300 min)', '$2.16'],
                ['Twilio inbound voice (300 min + number)', '$3.70'],
                ['Infrastructure (shared)', '$5.00'],
                ['Support, tooling, overhead', '~$3.00'],
              ].map(([label, cost]) => (
                <tr key={label}>
                  <td className="px-5 py-3 text-gray-300">{label}</td>
                  <td className="px-5 py-3 text-right text-gray-300 font-mono">{cost}</td>
                </tr>
              ))}
              <tr className="bg-white/[0.03]">
                <td className="px-5 py-3 font-semibold text-white">Our COGS</td>
                <td className="px-5 py-3 text-right font-semibold text-white font-mono">~$26.70</td>
              </tr>
              <tr className="bg-violet-500/10">
                <td className="px-5 py-3 text-violet-300">Your plan price</td>
                <td className="px-5 py-3 text-right text-violet-300 font-mono font-bold">$149</td>
              </tr>
            </tbody>
          </table>
        </div>
        <p className="text-xs text-gray-500 text-center mt-3">
          Costs shown are estimates based on published API pricing. Actual costs vary by usage pattern.
          All API costs are absorbed in the plan price — you don&apos;t pay API providers separately.
        </p>
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
        © {new Date().getFullYear()} AscenAI.{' '}
        <a href="mailto:billing@ascenai.com" className="hover:text-gray-300 transition-colors">
          billing@ascenai.com
        </a>
        {' · '}
        <a href="mailto:sales@ascenai.com" className="hover:text-gray-300 transition-colors">
          sales@ascenai.com
        </a>
      </footer>
    </main>
  )
}
