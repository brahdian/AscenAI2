'use client'

import { useState, useEffect, useRef } from 'react'
import { useParams, useRouter } from 'next/navigation'
import Link from 'next/link'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { agentsApi } from '@/lib/api'
import toast from 'react-hot-toast'
import {
  ArrowLeft,
  Bot,
  BookOpen,
  FileText,
  Shield,
  MessageSquare,
  Send,
  CheckCircle,
  XCircle,
  ChevronRight,
  ExternalLink,
} from 'lucide-react'

type TabId = 'overview' | 'test'

const TABS: { id: TabId; label: string; icon: React.ElementType }[] = [
  { id: 'overview', label: 'Overview', icon: Bot },
  { id: 'test', label: 'Test', icon: MessageSquare },
]

interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
}

export default function AgentDetailPage() {
  const params = useParams()
  const router = useRouter()
  const qc = useQueryClient()
  const id = params.id as string

  const [activeTab, setActiveTab] = useState<TabId>('overview')

  // Overview form state
  const [formData, setFormData] = useState<Record<string, unknown>>({})
  const [saving, setSaving] = useState(false)

  // Test chat state
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [chatInput, setChatInput] = useState('')
  const [chatLoading, setChatLoading] = useState(false)
  const chatEndRef = useRef<HTMLDivElement>(null)

  const { data: agent, isLoading } = useQuery({
    queryKey: ['agent', id],
    queryFn: () => agentsApi.get(id),
    enabled: !!id,
  })

  useEffect(() => {
    if (agent) {
      setFormData({
        name: agent.name || '',
        description: agent.description || '',
        business_type: agent.business_type || 'generic',
        language: agent.language || 'en',
        personality: agent.personality || '',
        system_prompt: agent.system_prompt || '',
        voice_enabled: agent.voice_enabled ?? true,
      })
    }
  }, [agent])

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const deactivateMutation = useMutation({
    mutationFn: () =>
      agentsApi.update(id, { is_active: !agent?.is_active }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['agent', id] })
      toast.success(agent?.is_active ? 'Agent deactivated' : 'Agent activated')
    },
    onError: () => toast.error('Failed to update agent status'),
  })

  const handleSave = async () => {
    setSaving(true)
    try {
      await agentsApi.update(id, formData)
      qc.invalidateQueries({ queryKey: ['agent', id] })
      toast.success('Agent updated!')
    } catch {
      toast.error('Failed to save changes')
    } finally {
      setSaving(false)
    }
  }

  const handleSendMessage = async () => {
    if (!chatInput.trim() || chatLoading) return
    const userMsg = chatInput.trim()
    setChatInput('')
    setMessages((prev) => [...prev, { role: 'user', content: userMsg }])
    setChatLoading(true)
    try {
      const res = await agentsApi.test(id, userMsg)
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', content: res.message || res.response || JSON.stringify(res) },
      ])
    } catch {
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', content: 'Error: Failed to get response from agent.' },
      ])
    } finally {
      setChatLoading(false)
    }
  }

  if (isLoading) {
    return (
      <div className="p-8 animate-pulse space-y-4">
        <div className="h-6 bg-gray-200 dark:bg-gray-800 rounded w-48" />
        <div className="h-32 bg-gray-200 dark:bg-gray-800 rounded-xl" />
      </div>
    )
  }

  if (!agent) {
    return (
      <div className="p-8 text-center text-gray-500">
        <p>Agent not found.</p>
        <Link href="/dashboard/agents" className="text-violet-600 hover:underline mt-2 inline-block">
          Back to Agents
        </Link>
      </div>
    )
  }

  return (
    <div className="p-8 max-w-4xl">
      {/* Breadcrumbs */}
      <div className="flex items-center gap-2 text-sm text-gray-500 dark:text-gray-400 mb-6">
        <Link href="/dashboard" className="hover:text-gray-900 dark:hover:text-white transition-colors">
          Dashboard
        </Link>
        <ChevronRight size={14} />
        <Link href="/dashboard/agents" className="hover:text-gray-900 dark:hover:text-white transition-colors">
          Agents
        </Link>
        <ChevronRight size={14} />
        <span className="text-gray-900 dark:text-white font-medium truncate max-w-[200px]">
          {agent.name}
        </span>
      </div>

      {/* Header */}
      <div className="flex items-start justify-between mb-6">
        <div className="flex items-center gap-4">
          <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-violet-500 to-blue-500 flex items-center justify-center">
            <Bot size={22} className="text-white" />
          </div>
          <div>
            <h1 className="text-2xl font-bold text-gray-900 dark:text-white">{agent.name}</h1>
            <p className="text-xs font-mono text-gray-400 mt-0.5">ID: {agent.id}</p>
          </div>
          <span
            className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium ${
              agent.is_active
                ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-900/20 dark:text-emerald-400'
                : 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400'
            }`}
          >
            {agent.is_active ? <CheckCircle size={12} /> : <XCircle size={12} />}
            {agent.is_active ? 'Active' : 'Inactive'}
          </span>
        </div>
        <button
          onClick={() => deactivateMutation.mutate()}
          disabled={deactivateMutation.isPending}
          className="px-4 py-2 rounded-lg border border-gray-200 dark:border-gray-700 text-sm text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors disabled:opacity-50"
        >
          {agent.is_active ? 'Deactivate' : 'Activate'}
        </button>
      </div>

      {/* Quick nav to sub-pages */}
      <div className="grid grid-cols-3 gap-3 mb-6">
        {[
          { href: `/dashboard/agents/${id}/playbooks`, icon: BookOpen, label: 'Playbooks', desc: 'Manage conversation playbooks' },
          { href: `/dashboard/agents/${id}/documents`, icon: FileText, label: 'Documents', desc: 'Upload RAG knowledge base files' },
          { href: `/dashboard/agents/${id}/guardrails`, icon: Shield, label: 'Guardrails', desc: 'Content filters & safety rules' },
        ].map((item) => (
          <Link
            key={item.href}
            href={item.href}
            className="flex items-center gap-3 p-4 bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 hover:border-violet-300 dark:hover:border-violet-700 hover:bg-violet-50/30 dark:hover:bg-violet-900/10 transition-colors group"
          >
            <div className="w-9 h-9 rounded-lg bg-violet-50 dark:bg-violet-900/20 flex items-center justify-center flex-shrink-0">
              <item.icon size={16} className="text-violet-600 dark:text-violet-400" />
            </div>
            <div className="min-w-0">
              <p className="text-sm font-medium text-gray-900 dark:text-white group-hover:text-violet-700 dark:group-hover:text-violet-300 transition-colors">
                {item.label}
              </p>
              <p className="text-xs text-gray-500 truncate">{item.desc}</p>
            </div>
            <ExternalLink size={14} className="text-gray-400 ml-auto flex-shrink-0" />
          </Link>
        ))}
      </div>

      {/* Tabs */}
      <div className="flex gap-1 border-b border-gray-200 dark:border-gray-800 mb-6">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors -mb-px ${
              activeTab === tab.id
                ? 'border-violet-600 text-violet-700 dark:text-violet-400'
                : 'border-transparent text-gray-500 hover:text-gray-900 dark:hover:text-white'
            }`}
          >
            <tab.icon size={15} />
            {tab.label}
          </button>
        ))}
      </div>

      {/* Tab Content */}
      {activeTab === 'overview' && (
        <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 p-6 space-y-5">
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1.5">
              Agent name *
            </label>
            <input
              value={(formData.name as string) || ''}
              onChange={(e) => setFormData((p) => ({ ...p, name: e.target.value }))}
              className="w-full px-3 py-2.5 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm focus:outline-none focus:ring-1 focus:ring-violet-500"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1.5">
              Description
            </label>
            <input
              value={(formData.description as string) || ''}
              onChange={(e) => setFormData((p) => ({ ...p, description: e.target.value }))}
              placeholder="Optional description"
              className="w-full px-3 py-2.5 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm focus:outline-none focus:ring-1 focus:ring-violet-500"
            />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1.5">
                Business type
              </label>
              <select
                value={(formData.business_type as string) || 'generic'}
                onChange={(e) => setFormData((p) => ({ ...p, business_type: e.target.value }))}
                className="w-full px-3 py-2.5 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm focus:outline-none focus:ring-1 focus:ring-violet-500"
              >
                <option value="generic">Generic</option>
                <option value="pizza_shop">Pizza / Restaurant</option>
                <option value="clinic">Medical Clinic</option>
                <option value="salon">Salon / Spa</option>
              </select>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1.5">
                Language
              </label>
              <select
                value={(formData.language as string) || 'en'}
                onChange={(e) => setFormData((p) => ({ ...p, language: e.target.value }))}
                className="w-full px-3 py-2.5 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm focus:outline-none focus:ring-1 focus:ring-violet-500"
              >
                <option value="en">English</option>
                <option value="es">Spanish</option>
                <option value="fr">French</option>
                <option value="de">German</option>
                <option value="pt">Portuguese</option>
              </select>
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1.5">
              Personality
            </label>
            <input
              value={(formData.personality as string) || ''}
              onChange={(e) => setFormData((p) => ({ ...p, personality: e.target.value }))}
              placeholder="e.g. Friendly, professional, concise..."
              className="w-full px-3 py-2.5 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm focus:outline-none focus:ring-1 focus:ring-violet-500"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1.5">
              System prompt
            </label>
            <textarea
              value={(formData.system_prompt as string) || ''}
              onChange={(e) => setFormData((p) => ({ ...p, system_prompt: e.target.value }))}
              rows={5}
              placeholder="You are a helpful assistant for {business_name}..."
              className="w-full px-3 py-2.5 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm focus:outline-none focus:ring-1 focus:ring-violet-500 resize-none"
            />
          </div>

          <div className="flex items-center gap-3">
            <input
              type="checkbox"
              id="voice_enabled"
              checked={!!(formData.voice_enabled)}
              onChange={(e) => setFormData((p) => ({ ...p, voice_enabled: e.target.checked }))}
              className="w-4 h-4 accent-violet-600"
            />
            <label htmlFor="voice_enabled" className="text-sm text-gray-700 dark:text-gray-300">
              Enable voice (STT/TTS)
            </label>
          </div>

          <div className="pt-2">
            <button
              onClick={handleSave}
              disabled={saving}
              className="px-5 py-2.5 rounded-lg bg-gradient-to-r from-violet-600 to-blue-600 text-white text-sm font-medium hover:opacity-90 disabled:opacity-50 transition-opacity"
            >
              {saving ? 'Saving…' : 'Save changes'}
            </button>
          </div>
        </div>
      )}

      {activeTab === 'test' && (
        <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 flex flex-col" style={{ height: '500px' }}>
          <div className="px-5 py-4 border-b border-gray-200 dark:border-gray-800">
            <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-300">
              Test &quot;{agent.name}&quot;
            </h2>
            <p className="text-xs text-gray-500 mt-0.5">Send a message to test your agent&apos;s responses</p>
          </div>

          {/* Messages */}
          <div className="flex-1 overflow-y-auto p-5 space-y-4">
            {messages.length === 0 && (
              <div className="text-center text-gray-400 text-sm pt-8">
                <MessageSquare size={32} className="mx-auto mb-2 opacity-50" />
                <p>Send a message to start testing</p>
              </div>
            )}
            {messages.map((msg, i) => (
              <div
                key={i}
                className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
              >
                <div
                  className={`max-w-[75%] px-4 py-2.5 rounded-2xl text-sm ${
                    msg.role === 'user'
                      ? 'bg-gradient-to-r from-violet-600 to-blue-600 text-white rounded-tr-sm'
                      : 'bg-gray-100 dark:bg-gray-800 text-gray-900 dark:text-white rounded-tl-sm'
                  }`}
                >
                  {msg.content}
                </div>
              </div>
            ))}
            {chatLoading && (
              <div className="flex justify-start">
                <div className="bg-gray-100 dark:bg-gray-800 px-4 py-3 rounded-2xl rounded-tl-sm">
                  <div className="flex gap-1">
                    {[0, 1, 2].map((i) => (
                      <div
                        key={i}
                        className="w-2 h-2 bg-gray-400 rounded-full animate-bounce"
                        style={{ animationDelay: `${i * 0.15}s` }}
                      />
                    ))}
                  </div>
                </div>
              </div>
            )}
            <div ref={chatEndRef} />
          </div>

          {/* Input */}
          <div className="p-4 border-t border-gray-200 dark:border-gray-800">
            <div className="flex gap-2">
              <input
                value={chatInput}
                onChange={(e) => setChatInput(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && !e.shiftKey && handleSendMessage()}
                placeholder="Type a message…"
                className="flex-1 px-3 py-2.5 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm focus:outline-none focus:ring-1 focus:ring-violet-500"
              />
              <button
                onClick={handleSendMessage}
                disabled={!chatInput.trim() || chatLoading}
                className="p-2.5 rounded-lg bg-violet-600 text-white hover:bg-violet-700 disabled:opacity-50 transition-colors"
              >
                <Send size={16} />
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
