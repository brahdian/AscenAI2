import Link from 'next/link'
import { DynamicHeroPrice } from './dynamic-price'

export default function HomePage() {
  return (
    <>

      {/* Hero */}
      <section className="max-w-7xl mx-auto px-8 pt-24 pb-32 text-center">
        <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-violet-500/10 border border-violet-500/20 text-violet-300 text-sm mb-8">
          <span className="w-2 h-2 rounded-full bg-green-400 animate-pulse" />
          <DynamicHeroPrice format="banner" /> · no setup fees · no per-resolution billing
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
            <DynamicHeroPrice format="button" />
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
      
      {/* Ecosystem Links */}
      <section className="max-w-7xl mx-auto px-8 pb-32">
        <div className="text-center mb-12">
          <h2 className="text-3xl font-bold mb-4">The Platform Ecosystem</h2>
          <p className="text-gray-400">Everything you need to manage your AI workforce.</p>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 gap-4">
          <Link href="/dashboard" className="p-6 rounded-2xl border border-white/10 bg-gradient-to-br from-violet-600/10 to-transparent hover:border-violet-500/50 transition-all group">
            <h3 className="text-lg font-bold text-white mb-1 group-hover:text-violet-400">Agent Studio →</h3>
            <p className="text-xs text-gray-500">Configure playbooks, knowledge bases, and tools.</p>
          </Link>
          <Link href="/tenant-admin/crm" className="p-6 rounded-2xl border border-white/10 bg-gradient-to-br from-blue-600/10 to-transparent hover:border-blue-500/50 transition-all group">
            <h3 className="text-lg font-bold text-white mb-1 group-hover:text-blue-400">Twenty CRM →</h3>
            <p className="text-xs text-gray-500">Manage customers, leads, and agent interactions.</p>
          </Link>
          <Link href="/tenant-admin/billing" className="p-6 rounded-2xl border border-white/10 bg-gradient-to-br from-emerald-600/10 to-transparent hover:border-emerald-500/50 transition-all group">
            <h3 className="text-lg font-bold text-white mb-1 group-hover:text-emerald-400">Billing & Usage →</h3>
            <p className="text-xs text-gray-500">Track token consumption and manage subscriptions.</p>
          </Link>
          <Link href="/admin" className="p-6 rounded-2xl border border-white/10 bg-gradient-to-br from-rose-600/10 to-transparent hover:border-rose-500/50 transition-all group">
            <h3 className="text-lg font-bold text-white mb-1 group-hover:text-rose-400">Platform Admin →</h3>
            <p className="text-xs text-gray-500">Global system health, CRM tracking, and tenants.</p>
          </Link>
        </div>
      </section>
    </>
  )
}
