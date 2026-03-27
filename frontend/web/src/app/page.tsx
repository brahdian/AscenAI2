import Link from 'next/link'

export default function HomePage() {
  return (
    <main className="min-h-screen bg-gradient-to-br from-[#0f0728] via-[#1a1040] to-[#0c1e4a] text-white">
      {/* Navbar */}
      <nav className="flex items-center justify-between px-8 py-5 max-w-7xl mx-auto">
        <div className="flex items-center gap-2">
          <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-violet-500 to-blue-500 flex items-center justify-center text-white font-bold text-sm">
            A
          </div>
          <span className="text-xl font-bold text-white">AscenAI</span>
        </div>
        <div className="flex items-center gap-4">
          <Link href="/pricing" className="text-gray-300 hover:text-white transition-colors text-sm">
            Pricing
          </Link>
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

      {/* Hero */}
      <section className="max-w-7xl mx-auto px-8 pt-24 pb-32 text-center">
        <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-violet-500/10 border border-violet-500/20 text-violet-300 text-sm mb-8">
          <span className="w-2 h-2 rounded-full bg-green-400 animate-pulse" />
          From $49/agent/month · no hidden fees
        </div>
        <h1 className="text-5xl sm:text-7xl font-bold mb-6 leading-tight">
          AI Agents that{' '}
          <span className="bg-gradient-to-r from-violet-400 to-blue-400 bg-clip-text text-transparent">
            grow your business
          </span>
        </h1>
        <p className="text-gray-400 text-lg sm:text-xl max-w-2xl mx-auto mb-10">
          Deploy intelligent voice and chat agents for your restaurant, clinic, or salon.
          Handle bookings, orders, and customer queries automatically — 24/7.
        </p>
        <div className="flex flex-col sm:flex-row gap-4 justify-center">
          <Link
            href="/register"
            className="px-8 py-4 rounded-xl bg-gradient-to-r from-violet-600 to-blue-600 text-white font-semibold hover:opacity-90 transition-all hover:shadow-[0_0_30px_rgba(124,58,237,0.5)]"
          >
            Get started — from $49/agent/month
          </Link>
          <Link
            href="/pricing"
            className="px-8 py-4 rounded-xl border border-white/10 text-white font-semibold hover:bg-white/5 transition-colors"
          >
            View pricing
          </Link>
        </div>
      </section>

      {/* Features */}
      <section className="max-w-7xl mx-auto px-8 pb-32">
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-6">
          {[
            {
              icon: '🎙️',
              title: 'Voice-first AI',
              desc: 'Real-time voice conversations with sub-200ms latency. Powered by Gemini audio and Google Cloud TTS with Twilio phone integration.',
            },
            {
              icon: '📚',
              title: 'Knowledge Base & Playbooks',
              desc: 'Upload documents your agent references. Set multiple playbooks with intent triggers for automatic routing.',
            },
            {
              icon: '🏢',
              title: 'Multi-tenant SaaS',
              desc: 'Enterprise-grade isolation: each business gets its own agents, guardrails, team members, and billing.',
            },
          ].map((f) => (
            <div
              key={f.title}
              className="p-6 rounded-2xl border border-white/5 bg-white/[0.02] backdrop-blur-sm hover:border-violet-500/30 transition-colors"
            >
              <div className="text-3xl mb-3">{f.icon}</div>
              <h3 className="text-white font-semibold text-lg mb-2">{f.title}</h3>
              <p className="text-gray-400 text-sm">{f.desc}</p>
            </div>
          ))}
        </div>
      </section>

      {/* Footer */}
      <footer className="border-t border-white/5 py-8 text-center text-gray-500 text-sm">
        © {new Date().getFullYear()} AscenAI. Built with FastAPI, Next.js, and Gemini.{' '}
        <Link href="/pricing" className="hover:text-gray-300 transition-colors">Pricing</Link>
      </footer>
    </main>
  )
}
