'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'

const navItems = [
  { href: '#prerequisites', label: "What You'll Need" },
  { href: '#step1', label: 'Step 1: Get Credentials' },
  { href: '#step2', label: 'Step 2: Webhooks' },
  { href: '#step3', label: 'Step 3: Twilio Pay' },
  { href: '#step4', label: 'Step 4: Connect Credentials' },
  { href: '#troubleshooting', label: 'Troubleshooting' },
]

export default function VoiceSetupPage() {
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
      {/* Navbar */}
      <nav className="flex items-center justify-between px-8 py-5 max-w-5xl mx-auto">
        <Link href="/" className="flex items-center gap-2">
          <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-violet-500 to-blue-500 flex items-center justify-center text-white font-bold text-sm">
            A
          </div>
          <span className="text-xl font-bold text-white">AscenAI</span>
        </Link>
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

      {/* Content */}
      <div className="max-w-7xl mx-auto px-8 py-16 flex gap-8">
        {/* Left sidebar */}
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

        {/* Main content */}
        <div className="flex-1 min-w-0">
          {/* Header */}
          <div className="mb-12">
            <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-blue-500/10 border border-blue-500/20 text-blue-300 text-sm mb-4">
              Documentation
            </div>
            <h1 className="text-4xl sm:text-5xl font-bold mb-4">
              Voice Channel Setup Guide
            </h1>
            <p className="text-gray-400 text-lg max-w-2xl">
              Configure Twilio to enable voice capabilities for your AI agents. Follow this guide to connect incoming phone calls to your AscenAI agents.
            </p>
          </div>

          {/* Prerequisites */}
          <div id="prerequisites" className="bg-white/[0.03] border border-white/10 rounded-2xl p-6 mb-8">
            <h2 className="text-lg font-semibold text-white mb-3">What You'll Need</h2>
            <ul className="space-y-2 text-gray-400 text-sm">
              <li className="flex items-start gap-2">
                <span className="text-violet-400 mt-0.5">&#9679;</span>
                A Twilio account (free trial available at <a href="https://www.twilio.com" target="_blank" rel="noopener noreferrer" className="text-blue-400 hover:underline">twilio.com</a>)
              </li>
              <li className="flex items-start gap-2">
                <span className="text-violet-400 mt-0.5">&#9679;</span>
                A voice-enabled Twilio phone number
              </li>
              <li className="flex items-start gap-2">
                <span className="text-violet-400 mt-0.5">&#9679;</span>
                Your Twilio Account SID and Auth Token
              </li>
              <li className="flex items-start gap-2">
                <span className="text-violet-400 mt-0.5">&#9679;</span>
                An active AscenAI subscription with Voice Support add-on (optional, for priority support)
              </li>
            </ul>
          </div>

          {/* Step 1 */}
          <section id="step1" className="mb-12">
            <div className="flex items-center gap-3 mb-6">
              <span className="flex items-center justify-center w-8 h-8 rounded-full bg-gradient-to-br from-violet-600 to-blue-600 text-white text-sm font-bold">1</span>
              <h2 className="text-2xl font-bold text-white">Get Your Twilio Credentials</h2>
            </div>

            <div className="bg-white/[0.03] border border-white/10 rounded-2xl p-6 space-y-6">
              <div>
                <h3 className="text-base font-semibold text-white mb-2">Account SID</h3>
                <p className="text-gray-400 text-sm mb-3">
                  Your Account SID uniquely identifies your Twilio account. It starts with <code className="bg-white/5 px-1.5 py-0.5 rounded text-blue-300">AC</code> followed by 32 hexadecimal characters.
                </p>
                <div className="bg-white/5 rounded-lg p-4 text-sm">
                  <p className="text-gray-300 mb-2 font-medium">Where to find it:</p>
                  <ol className="list-decimal list-inside space-y-1 text-gray-400">
                    <li>Log in to the <a href="https://console.twilio.com" target="_blank" rel="noopener noreferrer" className="text-blue-400 hover:underline">Twilio Console</a></li>
                    <li>On the Dashboard homepage, look for "Account SID" near the top</li>
                    <li>Click the eye icon to reveal, then copy it</li>
                  </ol>
                </div>
              </div>

              <div>
                <h3 className="text-base font-semibold text-white mb-2">Auth Token</h3>
                <p className="text-gray-400 text-sm mb-3">
                  Your Auth Token is like a password for your Twilio account. Keep it secure and never share it publicly.
                </p>
                <div className="bg-yellow-500/10 border border-yellow-500/20 rounded-lg p-4">
                  <p className="text-yellow-300 text-sm">
                    <strong>Security Warning:</strong> Your Auth Token grants full access to your Twilio account. If you suspect it has been compromised, regenerate it immediately in the Twilio Console.
                  </p>
                </div>
              </div>

              <div>
                <h3 className="text-base font-semibold text-white mb-2">Phone Number</h3>
                <p className="text-gray-400 text-sm mb-3">
                  You need at least one voice-enabled phone number from Twilio. This is the number customers will call to reach your AI agent.
                </p>
                <div className="bg-white/5 rounded-lg p-4 text-sm">
                  <p className="text-gray-300 mb-2 font-medium">How to buy a number:</p>
                  <ol className="list-decimal list-inside space-y-1 text-gray-400">
                    <li>In the Twilio Console, go to <strong>Phone Numbers</strong> → <strong>Manage</strong> → <strong>Buy a Number</strong></li>
                    <li>Search by country, area code, or capabilities</li>
                    <li>Ensure "Voice" is checked under capabilities</li>
                    <li>Click <strong>Buy</strong> to purchase (typically $1-15/month)</li>
                  </ol>
                </div>
              </div>
            </div>
          </section>

          {/* Step 2 */}
          <section id="step2" className="mb-12">
            <div className="flex items-center gap-3 mb-6">
              <span className="flex items-center justify-center w-8 h-8 rounded-full bg-gradient-to-br from-violet-600 to-blue-600 text-white text-sm font-bold">2</span>
              <h2 className="text-2xl font-bold text-white">Configure Twilio Webhook URLs</h2>
            </div>

            <div className="bg-white/[0.03] border border-white/10 rounded-2xl p-6 space-y-6">
              <p className="text-gray-400 text-sm">
                Twilio uses webhooks to notify AscenAI when someone calls your Twilio number. You need to configure the webhook URL in your Twilio phone number settings.
              </p>

              <div>
                <h3 className="text-base font-semibold text-white mb-2">Set the Webhook URL</h3>
                <div className="bg-white/5 rounded-lg p-4">
                  <p className="text-gray-300 mb-2 font-medium text-sm">In Twilio Console:</p>
                  <ol className="list-decimal list-inside space-y-1 text-gray-400 text-sm">
                    <li>Go to <strong>Phone Numbers</strong> → <strong>Manage</strong> → <strong>Active Numbers</strong></li>
                    <li>Click on the phone number you want to configure</li>
                    <li>Scroll down to the <strong>Voice & Fax</strong> section</li>
                    <li>Under "A call comes in", select <strong>Webhook</strong></li>
                    <li>Enter the webhook URL provided by AscenAI (found in your dashboard under Voice settings)</li>
                    <li>Set the HTTP method to <strong>HTTP POST</strong></li>
                    <li>Click <strong>Save</strong> at the bottom</li>
                  </ol>
                </div>
              </div>

              <div>
                <h3 className="text-base font-semibold text-white mb-2">Webhook URL Format</h3>
                <p className="text-gray-400 text-sm mb-2">
                  The webhook URL typically follows this pattern:
                </p>
                <div className="bg-black/30 rounded-lg p-3 font-mono text-sm text-green-400">
                  https://api.ascenai.com/v1/voice/twilio/webhook/{'{your_tenant_id}'}
                </div>
                <p className="text-gray-500 text-xs mt-2">
                  You can find your exact webhook URL in the AscenAI dashboard under Settings → Voice Channels.
                </p>
              </div>

              <div>
                <h3 className="text-base font-semibold text-white mb-2">Status Callback URL (Optional)</h3>
                <p className="text-gray-400 text-sm mb-2">
                  For call analytics and logging, configure the Status Callback URL:
                </p>
                <div className="bg-black/30 rounded-lg p-3 font-mono text-sm text-green-400">
                  https://api.ascenai.com/v1/voice/twilio/callback/{'{your_tenant_id}'}
                </div>
              </div>
            </div>
          </section>

          {/* Step 3 */}
          <section id="step3" className="mb-12">
            <div className="flex items-center gap-3 mb-6">
              <span className="flex items-center justify-center w-8 h-8 rounded-full bg-gradient-to-br from-violet-600 to-blue-600 text-white text-sm font-bold">3</span>
              <h2 className="text-2xl font-bold text-white">Set Up Twilio Pay for Payments</h2>
            </div>

            <div className="bg-white/[0.03] border border-white/10 rounded-2xl p-6 space-y-6">
              <p className="text-gray-400 text-sm">
                Twilio Pay allows your AI agent to securely collect credit card payments over the phone using DTMF tones (keypad presses). This is useful for order confirmations, service payments, and subscription renewals.
              </p>

              <div>
                <h3 className="text-base font-semibold text-white mb-2">Enable Twilio Pay</h3>
                <div className="bg-white/5 rounded-lg p-4 text-sm">
                  <ol className="list-decimal list-inside space-y-1 text-gray-400">
                    <li>In the Twilio Console, go to <strong>Explore Products</strong> → <strong>Pay</strong></li>
                    <li>Click <strong>Get Started</strong> to enable the Pay product</li>
                    <li>Connect your payment processor (Stripe is recommended)</li>
                    <li>Complete the PCI compliance questionnaire</li>
                  </ol>
                </div>
              </div>

              <div>
                <h3 className="text-base font-semibold text-white mb-2">Connect Stripe</h3>
                <div className="bg-white/5 rounded-lg p-4 text-sm">
                  <ol className="list-decimal list-inside space-y-1 text-gray-400">
                    <li>In the Twilio Pay setup, select <strong>Stripe</strong> as your payment processor</li>
                    <li>You'll be redirected to Stripe to authorize the connection</li>
                    <li>Log in to your Stripe account or create one</li>
                    <li>Authorize Twilio to process payments through your Stripe account</li>
                  </ol>
                </div>
              </div>

              <div className="bg-blue-500/10 border border-blue-500/20 rounded-lg p-4">
                <p className="text-blue-300 text-sm">
                  <strong>Note:</strong> Twilio Pay uses secure DTMF tone collection. Card numbers are never transmitted through AscenAI's servers — they go directly from the caller's keypad to your payment processor. This ensures PCI compliance.
                </p>
              </div>

              <div>
                <h3 className="text-base font-semibold text-white mb-2">Configure Payment Amounts</h3>
                <p className="text-gray-400 text-sm mb-2">
                  Payment amounts and triggers are configured in your AscenAI agent's playbook. You can set:
                </p>
                <ul className="list-disc list-inside space-y-1 text-gray-400 text-sm ml-4">
                  <li>Fixed amounts (e.g., "$50 consultation fee")</li>
                  <li>Dynamic amounts based on order details</li>
                  <li>Recurring payment authorizations</li>
                </ul>
              </div>
            </div>
          </section>

          {/* Step 4 */}
          <section id="step4" className="mb-12">
            <div className="flex items-center gap-3 mb-6">
              <span className="flex items-center justify-center w-8 h-8 rounded-full bg-gradient-to-br from-violet-600 to-blue-600 text-white text-sm font-bold">4</span>
              <h2 className="text-2xl font-bold text-white">Connect Credentials in AscenAI</h2>
            </div>

            <div className="bg-white/[0.03] border border-white/10 rounded-2xl p-6 space-y-6">
              <p className="text-gray-400 text-sm">
                Once you have your Twilio credentials, add them to your AscenAI dashboard.
              </p>

              <div className="bg-white/5 rounded-lg p-4 text-sm">
                <ol className="list-decimal list-inside space-y-1 text-gray-400">
                  <li>Log in to your <Link href="/login" className="text-blue-400 hover:underline">AscenAI dashboard</Link></li>
                  <li>Navigate to <strong>Settings</strong> → <strong>Voice Channels</strong></li>
                  <li>Enter your <strong>Account SID</strong>, <strong>Auth Token</strong>, and <strong>Phone Number</strong></li>
                  <li>Click <strong>Save & Test Connection</strong></li>
                  <li>If the test succeeds, your voice channel is ready</li>
                </ol>
              </div>

              <div className="bg-green-500/10 border border-green-500/20 rounded-lg p-4">
                <p className="text-green-300 text-sm">
                  <strong>Success!</strong> After saving, test by calling your Twilio number. You should hear your AI agent's greeting. If not, check the troubleshooting section below.
                </p>
              </div>
            </div>
          </section>

          {/* Troubleshooting */}
          <section id="troubleshooting" className="mb-12">
            <div className="flex items-center gap-3 mb-6">
              <span className="flex items-center justify-center w-8 h-8 rounded-full bg-gradient-to-br from-red-600 to-orange-600 text-white text-sm font-bold">?</span>
              <h2 className="text-2xl font-bold text-white">Troubleshooting</h2>
            </div>

            <div className="space-y-4">
              {/* Issue 1 */}
              <div className="bg-white/[0.03] border border-white/10 rounded-2xl p-6">
                <h3 className="text-base font-semibold text-white mb-2">I'm getting "Invalid Account SID" error</h3>
                <p className="text-gray-400 text-sm mb-2">
                  This usually means the Account SID was copied incorrectly.
                </p>
                <ul className="list-disc list-inside space-y-1 text-gray-400 text-sm ml-4">
                  <li>Ensure the SID starts with <code className="bg-white/5 px-1 rounded">AC</code></li>
                  <li>Check for extra spaces at the beginning or end</li>
                  <li>Verify you're using the SID from the correct Twilio account (not a sub-account)</li>
                </ul>
              </div>

              {/* Issue 2 */}
              <div className="bg-white/[0.03] border border-white/10 rounded-2xl p-6">
                <h3 className="text-base font-semibold text-white mb-2">Calls connect but I hear silence</h3>
                <p className="text-gray-400 text-sm mb-2">
                  This typically indicates a webhook configuration issue.
                </p>
                <ul className="list-disc list-inside space-y-1 text-gray-400 text-sm ml-4">
                  <li>Verify the webhook URL is correctly set in your Twilio phone number settings</li>
                  <li>Ensure the HTTP method is set to <strong>POST</strong></li>
                  <li>Check that your AscenAI voice channel is enabled and connected</li>
                  <li>Check Twilio's call logs in the Console for error details</li>
                </ul>
              </div>

              {/* Issue 3 */}
              <div className="bg-white/[0.03] border border-white/10 rounded-2xl p-6">
                <h3 className="text-base font-semibold text-white mb-2">"Authentication Error" in Twilio logs</h3>
                <p className="text-gray-400 text-sm mb-2">
                  Your Auth Token may be incorrect or expired.
                </p>
                <ul className="list-disc list-inside space-y-1 text-gray-400 text-sm ml-4">
                  <li>Re-copy the Auth Token from the Twilio Console</li>
                  <li>If you recently regenerated your token, update it in AscenAI</li>
                  <li>Ensure you're not using the test credentials (they start with <code className="bg-white/5 px-1 rounded">SK</code>)</li>
                </ul>
              </div>

              {/* Issue 4 */}
              <div className="bg-white/[0.03] border border-white/10 rounded-2xl p-6">
                <h3 className="text-base font-semibold text-white mb-2">Twilio Pay is not collecting payments</h3>
                <p className="text-gray-400 text-sm mb-2">
                  Verify your payment integration is properly configured.
                </p>
                <ul className="list-disc list-inside space-y-1 text-gray-400 text-sm ml-4">
                  <li>Confirm Twilio Pay is enabled in your Twilio account</li>
                  <li>Verify your Stripe account is connected and active</li>
                  <li>Check that your agent's playbook includes payment collection steps</li>
                  <li>Ensure the caller is using a touch-tone phone (DTMF capable)</li>
                </ul>
              </div>

              {/* Issue 5 */}
              <div className="bg-white/[0.03] border border-white/10 rounded-2xl p-6">
                <h3 className="text-base font-semibold text-white mb-2">High latency or poor audio quality</h3>
                <p className="text-gray-400 text-sm mb-2">
                  Audio quality issues can stem from network or configuration problems.
                </p>
                <ul className="list-disc list-inside space-y-1 text-gray-400 text-sm ml-4">
                  <li>Check your internet connection stability</li>
                  <li>Ensure your Twilio number is in a region close to your customers</li>
                  <li>Consider upgrading to a Twilio Elastic SIP Trunking for better quality</li>
                  <li>Contact AscenAI support if the issue persists</li>
                </ul>
              </div>
            </div>
          </section>

          {/* CTA */}
          <div className="bg-gradient-to-r from-violet-600/20 to-blue-600/20 border border-violet-500/20 rounded-2xl p-8 text-center">
            <h3 className="text-xl font-bold text-white mb-2">Need Help?</h3>
            <p className="text-gray-400 text-sm mb-6 max-w-lg mx-auto">
              If you're stuck or need assistance with your voice channel setup, our support team is here to help. 
              Upgrade to the Voice Support add-on for priority assistance.
            </p>
            <div className="flex flex-col sm:flex-row gap-3 justify-center">
              <Link
                href="/login"
                className="px-6 py-3 rounded-xl bg-gradient-to-r from-violet-600 to-blue-600 text-white font-medium hover:opacity-90 transition-opacity text-sm"
              >
                Go to Dashboard
              </Link>
              <Link
                href="/pricing"
                className="px-6 py-3 rounded-xl border border-white/10 text-white font-medium hover:bg-white/5 transition-colors text-sm"
              >
                View Pricing
              </Link>
            </div>
          </div>
        </div>
      </div>

      {/* Footer */}
      <footer className="border-t border-white/5 py-8 text-center text-gray-500 text-sm">
        © {new Date().getFullYear()} AscenAI. Built with FastAPI, Next.js, and Gemini.{' '}
        <Link href="/" className="hover:text-gray-300 transition-colors">Home</Link>
        {' · '}
        <Link href="/pricing" className="hover:text-gray-300 transition-colors">Pricing</Link>
      </footer>
    </main>
  )
}
