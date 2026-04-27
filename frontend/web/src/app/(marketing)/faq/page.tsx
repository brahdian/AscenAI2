'use client'

import { useState } from 'react'
import { ChevronDown } from 'lucide-react'

export default function FAQPage() {
  const [openFaq, setOpenFaq] = useState<number | null>(0)

  const faqs = [
    {
      q: 'What is AscenAI?',
      a: 'AscenAI is a platform that allows local businesses (like salons, clinics, and pizza shops) to deploy intelligent voice and chat agents. These agents can handle customer calls, bookings, orders, and general inquiries automatically, 24/7.',
    },
    {
      q: 'How does the "chat equivalents" billing model work?',
      a: 'Each plan gives you a pool of "chat equivalents" you can use flexibly. 1 voice minute = 100 chat equivalents. For example, if you have 80,000 chat equivalents, you could use them for 80,000 chats, 800 voice minutes, or any combination of the two.',
    },
    {
      q: 'Do I need my own telephony provider (like Twilio)?',
      a: 'Yes. You bring your own Twilio or Telnyx account for telephony. This means you only pay us for the AI layer (Speech-to-Text, LLM, and Text-to-Speech) and not for carrier costs, which allows us to offer much lower prices per minute compared to competitors.',
    },
    {
      q: 'Which AI models do your agents use?',
      a: 'Our platform is powered by Google\'s Gemini 2.5 Flash Lite. This model is extremely fast and optimized for real-time voice and chat, allowing us to maintain sub-200ms latency for seamless voice conversations.',
    },
    {
      q: 'Can the agent learn from my own documents?',
      a: 'Absolutely! You can upload your business documents (PDFs, menus, policy guidelines) into the agent\'s Knowledge Base. The agent uses Retrieval-Augmented Generation (RAG) to accurately answer questions based solely on your provided information.',
    },
    {
      q: 'What happens when I exceed my plan limits?',
      a: 'Your agents will continue to operate normally—we never cut off an active conversation. Any usage over your plan limit is billed at the standard overage rates specified in your plan, which will be added to your next invoice.',
    },
    {
      q: 'Can I switch or cancel my plan?',
      a: 'Yes, you can upgrade, downgrade, or cancel your plan at any time from your billing dashboard. Upgrades take effect immediately (prorated), and downgrades/cancellations take effect at the end of your current billing cycle.',
    },
    {
      q: 'Is AscenAI secure and compliant?',
      a: 'Security and privacy are foundational. AscenAI implements strong multi-tenant isolation, enterprise-grade zero-trust architecture, and strict PII/PHI redaction guardrails to keep your customer data secure and compliant.',
    },
  ]

  return (
    <div className="max-w-3xl mx-auto px-8 pt-24 pb-32">
      <div className="text-center mb-16">
        <h1 className="text-4xl sm:text-5xl font-bold mb-6">Frequently Asked Questions</h1>
        <p className="text-gray-400 text-lg">
          Everything you need to know about AscenAI, pricing, and how our agents work.
        </p>
      </div>

      <div className="space-y-4">
        {faqs.map((faq, idx) => {
          const isOpen = openFaq === idx
          return (
            <div
              key={idx}
              className={`border border-white/10 rounded-2xl bg-white/[0.02] overflow-hidden transition-all ${
                isOpen ? 'border-violet-500/30 bg-white/[0.04]' : ''
              }`}
            >
              <button
                onClick={() => setOpenFaq(isOpen ? null : idx)}
                className="w-full flex items-center justify-between p-6 text-left"
              >
                <span className="font-bold text-lg text-white">{faq.q}</span>
                <ChevronDown
                  className={`shrink-0 text-gray-500 transition-transform ${
                    isOpen ? 'rotate-180 text-violet-400' : ''
                  }`}
                  size={20}
                />
              </button>
              <div
                className={`overflow-hidden transition-all duration-300 ease-in-out ${
                  isOpen ? 'max-h-96 opacity-100' : 'max-h-0 opacity-0'
                }`}
              >
                <p className="px-6 pb-6 text-gray-400 leading-relaxed border-t border-white/5 pt-4">
                  {faq.a}
                </p>
              </div>
            </div>
          )
        })}
      </div>

      <div className="mt-16 p-8 rounded-2xl bg-gradient-to-br from-violet-600/20 to-blue-600/20 border border-violet-500/20 text-center">
        <h2 className="text-xl font-bold mb-2">Still have questions?</h2>
        <p className="text-gray-400 text-sm mb-6">
          Can&apos;t find the answer you&apos;re looking for? Please chat to our friendly team.
        </p>
        <a
          href="/contact"
          className="inline-block px-6 py-2.5 rounded-xl bg-violet-600 hover:bg-violet-700 text-white font-semibold transition-colors"
        >
          Get in touch
        </a>
      </div>
    </div>
  )
}
