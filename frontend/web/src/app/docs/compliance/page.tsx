'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'

const navItems = [
  { href: '#why-privacy', label: 'Why Privacy Matters' },
  { href: '#pipeda', label: 'PIPEDA (Canada)' },
  { href: '#gdpr', label: 'GDPR (Europe)' },
  { href: '#retention', label: 'Data Retention' },
  { href: '#exporting', label: 'Exporting Data' },
  { href: '#deleting', label: 'Deleting Data' },
  { href: '#consent', label: 'Customer Consent' },
  { href: '#breach', label: 'Data Breach Response' },
  { href: '#best-practices', label: 'Best Practices' },
]

export default function CompliancePage() {
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
    <main className="min-h-screen bg-gradient-to-br from-[#0f0728] via-[#1a1040] to-[#0c1e4a] text-white">
      <nav className="flex items-center justify-between px-8 py-5 max-w-5xl mx-auto">
        <Link href="/" className="flex items-center gap-2">
          <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-violet-500 to-blue-500 flex items-center justify-center text-white font-bold text-sm">A</div>
          <span className="text-xl font-bold text-white">AscenAI</span>
        </Link>
        <div className="flex items-center gap-4">
          <Link href="/pricing" className="text-gray-300 hover:text-white transition-colors text-sm">Pricing</Link>
          <Link href="/login" className="text-gray-300 hover:text-white transition-colors text-sm">Sign in</Link>
          <Link href="/register" className="px-4 py-2 rounded-lg bg-gradient-to-r from-violet-600 to-blue-600 text-white text-sm font-medium hover:opacity-90 transition-opacity">Get Started</Link>
        </div>
      </nav>

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
            <h1 className="text-4xl sm:text-5xl font-bold mb-4">Compliance & Privacy</h1>
            <p className="text-gray-400 text-lg max-w-2xl">Protect your customers' data and stay compliant with privacy laws.</p>
          </div>

          <section id="why-privacy" className="mb-12">
            <div className="bg-white/[0.03] border border-white/10 rounded-2xl p-6">
              <h2 className="text-lg font-semibold text-white mb-3">Why Privacy Matters</h2>
              <p className="text-gray-400 text-sm">Your AI agent handles customer conversations that may include personal information like names, phone numbers, email addresses, and appointment details. Protecting this information is not just good practice - it's the law in many regions. This guide covers the privacy regulations that may apply to your business and how AscenAI2 helps you comply.</p>
            </div>
          </section>

          <section id="pipeda" className="mb-12">
            <h2 className="text-2xl font-bold text-white mb-6">PIPEDA (Canadian Privacy Law)</h2>
            <div className="bg-white/[0.03] border border-white/10 rounded-2xl p-6 space-y-6">
              <p className="text-gray-400 text-sm">PIPEDA stands for the Personal Information Protection and Electronic Documents Act. It's Canada's federal privacy law for private-sector organizations. It applies to businesses of all sizes, including small businesses like dental clinics, restaurants, and salons.</p>
              <div className="space-y-4">
                {[
                  { title: '1. Consent', desc: 'You must get customer consent before collecting their personal information.', help: 'Your agent can be configured to inform customers that their conversation is being processed by an AI. You can add a consent message at the start of conversations.' },
                  { title: '2. Purpose', desc: 'You must identify the purpose for collecting personal information.', help: 'You control what information your agent collects and can configure it to only collect information necessary for the service.' },
                  { title: '3. Safeguards', desc: 'You must protect personal information with appropriate security measures.', help: 'All data is encrypted in transit and at rest. Access controls ensure only authorized team members can view conversations.' },
                  { title: '4. Access', desc: 'Customers have the right to access and correct their personal information.', help: 'You can export customer data from your dashboard and delete customer data upon request.' },
                  { title: '5. Retention', desc: 'Personal information should only be kept as long as necessary.', help: 'You can set automatic data retention periods. Old conversations can be automatically deleted.' },
                ].map((item) => (
                  <div key={item.title} className="bg-white/5 rounded-lg p-4">
                    <p className="text-white text-sm font-medium mb-1">{item.title}</p>
                    <p className="text-gray-400 text-sm mb-2">{item.desc}</p>
                    <p className="text-blue-300 text-sm"><strong>How AscenAI2 helps:</strong> {item.help}</p>
                  </div>
                ))}
              </div>
              <div className="bg-white/5 rounded-lg p-4">
                <p className="text-gray-300 text-sm font-medium mb-2">PIPEDA Compliance Checklist</p>
                <ul className="space-y-1 text-gray-400 text-sm">
                  <li>Inform customers that their conversation is handled by AI</li>
                  <li>Only collect information necessary for the service</li>
                  <li>Set appropriate data retention periods</li>
                  <li>Have a process for handling customer data access requests</li>
                  <li>Have a process for handling customer data deletion requests</li>
                  <li>Train your team on privacy responsibilities</li>
                  <li>Keep records of consent</li>
                </ul>
              </div>
            </div>
          </section>

          <section id="gdpr" className="mb-12">
            <h2 className="text-2xl font-bold text-white mb-6">GDPR (European Privacy Law)</h2>
            <div className="bg-white/[0.03] border border-white/10 rounded-2xl p-6 space-y-4">
              <p className="text-gray-400 text-sm">GDPR stands for the General Data Protection Regulation. It applies to any business that handles data of EU residents, regardless of where your business is located.</p>
              <div className="space-y-3">
                <div className="bg-white/5 rounded-lg p-4">
                  <p className="text-white text-sm font-medium mb-1">Key Requirements:</p>
                  <ul className="space-y-1 text-gray-400 text-sm">
                    <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span><strong>Lawful Basis</strong> - You must have a lawful reason to process personal data (consent, contract, legitimate interest)</li>
                    <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span><strong>Data Minimization</strong> - Only collect data that is necessary for your stated purpose</li>
                    <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span><strong>Right to Be Forgotten</strong> - Customers can request deletion of all their personal data within 30 days</li>
                    <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span><strong>Data Portability</strong> - Customers can request a copy of their data in a usable format</li>
                    <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span><strong>Breach Notification</strong> - Notify affected individuals within 72 hours if data is compromised</li>
                  </ul>
                </div>
                <div className="bg-white/5 rounded-lg p-4">
                  <p className="text-gray-300 text-sm font-medium mb-1">How AscenAI2 Helps:</p>
                  <ul className="space-y-1 text-gray-400 text-sm">
                    <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span>Data export in standard formats</li>
                    <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span>Individual or bulk data deletion</li>
                    <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span>Automatic data retention settings</li>
                    <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span>Consent message configuration</li>
                    <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span>Access controls to limit who can view data</li>
                  </ul>
                </div>
              </div>
            </div>
          </section>

          <section id="retention" className="mb-12">
            <h2 className="text-2xl font-bold text-white mb-6">Data Retention Settings</h2>
            <div className="bg-white/[0.03] border border-white/10 rounded-2xl p-6 space-y-4">
              <p className="text-gray-400 text-sm">Control how long customer conversations and data are stored.</p>
              <div>
                <h3 className="text-base font-semibold text-white mb-2">Setting Your Retention Period</h3>
                <ol className="list-decimal list-inside space-y-1 text-gray-400 text-sm">
                  <li>Go to <strong>Settings</strong> &gt; <strong>Privacy</strong> &gt; <strong>Data Retention</strong></li>
                  <li>Choose: 30 days, 90 days, 6 months, 1 year, or Indefinite</li>
                  <li>Click <strong>"Save"</strong></li>
                </ol>
              </div>
              <div>
                <h3 className="text-base font-semibold text-white mb-2">What Gets Deleted</h3>
                <ul className="space-y-1 text-gray-400 text-sm">
                  <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span>Chat conversation transcripts</li>
                  <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span>Voice call recordings</li>
                  <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span>Customer contact information from conversations</li>
                </ul>
                <p className="text-gray-400 text-sm mt-2"><strong>NOT deleted:</strong> Analytics data (aggregated), agent configurations, playbooks, knowledge base documents, team accounts.</p>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-sm text-gray-400">
                  <thead>
                    <tr className="border-b border-white/10">
                      <th className="text-left py-2 pr-4 text-white font-medium">Business Type</th>
                      <th className="text-left py-2 pr-4 text-white font-medium">Recommended</th>
                      <th className="text-left py-2 text-white font-medium">Reason</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr className="border-b border-white/5"><td className="py-2 pr-4">Dental clinic</td><td className="py-2 pr-4">1 year</td><td className="py-2">Patient records may be needed for follow-up</td></tr>
                    <tr className="border-b border-white/5"><td className="py-2 pr-4">Restaurant</td><td className="py-2 pr-4">30 days</td><td className="py-2">Orders and inquiries are short-term</td></tr>
                    <tr className="border-b border-white/5"><td className="py-2 pr-4">Hair salon</td><td className="py-2 pr-4">90 days</td><td className="py-2">Appointment history useful for scheduling</td></tr>
                    <tr className="border-b border-white/5"><td className="py-2 pr-4">Law firm</td><td className="py-2 pr-4">1 year+</td><td className="py-2">Client matters may require record keeping</td></tr>
                    <tr><td className="py-2 pr-4">Retail store</td><td className="py-2 pr-4">90 days</td><td className="py-2">Order history for returns and support</td></tr>
                  </tbody>
                </table>
              </div>
            </div>
          </section>

          <section id="exporting" className="mb-12">
            <h2 className="text-2xl font-bold text-white mb-6">Exporting Your Data</h2>
            <div className="bg-white/[0.03] border border-white/10 rounded-2xl p-6 space-y-4">
              <div>
                <h3 className="text-base font-semibold text-white mb-2">What You Can Export</h3>
                <ul className="space-y-1 text-gray-400 text-sm">
                  <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span><strong>Chat History</strong> - All conversation transcripts, timestamps, satisfaction ratings</li>
                  <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span><strong>Voice Call History</strong> - Recordings, duration, transcripts</li>
                  <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span><strong>Customer Data</strong> - Names, emails, phone numbers, booking history</li>
                  <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span><strong>Analytics</strong> - Volume trends, common topics, satisfaction trends</li>
                </ul>
              </div>
              <div>
                <h3 className="text-base font-semibold text-white mb-2">How to Export</h3>
                <ol className="list-decimal list-inside space-y-1 text-gray-400 text-sm">
                  <li>Go to <strong>Settings</strong> &gt; <strong>Privacy</strong> &gt; <strong>Export Data</strong></li>
                  <li>Choose what data to export and the date range</li>
                  <li>Choose format: <strong>CSV</strong> (for spreadsheets) or <strong>JSON</strong> (for technical use)</li>
                  <li>Click <strong>"Export"</strong> - you'll receive an email when ready</li>
                </ol>
              </div>
            </div>
          </section>

          <section id="deleting" className="mb-12">
            <h2 className="text-2xl font-bold text-white mb-6">Deleting Customer Data</h2>
            <div className="bg-white/[0.03] border border-white/10 rounded-2xl p-6 space-y-4">
              <div>
                <h3 className="text-base font-semibold text-white mb-2">Deleting Individual Customer Data</h3>
                <ol className="list-decimal list-inside space-y-1 text-gray-400 text-sm">
                  <li>Go to <strong>Chat History</strong> and search for the customer</li>
                  <li>Click on a conversation with that customer</li>
                  <li>Click the three dots &gt; <strong>"Delete Customer Data"</strong></li>
                </ol>
              </div>
              <div>
                <h3 className="text-base font-semibold text-white mb-2">Deleting All Data</h3>
                <ol className="list-decimal list-inside space-y-1 text-gray-400 text-sm">
                  <li>Go to <strong>Settings</strong> &gt; <strong>Privacy</strong> &gt; <strong>Delete All Data</strong></li>
                  <li>Type "DELETE ALL DATA" to confirm</li>
                  <li>Click <strong>"Delete"</strong></li>
                </ol>
                <div className="bg-red-500/10 border border-red-500/20 rounded-lg p-4 mt-3">
                  <p className="text-red-300 text-sm"><strong>Warning:</strong> This cannot be undone. All conversation transcripts, voice recordings, and customer contact information will be permanently deleted.</p>
                </div>
              </div>
            </div>
          </section>

          <section id="consent" className="mb-12">
            <h2 className="text-2xl font-bold text-white mb-6">Customer Consent</h2>
            <div className="bg-white/[0.03] border border-white/10 rounded-2xl p-6 space-y-4">
              <div>
                <h3 className="text-base font-semibold text-white mb-2">Adding Consent Messages</h3>
                <ol className="list-decimal list-inside space-y-1 text-gray-400 text-sm">
                  <li>Go to your <strong>Agent Settings</strong> &gt; <strong>Privacy</strong> tab</li>
                  <li>Toggle <strong>"Show consent message"</strong> to on</li>
                  <li>Customize the consent message</li>
                </ol>
              </div>
              <div className="space-y-3">
                <div className="bg-white/5 rounded-lg p-4">
                  <p className="text-gray-300 text-sm font-medium mb-1">Chat Example:</p>
                  <p className="text-gray-400 text-sm">"Hi! I'm an AI assistant for [Business]. Your conversation with me is processed securely to help answer your questions. By continuing, you consent to this processing. How can I help you today?"</p>
                </div>
                <div className="bg-white/5 rounded-lg p-4">
                  <p className="text-gray-300 text-sm font-medium mb-1">Voice Example:</p>
                  <p className="text-gray-400 text-sm">"Thank you for calling [Business]. This call is handled by an AI assistant. Your conversation is processed securely to help serve you. How can I help you today?"</p>
                </div>
              </div>
            </div>
          </section>

          <section id="breach" className="mb-12">
            <h2 className="text-2xl font-bold text-white mb-6">Data Breach Response</h2>
            <div className="bg-white/[0.03] border border-white/10 rounded-2xl p-6 space-y-4">
              <div className="bg-white/5 rounded-lg p-4">
                <p className="text-white text-sm font-medium mb-1">Immediate Steps:</p>
                <ol className="list-decimal list-inside space-y-1 text-gray-400 text-sm">
                  <li>Don't panic - AscenAI2 has security measures in place</li>
                  <li>Contact support: email <a href="mailto:security@ascenai.com" className="text-blue-400 hover:underline">security@ascenai.com</a> immediately</li>
                  <li>Document what happened - write down what you noticed and when</li>
                  <li>Don't delete evidence - keep any logs or screenshots</li>
                </ol>
              </div>
              <div>
                <h3 className="text-base font-semibold text-white mb-2">Your Obligations</h3>
                <ul className="space-y-1 text-gray-400 text-sm">
                  <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span><strong>PIPEDA</strong> - Report breaches to the Privacy Commissioner if there's a real risk of significant harm</li>
                  <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span><strong>GDPR</strong> - Report breaches to your supervisory authority within 72 hours</li>
                  <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span><strong>Both</strong> - Notify affected individuals if there's a risk to their rights and freedoms</li>
                </ul>
              </div>
            </div>
          </section>

          <section id="best-practices" className="mb-12">
            <h2 className="text-2xl font-bold text-white mb-6">Privacy Best Practices</h2>
            <div className="bg-white/[0.03] border border-white/10 rounded-2xl p-6 space-y-4">
              {[
                { num: '1', title: 'Collect Only What You Need', desc: "Don't ask customers for information you don't need." },
                { num: '2', title: 'Be Transparent', desc: "Tell customers when they're talking to an AI and what information you're collecting." },
                { num: '3', title: 'Set Appropriate Retention', desc: "Don't keep customer data longer than necessary." },
                { num: '4', title: 'Train Your Team', desc: 'Make sure everyone who has access to customer data understands their responsibilities.' },
                { num: '5', title: 'Have a Process', desc: 'Have a clear process for handling customer data requests (access, deletion, correction).' },
                { num: '6', title: 'Review Regularly', desc: 'Review your privacy settings and practices at least annually.' },
              ].map((item) => (
                <div key={item.num} className="bg-white/5 rounded-lg p-4 flex items-start gap-3">
                  <span className="flex items-center justify-center w-6 h-6 rounded-full bg-gradient-to-br from-violet-600 to-blue-600 text-white text-xs font-bold flex-shrink-0 mt-0.5">{item.num}</span>
                  <div>
                    <p className="text-white text-sm font-medium">{item.title}</p>
                    <p className="text-gray-400 text-sm">{item.desc}</p>
                  </div>
                </div>
              ))}
            </div>
          </section>

          <div className="bg-white/[0.03] border border-white/10 rounded-2xl p-6 mb-12">
            <h2 className="text-lg font-semibold text-white mb-3">AscenAI2's Privacy Commitments</h2>
            <ul className="space-y-2 text-gray-400 text-sm">
              <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span><strong>Encryption</strong> - All data is encrypted in transit and at rest</li>
              <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span><strong>Access controls</strong> - Only authorized personnel can access infrastructure</li>
              <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span><strong>No training on your data</strong> - Customer conversations are NOT used to train AI models</li>
              <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span><strong>Regular audits</strong> - Systems are regularly audited for security and compliance</li>
              <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span><strong>Data Processing Agreement</strong> - Available for customers who need one</li>
            </ul>
          </div>

          <div className="bg-gradient-to-r from-violet-600/20 to-blue-600/20 border border-violet-500/20 rounded-2xl p-8 text-center">
            <h3 className="text-xl font-bold text-white mb-2">Questions About Compliance?</h3>
            <p className="text-gray-400 text-sm mb-6 max-w-lg mx-auto">
              Contact our support team at <a href="mailto:support@ascenai.com" className="text-blue-400 hover:underline">support@ascenai.com</a> or consult with a privacy professional in your jurisdiction.
            </p>
            <div className="flex flex-col sm:flex-row gap-3 justify-center">
              <Link href="/docs/team" className="px-6 py-3 rounded-xl bg-gradient-to-r from-violet-600 to-blue-600 text-white font-medium hover:opacity-90 transition-opacity text-sm">Team Guide</Link>
              <Link href="/docs/billing" className="px-6 py-3 rounded-xl border border-white/10 text-white font-medium hover:bg-white/5 transition-colors text-sm">Billing Guide</Link>
            </div>
          </div>
        </div>
      </div>

      <footer className="border-t border-white/5 py-8 text-center text-gray-500 text-sm">
        &copy; {new Date().getFullYear()} AscenAI. Built with FastAPI, Next.js, and Gemini.{' '}
        <Link href="/" className="hover:text-gray-300 transition-colors">Home</Link>
        {' \u00b7 '}
        <Link href="/pricing" className="hover:text-gray-300 transition-colors">Pricing</Link>
      </footer>
    </main>
  )
}
