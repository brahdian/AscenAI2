'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'

const navItems = [
  { href: '#understanding-plan', label: 'Understanding Your Plan' },
  { href: '#viewing-usage', label: 'Viewing Usage' },
  { href: '#upgrading', label: 'Upgrading' },
  { href: '#payment-methods', label: 'Payment Methods' },
  { href: '#invoices', label: 'Invoices' },
  { href: '#managing-costs', label: 'Managing Costs' },
  { href: '#faq', label: 'Common Questions' },
]

export default function BillingPage() {
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
            <h1 className="text-4xl sm:text-5xl font-bold mb-4">Billing & Usage</h1>
            <p className="text-gray-400 text-lg max-w-2xl">Understand your plan, track your usage, and manage your subscription.</p>
          </div>

          <section id="understanding-plan" className="mb-12">
            <h2 className="text-2xl font-bold text-white mb-6">Understanding Your Plan</h2>
            <div className="bg-white/[0.03] border border-white/10 rounded-2xl p-6 space-y-6">
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                <div className="bg-white/5 rounded-lg p-4">
                  <h3 className="text-base font-semibold text-white mb-2">Starter Plan</h3>
                  <ul className="space-y-1 text-gray-400 text-sm">
                    <li>1 AI agent</li>
                    <li>500 chat conversations/month</li>
                    <li>60 voice minutes/month</li>
                    <li>Basic tools (email, SMS)</li>
                    <li>Email support</li>
                  </ul>
                </div>
                <div className="bg-white/5 rounded-lg p-4 border border-violet-500/20">
                  <div className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-violet-500/20 text-violet-300 text-xs font-medium mb-2">Popular</div>
                  <h3 className="text-base font-semibold text-white mb-2">Growth Plan</h3>
                  <ul className="space-y-1 text-gray-400 text-sm">
                    <li>3 AI agents</li>
                    <li>2,000 chat conversations/month</li>
                    <li>300 voice minutes/month</li>
                    <li>All tools (calendar, payments, webhooks)</li>
                    <li>Priority email support</li>
                  </ul>
                </div>
                <div className="bg-white/5 rounded-lg p-4">
                  <h3 className="text-base font-semibold text-white mb-2">Scale Plan</h3>
                  <ul className="space-y-1 text-gray-400 text-sm">
                    <li>10 AI agents</li>
                    <li>10,000 chat conversations/month</li>
                    <li>1,000 voice minutes/month</li>
                    <li>All tools plus custom API integrations</li>
                    <li>Dedicated account manager</li>
                  </ul>
                </div>
              </div>
              <div>
                <h3 className="text-base font-semibold text-white mb-2">What Counts as a Conversation?</h3>
                <p className="text-gray-400 text-sm mb-2">A conversation is a single chat session. It starts when a customer opens the chat widget and sends their first message, and ends after 30 minutes of inactivity.</p>
                <ul className="space-y-1 text-gray-400 text-sm">
                  <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span>A customer asks 5 questions in one chat session = <strong>1 conversation</strong></li>
                  <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span>A customer chats in the morning, then comes back in the afternoon = <strong>2 conversations</strong></li>
                  <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span>A customer opens the widget but doesn't send a message = <strong>0 conversations</strong></li>
                </ul>
              </div>
              <div>
                <h3 className="text-base font-semibold text-white mb-2">What Counts as a Voice Minute?</h3>
                <p className="text-gray-400 text-sm mb-2">Voice minutes are the total duration of all phone calls handled by your agent.</p>
                <ul className="space-y-1 text-gray-400 text-sm">
                  <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span>A 3-minute call = <strong>3 voice minutes</strong></li>
                  <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span>Ten 2-minute calls = <strong>20 voice minutes</strong></li>
                  <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span>A call that lasts 1 minute 45 seconds = <strong>2 voice minutes</strong> (rounded up)</li>
                </ul>
              </div>
            </div>
          </section>

          <section id="viewing-usage" className="mb-12">
            <h2 className="text-2xl font-bold text-white mb-6">Viewing Your Usage</h2>
            <div className="bg-white/[0.03] border border-white/10 rounded-2xl p-6 space-y-4">
              <div>
                <h3 className="text-base font-semibold text-white mb-2">Usage Dashboard</h3>
                <ol className="list-decimal list-inside space-y-1 text-gray-400 text-sm">
                  <li>In your dashboard, click <strong>"Billing"</strong> in the left sidebar</li>
                  <li>Click the <strong>"Usage"</strong> tab</li>
                  <li>You'll see a visual overview of your current usage</li>
                </ol>
              </div>
              <div>
                <h3 className="text-base font-semibold text-white mb-2">What You'll See</h3>
                <ul className="space-y-2 text-gray-400 text-sm">
                  <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span><strong>Chat Conversations</strong> - Progress bar, daily breakdown, end-of-month projection</li>
                  <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span><strong>Voice Minutes</strong> - Progress bar, recent calls list, total used</li>
                  <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span><strong>Agents</strong> - How many created vs. plan limit, status of each</li>
                  <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span><strong>Tool Usage</strong> - Emails sent, SMS sent, calendar events, payments processed</li>
                </ul>
              </div>
              <div className="bg-blue-500/10 border border-blue-500/20 rounded-lg p-4">
                <p className="text-blue-300 text-sm"><strong>Usage Alerts:</strong> You'll be notified at 80% usage (warning), 90% usage (with upgrade options), and 100% usage (dashboard banner).</p>
              </div>
            </div>
          </section>

          <section id="upgrading" className="mb-12">
            <h2 className="text-2xl font-bold text-white mb-6">Upgrading Your Plan</h2>
            <div className="bg-white/[0.03] border border-white/10 rounded-2xl p-6 space-y-4">
              <div>
                <h3 className="text-base font-semibold text-white mb-2">When to Upgrade</h3>
                <ul className="space-y-1 text-gray-400 text-sm">
                  <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span>Consistently hitting 80%+ of your conversation limit</li>
                  <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span>Running out of voice minutes</li>
                  <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span>Need more agents or tools not available on your current plan</li>
                </ul>
              </div>
              <div>
                <h3 className="text-base font-semibold text-white mb-2">How to Upgrade</h3>
                <ol className="list-decimal list-inside space-y-1 text-gray-400 text-sm">
                  <li>Go to <strong>Billing</strong> &gt; <strong>Plan</strong></li>
                  <li>Click <strong>"Upgrade Plan"</strong></li>
                  <li>Choose your new plan and confirm</li>
                </ol>
                <p className="text-gray-400 text-sm mt-2">New limits take effect immediately. You're charged a prorated amount for the remainder of your billing cycle.</p>
              </div>
              <div>
                <h3 className="text-base font-semibold text-white mb-2">Downgrading</h3>
                <p className="text-gray-400 text-sm">The change takes effect at the start of your next billing cycle. If you have more agents than the lower plan allows, you'll need to pause or delete the extras.</p>
              </div>
            </div>
          </section>

          <section id="payment-methods" className="mb-12">
            <h2 className="text-2xl font-bold text-white mb-6">Payment Methods</h2>
            <div className="bg-white/[0.03] border border-white/10 rounded-2xl p-6 space-y-4">
              <p className="text-gray-400 text-sm"><strong>Accepted:</strong> Visa, Mastercard, American Express, Discover (credit and debit cards).</p>
              <div>
                <h3 className="text-base font-semibold text-white mb-2">Adding a Payment Method</h3>
                <ol className="list-decimal list-inside space-y-1 text-gray-400 text-sm">
                  <li>Go to <strong>Billing</strong> &gt; <strong>Payment Methods</strong></li>
                  <li>Click <strong>"Add Payment Method"</strong> and enter your card details</li>
                  <li>Click <strong>"Save"</strong></li>
                </ol>
              </div>
              <div>
                <h3 className="text-base font-semibold text-white mb-2">Failed Payments</h3>
                <p className="text-gray-400 text-sm mb-2">If a payment fails, you'll receive an email. AscenAI2 will retry after 3 days. After 7 days without successful payment, your account may be paused.</p>
                <p className="text-gray-400 text-sm">To resolve: update your card information and click <strong>"Retry Payment"</strong>.</p>
              </div>
            </div>
          </section>

          <section id="invoices" className="mb-12">
            <h2 className="text-2xl font-bold text-white mb-6">Understanding Your Invoice</h2>
            <div className="bg-white/[0.03] border border-white/10 rounded-2xl p-6 space-y-4">
              <p className="text-gray-400 text-sm">Go to <strong>Billing</strong> &gt; <strong>Invoices</strong> to view and download past invoices as PDFs.</p>
              <div>
                <h3 className="text-base font-semibold text-white mb-2">What's on Your Invoice</h3>
                <ul className="space-y-1 text-gray-400 text-sm">
                  <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span><strong>Plan cost</strong> - Your monthly subscription fee</li>
                  <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span><strong>Overage charges</strong> - Any conversations or minutes beyond your plan limit</li>
                  <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span><strong>Add-ons</strong> - Any additional features you've purchased</li>
                  <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span><strong>Tax</strong> - Applicable taxes based on your location</li>
                </ul>
              </div>
              <div>
                <h3 className="text-base font-semibold text-white mb-2">Cancelling Your Subscription</h3>
                <p className="text-gray-400 text-sm mb-2">Go to <strong>Billing</strong> &gt; <strong>Plan</strong> &gt; <strong>"Cancel Subscription"</strong>.</p>
                <ul className="space-y-1 text-gray-400 text-sm">
                  <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span>Your account remains active until the end of your current billing period</li>
                  <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span>All your data is preserved for 30 days after cancellation</li>
                  <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span>You can reactivate anytime within 30 days</li>
                </ul>
              </div>
            </div>
          </section>

          <section id="managing-costs" className="mb-12">
            <h2 className="text-2xl font-bold text-white mb-6">Managing Costs</h2>
            <div className="bg-white/[0.03] border border-white/10 rounded-2xl p-6 space-y-4">
              <div className="bg-white/5 rounded-lg p-4">
                <p className="text-white text-sm font-medium mb-1">Tips to Stay Within Your Plan</p>
                <ul className="space-y-1 text-gray-400 text-sm">
                  <li>Make sure your agent's greeting is clear so customers know what it can help with</li>
                  <li>Add a "quick answers" section to your website for common questions</li>
                  <li>Set up after-hours messages to avoid unnecessary voice calls</li>
                  <li>Check your usage dashboard weekly</li>
                </ul>
              </div>
              <div className="bg-white/5 rounded-lg p-4">
                <p className="text-white text-sm font-medium mb-1">Setting Usage Limits</p>
                <p className="text-gray-400 text-sm mb-2">Go to <strong>Billing</strong> &gt; <strong>Usage Limits</strong> to toggle <strong>"Stop at limit"</strong>. When reached, your agent stops accepting new conversations until the next billing cycle.</p>
              </div>
            </div>
          </section>

          <section id="faq" className="mb-12">
            <h2 className="text-2xl font-bold text-white mb-6">Common Billing Questions</h2>
            <div className="space-y-4">
              <div className="bg-white/[0.03] border border-white/10 rounded-2xl p-6">
                <h3 className="text-base font-semibold text-white mb-2">"Why did my bill change this month?"</h3>
                <p className="text-gray-400 text-sm">Possible reasons: plan upgrade/downgrade, overage charges, added/removed team members, or tax rate changes.</p>
              </div>
              <div className="bg-white/[0.03] border border-white/10 rounded-2xl p-6">
                <h3 className="text-base font-semibold text-white mb-2">"Can I get a refund?"</h3>
                <p className="text-gray-400 text-sm">Refunds are handled case-by-case. Contact <a href="mailto:billing@ascenai.com" className="text-blue-400 hover:underline">billing@ascenai.com</a> with your account details.</p>
              </div>
              <div className="bg-white/[0.03] border border-white/10 rounded-2xl p-6">
                <h3 className="text-base font-semibold text-white mb-2">"Do unused conversations roll over?"</h3>
                <p className="text-gray-400 text-sm">No. Unused conversations and voice minutes reset each billing cycle. They do not roll over.</p>
              </div>
              <div className="bg-white/[0.03] border border-white/10 rounded-2xl p-6">
                <h3 className="text-base font-semibold text-white mb-2">"Can I pause my account?"</h3>
                <p className="text-gray-400 text-sm">Yes. You can pause for up to 3 months. During the pause, your agents are paused, you won't be charged, and your data is preserved.</p>
              </div>
              <div className="bg-white/[0.03] border border-white/10 rounded-2xl p-6">
                <h3 className="text-base font-semibold text-white mb-2">"What happens if I exceed my limit?"</h3>
                <p className="text-gray-400 text-sm">By default (soft limit), you continue to be served but are charged for overage. You can set a hard limit to stop service at your plan cap.</p>
              </div>
            </div>
          </section>

          <div className="bg-gradient-to-r from-violet-600/20 to-blue-600/20 border border-violet-500/20 rounded-2xl p-8 text-center">
            <h3 className="text-xl font-bold text-white mb-2">Need Help with Billing?</h3>
            <p className="text-gray-400 text-sm mb-6 max-w-lg mx-auto">
              Contact our support team at <a href="mailto:billing@ascenai.com" className="text-blue-400 hover:underline">billing@ascenai.com</a> or learn about compliance and data privacy.
            </p>
            <div className="flex flex-col sm:flex-row gap-3 justify-center">
              <Link href="/docs/compliance" className="px-6 py-3 rounded-xl bg-gradient-to-r from-violet-600 to-blue-600 text-white font-medium hover:opacity-90 transition-opacity text-sm">Compliance Guide</Link>
              <Link href="/pricing" className="px-6 py-3 rounded-xl border border-white/10 text-white font-medium hover:bg-white/5 transition-colors text-sm">View Pricing Plans</Link>
            </div>
          </div>
        </div>
      </div>

      
    </div>
  )
}
