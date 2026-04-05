'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'

const navItems = [
  { href: '#what-is-playbook', label: 'What Is a Playbook?' },
  { href: '#structure', label: 'Playbook Structure' },
  { href: '#create', label: 'How to Create' },
  { href: '#examples', label: 'Examples' },
  { href: '#best-practices', label: 'Best Practices' },
  { href: '#testing', label: 'Testing' },
  { href: '#how-many', label: 'How Many Do You Need?' },
]

export default function PlaybooksPage() {
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
            <h1 className="text-4xl sm:text-5xl font-bold mb-4">Playbooks</h1>
            <p className="text-gray-400 text-lg max-w-2xl">Create conversation scripts that guide your agent through specific scenarios.</p>
          </div>

          <section id="what-is-playbook" className="mb-12">
            <div className="bg-white/[0.03] border border-white/10 rounded-2xl p-6 space-y-4">
              <h2 className="text-lg font-semibold text-white">What Is a Playbook?</h2>
              <p className="text-gray-400 text-sm">A playbook is a set of instructions that tells your agent how to handle a specific type of conversation. Think of it this way: If your agent is a new employee, a playbook is the training manual for a specific task.</p>
              <div className="bg-white/5 rounded-lg p-4">
                <p className="text-gray-300 text-sm font-medium mb-2">Examples of When to Use Playbooks:</p>
                <ul className="space-y-1 text-gray-400 text-sm">
                  <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span>A customer wants to <strong>book an appointment</strong></li>
                  <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span>A customer asks about <strong>pricing</strong></li>
                  <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span>A customer wants to <strong>leave feedback</strong></li>
                  <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span>A customer asks about your <strong>return policy</strong></li>
                  <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span>A customer wants to <strong>cancel or reschedule</strong></li>
                </ul>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-sm text-gray-400">
                  <thead>
                    <tr className="border-b border-white/10">
                      <th className="text-left py-2 pr-4 text-white font-medium">Knowledge Base</th>
                      <th className="text-left py-2 text-white font-medium">Playbooks</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr className="border-b border-white/5"><td className="py-2 pr-4">General information about your business</td><td className="py-2">Step-by-step conversation flows</td></tr>
                    <tr className="border-b border-white/5"><td className="py-2 pr-4">Answers "what" questions</td><td className="py-2">Guides customers through a process</td></tr>
                    <tr><td className="py-2 pr-4">Static documents</td><td className="py-2">Interactive conversations</td></tr>
                  </tbody>
                </table>
              </div>
            </div>
          </section>

          <section id="structure" className="mb-12">
            <h2 className="text-2xl font-bold text-white mb-6">Playbook Structure</h2>
            <div className="space-y-4">
              <div className="bg-white/[0.03] border border-white/10 rounded-2xl p-6">
                <h3 className="text-base font-semibold text-white mb-2">1. Triggers</h3>
                <p className="text-gray-400 text-sm mb-2">Triggers tell your agent when to use this playbook. These are the words or phrases that activate it.</p>
                <div className="bg-white/5 rounded-lg p-4">
                  <p className="text-gray-300 text-sm font-medium mb-1">Booking Playbook Triggers:</p>
                  <ul className="text-gray-400 text-sm space-y-1">
                    <li>"book an appointment"</li>
                    <li>"schedule a visit"</li>
                    <li>"make a reservation"</li>
                    <li>"I'd like to come in"</li>
                    <li>"are you available"</li>
                  </ul>
                </div>
              </div>
              <div className="bg-white/[0.03] border border-white/10 rounded-2xl p-6">
                <h3 className="text-base font-semibold text-white mb-2">2. Responses</h3>
                <p className="text-gray-400 text-sm mb-2">Responses are what your agent says during the conversation. You can set up multiple responses that flow together.</p>
                <div className="bg-white/5 rounded-lg p-4 space-y-2">
                  <p className="text-gray-300 text-sm"><strong>Response 1:</strong> "I'd be happy to help you book an appointment! What day works best for you?"</p>
                  <p className="text-gray-300 text-sm"><strong>Response 2:</strong> "Great! We have availability on [day] at [times]. Which time would you prefer?"</p>
                  <p className="text-gray-300 text-sm"><strong>Response 3:</strong> "Perfect! I just need your name and phone number to confirm."</p>
                  <p className="text-gray-300 text-sm"><strong>Response 4:</strong> "Thank you! Your appointment is confirmed for [day] at [time]."</p>
                </div>
              </div>
              <div className="bg-white/[0.03] border border-white/10 rounded-2xl p-6">
                <h3 className="text-base font-semibold text-white mb-2">3. Actions</h3>
                <p className="text-gray-400 text-sm mb-2">Actions are things your agent does during the conversation.</p>
                <ul className="space-y-1 text-gray-400 text-sm">
                  <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span>Send a confirmation email to the customer</li>
                  <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span>Add the appointment to your calendar</li>
                  <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span>Send an SMS reminder to the customer</li>
                  <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span>Notify your team via email</li>
                </ul>
              </div>
            </div>
          </section>

          <section id="create" className="mb-12">
            <h2 className="text-2xl font-bold text-white mb-6">How to Create a Playbook</h2>
            <div className="bg-white/[0.03] border border-white/10 rounded-2xl p-6 space-y-4">
              <ol className="list-decimal list-inside space-y-3 text-gray-400 text-sm">
                <li><strong>Go to Playbooks</strong> - From your dashboard, click "Playbooks" in the left sidebar, then "Create Playbook"</li>
                <li><strong>Name Your Playbook</strong> - Give it a clear name: "Appointment Booking", "FAQ Response", "Customer Feedback Collection"</li>
                <li><strong>Set Triggers</strong> - Type the words or phrases that should activate this playbook. Press Enter after each trigger.</li>
                <li><strong>Write Responses</strong> - Click "Add Response" and type the message your agent should say. Add follow-up responses for each step.</li>
                <li><strong>Add Actions (Optional)</strong> - Choose the action type (send email, book calendar, send SMS, etc.)</li>
                <li><strong>Save and Test</strong> - Click "Save Playbook" and test in your agent's Preview window</li>
              </ol>
            </div>
          </section>

          <section id="examples" className="mb-12">
            <h2 className="text-2xl font-bold text-white mb-6">Playbook Examples</h2>
            <div className="space-y-4">
              <div className="bg-white/[0.03] border border-white/10 rounded-2xl p-6">
                <h3 className="text-base font-semibold text-white mb-3">Appointment Booking (Dental Clinic)</h3>
                <div className="space-y-3">
                  <div className="bg-white/5 rounded-lg p-4">
                    <p className="text-gray-300 text-sm font-medium mb-1">Triggers:</p>
                    <p className="text-gray-400 text-sm">book appointment, schedule a visit, make an appointment, when are you available</p>
                  </div>
                  <div className="bg-white/5 rounded-lg p-4">
                    <p className="text-gray-300 text-sm font-medium mb-1">Responses:</p>
                    <ol className="text-gray-400 text-sm space-y-2 list-decimal list-inside">
                      <li>"I'd be happy to help you book an appointment at Smile Bright Dental! Are you a new patient or have you visited us before?"</li>
                      <li>"Great! What day of the week works best for you? We're open Monday through Friday from 9 AM to 5 PM."</li>
                      <li>"Let me check our availability. We have openings on [day] at [time slots]. Which works best for you?"</li>
                      <li>"Perfect! I just need your full name, phone number, and reason for visit."</li>
                      <li>"Thank you! Your appointment is confirmed for [day] at [time]. We'll send you a text reminder 24 hours before."</li>
                    </ol>
                  </div>
                  <div className="bg-white/5 rounded-lg p-4">
                    <p className="text-gray-300 text-sm font-medium mb-1">Actions:</p>
                    <ul className="text-gray-400 text-sm space-y-1">
                      <li>Add appointment to Google Calendar</li>
                      <li>Send confirmation email to customer</li>
                      <li>Send SMS reminder 24 hours before appointment</li>
                    </ul>
                  </div>
                </div>
              </div>
              <div className="bg-white/[0.03] border border-white/10 rounded-2xl p-6">
                <h3 className="text-base font-semibold text-white mb-3">Delivery FAQ (Pizza Shop)</h3>
                <div className="space-y-3">
                  <div className="bg-white/5 rounded-lg p-4">
                    <p className="text-gray-300 text-sm font-medium mb-1">Triggers:</p>
                    <p className="text-gray-400 text-sm">delivery area, do you deliver, how far do you deliver, delivery fee</p>
                  </div>
                  <div className="bg-white/5 rounded-lg p-4">
                    <p className="text-gray-300 text-sm font-medium mb-1">Responses:</p>
                    <ol className="text-gray-400 text-sm space-y-2 list-decimal list-inside">
                      <li>"Yes, we deliver! Our delivery area covers everything within 5 miles of our location on Main Street."</li>
                      <li>"Our delivery fee is $3.99 for orders under $30, and FREE for orders over $30."</li>
                      <li>"Delivery usually takes 30-45 minutes. Would you like to place an order now?"</li>
                    </ol>
                  </div>
                </div>
              </div>
              <div className="bg-white/[0.03] border border-white/10 rounded-2xl p-6">
                <h3 className="text-base font-semibold text-white mb-3">Customer Feedback Collection (Hair Salon)</h3>
                <div className="space-y-3">
                  <div className="bg-white/5 rounded-lg p-4">
                    <p className="text-gray-300 text-sm font-medium mb-1">Triggers:</p>
                    <p className="text-gray-400 text-sm">leave feedback, I want to review, how was my service, customer satisfaction</p>
                  </div>
                  <div className="bg-white/5 rounded-lg p-4">
                    <p className="text-gray-300 text-sm font-medium mb-1">Responses:</p>
                    <ol className="text-gray-400 text-sm space-y-2 list-decimal list-inside">
                      <li>"We'd love to hear about your experience at Serenity Salon! On a scale of 1 to 5, how would you rate your visit today?"</li>
                      <li>"Thank you for that rating! Is there anything specific you'd like to share about your experience?"</li>
                      <li>"We really appreciate your feedback! Here's a 10% discount code for your next visit: THANKYOU10."</li>
                    </ol>
                  </div>
                  <div className="bg-white/5 rounded-lg p-4">
                    <p className="text-gray-300 text-sm font-medium mb-1">Actions:</p>
                    <ul className="text-gray-400 text-sm space-y-1">
                      <li>Send feedback summary to salon manager via email</li>
                      <li>If rating is 3 or below, send alert to manager for follow-up</li>
                    </ul>
                  </div>
                </div>
              </div>
            </div>
          </section>

          <section id="best-practices" className="mb-12">
            <h2 className="text-2xl font-bold text-white mb-6">Best Practices</h2>
            <div className="bg-white/[0.03] border border-white/10 rounded-2xl p-6 space-y-4">
              <div className="bg-white/5 rounded-lg p-4">
                <p className="text-white text-sm font-medium mb-1">1. Keep It Conversational</p>
                <p className="text-gray-400 text-sm">Write responses the way you'd actually talk to a customer. <strong className="text-green-400">Good:</strong> "Sure! I can help you with that." <strong className="text-red-400">Bad:</strong> "Acknowledged. Please specify the desired date."</p>
              </div>
              <div className="bg-white/5 rounded-lg p-4">
                <p className="text-white text-sm font-medium mb-1">2. Ask One Question at a Time</p>
                <p className="text-gray-400 text-sm">Don't overwhelm customers with multiple questions in one message.</p>
              </div>
              <div className="bg-white/5 rounded-lg p-4">
                <p className="text-white text-sm font-medium mb-1">3. Always Offer Next Steps</p>
                <p className="text-gray-400 text-sm">End each playbook with a clear next step or an offer to help further.</p>
              </div>
              <div className="bg-white/5 rounded-lg p-4">
                <p className="text-white text-sm font-medium mb-1">4. Handle Dead Ends</p>
                <p className="text-gray-400 text-sm">Add a fallback response: "I'm not sure I understood. Could you rephrase that? Or would you like to speak with a team member instead?"</p>
              </div>
              <div className="bg-white/5 rounded-lg p-4">
                <p className="text-white text-sm font-medium mb-1">5. Keep Playbooks Focused</p>
                <p className="text-gray-400 text-sm">One playbook per scenario. Don't try to handle bookings, complaints, and pricing in the same playbook.</p>
              </div>
            </div>
          </section>

          <section id="testing" className="mb-12">
            <h2 className="text-2xl font-bold text-white mb-6">Testing Playbooks</h2>
            <div className="bg-white/[0.03] border border-white/10 rounded-2xl p-6 space-y-4">
              <div>
                <h3 className="text-base font-semibold text-white mb-2">Before Going Live</h3>
                <ol className="list-decimal list-inside space-y-1 text-gray-400 text-sm">
                  <li>Open your agent's Preview window</li>
                  <li>Type each trigger you set up</li>
                  <li>Walk through the entire conversation flow</li>
                  <li>Check that responses sound natural, the conversation flows logically, and actions trigger correctly</li>
                </ol>
              </div>
              <div>
                <h3 className="text-base font-semibold text-white mb-2">Common Issues and Fixes</h3>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm text-gray-400">
                    <thead>
                      <tr className="border-b border-white/10">
                        <th className="text-left py-2 pr-4 text-white font-medium">Issue</th>
                        <th className="text-left py-2 text-white font-medium">Fix</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr className="border-b border-white/5"><td className="py-2 pr-4">Playbook doesn't activate</td><td className="py-2">Add more trigger variations</td></tr>
                      <tr className="border-b border-white/5"><td className="py-2 pr-4">Responses feel robotic</td><td className="py-2">Rewrite in a more conversational tone</td></tr>
                      <tr className="border-b border-white/5"><td className="py-2 pr-4">Conversation gets stuck</td><td className="py-2">Add fallback responses</td></tr>
                      <tr className="border-b border-white/5"><td className="py-2 pr-4">Actions don't trigger</td><td className="py-2">Check that the tool is properly connected</td></tr>
                      <tr><td className="py-2 pr-4">Playbook activates when it shouldn't</td><td className="py-2">Make triggers more specific</td></tr>
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          </section>

          <section id="how-many" className="mb-12">
            <div className="bg-white/[0.03] border border-white/10 rounded-2xl p-6">
              <h2 className="text-lg font-semibold text-white mb-3">How Many Playbooks Do You Need?</h2>
              <p className="text-gray-400 text-sm mb-3">Start with 2-3 playbooks for your most common scenarios.</p>
              <div className="bg-white/5 rounded-lg p-4">
                <p className="text-gray-300 text-sm font-medium mb-2">Recommended starting playbooks:</p>
                <ul className="space-y-1 text-gray-400 text-sm">
                  <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span><strong>Appointment/Booking</strong> - If you take appointments</li>
                  <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span><strong>FAQ</strong> - For your most common questions</li>
                  <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span><strong>Feedback</strong> - To collect customer reviews</li>
                </ul>
              </div>
            </div>
          </section>

          <div className="bg-gradient-to-r from-violet-600/20 to-blue-600/20 border border-violet-500/20 rounded-2xl p-8 text-center">
            <h3 className="text-xl font-bold text-white mb-2">Ready to Create Playbooks?</h3>
            <p className="text-gray-400 text-sm mb-6 max-w-lg mx-auto">
              Explore Tools to give your agent the ability to take real actions, or set up Voice for phone calls.
            </p>
            <div className="flex flex-col sm:flex-row gap-3 justify-center">
              <Link href="/docs/tools" className="px-6 py-3 rounded-xl bg-gradient-to-r from-violet-600 to-blue-600 text-white font-medium hover:opacity-90 transition-opacity text-sm">Tools Guide</Link>
              <Link href="/docs/voice-setup" className="px-6 py-3 rounded-xl border border-white/10 text-white font-medium hover:bg-white/5 transition-colors text-sm">Voice Setup</Link>
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
