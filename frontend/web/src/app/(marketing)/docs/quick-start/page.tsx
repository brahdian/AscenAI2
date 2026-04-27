'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'

const navItems = [
  { href: '#what-youll-build', label: "What You'll Build" },
  { href: '#step1', label: 'Step 1: Sign Up' },
  { href: '#step2', label: 'Step 2: Payment' },
  { href: '#step3', label: 'Step 3: Create Agent' },
  { href: '#step4', label: 'Step 4: Configure' },
  { href: '#step5', label: 'Step 5: Test' },
  { href: '#step6', label: 'Step 6: Embed' },
  { href: '#step7', label: 'Step 7: Go Live' },
  { href: '#scenarios', label: 'Common Scenarios' },
  { href: '#whats-next', label: "What's Next?" },
]

export default function QuickStartPage() {
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
            <h1 className="text-4xl sm:text-5xl font-bold mb-4">Quick Start Guide</h1>
            <p className="text-gray-400 text-lg max-w-2xl">
              Get your first AI agent up and running in under 10 minutes.
            </p>
          </div>

          <div id="what-youll-build" className="bg-white/[0.03] border border-white/10 rounded-2xl p-6 mb-8">
            <h2 className="text-lg font-semibold text-white mb-3">What You'll Build</h2>
            <p className="text-gray-400 text-sm mb-3">By the end of this guide, you'll have a working AI agent that can:</p>
            <ul className="space-y-2 text-gray-400 text-sm">
              <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span>Answer customer questions on your website</li>
              <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span>Handle common inquiries automatically</li>
              <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span>Collect leads and book appointments</li>
              <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span>Work 24/7 without you needing to be at your desk</li>
            </ul>
          </div>

          <section id="step1" className="mb-12">
            <div className="flex items-center gap-3 mb-6">
              <span className="flex items-center justify-center w-8 h-8 rounded-full bg-gradient-to-br from-violet-600 to-blue-600 text-white text-sm font-bold">1</span>
              <h2 className="text-2xl font-bold text-white">Sign Up for AscenAI2</h2>
            </div>
            <div className="bg-white/[0.03] border border-white/10 rounded-2xl p-6">
              <ol className="list-decimal list-inside space-y-2 text-gray-400 text-sm">
                <li>Go to <strong>ascenai.com</strong> and click <strong>"Get Started"</strong> in the top right corner</li>
                <li>Enter your email address and choose a strong password</li>
                <li>Click <strong>"Create Account"</strong></li>
                <li>Check your email inbox for a verification message from AscenAI2</li>
                <li>Click the <strong>"Verify Email"</strong> button in that message</li>
              </ol>
              <div className="bg-blue-500/10 border border-blue-500/20 rounded-lg p-4 mt-4">
                <p className="text-blue-300 text-sm"><strong>Note:</strong> If you don't see the verification email within 2 minutes, check your spam or junk folder. You can also click <strong>"Resend Verification"</strong> on the sign-up page.</p>
              </div>
            </div>
          </section>

          <section id="step2" className="mb-12">
            <div className="flex items-center gap-3 mb-6">
              <span className="flex items-center justify-center w-8 h-8 rounded-full bg-gradient-to-br from-violet-600 to-blue-600 text-white text-sm font-bold">2</span>
              <h2 className="text-2xl font-bold text-white">Complete Your Payment</h2>
            </div>
            <div className="bg-white/[0.03] border border-white/10 rounded-2xl p-6 space-y-4">
              <p className="text-gray-400 text-sm">After verifying your email, you'll be taken to the payment screen.</p>
              <ol className="list-decimal list-inside space-y-2 text-gray-400 text-sm">
                <li>Choose the plan that fits your business:
                  <ul className="list-disc list-inside ml-4 mt-1 space-y-1">
                    <li><strong>Starter</strong> - Perfect for solo businesses (up to 500 chats/month)</li>
                    <li><strong>Growth</strong> - Great for growing businesses (up to 2,000 chats/month)</li>
                    <li><strong>Scale</strong> - For busy operations (up to 10,000 chats/month)</li>
                  </ul>
                </li>
                <li>Enter your payment details (credit card or debit card accepted)</li>
                <li>Click <strong>"Subscribe"</strong></li>
                <li>You'll see a confirmation screen and receive a receipt by email</li>
              </ol>
              <div className="bg-green-500/10 border border-green-500/20 rounded-lg p-4">
                <p className="text-green-300 text-sm"><strong>Tip:</strong> All plans include a 14-day free trial. You won't be charged until the trial ends. You can cancel anytime during the trial with no charge.</p>
              </div>
            </div>
          </section>

          <section id="step3" className="mb-12">
            <div className="flex items-center gap-3 mb-6">
              <span className="flex items-center justify-center w-8 h-8 rounded-full bg-gradient-to-br from-violet-600 to-blue-600 text-white text-sm font-bold">3</span>
              <h2 className="text-2xl font-bold text-white">Create Your First Agent</h2>
            </div>
            <div className="bg-white/[0.03] border border-white/10 rounded-2xl p-6 space-y-4">
              <p className="text-gray-400 text-sm">Once your account is active, you'll land on the <strong>Dashboard</strong>. This is your command center.</p>
              <h3 className="text-base font-semibold text-white">What You'll See on the Dashboard</h3>
              <ul className="space-y-1 text-gray-400 text-sm">
                <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span><strong>Left sidebar</strong> - Navigation menu (Agents, Playbooks, Tools, Settings)</li>
                <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span><strong>Main area</strong> - Overview of your account, usage stats, and quick actions</li>
                <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span><strong>Top bar</strong> - Your account name, notifications, and help button</li>
              </ul>
              <h3 className="text-base font-semibold text-white">Creating the Agent</h3>
              <ol className="list-decimal list-inside space-y-2 text-gray-400 text-sm">
                <li>Click the <strong>"Create Agent"</strong> button in the top right of the dashboard</li>
                <li>You'll see a form with the following fields:
                  <div className="ml-4 mt-2 space-y-3">
                    <div className="bg-white/5 rounded-lg p-4">
                      <p className="text-white text-sm font-medium">Agent Name</p>
                      <p className="text-gray-400 text-xs mt-1">Give your agent a name that makes sense for your business. Examples: "Front Desk Helper" for a dental clinic, "Order Assistant" for a pizza shop, "Style Advisor" for a salon.</p>
                    </div>
                    <div className="bg-white/5 rounded-lg p-4">
                      <p className="text-white text-sm font-medium">Agent Role</p>
                      <p className="text-gray-400 text-xs mt-1">Describe what this agent should do in plain language. Example for a dentist: "You are a friendly receptionist for Smile Bright Dental Clinic. You help patients book appointments, answer questions about our services, and provide office hours and location information."</p>
                    </div>
                  </div>
                </li>
                <li>Choose a <strong>language</strong> for your agent (English is default)</li>
                <li>Click <strong>"Create Agent"</strong></li>
              </ol>
              <div className="bg-yellow-500/10 border border-yellow-500/20 rounded-lg p-4">
                <p className="text-yellow-300 text-sm"><strong>Tip:</strong> Think of the Agent Role as giving instructions to a new employee. The more specific you are about what they should do and how they should behave, the better they'll perform.</p>
              </div>
            </div>
          </section>

          <section id="step4" className="mb-12">
            <div className="flex items-center gap-3 mb-6">
              <span className="flex items-center justify-center w-8 h-8 rounded-full bg-gradient-to-br from-violet-600 to-blue-600 text-white text-sm font-bold">4</span>
              <h2 className="text-2xl font-bold text-white">Configure Your Agent</h2>
            </div>
            <div className="bg-white/[0.03] border border-white/10 rounded-2xl p-6 space-y-6">
              <p className="text-gray-400 text-sm">After creating your agent, you'll be taken to the <strong>Agent Settings</strong> page. Here's what to set up first:</p>
              <div>
                <h3 className="text-base font-semibold text-white mb-2">Greeting Message</h3>
                <p className="text-gray-400 text-sm mb-2">This is the first thing customers see when they open the chat widget.</p>
                <div className="bg-white/5 rounded-lg p-4 space-y-2">
                  <p className="text-gray-300 text-sm font-medium">Good examples:</p>
                  <ul className="space-y-1 text-gray-400 text-sm">
                    <li>"Hi! Welcome to Smile Bright Dental. How can I help you today?"</li>
                    <li>"Hey there! Thanks for visiting Tony's Pizza. Want to place an order or have a question?"</li>
                    <li>"Hello! I'm here to help you book your next appointment at Serenity Spa."</li>
                  </ul>
                </div>
                <div className="bg-white/5 rounded-lg p-4 mt-3">
                  <p className="text-gray-300 text-sm font-medium">Best practices:</p>
                  <ul className="space-y-1 text-gray-400 text-sm">
                    <li>Keep it short (1-2 sentences)</li>
                    <li>Match the tone of your business (formal for a law firm, casual for a food truck)</li>
                    <li>Mention what the agent can help with</li>
                  </ul>
                </div>
              </div>
              <div>
                <h3 className="text-base font-semibold text-white mb-2">Upload Your Knowledge</h3>
                <p className="text-gray-400 text-sm mb-2">This is how your agent learns about your business.</p>
                <ol className="list-decimal list-inside space-y-1 text-gray-400 text-sm">
                  <li>Click the <strong>"Knowledge Base"</strong> tab in the agent settings</li>
                  <li>Click <strong>"Upload Documents"</strong></li>
                  <li>Upload files that contain information about your business:
                    <ul className="list-disc list-inside ml-4 mt-1 space-y-1">
                      <li>Price lists or menus</li>
                      <li>Frequently asked questions</li>
                      <li>Service descriptions</li>
                      <li>Office hours and location details</li>
                      <li>Policies (cancellation, refund, etc.)</li>
                    </ul>
                  </li>
                </ol>
                <p className="text-gray-400 text-sm mt-2"><strong>Supported file types:</strong> PDF, Word documents, text files, and CSV files.</p>
                <div className="bg-blue-500/10 border border-blue-500/20 rounded-lg p-4 mt-3">
                  <p className="text-blue-300 text-sm"><strong>Tip:</strong> The more information you provide, the better your agent can answer questions. Think about what your customers ask most often and make sure that information is in the documents you upload.</p>
                </div>
              </div>
            </div>
          </section>

          <section id="step5" className="mb-12">
            <div className="flex items-center gap-3 mb-6">
              <span className="flex items-center justify-center w-8 h-8 rounded-full bg-gradient-to-br from-violet-600 to-blue-600 text-white text-sm font-bold">5</span>
              <h2 className="text-2xl font-bold text-white">Test Your Agent</h2>
            </div>
            <div className="bg-white/[0.03] border border-white/10 rounded-2xl p-6 space-y-4">
              <p className="text-gray-400 text-sm">Before putting your agent on your website, test it to make sure it works the way you want.</p>
              <ol className="list-decimal list-inside space-y-2 text-gray-400 text-sm">
                <li>In the agent settings, click the <strong>"Preview"</strong> button in the top right</li>
                <li>A chat window will open on the right side of your screen</li>
                <li>Type messages as if you were a customer</li>
              </ol>
              <div className="bg-white/5 rounded-lg p-4">
                <p className="text-gray-300 text-sm font-medium mb-2">Things to test:</p>
                <ul className="space-y-1 text-gray-400 text-sm">
                  <li>Ask about your business hours</li>
                  <li>Ask about your services or products</li>
                  <li>Try to book an appointment</li>
                  <li>Ask a question that's NOT related to your business (to see how the agent handles it)</li>
                  <li>Ask about pricing</li>
                </ul>
              </div>
              <div className="bg-white/5 rounded-lg p-4">
                <p className="text-gray-300 text-sm font-medium mb-2">What to Look For</p>
                <ul className="space-y-1 text-gray-400 text-sm">
                  <li>Does the agent answer accurately based on the information you provided?</li>
                  <li>Is the tone appropriate for your business?</li>
                  <li>Does it handle questions it can't answer gracefully?</li>
                </ul>
              </div>
              <p className="text-gray-400 text-sm">If something isn't right, go back to the agent settings and adjust the greeting message, agent role, or upload more documents.</p>
            </div>
          </section>

          <section id="step6" className="mb-12">
            <div className="flex items-center gap-3 mb-6">
              <span className="flex items-center justify-center w-8 h-8 rounded-full bg-gradient-to-br from-violet-600 to-blue-600 text-white text-sm font-bold">6</span>
              <h2 className="text-2xl font-bold text-white">Embed the Widget on Your Website</h2>
            </div>
            <div className="bg-white/[0.03] border border-white/10 rounded-2xl p-6 space-y-4">
              <p className="text-gray-400 text-sm">Once you're happy with how your agent works, it's time to put it on your website.</p>
              <ol className="list-decimal list-inside space-y-2 text-gray-400 text-sm">
                <li>In the agent settings, click the <strong>"Embed"</strong> tab</li>
                <li>You'll see a preview of the chat widget</li>
                <li>Customize the widget appearance:
                  <ul className="list-disc list-inside ml-4 mt-1 space-y-1">
                    <li><strong>Widget color</strong> - Match your brand colors</li>
                    <li><strong>Position</strong> - Choose bottom-right (default) or bottom-left</li>
                    <li><strong>Welcome message</strong> - The text that appears before a customer starts chatting</li>
                  </ul>
                </li>
                <li>Click <strong>"Copy Embed Code"</strong></li>
                <li>Paste the code into your website's HTML, just before the closing <code className="bg-white/5 px-1.5 py-0.5 rounded text-blue-300">&lt;/body&gt;</code> tag</li>
              </ol>
              <div className="bg-white/5 rounded-lg p-4 space-y-3 mt-4">
                <p className="text-gray-300 text-sm font-medium">If You Use a Website Builder</p>
                <div className="space-y-3">
                  <div>
                    <p className="text-white text-sm font-medium">WordPress:</p>
                    <ul className="text-gray-400 text-sm list-disc list-inside">
                      <li>Go to Appearance &gt; Theme Editor (or use a plugin like "Insert Headers and Footers")</li>
                      <li>Paste the code in the footer section</li>
                      <li>Save changes</li>
                    </ul>
                  </div>
                  <div>
                    <p className="text-white text-sm font-medium">Wix:</p>
                    <ul className="text-gray-400 text-sm list-disc list-inside">
                      <li>Go to Settings &gt; Advanced &gt; Custom Code</li>
                      <li>Paste the code in the "Body - End" section</li>
                      <li>Click Apply</li>
                    </ul>
                  </div>
                  <div>
                    <p className="text-white text-sm font-medium">Shopify:</p>
                    <ul className="text-gray-400 text-sm list-disc list-inside">
                      <li>Go to Online Store &gt; Themes &gt; Actions &gt; Edit Code</li>
                      <li>Open <code className="bg-white/5 px-1.5 py-0.5 rounded text-blue-300">theme.liquid</code></li>
                      <li>Paste the code just before <code className="bg-white/5 px-1.5 py-0.5 rounded text-blue-300">&lt;/body&gt;</code></li>
                      <li>Save</li>
                    </ul>
                  </div>
                  <div>
                    <p className="text-white text-sm font-medium">Squarespace:</p>
                    <ul className="text-gray-400 text-sm list-disc list-inside">
                      <li>Go to Settings &gt; Advanced &gt; Code Injection</li>
                      <li>Paste the code in the Footer section</li>
                      <li>Save</li>
                    </ul>
                  </div>
                </div>
              </div>
              <div className="bg-blue-500/10 border border-blue-500/20 rounded-lg p-4">
                <p className="text-blue-300 text-sm"><strong>Note:</strong> If you're not comfortable editing your website's code, ask your web developer to add the embed code. It takes less than 2 minutes.</p>
              </div>
            </div>
          </section>

          <section id="step7" className="mb-12">
            <div className="flex items-center gap-3 mb-6">
              <span className="flex items-center justify-center w-8 h-8 rounded-full bg-gradient-to-br from-violet-600 to-blue-600 text-white text-sm font-bold">7</span>
              <h2 className="text-2xl font-bold text-white">Go Live and Monitor</h2>
            </div>
            <div className="bg-white/[0.03] border border-white/10 rounded-2xl p-6 space-y-4">
              <p className="text-gray-400 text-sm">Your agent is now live on your website! Here's what to do next:</p>
              <div>
                <h3 className="text-base font-semibold text-white mb-2">Check Your Dashboard Regularly</h3>
                <ul className="space-y-1 text-gray-400 text-sm">
                  <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span><strong>Chat History</strong> - See what customers are asking</li>
                  <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span><strong>Satisfaction</strong> - Review customer feedback ratings</li>
                  <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span><strong>Common Questions</strong> - Identify topics your agent handles most often</li>
                </ul>
              </div>
              <div>
                <h3 className="text-base font-semibold text-white mb-2">Make Improvements Over Time</h3>
                <p className="text-gray-400 text-sm mb-2">After your agent has been running for a few days:</p>
                <ol className="list-decimal list-inside space-y-1 text-gray-400 text-sm">
                  <li>Review the chat history to see what customers are asking</li>
                  <li>If the agent struggled with certain questions, upload more documents with that information</li>
                  <li>Adjust the greeting message or agent role if needed</li>
                  <li>Add playbooks for common scenarios (see the Playbooks guide)</li>
                </ol>
              </div>
            </div>
          </section>

          <section id="scenarios" className="mb-12">
            <h2 className="text-2xl font-bold text-white mb-6">Common First-Day Scenarios</h2>
            <div className="space-y-4">
              <div className="bg-white/[0.03] border border-white/10 rounded-2xl p-6">
                <h3 className="text-base font-semibold text-white mb-3">Scenario 1: A Dental Clinic</h3>
                <div className="space-y-3">
                  <div className="bg-white/5 rounded-lg p-4">
                    <p className="text-gray-300 text-sm font-medium">Customer asks:</p>
                    <p className="text-gray-400 text-sm">"Do you take new patients?"</p>
                    <p className="text-gray-300 text-sm font-medium mt-2">Agent responds:</p>
                    <p className="text-gray-400 text-sm">"Yes! We're always happy to welcome new patients to Smile Bright Dental. Would you like to schedule your first visit? I can help you find a convenient time."</p>
                  </div>
                  <div className="bg-white/5 rounded-lg p-4">
                    <p className="text-gray-300 text-sm font-medium">Customer asks:</p>
                    <p className="text-gray-400 text-sm">"How much is a cleaning?"</p>
                    <p className="text-gray-300 text-sm font-medium mt-2">Agent responds:</p>
                    <p className="text-gray-400 text-sm">"A routine dental cleaning at our clinic is $120. This includes a thorough cleaning, examination, and X-rays if needed. We also accept most major insurance plans. Would you like to book an appointment?"</p>
                  </div>
                </div>
              </div>
              <div className="bg-white/[0.03] border border-white/10 rounded-2xl p-6">
                <h3 className="text-base font-semibold text-white mb-3">Scenario 2: A Pizza Shop</h3>
                <div className="space-y-3">
                  <div className="bg-white/5 rounded-lg p-4">
                    <p className="text-gray-300 text-sm font-medium">Customer asks:</p>
                    <p className="text-gray-400 text-sm">"Are you open now?"</p>
                    <p className="text-gray-300 text-sm font-medium mt-2">Agent responds:</p>
                    <p className="text-gray-400 text-sm">"Yes! Tony's Pizza is open until 11 PM tonight. Would you like to place an order for delivery or pickup?"</p>
                  </div>
                  <div className="bg-white/5 rounded-lg p-4">
                    <p className="text-gray-300 text-sm font-medium">Customer asks:</p>
                    <p className="text-gray-400 text-sm">"Do you have gluten-free crust?"</p>
                    <p className="text-gray-300 text-sm font-medium mt-2">Agent responds:</p>
                    <p className="text-gray-400 text-sm">"Yes, we offer gluten-free crust for an additional $3. Our gluten-free options include all our regular toppings. Would you like to see our full menu?"</p>
                  </div>
                </div>
              </div>
              <div className="bg-white/[0.03] border border-white/10 rounded-2xl p-6">
                <h3 className="text-base font-semibold text-white mb-3">Scenario 3: A Hair Salon</h3>
                <div className="bg-white/5 rounded-lg p-4">
                  <p className="text-gray-300 text-sm font-medium">Customer asks:</p>
                  <p className="text-gray-400 text-sm">"How much is a haircut?"</p>
                  <p className="text-gray-300 text-sm font-medium mt-2">Agent responds:</p>
                  <p className="text-gray-400 text-sm">"At Serenity Salon, a women's haircut and style is $65, and a men's haircut is $35. We also offer blowouts starting at $45. Would you like to book an appointment?"</p>
                </div>
              </div>
            </div>
          </section>

          <section id="whats-next" className="mb-12">
            <div className="bg-white/[0.03] border border-white/10 rounded-2xl p-6">
              <h2 className="text-lg font-semibold text-white mb-3">What's Next?</h2>
              <p className="text-gray-400 text-sm mb-3">Now that your agent is live, explore these features to make it even more powerful:</p>
              <ul className="space-y-2 text-gray-400 text-sm">
                <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span><Link href="/docs/agent-setup" className="text-blue-400 hover:underline">Agent Setup</Link> - Fine-tune your agent's personality, voice, and guardrails</li>
                <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span><Link href="/docs/playbooks" className="text-blue-400 hover:underline">Playbooks</Link> - Create conversation scripts for specific scenarios</li>
                <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span><Link href="/docs/tools" className="text-blue-400 hover:underline">Tools</Link> - Give your agent the ability to send emails, book calendar events, and collect payments</li>
                <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span><Link href="/docs/voice-setup" className="text-blue-400 hover:underline">Voice Setup</Link> - Let customers call your agent directly by phone</li>
              </ul>
            </div>
          </section>

          <div className="bg-gradient-to-r from-violet-600/20 to-blue-600/20 border border-violet-500/20 rounded-2xl p-8 text-center">
            <h3 className="text-xl font-bold text-white mb-2">Need Help?</h3>
            <p className="text-gray-400 text-sm mb-6 max-w-lg mx-auto">
              Click the <strong>"?"</strong> icon in the bottom left of your dashboard for instant help, or email us at <a href="mailto:support@ascenai.com" className="text-blue-400 hover:underline">support@ascenai.com</a>.
            </p>
            <div className="flex flex-col sm:flex-row gap-3 justify-center">
              <Link href="/login" className="px-6 py-3 rounded-xl bg-gradient-to-r from-violet-600 to-blue-600 text-white font-medium hover:opacity-90 transition-opacity text-sm">Go to Dashboard</Link>
              <Link href="/pricing" className="px-6 py-3 rounded-xl border border-white/10 text-white font-medium hover:bg-white/5 transition-colors text-sm">View Pricing</Link>
            </div>
          </div>
        </div>
      </div>

      
    </div>
  )
}
