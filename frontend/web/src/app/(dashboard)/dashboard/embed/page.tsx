'use client'

import { useEffect, useRef, useState, useCallback } from 'react'
import { agentsApi, apiKeysApi, feedbackApi } from '@/lib/api'
import { Code2, Copy, Check, Globe, Package, Terminal, MessageSquare, Eye, RefreshCw, Send, X, ThumbsUp, ThumbsDown, PenLine } from 'lucide-react'

interface Agent { id: string; name: string }
interface APIKey { id: string; name: string; key_prefix: string; key?: string }

interface PreviewMessage {
  role: 'user' | 'assistant'
  content: string
  feedback?: {
    rating?: 'positive' | 'negative'
    ideal_response?: string
    comment?: string
  }
}

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

export default function EmbedPage() {
  const [agents, setAgents] = useState<Agent[]>([])
  const [keys, setKeys] = useState<APIKey[]>([])
  const [agentId, setAgentId] = useState('')
  const [selectedKeyId, setSelectedKeyId] = useState('')
  const [activeTab, setActiveTab] = useState<'widget' | 'sdk' | 'api'>('widget')
  const [copied, setCopied] = useState<string | null>(null)
  const [previewKey, setPreviewKey] = useState(0)

  // Preview chat state
  const [previewOpen, setPreviewOpen] = useState(true)
  const [previewMessages, setPreviewMessages] = useState<PreviewMessage[]>([])
  const [previewInput, setPreviewInput] = useState('')
  const [previewLoading, setPreviewLoading] = useState(false)
  const [previewStreaming, setPreviewStreaming] = useState(false)
  const [previewSessionId, setPreviewSessionId] = useState<string | null>(null)
  const previewEndRef = useRef<HTMLDivElement>(null)

  // Feedback state
  const [showFeedbackModal, setShowFeedbackModal] = useState(false)
  const [feedbackMessageIndex, setFeedbackMessageIndex] = useState<number | null>(null)
  const [feedbackMode, setFeedbackMode] = useState<'rate' | 'correct'>('rate')

  const selectedAgent = agents.find((a) => a.id === agentId)
  const selectedKey = keys.find((k) => k.id === selectedKeyId)
  const apiKeyDisplay = selectedKey?.key || (selectedKey ? `${selectedKey.key_prefix}… (use full key)` : 'YOUR_API_KEY')

  useEffect(() => {
    agentsApi.list().then(setAgents).catch(() => {})
    apiKeysApi.list().then(setKeys).catch(() => {})
  }, [])

  useEffect(() => {
    previewEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [previewMessages])

  const resetPreview = () => {
    setPreviewKey(k => k + 1)
    setPreviewMessages([])
    setPreviewInput('')
    setPreviewLoading(false)
    setPreviewStreaming(false)
    setPreviewSessionId(null)
    setPreviewOpen(true)
  }

  const handlePreviewSend = useCallback(async () => {
    if (!previewInput.trim() || previewLoading) return
    const userMsg = previewInput.trim()
    setPreviewInput('')
    setPreviewMessages(prev => [...prev, { role: 'user', content: userMsg }])
    setPreviewLoading(true)
    setPreviewStreaming(false)

    const apiKey = selectedKey?.key
    if (agentId && apiKey) {
      try {
        const response = await fetch(`${API_URL}/api/v1/proxy/chat/stream`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${apiKey}`,
          },
          body: JSON.stringify({
            agent_id: agentId,
            message: userMsg,
            session_id: previewSessionId || undefined,
            channel: 'chat',
          }),
        })

        if (response.ok && response.body) {
          const reader = response.body.getReader()
          const decoder = new TextDecoder()
          let firstChunk = true

          while (true) {
            const { done, value } = await reader.read()
            if (done) break
            const chunk = decoder.decode(value, { stream: true })
            const lines = chunk.split('\n')
            for (const line of lines) {
              if (line.startsWith('data: ')) {
                try {
                  const parsed = JSON.parse(line.substring(6))
                  if (parsed.type === 'text' && parsed.data) {
                    setPreviewLoading(false)
                    setPreviewStreaming(true)
                    firstChunk = false
                    setPreviewMessages(prev => {
                      const last = prev[prev.length - 1]
                      if (last && last.role === 'assistant') {
                        return [...prev.slice(0, -1), { ...last, content: last.content + parsed.data }]
                      }
                      return [...prev, { role: 'assistant', content: parsed.data }]
                    })
                  } else if (parsed.session_id) {
                    setPreviewSessionId(parsed.session_id)
                  }
                } catch {}
              }
            }
          }
          if (firstChunk) {
            setPreviewMessages(prev => [...prev, { role: 'assistant', content: 'No response received.' }])
          }
        } else {
          throw new Error('Stream failed')
        }
      } catch {
        try {
          const res = await fetch(`${API_URL}/api/v1/proxy/chat`, {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              'Authorization': `Bearer ${apiKey}`,
            },
            body: JSON.stringify({
              agent_id: agentId,
              message: userMsg,
              session_id: previewSessionId || undefined,
              channel: 'chat',
            }),
          })
          if (res.ok) {
            const data = await res.json()
            if (data.session_id) setPreviewSessionId(data.session_id)
            const fullText = data.message || data.response || 'No response.'
            setPreviewLoading(false)
            setPreviewStreaming(true)
            // Simulate streaming by revealing characters
            let displayed = ''
            for (let i = 0; i < fullText.length; i++) {
              displayed += fullText[i]
              const current = displayed
              setPreviewMessages(prev => {
                const last = prev[prev.length - 1]
                if (last && last.role === 'assistant' && i > 0) {
                  return [...prev.slice(0, -1), { ...last, content: current }]
                }
                return [...prev, { role: 'assistant', content: current }]
              })
              await new Promise(r => setTimeout(r, 12))
            }
          } else {
            throw new Error('Chat failed')
          }
        } catch {
          setPreviewMessages(prev => [
            ...prev,
            { role: 'assistant', content: 'Sorry, I could not connect to the agent. Please check your API key and agent configuration.' },
          ])
        }
      }
    } else {
      // No agent/key — simulate a response
      await new Promise(r => setTimeout(r, 800))
      const responses = [
        "Hi there! I'm your AI assistant. How can I help you today?",
        "I'd be happy to help with that! Could you provide more details?",
        "That's a great question. Let me look into it for you.",
        "I can assist you with booking, questions, and more. What do you need?",
      ]
      const reply = responses[Math.floor(Math.random() * responses.length)]
      setPreviewLoading(false)
      setPreviewStreaming(true)
      let displayed = ''
      for (let i = 0; i < reply.length; i++) {
        displayed += reply[i]
        const current = displayed
        setPreviewMessages(prev => {
          const last = prev[prev.length - 1]
          if (last && last.role === 'assistant' && i > 0) {
            return [...prev.slice(0, -1), { ...last, content: current }]
          }
          return [...prev, { role: 'assistant', content: current }]
        })
        await new Promise(r => setTimeout(r, 18))
      }
    }
    setPreviewStreaming(false)
    setPreviewLoading(false)
  }, [previewInput, previewLoading, agentId, selectedKey, previewSessionId])

  const widgetSnippet = `<!-- AscenAI Chat Widget -->
<script>
  window.AscenAI = {
    agentId: '${agentId || 'YOUR_AGENT_ID'}',
    apiKey: '${apiKeyDisplay}',
    apiUrl: '${API_URL}',
    theme: { primaryColor: '#7c3aed' },
  };
</script>
<script src="${API_URL}/widget/widget.js" defer></script>`

  const sdkUsage = `// AscenAI JavaScript client — copy this into your project
// (npm package @ascenai/sdk coming soon)

const ASCENAI_API = '${API_URL}';
const API_KEY     = '${apiKeyDisplay}';
const AGENT_ID    = '${agentId || 'YOUR_AGENT_ID'}';

async function chat(message, sessionId = null) {
  const res = await fetch(\`\${ASCENAI_API}/api/v1/proxy/chat\`, {
    method: 'POST',
    headers: {
      'Authorization': \`Bearer \${API_KEY}\`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ agent_id: AGENT_ID, message, session_id: sessionId, channel: 'api' }),
  });
  if (!res.ok) throw new Error(\`AscenAI error: \${res.status}\`);
  return res.json(); // { message, session_id, ... }
}

// Usage
const reply = await chat('Hello, I need to book an appointment');
console.log(reply.message);

// Continue same session
const followUp = await chat('Tomorrow at 2pm works', reply.session_id);`

  const curlExample = `curl -X POST ${API_URL}/api/v1/proxy/chat \\
  -H "Authorization: Bearer YOUR_API_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{
    "agent_id": "${agentId || 'YOUR_AGENT_ID'}",
    "message": "Hello, I need help",
    "channel": "api"
  }'`

  const copy = (text: string, key: string) => {
    navigator.clipboard.writeText(text)
    setCopied(key)
    setTimeout(() => setCopied(null), 2000)
  }

  const CopyBtn = ({ text, id }: { text: string; id: string }) => (
    <button
      onClick={() => copy(text, id)}
      className="absolute top-3 right-3 p-1.5 rounded-md bg-gray-700 hover:bg-gray-600 text-gray-300 transition-colors"
    >
      {copied === id ? <Check size={14} className="text-green-400" /> : <Copy size={14} />}
    </button>
  )

  const openFeedbackModal = (index: number, mode: 'rate' | 'correct') => {
    setFeedbackMessageIndex(index)
    setFeedbackMode(mode)
    setShowFeedbackModal(true)
  }

  const closeFeedbackModal = () => {
    setShowFeedbackModal(false)
    setFeedbackMessageIndex(null)
  }

  const handleFeedbackSubmit = async (rating?: 'positive' | 'negative', idealResponse?: string, comment?: string) => {
    if (feedbackMessageIndex === null || !agentId) return
    const msg = previewMessages[feedbackMessageIndex]
    if (!msg || msg.role !== 'assistant') return

    const messageId = `embed-${agentId}-${feedbackMessageIndex}-${Date.now()}`
    const sessionIdValue = previewSessionId || `embed-session-${Date.now()}`

    try {
      await feedbackApi.submit({
        message_id: messageId,
        session_id: sessionIdValue,
        agent_id: agentId,
        rating,
        ideal_response: idealResponse,
        comment,
        feedback_source: 'operator',
      })
      setPreviewMessages(prev => prev.map((m, i) =>
        i === feedbackMessageIndex
          ? { ...m, feedback: { rating: rating || undefined, ideal_response: idealResponse, comment } }
          : m
      ))
      closeFeedbackModal()
    } catch {
      // Silent fail - this is a preview page
    }
  }

  return (
    <div className="p-8 w-full">
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-gray-900 dark:text-white flex items-center gap-2">
          <Code2 size={24} className="text-violet-500" />
          Embed & SDK
        </h1>
        <p className="text-gray-500 mt-1">Integrate AscenAI into your website or application.</p>
      </div>

      {/* Step 1: Select agent + key */}
      <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 p-6 mb-6">
        <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-4">1. Select Agent & API Key</h2>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-xs text-gray-500 mb-1">Agent</label>
            <select
              value={agentId}
              onChange={(e) => setAgentId(e.target.value)}
              className="w-full px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-sm text-gray-900 dark:text-white"
            >
              <option value="">Select an agent…</option>
              {agents.map((a) => (
                <option key={a.id} value={a.id}>{a.name}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">API Key</label>
            <select
              value={selectedKeyId}
              onChange={(e) => setSelectedKeyId(e.target.value)}
              className="w-full px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-sm text-gray-900 dark:text-white"
            >
              <option value="">Select an API key…</option>
              {keys.map((k) => (
                <option key={k.id} value={k.id}>{k.name} ({k.key_prefix}…)</option>
              ))}
            </select>
          </div>
        </div>
        {(!agentId || !selectedKeyId) && (
          <p className="text-xs text-amber-600 dark:text-amber-400 mt-3">
            Select an agent and API key to generate your integration code.
          </p>
        )}
        {selectedKey && !selectedKey.key && (
          <p className="text-xs text-amber-600 dark:text-amber-400 mt-3">
            ⚠️ The full API key is only shown when first created. Replace <code className="font-mono text-violet-600">{selectedKey.key_prefix}…</code> in the snippet with your actual key.
          </p>
        )}
      </div>

      {/* Step 2: Integration tabs */}
      <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 p-6">
        <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-4">2. Integration Code</h2>

        <div className="flex gap-1 mb-5 bg-gray-100 dark:bg-gray-800 rounded-lg p-1 w-fit">
          {[
            { id: 'widget', label: 'Web Widget', icon: Globe },
            { id: 'sdk', label: 'JavaScript', icon: Package },
            { id: 'api', label: 'REST API', icon: Terminal },
          ].map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              onClick={() => setActiveTab(id as typeof activeTab)}
              className={`flex items-center gap-2 px-4 py-2 rounded-md text-sm font-medium transition-colors ${
                activeTab === id
                  ? 'bg-white dark:bg-gray-900 text-violet-700 dark:text-violet-300 shadow-sm'
                  : 'text-gray-500 hover:text-gray-700 dark:hover:text-gray-300'
              }`}
            >
              <Icon size={14} />
              {label}
            </button>
          ))}
        </div>

        {activeTab === 'widget' && (
          <div className="space-y-4">
            <p className="text-sm text-gray-600 dark:text-gray-400">
              Paste this snippet before the closing <code className="text-violet-600">&lt;/body&gt;</code> tag on any page.
            </p>
            <div className="relative">
              <pre className="bg-gray-950 text-gray-100 rounded-lg p-4 text-xs overflow-x-auto leading-relaxed">
                {widgetSnippet}
              </pre>
              <CopyBtn text={widgetSnippet} id="widget" />
            </div>

            {/* Live preview */}
            <div className="rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden">
              <div className="flex items-center justify-between px-4 py-2.5 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">
                <div className="flex items-center gap-2 text-sm font-medium text-gray-700 dark:text-gray-300">
                  <Eye size={14} className="text-violet-500" />
                  Live Preview
                  {agentId && selectedKeyId && (
                    <span className="text-xs text-emerald-600 dark:text-emerald-400 font-normal">— Connected to {selectedAgent?.name || 'agent'}</span>
                  )}
                  {!agentId && (
                    <span className="text-xs text-gray-400 font-normal">— Select an agent above to connect</span>
                  )}
                </div>
                <button
                  onClick={resetPreview}
                  className="flex items-center gap-1.5 text-xs text-gray-500 hover:text-gray-700 dark:hover:text-gray-300 transition-colors px-2 py-1 rounded-md hover:bg-gray-200 dark:hover:bg-gray-700"
                >
                  <RefreshCw size={12} />
                  Reset
                </button>
              </div>
              <div className="relative bg-[#f8f9ff] dark:bg-gray-900" style={{ height: '420px' }}>
                {/* Fake page background */}
                <div className="p-8 text-gray-400 text-sm select-none">
                  <p className="text-gray-600 dark:text-gray-300 font-medium text-base mb-1">Your website</p>
                  <p>This is how the chat widget appears on your customers&apos; site.</p>
                  <p className="mt-1">Click the bubble or type below to try it.</p>
                </div>

                {/* Interactive chat widget */}
                {previewOpen ? (
                  <div className="absolute bottom-16 right-4 w-80 rounded-2xl overflow-hidden shadow-2xl border border-gray-100 dark:border-gray-700 bg-white dark:bg-gray-800 flex flex-col" style={{ height: '340px' }}>
                    {/* Header */}
                    <div className="flex items-center justify-between px-4 py-3 flex-shrink-0" style={{ background: '#7c3aed' }}>
                      <div className="flex items-center gap-2.5">
                        <div className="w-8 h-8 rounded-full bg-white/20 flex items-center justify-center">
                          <MessageSquare size={14} className="text-white" />
                        </div>
                        <div>
                          <p className="text-white text-sm font-semibold leading-tight">
                            {selectedAgent?.name || 'Support'}
                          </p>
                          <p className="text-white/70 text-xs">Online now</p>
                        </div>
                      </div>
                      <button onClick={() => setPreviewOpen(false)} className="text-white/70 hover:text-white transition-colors">
                        <X size={16} />
                      </button>
                    </div>
                    {/* Messages */}
                    <div className="flex-1 overflow-y-auto p-3 space-y-2 bg-gray-50 dark:bg-gray-900">
                      {previewMessages.length === 0 && (
                        <div className="flex gap-2 items-end">
                          <div className="w-6 h-6 rounded-full flex-shrink-0 flex items-center justify-center" style={{ background: '#7c3aed' }}>
                            <MessageSquare size={10} className="text-white" />
                          </div>
                          <div className="bg-white dark:bg-gray-800 rounded-2xl rounded-bl-sm px-3 py-2 text-xs text-gray-700 dark:text-gray-200 shadow-sm max-w-[75%]">
                            Hi! How can I help you today?
                          </div>
                        </div>
                      )}
                      {previewMessages.map((msg, i) => (
                        <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start gap-2 items-end'}`}>
                          {msg.role === 'assistant' && (
                            <div className="w-6 h-6 rounded-full flex-shrink-0 flex items-center justify-center" style={{ background: '#7c3aed' }}>
                              <MessageSquare size={10} className="text-white" />
                            </div>
                          )}
                          <div className="flex flex-col gap-1 max-w-[75%]">
                            <div
                              className={`px-3 py-2 text-xs shadow-sm ${
                                msg.role === 'user'
                                  ? 'rounded-2xl rounded-br-sm text-white'
                                  : 'bg-white dark:bg-gray-800 rounded-2xl rounded-bl-sm text-gray-700 dark:text-gray-200'
                              }`}
                              style={msg.role === 'user' ? { background: '#7c3aed' } : {}}
                            >
                              {msg.content}
                              {previewStreaming && msg.role === 'assistant' && i === previewMessages.length - 1 && (
                                <span className="inline-block w-1 h-3 ml-0.5 bg-violet-500 animate-pulse rounded-sm align-middle" />
                              )}
                            </div>
                          </div>
                        </div>
                      ))}
                      {previewLoading && (
                        <div className="flex gap-2 items-end">
                          <div className="w-6 h-6 rounded-full flex-shrink-0" style={{ background: '#7c3aed' }} />
                          <div className="bg-white dark:bg-gray-800 rounded-2xl rounded-bl-sm px-4 py-3 shadow-sm">
                            <div className="flex gap-1">
                              {[0, 1, 2].map((i) => (
                                <div key={i} className="w-1.5 h-1.5 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: `${i * 0.15}s` }} />
                              ))}
                            </div>
                          </div>
                        </div>
                      )}
                      <div ref={previewEndRef} />
                    </div>
                    {/* Input */}
                    <div className="flex items-center gap-2 px-3 py-2.5 border-t border-gray-100 dark:border-gray-700 bg-white dark:bg-gray-800 flex-shrink-0">
                      <input
                        value={previewInput}
                        onChange={(e) => setPreviewInput(e.target.value)}
                        onKeyDown={(e) => e.key === 'Enter' && !e.shiftKey && handlePreviewSend()}
                        placeholder="Type a message…"
                        className="flex-1 rounded-full border border-gray-200 dark:border-gray-600 px-3 py-1.5 text-xs bg-transparent text-gray-700 dark:text-gray-200 focus:outline-none focus:ring-1 focus:ring-violet-500"
                      />
                      <button
                        onClick={handlePreviewSend}
                        disabled={!previewInput.trim() || previewLoading}
                        className="w-7 h-7 rounded-full flex items-center justify-center flex-shrink-0 text-white disabled:opacity-50 transition-opacity"
                        style={{ background: '#7c3aed' }}
                      >
                        <Send size={12} />
                      </button>
                    </div>
                  </div>
                ) : (
                  <button
                    onClick={() => setPreviewOpen(true)}
                    className="absolute bottom-4 right-4 w-12 h-12 rounded-full flex items-center justify-center shadow-lg hover:scale-105 transition-transform"
                    style={{ background: '#7c3aed' }}
                  >
                    <MessageSquare size={20} className="text-white" />
                  </button>
                )}

                {/* Bubble (always visible when panel is open) */}
                {previewOpen && (
                  <div className="absolute bottom-4 right-4 w-12 h-12 rounded-full flex items-center justify-center shadow-lg" style={{ background: '#7c3aed' }}>
                    <MessageSquare size={20} className="text-white" />
                  </div>
                )}
              </div>
            </div>
          </div>
        )}

        {activeTab === 'sdk' && (
          <div className="space-y-4">
            <div className="flex items-start gap-3 p-3 rounded-lg bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800">
              <Package size={15} className="text-amber-600 dark:text-amber-400 shrink-0 mt-0.5" />
              <p className="text-xs text-amber-700 dark:text-amber-300">
                <strong>npm package coming soon.</strong> Copy the vanilla JS snippet below into your project — it works in any browser or Node.js environment today.
              </p>
            </div>
            <div>
              <p className="text-xs text-gray-500 mb-2">Vanilla JavaScript (copy into your project)</p>
              <div className="relative">
                <pre className="bg-gray-950 text-gray-100 rounded-lg p-4 text-xs overflow-x-auto leading-relaxed">{sdkUsage}</pre>
                <CopyBtn text={sdkUsage} id="sdk" />
              </div>
            </div>
          </div>
        )}

        {activeTab === 'api' && (
          <div className="space-y-4">
            <p className="text-sm text-gray-600 dark:text-gray-400">
              Use the REST API directly from any language or platform.
            </p>
            <div className="relative">
              <pre className="bg-gray-950 text-gray-100 rounded-lg p-4 text-xs overflow-x-auto leading-relaxed">{curlExample}</pre>
              <CopyBtn text={curlExample} id="curl" />
            </div>
            <p className="text-xs text-gray-500">
              Full API docs at{' '}
              <a href={`${API_URL}/docs`} target="_blank" rel="noopener noreferrer" className="text-violet-600 hover:underline">
                {API_URL}/docs
              </a>
            </p>
          </div>
        )}
      </div>

      {showFeedbackModal && feedbackMessageIndex !== null && previewMessages[feedbackMessageIndex] && (
        <EmbedFeedbackModal
          message={previewMessages[feedbackMessageIndex]}
          focusCorrection={feedbackMode === 'correct'}
          onClose={closeFeedbackModal}
          onSubmit={handleFeedbackSubmit}
        />
      )}
    </div>
  )
}

function EmbedFeedbackModal({
  message,
  focusCorrection = false,
  onClose,
  onSubmit,
}: {
  message: PreviewMessage
  focusCorrection?: boolean
  onClose: () => void
  onSubmit: (rating?: 'positive' | 'negative', idealResponse?: string, comment?: string) => void
}) {
  const [rating, setRating] = useState<'positive' | 'negative' | null>(message.feedback?.rating ?? null)
  const [idealResponse, setIdealResponse] = useState(message.feedback?.ideal_response ?? '')
  const [comment, setComment] = useState(message.feedback?.comment ?? '')
  const correctionRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    if (focusCorrection && correctionRef.current) {
      correctionRef.current.scrollIntoView({ behavior: 'smooth', block: 'center' })
      correctionRef.current.focus()
    }
  }, [focusCorrection])

  const handleSubmit = () => {
    if (!rating && !idealResponse) return
    onSubmit(rating || undefined, idealResponse || undefined, comment || undefined)
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm p-4">
      <div className="bg-white dark:bg-gray-900 rounded-2xl shadow-xl w-full max-w-lg max-h-[90vh] overflow-y-auto p-6 relative">
        <button onClick={onClose} className="absolute top-4 right-4 text-gray-400 hover:text-gray-600 dark:hover:text-gray-200">
          <X size={18} />
        </button>
        <h3 className="text-base font-semibold text-gray-900 dark:text-white mb-4">
          Review this response
        </h3>

        <p className="text-sm text-gray-600 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 rounded-lg p-3 mb-5 line-clamp-3">
          {message.content}
        </p>

        <div className="flex gap-3 mb-5">
          <button
            onClick={() => setRating('positive')}
            className={`flex-1 flex items-center justify-center gap-2 py-2.5 rounded-xl border-2 text-sm font-medium transition-all ${
              rating === 'positive'
                ? 'border-green-500 bg-green-50 text-green-700 dark:bg-green-900/30 dark:text-green-300'
                : 'border-gray-200 dark:border-gray-700 text-gray-600 dark:text-gray-400 hover:border-green-400'
            }`}
          >
            <ThumbsUp size={16} />
            Positive
          </button>
          <button
            onClick={() => setRating('negative')}
            className={`flex-1 flex items-center justify-center gap-2 py-2.5 rounded-xl border-2 text-sm font-medium transition-all ${
              rating === 'negative'
                ? 'border-red-500 bg-red-50 text-red-700 dark:bg-red-900/30 dark:text-red-300'
                : 'border-gray-200 dark:border-gray-700 text-gray-600 dark:text-gray-400 hover:border-red-400'
            }`}
          >
            <ThumbsDown size={16} />
            Negative
          </button>
        </div>

        <div className="mb-4">
          <label className="text-xs font-medium text-gray-500 uppercase tracking-wider block mb-1.5">
            What should it have said?
            <span className="normal-case text-gray-400 ml-1">(trains the bot)</span>
          </label>
          <textarea
            ref={correctionRef}
            value={idealResponse}
            onChange={(e) => setIdealResponse(e.target.value)}
            placeholder="Write the ideal response here…"
            rows={4}
            className="w-full text-sm rounded-xl border border-violet-200 dark:border-violet-800 bg-violet-50/40 dark:bg-violet-900/10 px-3 py-2 text-gray-900 dark:text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-violet-400 resize-none"
          />
        </div>

        <textarea
          value={comment}
          onChange={(e) => setComment(e.target.value)}
          placeholder="Any other notes…"
          rows={2}
          className="w-full text-sm rounded-xl border border-gray-200 dark:border-gray-700 bg-transparent px-3 py-2 text-gray-900 dark:text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-violet-400 mb-4 resize-none"
        />

        <button
          disabled={!rating && !idealResponse}
          onClick={handleSubmit}
          className="w-full py-2.5 rounded-xl bg-violet-600 hover:bg-violet-700 disabled:opacity-40 text-white text-sm font-medium transition-colors"
        >
          {idealResponse ? 'Save Correction' : 'Save & Learn'}
        </button>
      </div>
    </div>
  )
}
