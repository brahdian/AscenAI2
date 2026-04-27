'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'

const navItems = [
  { href: '#what-are-tools', label: 'What Are Tools?' },
  { href: '#available', label: 'Available Tools' },
  { href: '#sms', label: 'SMS Notifications' },
  { href: '#email', label: 'Email Sending' },
  { href: '#calendar', label: 'Calendar Booking' },
  { href: '#payments', label: 'Payment Collection' },
  { href: '#webhooks', label: 'Webhook Calls' },
  { href: '#custom-api', label: 'Custom API' },
  { href: '#best-practices', label: 'Best Practices' },
  { href: '#troubleshooting', label: 'Troubleshooting' },
]

export default function ToolsPage() {
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
            <h1 className="text-4xl sm:text-5xl font-bold mb-4">Tools & Integrations</h1>
            <p className="text-gray-400 text-lg max-w-2xl">Give your AI agent the ability to take real actions like sending emails, booking appointments, and collecting payments.</p>
          </div>

          <section id="what-are-tools" className="mb-12">
            <div className="bg-white/[0.03] border border-white/10 rounded-2xl p-6 space-y-4">
              <h2 className="text-lg font-semibold text-white">What Are Tools?</h2>
              <p className="text-gray-400 text-sm">Think of tools as your agent's superpowers. Without tools, your agent can only chat and answer questions. With tools, your agent can send emails, book appointments, collect payments, update databases, and notify your team.</p>
              <div className="overflow-x-auto">
                <table className="w-full text-sm text-gray-400">
                  <thead>
                    <tr className="border-b border-white/10">
                      <th className="text-left py-2 pr-4 text-white font-medium">Playbooks</th>
                      <th className="text-left py-2 text-white font-medium">Tools</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr className="border-b border-white/5"><td className="py-2 pr-4">Conversation scripts</td><td className="py-2">Real-world actions</td></tr>
                    <tr className="border-b border-white/5"><td className="py-2 pr-4">Tell the agent what to say</td><td className="py-2">Tell the agent what to do</td></tr>
                    <tr><td className="py-2 pr-4">"I'll book that for you!"</td><td className="py-2">Actually adds the event to your calendar</td></tr>
                  </tbody>
                </table>
              </div>
            </div>
          </section>

          <section id="sms" className="mb-12">
            <div className="bg-white/[0.03] border border-white/10 rounded-2xl p-6 space-y-4">
              <h2 className="text-lg font-semibold text-white">SMS Notifications</h2>
              <p className="text-gray-400 text-sm">Send text messages to customers automatically for appointment reminders, order confirmations, follow-ups, and promotional offers.</p>
              <div className="bg-white/5 rounded-lg p-4">
                <p className="text-gray-300 text-sm font-medium mb-2">How to configure:</p>
                <ol className="list-decimal list-inside space-y-1 text-gray-400 text-sm">
                  <li>Go to <strong>Tools</strong> in the left sidebar</li>
                  <li>Click <strong>"SMS Notifications"</strong></li>
                  <li>Enter your phone number and click <strong>"Connect"</strong></li>
                  <li>Verify your phone number by entering the code sent to you</li>
                </ol>
              </div>
              <div className="bg-white/5 rounded-lg p-4">
                <p className="text-gray-300 text-sm font-medium mb-1">Example - Appointment Reminder:</p>
                <p className="text-gray-400 text-sm">"Hi [Name], this is a reminder about your appointment at [Business] tomorrow at [Time]. Reply CANCEL to reschedule."</p>
              </div>
            </div>
          </section>

          <section id="email" className="mb-12">
            <div className="bg-white/[0.03] border border-white/10 rounded-2xl p-6 space-y-4">
              <h2 className="text-lg font-semibold text-white">Email Sending</h2>
              <p className="text-gray-400 text-sm">Send emails to customers or your team for booking confirmations, receipts, welcome emails, and internal notifications.</p>
              <div className="bg-white/5 rounded-lg p-4">
                <p className="text-gray-300 text-sm font-medium mb-2">How to configure:</p>
                <ol className="list-decimal list-inside space-y-1 text-gray-400 text-sm">
                  <li>Go to <strong>Tools</strong> in the left sidebar</li>
                  <li>Click <strong>"Email"</strong></li>
                  <li>Connect your email provider (Gmail, Outlook, or custom SMTP)</li>
                  <li>Authorize AscenAI2 to send emails on your behalf</li>
                  <li>Set up email templates or use the default ones</li>
                </ol>
              </div>
            </div>
          </section>

          <section id="calendar" className="mb-12">
            <div className="bg-white/[0.03] border border-white/10 rounded-2xl p-6 space-y-4">
              <h2 className="text-lg font-semibold text-white">Calendar Booking</h2>
              <p className="text-gray-400 text-sm">Connect your calendar so your agent can check availability and book appointments. Supports Google Calendar, Microsoft Outlook Calendar, and Apple Calendar.</p>
              <div className="bg-white/5 rounded-lg p-4">
                <p className="text-gray-300 text-sm font-medium mb-2">Settings you can customize:</p>
                <ul className="space-y-1 text-gray-400 text-sm">
                  <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span><strong>Working hours</strong> - When appointments can be booked</li>
                  <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span><strong>Buffer time</strong> - Gap between appointments (e.g., 15 minutes)</li>
                  <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span><strong>Advance notice</strong> - How far in advance customers can book</li>
                  <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span><strong>Maximum bookings per day</strong> - Limit daily appointments</li>
                </ul>
              </div>
            </div>
          </section>

          <section id="payments" className="mb-12">
            <div className="bg-white/[0.03] border border-white/10 rounded-2xl p-6 space-y-4">
              <h2 className="text-lg font-semibold text-white">Payment Collection</h2>
              <p className="text-gray-400 text-sm">Let your agent collect payments directly in the conversation. Supported providers: Stripe, Square, PayPal, and Twilio Pay.</p>
              <div className="space-y-3">
                <div className="bg-white/5 rounded-lg p-4">
                  <p className="text-white text-sm font-medium mb-1">Setting Up Stripe:</p>
                  <ol className="list-decimal list-inside space-y-1 text-gray-400 text-sm">
                    <li>Go to <strong>Tools</strong> &gt; <strong>Payments</strong></li>
                    <li>Click <strong>"Connect Stripe"</strong></li>
                    <li>Sign in to your Stripe account and authorize the connection</li>
                    <li>You'll be redirected back to AscenAI2</li>
                  </ol>
                </div>
                <div className="bg-white/5 rounded-lg p-4">
                  <p className="text-white text-sm font-medium mb-1">Use cases:</p>
                  <ul className="space-y-1 text-gray-400 text-sm">
                    <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span>Collect deposits for appointments</li>
                    <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span>Process orders over chat</li>
                    <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span>Collect overdue invoices</li>
                  </ul>
                </div>
              </div>
            </div>
          </section>

          <section id="webhooks" className="mb-12">
            <div className="bg-white/[0.03] border border-white/10 rounded-2xl p-6 space-y-4">
              <h2 className="text-lg font-semibold text-white">Webhook Calls</h2>
              <p className="text-gray-400 text-sm">Webhooks let your agent send information to other apps and services you use. Think of a webhook as a messenger that delivers information from your agent to another app.</p>
              <div className="bg-white/5 rounded-lg p-4">
                <p className="text-gray-300 text-sm font-medium mb-2">How to configure:</p>
                <ol className="list-decimal list-inside space-y-1 text-gray-400 text-sm">
                  <li>Go to <strong>Tools</strong> &gt; <strong>Webhooks</strong></li>
                  <li>Click <strong>"Add Webhook"</strong></li>
                  <li>Enter the webhook URL provided by the app you're connecting to</li>
                  <li>Choose what information to send and when to send it</li>
                  <li>Click <strong>"Save"</strong></li>
                </ol>
              </div>
              <div className="bg-white/5 rounded-lg p-4">
                <p className="text-gray-300 text-sm font-medium mb-1">Use cases:</p>
                <ul className="space-y-1 text-gray-400 text-sm">
                  <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span>Send new leads to your CRM</li>
                  <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span>Create support tickets</li>
                  <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span>Notify your team on Slack or Microsoft Teams</li>
                </ul>
              </div>
            </div>
          </section>

          <section id="custom-api" className="mb-12">
            <div className="bg-white/[0.03] border border-white/10 rounded-2xl p-6 space-y-4">
              <h2 className="text-lg font-semibold text-white">Custom API Integrations</h2>
              <p className="text-gray-400 text-sm">For businesses that use custom software, you can connect your agent to any system with an API.</p>
              <div className="bg-white/5 rounded-lg p-4">
                <p className="text-gray-300 text-sm font-medium mb-2">How to configure:</p>
                <ol className="list-decimal list-inside space-y-1 text-gray-400 text-sm">
                  <li>Go to <strong>Tools</strong> &gt; <strong>Custom API</strong></li>
                  <li>Enter your API endpoint URL</li>
                  <li>Choose the request method (GET or POST)</li>
                  <li>Set up the data format</li>
                  <li>Test the connection and click <strong>"Save"</strong></li>
                </ol>
              </div>
              <div className="bg-yellow-500/10 border border-yellow-500/20 rounded-lg p-4">
                <p className="text-yellow-300 text-sm"><strong>Note:</strong> Custom API integrations require some technical knowledge. If you're not comfortable setting this up, ask your developer or contact our support team.</p>
              </div>
            </div>
          </section>

          <section id="best-practices" className="mb-12">
            <h2 className="text-2xl font-bold text-white mb-6">Best Practices</h2>
            <div className="bg-white/[0.03] border border-white/10 rounded-2xl p-6 space-y-4">
              <div className="bg-white/5 rounded-lg p-4">
                <p className="text-white text-sm font-medium mb-1">1. Start Simple</p>
                <p className="text-gray-400 text-sm">Connect one tool at a time. Start with the most important one for your business.</p>
              </div>
              <div className="bg-white/5 rounded-lg p-4">
                <p className="text-white text-sm font-medium mb-1">2. Test Every Tool</p>
                <p className="text-gray-400 text-sm">Book a test appointment, send a test email, process a small test payment.</p>
              </div>
              <div className="bg-white/5 rounded-lg p-4">
                <p className="text-white text-sm font-medium mb-1">3. Monitor Tool Usage</p>
                <p className="text-gray-400 text-sm">Check your dashboard regularly to see how many emails, appointments, and payments your agent has processed.</p>
              </div>
              <div className="bg-white/5 rounded-lg p-4">
                <p className="text-white text-sm font-medium mb-1">4. Keep Credentials Secure</p>
                <p className="text-gray-400 text-sm">Never share your API keys. If a team member leaves, review and rotate credentials.</p>
              </div>
            </div>
          </section>

          <section id="troubleshooting" className="mb-12">
            <h2 className="text-2xl font-bold text-white mb-6">Troubleshooting</h2>
            <div className="bg-white/[0.03] border border-white/10 rounded-2xl p-6 space-y-4">
              <div className="bg-white/5 rounded-lg p-4">
                <p className="text-white text-sm font-medium mb-1">Calendar Not Showing Availability</p>
                <ul className="text-gray-400 text-sm space-y-1">
                  <li>Check that your working hours are set correctly</li>
                  <li>Make sure your calendar is connected and authorized</li>
                  <li>Verify that there are no conflicting events</li>
                </ul>
              </div>
              <div className="bg-white/5 rounded-lg p-4">
                <p className="text-white text-sm font-medium mb-1">Emails Not Sending</p>
                <ul className="text-gray-400 text-sm space-y-1">
                  <li>Check that your email provider is connected</li>
                  <li>Verify the recipient email address is correct</li>
                  <li>Check your email provider's sending limits</li>
                </ul>
              </div>
              <div className="bg-white/5 rounded-lg p-4">
                <p className="text-white text-sm font-medium mb-1">Payments Failing</p>
                <ul className="text-gray-400 text-sm space-y-1">
                  <li>Check that your payment provider account is active</li>
                  <li>Verify your bank account is linked correctly</li>
                  <li>Review the payment provider's dashboard for errors</li>
                </ul>
              </div>
              <div className="bg-white/5 rounded-lg p-4">
                <p className="text-white text-sm font-medium mb-1">Webhooks Not Triggering</p>
                <ul className="text-gray-400 text-sm space-y-1">
                  <li>Verify the webhook URL is correct</li>
                  <li>Check that the receiving service is online</li>
                  <li>Review the webhook logs for error messages</li>
                </ul>
              </div>
            </div>
          </section>

          <div className="bg-gradient-to-r from-violet-600/20 to-blue-600/20 border border-violet-500/20 rounded-2xl p-8 text-center">
            <h3 className="text-xl font-bold text-white mb-2">Ready to Connect Tools?</h3>
            <p className="text-gray-400 text-sm mb-6 max-w-lg mx-auto">
              Create conversation flows that use your tools with Playbooks, or set up voice channels.
            </p>
            <div className="flex flex-col sm:flex-row gap-3 justify-center">
              <Link href="/docs/playbooks" className="px-6 py-3 rounded-xl bg-gradient-to-r from-violet-600 to-blue-600 text-white font-medium hover:opacity-90 transition-opacity text-sm">Playbooks Guide</Link>
              <Link href="/docs/voice-setup" className="px-6 py-3 rounded-xl border border-white/10 text-white font-medium hover:bg-white/5 transition-colors text-sm">Voice Setup</Link>
            </div>
          </div>
        </div>
      </div>

      
    </div>
  )
}
