'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'

const navItems = [
  { href: '#why-add', label: 'Why Add Team Members?' },
  { href: '#adding', label: 'Adding Members' },
  { href: '#roles', label: 'Roles & Permissions' },
  { href: '#comparison', label: 'Role Comparison' },
  { href: '#api-keys', label: 'API Keys' },
  { href: '#scenarios', label: 'Common Scenarios' },
  { href: '#transferring', label: 'Transferring Ownership' },
  { href: '#security', label: 'Security Best Practices' },
]

export default function TeamPage() {
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
            <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-blue-500/10 border border-blue-500/20 text-blue-300 text-sm mb-4">Documentation</div>
            <h1 className="text-4xl sm:text-5xl font-bold mb-4">Team & Permissions</h1>
            <p className="text-gray-400 text-lg max-w-2xl">Invite your team to collaborate on building and managing your AI agents.</p>
          </div>

          <section id="why-add" className="mb-12">
            <div className="bg-white/[0.03] border border-white/10 rounded-2xl p-6">
              <h2 className="text-lg font-semibold text-white mb-3">Why Add Team Members?</h2>
              <p className="text-gray-400 text-sm mb-3">Your AI agent is only as good as the information and effort you put into it. Adding team members lets you:</p>
              <ul className="space-y-2 text-gray-400 text-sm">
                <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span>Share the workload of building and improving your agent</li>
                <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span>Let subject matter experts contribute knowledge</li>
                <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span>Give developers access to set up integrations without full account access</li>
                <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span>Keep an eye on performance with viewer access for managers</li>
              </ul>
            </div>
          </section>

          <section id="adding" className="mb-12">
            <h2 className="text-2xl font-bold text-white mb-6">Adding Team Members</h2>
            <div className="bg-white/[0.03] border border-white/10 rounded-2xl p-6 space-y-4">
              <ol className="list-decimal list-inside space-y-3 text-gray-400 text-sm">
                <li><strong>Go to Team Settings</strong> - In your dashboard, click "Settings" in the left sidebar, then the "Team" tab</li>
                <li><strong>Invite a Member</strong> - Click "Invite Member", enter the person's email, choose their role, and click "Send Invitation"</li>
                <li><strong>They Accept</strong> - The person receives an email invitation with a link to join your workspace</li>
              </ol>
              <div className="bg-white/5 rounded-lg p-4">
                <p className="text-gray-300 text-sm font-medium mb-2">Managing Existing Members:</p>
                <ul className="space-y-1 text-gray-400 text-sm">
                  <li><strong>Change role</strong> - Click the dropdown next to their name and select a new role</li>
                  <li><strong>Remove member</strong> - Click the three dots next to their name and select "Remove"</li>
                  <li><strong>Resend invitation</strong> - If they haven't accepted, click "Resend Invitation"</li>
                </ul>
              </div>
            </div>
          </section>

          <section id="roles" className="mb-12">
            <h2 className="text-2xl font-bold text-white mb-6">Roles and Permissions</h2>
            <div className="space-y-4">
              <div className="bg-white/[0.03] border border-white/10 rounded-2xl p-6">
                <h3 className="text-base font-semibold text-white mb-2">Owner</h3>
                <p className="text-gray-400 text-sm mb-2">The owner has full control over everything in the account. There can only be one owner per account.</p>
                <div className="bg-white/5 rounded-lg p-4">
                  <p className="text-gray-300 text-sm font-medium mb-1">Who Should Be an Owner:</p>
                  <ul className="text-gray-400 text-sm space-y-1">
                    <li>The business owner</li>
                    <li>The person who pays for the account</li>
                    <li>The primary decision-maker for the AI agent strategy</li>
                  </ul>
                </div>
              </div>
              <div className="bg-white/[0.03] border border-white/10 rounded-2xl p-6">
                <h3 className="text-base font-semibold text-white mb-2">Admin</h3>
                <p className="text-gray-400 text-sm mb-2">Admins have nearly full control, with a few restrictions. They cannot delete the account, change the owner, change payment methods, or invite other admins.</p>
                <div className="bg-white/5 rounded-lg p-4">
                  <p className="text-gray-300 text-sm font-medium mb-1">Who Should Be an Admin:</p>
                  <ul className="text-gray-400 text-sm space-y-1">
                    <li>Marketing managers</li>
                    <li>Operations managers</li>
                    <li>Senior team members who manage the agent day-to-day</li>
                  </ul>
                </div>
              </div>
              <div className="bg-white/[0.03] border border-white/10 rounded-2xl p-6">
                <h3 className="text-base font-semibold text-white mb-2">Developer</h3>
                <p className="text-gray-400 text-sm mb-2">Developers have technical access for setting up integrations. They cannot manage team members, access billing, delete agents, or export data.</p>
                <div className="bg-white/5 rounded-lg p-4">
                  <p className="text-gray-300 text-sm font-medium mb-1">Who Should Be a Developer:</p>
                  <ul className="text-gray-400 text-sm space-y-1">
                    <li>Web developers who embed the widget</li>
                    <li>IT staff who set up integrations</li>
                    <li>Freelancers or agencies managing your technical setup</li>
                  </ul>
                </div>
              </div>
              <div className="bg-white/[0.03] border border-white/10 rounded-2xl p-6">
                <h3 className="text-base font-semibold text-white mb-2">Viewer</h3>
                <p className="text-gray-400 text-sm mb-2">Viewers can see everything but change nothing. They can view agents, playbooks, tools, chat history, and analytics.</p>
                <div className="bg-white/5 rounded-lg p-4">
                  <p className="text-gray-300 text-sm font-medium mb-1">Who Should Be a Viewer:</p>
                  <ul className="text-gray-400 text-sm space-y-1">
                    <li>Business partners who want to monitor performance</li>
                    <li>Managers who review customer interactions</li>
                    <li>Consultants who audit your AI agent performance</li>
                    <li>New team members who are learning the system</li>
                  </ul>
                </div>
              </div>
            </div>
          </section>

          <section id="comparison" className="mb-12">
            <h2 className="text-2xl font-bold text-white mb-6">Role Comparison Table</h2>
            <div className="bg-white/[0.03] border border-white/10 rounded-2xl p-6 overflow-x-auto">
              <table className="w-full text-sm text-gray-400">
                <thead>
                  <tr className="border-b border-white/10">
                    <th className="text-left py-2 pr-4 text-white font-medium">Permission</th>
                    <th className="text-center py-2 pr-4 text-white font-medium">Owner</th>
                    <th className="text-center py-2 pr-4 text-white font-medium">Admin</th>
                    <th className="text-center py-2 pr-4 text-white font-medium">Developer</th>
                    <th className="text-center py-2 text-white font-medium">Viewer</th>
                  </tr>
                </thead>
                <tbody>
                  {[
                    ['Create/edit agents', 'Yes', 'Yes', 'Yes', 'No'],
                    ['Delete agents', 'Yes', 'Yes', 'No', 'No'],
                    ['Manage playbooks', 'Yes', 'Yes', 'Yes', 'No'],
                    ['Connect tools', 'Yes', 'Yes', 'Yes', 'No'],
                    ['Manage team', 'Yes', 'Partial', 'No', 'No'],
                    ['View billing', 'Yes', 'View only', 'No', 'No'],
                    ['Change payment', 'Yes', 'No', 'No', 'No'],
                    ['Manage API keys', 'Yes', 'Yes', 'Yes', 'No'],
                    ['View chat history', 'Yes', 'Yes', 'Yes', 'Yes'],
                    ['View analytics', 'Yes', 'Yes', 'Yes', 'Yes'],
                    ['Export data', 'Yes', 'Yes', 'No', 'Partial'],
                    ['Delete account', 'Yes', 'No', 'No', 'No'],
                  ].map((row, i) => (
                    <tr key={i} className="border-b border-white/5">
                      <td className="py-2 pr-4 text-white text-sm">{row[0]}</td>
                      {row.slice(1).map((cell, j) => (
                        <td key={j} className={`py-2 text-center ${j === 3 ? '' : 'pr-4'}`}>
                          <span className={cell === 'Yes' ? 'text-green-400' : cell === 'No' ? 'text-red-400' : 'text-yellow-400'}>{cell}</span>
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <section id="api-keys" className="mb-12">
            <h2 className="text-2xl font-bold text-white mb-6">Managing API Keys</h2>
            <div className="bg-white/[0.03] border border-white/10 rounded-2xl p-6 space-y-4">
              <p className="text-gray-400 text-sm">API keys allow external systems to interact with your AscenAI2 account. They're used for custom integrations, webhooks, and connecting to other software.</p>
              <div className="bg-white/5 rounded-lg p-4">
                <p className="text-gray-300 text-sm font-medium mb-2">Creating an API Key:</p>
                <ol className="list-decimal list-inside space-y-1 text-gray-400 text-sm">
                  <li>Go to <strong>Settings</strong> &gt; <strong>API Keys</strong></li>
                  <li>Click <strong>"Create API Key"</strong></li>
                  <li>Give the key a name and choose permissions (Read only or Read and write)</li>
                  <li>Click <strong>"Create"</strong> and copy the key immediately - you won't be able to see it again</li>
                </ol>
              </div>
              <div className="bg-white/5 rounded-lg p-4">
                <p className="text-gray-300 text-sm font-medium mb-2">Best Practices:</p>
                <ul className="space-y-1 text-gray-400 text-sm">
                  <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span>Name keys clearly so you know what each one is used for</li>
                  <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span>Use read-only when possible</li>
                  <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span>Rotate keys regularly</li>
                  <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span>Never share keys publicly</li>
                  <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span>Delete unused keys</li>
                </ul>
              </div>
            </div>
          </section>

          <section id="scenarios" className="mb-12">
            <h2 className="text-2xl font-bold text-white mb-6">Common Team Scenarios</h2>
            <div className="space-y-4">
              <div className="bg-white/[0.03] border border-white/10 rounded-2xl p-6">
                <h3 className="text-base font-semibold text-white mb-2">Small Business Owner + Receptionist</h3>
                <p className="text-gray-400 text-sm"><strong>Owner:</strong> Business owner | <strong>Viewer:</strong> Receptionist</p>
                <p className="text-gray-400 text-sm mt-1">The owner sets up and manages the agent. The receptionist can view chat history to see what customers are asking.</p>
              </div>
              <div className="bg-white/[0.03] border border-white/10 rounded-2xl p-6">
                <h3 className="text-base font-semibold text-white mb-2">Restaurant + Web Developer</h3>
                <p className="text-gray-400 text-sm"><strong>Owner:</strong> Restaurant owner | <strong>Admin:</strong> Restaurant manager | <strong>Developer:</strong> Web developer</p>
                <p className="text-gray-400 text-sm mt-1">The owner manages the account. The manager handles day-to-day improvements. The developer embeds the widget and sets up payment integrations.</p>
              </div>
              <div className="bg-white/[0.03] border border-white/10 rounded-2xl p-6">
                <h3 className="text-base font-semibold text-white mb-2">Marketing Agency + Client</h3>
                <p className="text-gray-400 text-sm"><strong>Owner:</strong> Agency account | <strong>Admin:</strong> Agency account manager | <strong>Developer:</strong> Agency developer | <strong>Viewer:</strong> Client</p>
                <p className="text-gray-400 text-sm mt-1">The agency manages everything. The client can view performance and chat history.</p>
              </div>
            </div>
          </section>

          <section id="transferring" className="mb-12">
            <h2 className="text-2xl font-bold text-white mb-6">Transferring Ownership</h2>
            <div className="bg-white/[0.03] border border-white/10 rounded-2xl p-6 space-y-4">
              <ol className="list-decimal list-inside space-y-2 text-gray-400 text-sm">
                <li>Go to <strong>Settings</strong> &gt; <strong>Team</strong></li>
                <li>Find the team member you want to make the new owner</li>
                <li>Click the three dots next to their name</li>
                <li>Click <strong>"Transfer Ownership"</strong> and confirm</li>
              </ol>
              <div className="bg-yellow-500/10 border border-yellow-500/20 rounded-lg p-4">
                <p className="text-yellow-300 text-sm"><strong>Warning:</strong> After transferring ownership, you will become an Admin. The new owner will have full control over the account.</p>
              </div>
            </div>
          </section>

          <section id="security" className="mb-12">
            <h2 className="text-2xl font-bold text-white mb-6">Security Best Practices</h2>
            <div className="bg-white/[0.03] border border-white/10 rounded-2xl p-6 space-y-4">
              <div className="bg-white/5 rounded-lg p-4">
                <p className="text-white text-sm font-medium mb-1">1. Use the Principle of Least Privilege</p>
                <p className="text-gray-400 text-sm">Give people only the access they need.</p>
              </div>
              <div className="bg-white/5 rounded-lg p-4">
                <p className="text-white text-sm font-medium mb-1">2. Review Team Access Regularly</p>
                <p className="text-gray-400 text-sm">Every few months, review your team list and remove anyone who no longer needs access.</p>
              </div>
              <div className="bg-white/5 rounded-lg p-4">
                <p className="text-white text-sm font-medium mb-1">3. Monitor API Key Usage</p>
                <p className="text-gray-400 text-sm">Check which API keys are active and what they're being used for.</p>
              </div>
              <div className="bg-white/5 rounded-lg p-4">
                <p className="text-white text-sm font-medium mb-1">4. Use Strong Passwords & Two-Factor Authentication</p>
                <p className="text-gray-400 text-sm">Make sure everyone on your team uses strong, unique passwords and enables 2FA if available.</p>
              </div>
            </div>
          </section>

          <div className="bg-gradient-to-r from-violet-600/20 to-blue-600/20 border border-violet-500/20 rounded-2xl p-8 text-center">
            <h3 className="text-xl font-bold text-white mb-2">Ready to Build Your Team?</h3>
            <p className="text-gray-400 text-sm mb-6 max-w-lg mx-auto">
              Learn about billing and compliance to ensure your team follows best practices.
            </p>
            <div className="flex flex-col sm:flex-row gap-3 justify-center">
              <Link href="/docs/billing" className="px-6 py-3 rounded-xl bg-gradient-to-r from-violet-600 to-blue-600 text-white font-medium hover:opacity-90 transition-opacity text-sm">Billing Guide</Link>
              <Link href="/docs/compliance" className="px-6 py-3 rounded-xl border border-white/10 text-white font-medium hover:bg-white/5 transition-colors text-sm">Compliance Guide</Link>
            </div>
          </div>
        </div>
      </div>

      
    </div>
  )
}
