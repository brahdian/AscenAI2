'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'

const navItems = [
  { href: '#name-identity', label: 'Name & Identity' },
  { href: '#greeting', label: 'Greeting Message' },
  { href: '#voice', label: 'Voice Settings' },
  { href: '#personality', label: 'Personality & Tone' },
  { href: '#guardrails', label: 'Guardrails' },
  { href: '#knowledge', label: 'Knowledge Base' },
  { href: '#testing', label: 'Testing' },
]

export default function AgentSetupPage() {
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
            <h1 className="text-4xl sm:text-5xl font-bold mb-4">Agent Configuration</h1>
            <p className="text-gray-400 text-lg max-w-2xl">
              Make your AI agent sound like it belongs to your business. This guide covers every setting you can customize.
            </p>
          </div>

          <section id="name-identity" className="mb-12">
            <h2 className="text-2xl font-bold text-white mb-6">Agent Name and Identity</h2>
            <div className="bg-white/[0.03] border border-white/10 rounded-2xl p-6 space-y-6">
              <p className="text-gray-400 text-sm">Your agent's name is the first thing customers see. Choose something that fits your business.</p>
              <div>
                <h3 className="text-base font-semibold text-white mb-2">Naming Guidelines</h3>
                <div className="bg-white/5 rounded-lg p-4 space-y-3">
                  <div>
                    <p className="text-gray-300 text-sm font-medium">Match your business style:</p>
                    <ul className="text-gray-400 text-sm space-y-1 mt-1">
                      <li>Professional services (dentists, lawyers, clinics): Use formal names like "Reception Assistant" or "Patient Coordinator"</li>
                      <li>Casual businesses (restaurants, shops, salons): Use friendly names like "Order Helper" or "Style Advisor"</li>
                      <li>Personal brands: Use your name with a role, like "Sarah's Assistant" or "Mike's Booking Bot"</li>
                    </ul>
                  </div>
                  <div>
                    <p className="text-gray-300 text-sm font-medium">What to avoid:</p>
                    <ul className="text-gray-400 text-sm space-y-1 mt-1">
                      <li>Generic names like "Chatbot" or "AI Assistant"</li>
                      <li>Names that are too long or hard to spell</li>
                      <li>Names that don't match your brand voice</li>
                    </ul>
                  </div>
                </div>
              </div>
              <div>
                <h3 className="text-base font-semibold text-white mb-2">Agent Role Description</h3>
                <p className="text-gray-400 text-sm mb-3">The role description is the most important setting. It tells your agent who it is and what it should do. Think of it like training a new employee.</p>
                <div className="bg-white/5 rounded-lg p-4 mb-3">
                  <p className="text-gray-300 text-sm font-medium mb-2">Template:</p>
                  <div className="bg-black/30 rounded-lg p-3 font-mono text-sm text-gray-300">
                    You are a [role] for [business name]. You help customers with [main tasks]. Your tone should be [tone]. You should [specific behaviors]. You should NOT [things to avoid].
                  </div>
                </div>
                <div className="space-y-3">
                  <div className="bg-white/5 rounded-lg p-4">
                    <p className="text-white text-sm font-medium mb-1">Dental Clinic:</p>
                    <p className="text-gray-400 text-sm">"You are a friendly receptionist for Smile Bright Dental Clinic. You help patients book appointments, answer questions about our services, and provide office hours and location information. Your tone should be warm and professional. Always ask if they'd like to book an appointment after answering their question. You should NOT give medical advice or discuss specific treatments."</p>
                  </div>
                  <div className="bg-white/5 rounded-lg p-4">
                    <p className="text-white text-sm font-medium mb-1">Pizza Shop:</p>
                    <p className="text-gray-400 text-sm">"You are a helpful order assistant for Tony's Pizza. You help customers place orders, answer questions about our menu, and provide delivery information. Your tone should be casual and enthusiastic. Always suggest our daily special. You should NOT promise delivery times during busy hours or discuss ingredients you don't have information about."</p>
                  </div>
                  <div className="bg-white/5 rounded-lg p-4">
                    <p className="text-white text-sm font-medium mb-1">Hair Salon:</p>
                    <p className="text-gray-400 text-sm">"You are a style advisor for Serenity Salon. You help clients book appointments, learn about our services, and choose the right treatment for their needs. Your tone should be friendly and knowledgeable. Always mention our first-visit discount. You should NOT recommend specific hairstyles without knowing the client's hair type."</p>
                  </div>
                </div>
              </div>
            </div>
          </section>

          <section id="greeting" className="mb-12">
            <h2 className="text-2xl font-bold text-white mb-6">Greeting Message</h2>
            <div className="bg-white/[0.03] border border-white/10 rounded-2xl p-6 space-y-4">
              <p className="text-gray-400 text-sm">The greeting message is what customers see the moment they open the chat widget.</p>
              <div className="bg-white/5 rounded-lg p-4">
                <p className="text-gray-300 text-sm font-medium mb-2">A good greeting does three things:</p>
                <ol className="list-decimal list-inside space-y-1 text-gray-400 text-sm">
                  <li>Welcomes the customer</li>
                  <li>Identifies your business</li>
                  <li>Invites them to ask a question</li>
                </ol>
              </div>
              <div className="space-y-3">
                <div className="bg-white/5 rounded-lg p-4">
                  <p className="text-white text-sm font-medium mb-1">Dental Clinic:</p>
                  <p className="text-gray-400 text-sm">"Hi! Welcome to Smile Bright Dental. How can I help you today? I can answer questions about our services, check our availability, or help you book an appointment."</p>
                </div>
                <div className="bg-white/5 rounded-lg p-4">
                  <p className="text-white text-sm font-medium mb-1">Pizza Shop:</p>
                  <p className="text-gray-400 text-sm">"Hey there! Thanks for visiting Tony's Pizza. Hungry? I can help you place an order, check our menu, or answer any questions about delivery."</p>
                </div>
                <div className="bg-white/5 rounded-lg p-4">
                  <p className="text-white text-sm font-medium mb-1">Hair Salon:</p>
                  <p className="text-gray-400 text-sm">"Hello! Welcome to Serenity Salon. I'm here to help you book your next appointment or answer any questions about our services. What can I do for you?"</p>
                </div>
                <div className="bg-white/5 rounded-lg p-4">
                  <p className="text-white text-sm font-medium mb-1">Law Firm:</p>
                  <p className="text-gray-400 text-sm">"Good day. Thank you for contacting Morrison & Associates. How may I assist you? I can provide information about our practice areas or help you schedule a consultation."</p>
                </div>
              </div>
              <div className="bg-white/5 rounded-lg p-4">
                <p className="text-gray-300 text-sm font-medium mb-2">Best Practices</p>
                <ul className="space-y-1 text-gray-400 text-sm">
                  <li>Keep it under 3 sentences</li>
                  <li>Match your business tone (formal, casual, friendly)</li>
                  <li>Mention 2-3 things the agent can help with</li>
                  <li>Avoid generic greetings like "How can I help?" without context</li>
                  <li>Update it seasonally or during promotions</li>
                </ul>
              </div>
            </div>
          </section>

          <section id="voice" className="mb-12">
            <h2 className="text-2xl font-bold text-white mb-6">Voice Settings</h2>
            <div className="bg-white/[0.03] border border-white/10 rounded-2xl p-6 space-y-6">
              <p className="text-gray-400 text-sm">If your agent handles phone calls, voice settings determine how it sounds.</p>
              <div>
                <h3 className="text-base font-semibold text-white mb-2">Language</h3>
                <ul className="space-y-1 text-gray-400 text-sm">
                  <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span><strong>English</strong> - Default, supports American, British, Australian, and other accents</li>
                  <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span><strong>French</strong> - For Canadian and French businesses</li>
                  <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span><strong>Spanish</strong> - For businesses serving Spanish-speaking communities</li>
                  <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span><strong>Hindi, Mandarin, Arabic</strong> - Available on Growth and Scale plans</li>
                </ul>
              </div>
              <div>
                <h3 className="text-base font-semibold text-white mb-2">Voice Selection</h3>
                <p className="text-gray-400 text-sm mb-2">Choose from a variety of natural-sounding voices. You can preview each voice before selecting.</p>
                <ul className="space-y-1 text-gray-400 text-sm">
                  <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span><strong>Professional</strong> - Clear, formal voices good for clinics, law firms, and financial services</li>
                  <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span><strong>Friendly</strong> - Warm, conversational voices good for restaurants, salons, and retail</li>
                  <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span><strong>Energetic</strong> - Upbeat voices good for fitness centers, entertainment, and youth-oriented businesses</li>
                </ul>
              </div>
              <div>
                <h3 className="text-base font-semibold text-white mb-2">Voice Speed</h3>
                <ul className="space-y-1 text-gray-400 text-sm">
                  <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span><strong>Slow</strong> - Good for older customers or complex information</li>
                  <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span><strong>Normal</strong> - Default, works for most situations</li>
                  <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span><strong>Fast</strong> - Good for quick confirmations and simple interactions</li>
                </ul>
              </div>
            </div>
          </section>

          <section id="personality" className="mb-12">
            <h2 className="text-2xl font-bold text-white mb-6">Personality and Tone</h2>
            <div className="bg-white/[0.03] border border-white/10 rounded-2xl p-6 space-y-6">
              <div>
                <h3 className="text-base font-semibold text-white mb-2">Tone Settings</h3>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm text-gray-400">
                    <thead>
                      <tr className="border-b border-white/10">
                        <th className="text-left py-2 pr-4 text-white font-medium">Tone</th>
                        <th className="text-left py-2 pr-4 text-white font-medium">Best For</th>
                        <th className="text-left py-2 text-white font-medium">Example Response</th>
                      </tr>
                    </thead>
                    <tbody className="space-y-1">
                      <tr className="border-b border-white/5">
                        <td className="py-2 pr-4">Professional</td>
                        <td className="py-2 pr-4">Law firms, clinics, financial services</td>
                        <td className="py-2">"I'd be happy to help you schedule a consultation."</td>
                      </tr>
                      <tr className="border-b border-white/5">
                        <td className="py-2 pr-4">Friendly</td>
                        <td className="py-2 pr-4">Restaurants, salons, retail</td>
                        <td className="py-2">"Sure thing! Let me help you with that!"</td>
                      </tr>
                      <tr className="border-b border-white/5">
                        <td className="py-2 pr-4">Casual</td>
                        <td className="py-2 pr-4">Food trucks, bars, youth brands</td>
                        <td className="py-2">"No worries, I got you covered!"</td>
                      </tr>
                      <tr>
                        <td className="py-2 pr-4">Enthusiastic</td>
                        <td className="py-2 pr-4">Fitness, entertainment, events</td>
                        <td className="py-2">"That's awesome! Let's get you set up!"</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </div>
              <div>
                <h3 className="text-base font-semibold text-white mb-2">Custom Personality Instructions</h3>
                <ul className="space-y-1 text-gray-400 text-sm">
                  <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span>"Always be patient and explain things clearly"</li>
                  <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span>"Use humor when appropriate, but stay respectful"</li>
                  <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span>"Be brief and direct - our customers are in a hurry"</li>
                  <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span>"Always thank the customer at the end of the conversation"</li>
                  <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span>"Use the customer's name if they provide it"</li>
                </ul>
              </div>
              <div>
                <h3 className="text-base font-semibold text-white mb-2">What to Avoid</h3>
                <ul className="space-y-1 text-gray-400 text-sm">
                  <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span>Overly casual language for professional services</li>
                  <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span>Robotic or overly formal language for casual businesses</li>
                  <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span>Making promises you can't keep</li>
                  <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span>Using slang or jargon your customers won't understand</li>
                </ul>
              </div>
            </div>
          </section>

          <section id="guardrails" className="mb-12">
            <h2 className="text-2xl font-bold text-white mb-6">Guardrails</h2>
            <div className="bg-white/[0.03] border border-white/10 rounded-2xl p-6 space-y-6">
              <p className="text-gray-400 text-sm">Guardrails are rules that tell your agent what NOT to do. They protect your business from mistakes and keep conversations on track.</p>
              <div>
                <h3 className="text-base font-semibold text-white mb-2">Why Guardrails Matter</h3>
                <p className="text-gray-400 text-sm mb-2">Without guardrails, your agent might:</p>
                <ul className="space-y-1 text-gray-400 text-sm">
                  <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span>Give incorrect information about pricing</li>
                  <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span>Promise services you don't offer</li>
                  <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span>Share sensitive business information</li>
                  <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span>Handle complaints inappropriately</li>
                  <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span>Go off-topic for too long</li>
                </ul>
              </div>
              <div>
                <h3 className="text-base font-semibold text-white mb-2">Common Guardrails</h3>
                <div className="space-y-3">
                  <div className="bg-white/5 rounded-lg p-4">
                    <p className="text-white text-sm font-medium mb-1">Information Guardrails:</p>
                    <ul className="text-gray-400 text-sm space-y-1">
                      <li>"Do not provide pricing information not found in the knowledge base"</li>
                      <li>"Do not discuss competitor businesses"</li>
                      <li>"Do not share internal company information"</li>
                    </ul>
                  </div>
                  <div className="bg-white/5 rounded-lg p-4">
                    <p className="text-white text-sm font-medium mb-1">Behavior Guardrails:</p>
                    <ul className="text-gray-400 text-sm space-y-1">
                      <li>"Do not make promises about delivery times"</li>
                      <li>"Do not offer discounts not listed in the knowledge base"</li>
                      <li>"Do not argue with customers - always stay polite"</li>
                    </ul>
                  </div>
                  <div className="bg-white/5 rounded-lg p-4">
                    <p className="text-white text-sm font-medium mb-1">Scope Guardrails:</p>
                    <ul className="text-gray-400 text-sm space-y-1">
                      <li>"If asked about topics outside your knowledge, say: 'I'm not sure about that. Let me connect you with someone who can help.'"</li>
                      <li>"If a customer is upset, apologize and offer to have a team member follow up"</li>
                      <li>"If asked for medical or legal advice, direct them to speak with a professional"</li>
                    </ul>
                  </div>
                </div>
              </div>
              <div>
                <h3 className="text-base font-semibold text-white mb-2">Setting Guardrails</h3>
                <ol className="list-decimal list-inside space-y-1 text-gray-400 text-sm">
                  <li>In your agent settings, go to the <strong>"Guardrails"</strong> tab</li>
                  <li>Click <strong>"Add Guardrail"</strong></li>
                  <li>Type your rule in plain language</li>
                  <li>Click <strong>"Save"</strong></li>
                </ol>
              </div>
            </div>
          </section>

          <section id="knowledge" className="mb-12">
            <h2 className="text-2xl font-bold text-white mb-6">Knowledge Base</h2>
            <div className="bg-white/[0.03] border border-white/10 rounded-2xl p-6 space-y-6">
              <p className="text-gray-400 text-sm">Your knowledge base is where you upload information about your business. This is how your agent learns what to say.</p>
              <div>
                <h3 className="text-base font-semibold text-white mb-2">What to Upload</h3>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm text-gray-400">
                    <thead>
                      <tr className="border-b border-white/10">
                        <th className="text-left py-2 pr-4 text-white font-medium">Document Type</th>
                        <th className="text-left py-2 text-white font-medium">Example Content</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr className="border-b border-white/5"><td className="py-2 pr-4">FAQ document</td><td className="py-2">Answers to your 20 most common customer questions</td></tr>
                      <tr className="border-b border-white/5"><td className="py-2 pr-4">Price list</td><td className="py-2">All your services and their prices</td></tr>
                      <tr className="border-b border-white/5"><td className="py-2 pr-4">Menu</td><td className="py-2">Full menu with descriptions and prices</td></tr>
                      <tr className="border-b border-white/5"><td className="py-2 pr-4">Service descriptions</td><td className="py-2">Detailed explanations of what you offer</td></tr>
                      <tr className="border-b border-white/5"><td className="py-2 pr-4">Office hours</td><td className="py-2">When you're open, holiday schedules</td></tr>
                      <tr className="border-b border-white/5"><td className="py-2 pr-4">Location info</td><td className="py-2">Address, parking instructions, directions</td></tr>
                      <tr className="border-b border-white/5"><td className="py-2 pr-4">Policies</td><td className="py-2">Cancellation, refund, return policies</td></tr>
                      <tr><td className="py-2 pr-4">Staff bios</td><td className="py-2">Information about your team members</td></tr>
                    </tbody>
                  </table>
                </div>
              </div>
              <div>
                <h3 className="text-base font-semibold text-white mb-2">How to Upload</h3>
                <ol className="list-decimal list-inside space-y-1 text-gray-400 text-sm">
                  <li>In your agent settings, click the <strong>"Knowledge Base"</strong> tab</li>
                  <li>Click <strong>"Upload Documents"</strong></li>
                  <li>Select files from your computer</li>
                  <li>Wait for the upload to complete (you'll see a progress bar)</li>
                  <li>Your documents are automatically processed and ready to use</li>
                </ol>
                <p className="text-gray-400 text-sm mt-2"><strong>Supported file types:</strong> PDF, Word (.doc, .docx), Text (.txt), CSV</p>
              </div>
              <div>
                <h3 className="text-base font-semibold text-white mb-2">Organizing Your Knowledge</h3>
                <ul className="space-y-1 text-gray-400 text-sm">
                  <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span><strong>Use clear headings</strong> - Your agent uses headings to find information quickly</li>
                  <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span><strong>Keep documents focused</strong> - One topic per document works best</li>
                  <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span><strong>Update regularly</strong> - When prices or hours change, upload the new version</li>
                  <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span><strong>Remove outdated documents</strong> - Old information can confuse your agent</li>
                </ul>
              </div>
            </div>
          </section>

          <section id="testing" className="mb-12">
            <h2 className="text-2xl font-bold text-white mb-6">Testing Your Configuration</h2>
            <div className="bg-white/[0.03] border border-white/10 rounded-2xl p-6 space-y-6">
              <div>
                <h3 className="text-base font-semibold text-white mb-2">Testing Checklist</h3>
                <ul className="space-y-1 text-gray-400 text-sm">
                  <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span>Ask about business hours</li>
                  <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span>Ask about pricing for a specific service</li>
                  <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span>Try to book an appointment</li>
                  <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span>Ask a question NOT covered in your knowledge base</li>
                  <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span>Ask about a topic your guardrails should block</li>
                  <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span>Test the greeting message by opening the widget</li>
                  <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span>Check that the tone matches your brand</li>
                </ul>
              </div>
              <div>
                <h3 className="text-base font-semibold text-white mb-2">When to Revisit Your Configuration</h3>
                <ul className="space-y-1 text-gray-400 text-sm">
                  <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span><strong>Monthly</strong> - Review chat history and update knowledge base</li>
                  <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span><strong>When prices change</strong> - Update pricing documents immediately</li>
                  <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span><strong>When you add services</strong> - Upload new service descriptions</li>
                  <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span><strong>When customers ask questions your agent can't answer</strong> - Add that information</li>
                  <li className="flex items-start gap-2"><span className="text-violet-400 mt-0.5">&#9679;</span><strong>Seasonally</strong> - Update hours, promotions, and greeting messages</li>
                </ul>
              </div>
            </div>
          </section>

          <div className="bg-gradient-to-r from-violet-600/20 to-blue-600/20 border border-violet-500/20 rounded-2xl p-8 text-center">
            <h3 className="text-xl font-bold text-white mb-2">Ready to Build Your Agent?</h3>
            <p className="text-gray-400 text-sm mb-6 max-w-lg mx-auto">
              Follow our Quick Start guide to get your first agent running in under 10 minutes.
            </p>
            <div className="flex flex-col sm:flex-row gap-3 justify-center">
              <Link href="/docs/quick-start" className="px-6 py-3 rounded-xl bg-gradient-to-r from-violet-600 to-blue-600 text-white font-medium hover:opacity-90 transition-opacity text-sm">Quick Start Guide</Link>
              <Link href="/login" className="px-6 py-3 rounded-xl border border-white/10 text-white font-medium hover:bg-white/5 transition-colors text-sm">Go to Dashboard</Link>
            </div>
          </div>
        </div>
      </div>

      
    </div>
  )
}
