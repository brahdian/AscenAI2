import Link from 'next/link'
import { Check } from 'lucide-react'

const included = [
  'Unlimited chat & voice sessions',
  'Multi-playbook intent routing',
  'RAG knowledge base (document upload)',
  'Guardrails & content filtering',
  'Conversational learning & feedback',
  'Analytics & session history',
  'Team members (unlimited seats)',
  'API access & embeddable widget',
  'Twilio phone call integration',
  'Webhook events',
  'Email & chat support',
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
      <section className="max-w-3xl mx-auto px-8 pt-20 pb-12 text-center">
        <h1 className="text-5xl font-bold mb-4">Simple, predictable pricing</h1>
        <p className="text-gray-400 text-lg">
          One flat rate per active agent. No usage caps, no hidden fees.
        </p>
      </section>

      {/* Pricing card */}
      <section className="max-w-lg mx-auto px-8 pb-20">
        <div className="rounded-2xl border border-violet-500/40 bg-white/[0.03] backdrop-blur-sm p-8 shadow-[0_0_60px_rgba(124,58,237,0.15)]">
          {/* Badge */}
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-violet-500/20 border border-violet-500/30 text-violet-300 text-xs font-medium mb-6">
            Per active agent
          </div>

          {/* Price */}
          <div className="mb-2">
            <span className="text-6xl font-bold text-white">$100</span>
            <span className="text-gray-400 text-lg ml-2">/ agent / month</span>
          </div>
          <p className="text-gray-400 text-sm mb-8">
            Billed monthly. Add or remove agents at any time — billing adjusts automatically.
          </p>

          {/* CTA */}
          <Link
            href="/register"
            className="block w-full text-center py-4 rounded-xl bg-gradient-to-r from-violet-600 to-blue-600 text-white font-semibold text-lg hover:opacity-90 transition-all hover:shadow-[0_0_30px_rgba(124,58,237,0.4)] mb-8"
          >
            Get started →
          </Link>

          {/* Divider */}
          <div className="border-t border-white/10 mb-6" />

          {/* Everything included */}
          <p className="text-sm font-semibold text-gray-300 mb-4">Everything included:</p>
          <ul className="space-y-3">
            {included.map((item) => (
              <li key={item} className="flex items-start gap-3 text-sm text-gray-300">
                <Check size={16} className="text-violet-400 flex-shrink-0 mt-0.5" />
                {item}
              </li>
            ))}
          </ul>
        </div>

        {/* Example */}
        <div className="mt-6 p-5 rounded-xl bg-white/[0.02] border border-white/5 text-sm text-gray-400">
          <p className="font-medium text-gray-300 mb-2">Example</p>
          <p>
            3 agents (a booking bot, a support bot, and a sales bot) = <span className="text-white font-semibold">$300/month</span>.
            Deactivate any agent and it stops billing immediately.
          </p>
        </div>

        {/* FAQ */}
        <div className="mt-10 space-y-5">
          {[
            {
              q: 'Is there a free trial?',
              a: 'No. AscenAI is a professional platform starting at $100/agent/month. Contact us to discuss your requirements before signing up.',
            },
            {
              q: 'What counts as an active agent?',
              a: 'Any agent with status "active" in your dashboard. Deactivating an agent stops billing for it from the next billing cycle.',
            },
            {
              q: 'What payment methods do you accept?',
              a: 'Credit card via Stripe. Enterprise invoicing is available — contact billing@ascenai.com.',
            },
            {
              q: 'Are voice minutes extra?',
              a: 'No. Voice sessions are included in the per-agent price. You only pay separately for third-party services you configure (Twilio, Google Cloud TTS, etc.).',
            },
          ].map(({ q, a }) => (
            <div key={q}>
              <p className="font-medium text-white mb-1">{q}</p>
              <p className="text-gray-400 text-sm">{a}</p>
            </div>
          ))}
        </div>
      </section>

      <footer className="border-t border-white/5 py-8 text-center text-gray-500 text-sm">
        © {new Date().getFullYear()} AscenAI.{' '}
        <a href="mailto:billing@ascenai.com" className="hover:text-gray-300 transition-colors">
          billing@ascenai.com
        </a>
      </footer>
    </main>
  )
}
