'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'

const navItems = [
  { href: '#overview', label: 'Platform CRM Overview' },
  { href: '#workspaces', label: 'Managing Workspaces' },
  { href: '#seats', label: 'Seat Limits & Billing' },
  { href: '#repair', label: 'Repairing Mappings' },
  { href: '#sso', label: 'SSO & Redis Sessions' },
]

export default function CrmDocsPage() {
  const [activeSection, setActiveSection] = useState('')

  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            setActiveSection(entry.target.id)
          }
        })
      },
      { rootMargin: '-80px 0px -60% 0px', threshold: 0 }
    )

    navItems.forEach((item) => {
      const el = document.getElementById(item.href.slice(1))
      if (el) observer.observe(el)
    })

    return () => observer.disconnect()
  }, [])

  return (
    <div className="w-full">
      <div className="max-w-7xl mx-auto px-8 py-16 flex gap-8">
        <aside className="w-60 flex-shrink-0 hidden lg:block">
          <nav className="sticky top-24 space-y-1">
            <Link href="/docs" className="flex items-center gap-1 text-sm text-gray-400 hover:text-white transition-colors mb-6">
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
              </svg>
              Back to Docs
            </Link>
            <p className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-3">On this page</p>
            {navItems.map((item) => (
              <a
                key={item.href}
                href={item.href}
                className={`block text-sm py-1 transition-colors border-l-2 pl-3 ${
                  activeSection === item.href.slice(1)
                    ? 'text-white border-violet-500'
                    : 'text-gray-400 border-transparent hover:text-white'
                }`}
              >
                {item.label}
              </a>
            ))}
          </nav>
        </aside>

        <div className="flex-1 min-w-0">
          <div className="mb-12">
            <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-blue-500/10 border border-blue-500/20 text-blue-300 text-sm mb-4">
              Documentation
            </div>
            <h1 className="text-4xl sm:text-5xl font-bold mb-4">CRM Integration</h1>
            <p className="text-gray-400 text-lg max-w-2xl">
              Learn how AscenAI seamlessly integrates with Twenty CRM to provide a unified platform for AI agent interactions and customer relationship management.
            </p>
          </div>

          <section id="overview" className="mb-12">
            <h2 className="text-2xl font-bold text-white mb-6">Platform CRM Overview</h2>
            <div className="bg-white/[0.03] border border-white/10 rounded-2xl p-6 space-y-6">
              <p className="text-gray-400 text-sm">
                AscenAI utilizes an embedded instance of <strong>Twenty CRM</strong> to handle all customer interactions, agent call logs, and support tickets.
                This provides a deep, native integration rather than relying on brittle third-party Zapier connections.
              </p>
              
              <div className="bg-white/5 rounded-lg p-4">
                <h3 className="text-sm font-semibold text-white mb-2">How it works under the hood</h3>
                <ul className="text-gray-400 text-sm space-y-2">
                  <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span><strong>Separate Databases:</strong> The AscenAI main database and Twenty CRM `core` schema run side-by-side.</li>
                  <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span><strong>Tenant Isolation:</strong> A single Twenty CRM workspace maps 1:1 with an AscenAI Tenant.</li>
                  <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span><strong>Seamless SSO:</strong> When a user clicks the "CRM" button, AscenAI injects an authentication session into Redis and securely proxies the user into Twenty, eliminating the need to log in twice.</li>
                </ul>
              </div>
            </div>
          </section>

          <section id="workspaces" className="mb-12">
            <h2 className="text-2xl font-bold text-white mb-6">Managing Workspaces</h2>
            <div className="bg-white/[0.03] border border-white/10 rounded-2xl p-6 space-y-6">
              <p className="text-gray-400 text-sm">
                Every tenant is automatically provisioned a CRM workspace when their account is created.
                Platform Administrators can monitor all global workspaces via the CRM Management Dashboard (`/admin/crm`).
              </p>
              <div>
                <h3 className="text-base font-semibold text-white mb-2">Monitoring Health</h3>
                <p className="text-gray-400 text-sm mb-3">
                  The CRM Management Dashboard provides real-time health checks of the Twenty PostgreSQL database and the Redis SSO session store.
                  If either goes offline, you will see immediate diagnostic alerts.
                </p>
              </div>
            </div>
          </section>

          <section id="seats" className="mb-12">
            <h2 className="text-2xl font-bold text-white mb-6">Seat Limits & Billing</h2>
            <div className="bg-white/[0.03] border border-white/10 rounded-2xl p-6 space-y-6">
              <p className="text-gray-400 text-sm">
                CRM access is billed on a per-seat basis depending on the user's subscription plan.
              </p>
              <div>
                <h3 className="text-base font-semibold text-white mb-2">Seat Enforcement</h3>
                <ul className="space-y-2 text-gray-400 text-sm">
                  <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span><strong>Quota Tracking:</strong> The AscenAI `Tenant.crm_seats` value dictates how many team members can access the CRM.</li>
                  <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span><strong>Overage Alerts:</strong> The `/admin/crm` dashboard cross-references the allowed quota with the actual number of users in the Twenty database (`core.workspaceMember`), instantly flagging any tenant who exceeds their limit.</li>
                </ul>
              </div>
            </div>
          </section>

          <section id="repair" className="mb-12">
            <h2 className="text-2xl font-bold text-white mb-6">Repairing Mappings</h2>
            <div className="bg-white/[0.03] border border-white/10 rounded-2xl p-6 space-y-6">
              <p className="text-gray-400 text-sm">
                Occasionally, a workspace mapping may fall out of sync if a tenant manually deletes their Twenty workspace from inside the CRM UI without notifying AscenAI.
              </p>
              <div className="bg-orange-500/10 border border-orange-500/20 rounded-lg p-4">
                <p className="text-orange-300 text-sm font-medium mb-1">Using the Repair Tool</p>
                <p className="text-gray-400 text-sm">
                  If a user reports an "Invalid CRM Workspace" error, platform admins can click the <strong>Repair Mapping</strong> button in the CRM Dashboard. 
                  This will verify the existence of the workspace in the Twenty database. If it's missing, AscenAI will gracefully unlink it, allowing the tenant to generate a fresh workspace.
                </p>
              </div>
            </div>
          </section>

          <section id="sso" className="mb-12">
            <h2 className="text-2xl font-bold text-white mb-6">SSO & Redis Sessions</h2>
            <div className="bg-white/[0.03] border border-white/10 rounded-2xl p-6 space-y-6">
              <p className="text-gray-400 text-sm">
                We utilize a zero-trust pattern for authenticating into the embedded CRM without requiring the user to manage two separate passwords.
              </p>
              <div>
                <h3 className="text-base font-semibold text-white mb-2">The Handshake Process</h3>
                <ol className="list-decimal list-inside space-y-1 text-gray-400 text-sm">
                  <li>User requests CRM access via AscenAI API.</li>
                  <li>AscenAI validates the JWT token and verifies the user has a CRM seat.</li>
                  <li>AscenAI generates a secure UUID session token.</li>
                  <li>AscenAI injects the token directly into <strong>Redis (Index 1)</strong>, which Twenty uses for its sessions.</li>
                  <li>A Set-Cookie directive is returned to the browser with the token.</li>
                  <li>The user is redirected to `/crm` and instantly logged in.</li>
                </ol>
              </div>
            </div>
          </section>

        </div>
      </div>
    </div>
  )
}
