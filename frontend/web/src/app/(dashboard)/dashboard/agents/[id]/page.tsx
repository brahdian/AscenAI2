'use client'

import { useState, useEffect, useRef } from 'react'
import { useParams, useRouter } from 'next/navigation'
import Link from 'next/link'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { agentsApi, chatApi, voiceApi, feedbackApi } from '@/lib/api'
import toast from 'react-hot-toast'
import {
  ArrowLeft,
  Bot,
  BookOpen,
  FileText,
  Shield,
  Wrench,
  MessageSquare,
  Send,
  CheckCircle,
  XCircle,
  ChevronRight,
  ExternalLink,
  PhoneCall,
  Mic,
  Settings,
  Phone,
  MessageCircle,
  RefreshCw,
  Clock,
  ThumbsUp,
  ThumbsDown,
  PenLine,
  X,
} from 'lucide-react'

// Map known icons
const CATEGORY_ICONS: Record<string, any> = {
  general: Bot,
  retail: Bot,
  medical: Bot,
  beauty: Bot,
}

const LANGUAGES = [
  { code: 'en',    label: 'English (Global)' },
  { code: 'en-CA', label: 'English (Canada)' },
  { code: 'fr',    label: 'French (France)' },
  { code: 'fr-CA', label: 'French (Canada / Québec)' },
  { code: 'es',    label: 'Spanish' },
  { code: 'es-MX', label: 'Spanish (Mexico)' },
  { code: 'de',    label: 'German' },
  { code: 'it',    label: 'Italian' },
  { code: 'pt',    label: 'Portuguese' },
  { code: 'pt-BR', label: 'Portuguese (Brazil)' },
  { code: 'nl',    label: 'Dutch' },
  { code: 'pl',    label: 'Polish' },
  { code: 'ru',    label: 'Russian' },
  { code: 'zh',    label: 'Chinese (Mandarin)' },
  { code: 'ja',    label: 'Japanese' },
  { code: 'ko',    label: 'Korean' },
  { code: 'hi',    label: 'Hindi' },
  { code: 'pa',    label: 'Punjabi' },
  { code: 'ar',    label: 'Arabic' },
  { code: 'tr',    label: 'Turkish' },
  { code: 'uk',    label: 'Ukrainian' },
  { code: 'vi',    label: 'Vietnamese' },
  { code: 'id',    label: 'Indonesian' },
  { code: 'tl',    label: 'Tagalog / Filipino' },
]

type TabId = 'overview' | 'test'

const TABS: { id: TabId; label: string; icon: React.ElementType }[] = [
  { id: 'overview', label: 'Overview', icon: Bot },
  { id: 'test', label: 'Test', icon: MessageSquare },
]

interface ChatMessage {
  role: 'user' | 'assistant' | 'system'
  content: string
  feedback?: {
    rating?: 'positive' | 'negative'
    labels?: string[]
    ideal_response?: string
    comment?: string
  }
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
  
  // Template instance state
  const [variables, setVariables] = useState<Record<string, any>>({})
  const [savingInstance, setSavingInstance] = useState(false)

  // Test chat state
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [chatInput, setChatInput] = useState('')
  const [chatLoading, setChatLoading] = useState(false)
  const [streaming, setStreaming] = useState(false)
  const [selectedChannel, setSelectedChannel] = useState<'voice' | 'chat' | null>(null)
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [sessionStatus, setSessionStatus] = useState<'active' | 'closed' | 'ended'>('active')
  const [minutesUntilExpiry, setMinutesUntilExpiry] = useState<number | null>(null)
  const [showExpiryWarning, setShowExpiryWarning] = useState(false)
  const chatEndRef = useRef<HTMLDivElement>(null)
  const ttsCancelRef = useRef<(() => void) | null>(null)

  // Feedback state
  const [showFeedbackModal, setShowFeedbackModal] = useState(false)
  const [feedbackMessageIndex, setFeedbackMessageIndex] = useState<number | null>(null)
  const [feedbackMode, setFeedbackMode] = useState<'rate' | 'correct'>('rate')

  const { data: agent, isLoading, isError, error, refetch } = useQuery({
    queryKey: ['agent', id],
    queryFn: () => agentsApi.get(id),
    enabled: !!id,
    retry: 1,
  })

  const getBrowserLanguage = (): string => {
    const lang = navigator.language || 'en'
    if (lang.startsWith('fr')) return 'French'
    if (lang.startsWith('es')) return 'Spanish'
    if (lang.startsWith('de')) return 'German'
    if (lang.startsWith('it')) return 'Italian'
    if (lang.startsWith('pt')) return 'Portuguese'
    if (lang.startsWith('zh')) return 'Chinese'
    if (lang.startsWith('ja')) return 'Japanese'
    if (lang.startsWith('ko')) return 'Korean'
    if (lang.startsWith('hi')) return 'Hindi'
    return 'English'
  }

  const handleChannelSelect = (channel: 'voice' | 'chat') => {
    if (!agent) return
    // Cancel any in-flight TTS
    if (ttsCancelRef.current) {
      ttsCancelRef.current()
      ttsCancelRef.current = null
    }
    setSelectedChannel(channel)
    setSessionId(null)
    setSessionStatus('active')
    setMinutesUntilExpiry(null)
    setShowExpiryWarning(false)
    const greeting = agent.greeting_message || "Hi! How can I help you today?"
    const langMsg = channel === 'voice'
      ? "I'll be responding in English. Let me know if you'd prefer French or another language."
      : null
    
    const messages: ChatMessage[] = [{ role: 'assistant', content: greeting }]
    if (langMsg) {
      messages.push({ role: 'assistant', content: langMsg })
    }
    setMessages(messages)
  }

  const handleNewSession = () => {
    // Cancel any in-flight TTS
    if (ttsCancelRef.current) {
      ttsCancelRef.current()
      ttsCancelRef.current = null
    }
    setSessionId(null)
    setSessionStatus('active')
    setMinutesUntilExpiry(null)
    setShowExpiryWarning(false)
    if (selectedChannel && agent) {
      const greeting = agent.greeting_message || "Hi! How can I help you today?"
      const msgs: ChatMessage[] = [{ role: 'assistant', content: greeting }]
      if (selectedChannel === 'voice') {
        msgs.push({ role: 'assistant', content: "I'll be responding in English. Let me know if you'd prefer French or another language." })
      }
      setMessages(msgs)
    } else {
      setMessages([])
    }
  }

  const handleChannelSwitch = (newChannel: 'voice' | 'chat') => {
    if (newChannel === selectedChannel || !selectedChannel) return
    
    // Cancel any in-flight TTS
    if (ttsCancelRef.current) {
      ttsCancelRef.current()
      ttsCancelRef.current = null
    }

    const langMsg = newChannel === 'voice'
      ? "I'll be responding in English. Let me know if you'd prefer French or another language."
      : null
    
    const switchMsg = newChannel === 'voice'
      ? "Switched to Voice mode"
      : "Switched to Chat mode"
    
    setSelectedChannel(newChannel)
    setMessages((prev) => {
      const newMessages: ChatMessage[] = [...prev, { role: 'system', content: switchMsg }]
      if (langMsg) {
        newMessages.push({ role: 'assistant', content: langMsg })
      }
      return newMessages
    })
  }

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
    if (feedbackMessageIndex === null) return
    const msg = messages[feedbackMessageIndex]
    if (!msg || msg.role !== 'assistant') return

    const messageId = `test-${id}-${feedbackMessageIndex}-${Date.now()}`
    const sessionIdValue = sessionId || `test-session-${Date.now()}`

    try {
      await feedbackApi.submit({
        message_id: messageId,
        session_id: sessionIdValue,
        agent_id: id,
        rating,
        ideal_response: idealResponse,
        comment,
        feedback_source: 'operator',
      })
      setMessages(prev => prev.map((m, i) =>
        i === feedbackMessageIndex
          ? { ...m, feedback: { rating: rating || undefined, ideal_response: idealResponse, comment } }
          : m
      ))
      toast.success('Feedback saved')
      closeFeedbackModal()
    } catch {
      toast.error('Failed to save feedback')
    }
  }

  // Template Data
  const { data: templates = [] } = useQuery({
    queryKey: ['templates'],
    queryFn: () => {
      // @ts-ignore
      return import('@/lib/api').then(m => m.templatesApi.list().catch(() => []))
    },
  })

  const { data: instance, refetch: refetchInstance } = useQuery({
    queryKey: ['agent-instance', id],
    queryFn: () => {
      // @ts-ignore
      return import('@/lib/api').then(m => m.templatesApi.getInstanceByAgent(id).catch(() => null))
    },
    enabled: !!id,
    retry: 0,
  })

  const selectedTemplate = templates?.find((t: any) => 
    t.versions?.some((v: any) => v.id === instance?.template_version_id)
  )

  useEffect(() => {
    if (instance?.variable_values) {
      setVariables(instance.variable_values)
    }
  }, [instance])

  useEffect(() => {
    if (agent) {
      const voiceConfig = agent.voice_config || {}
      setFormData({
        name: agent.name || '',
        description: agent.description || '',
        business_type: agent.business_type || 'generic',
        language: agent.language || 'en',
        personality: agent.personality || '',
        system_prompt: agent.system_prompt || '',
        greeting_message: agent.greeting_message || '',
        voice_enabled: agent.voice_enabled ?? true,
        voice_config: {
          twilio_phone_number: voiceConfig.twilio_phone_number || '',
          twilio_account_sid: voiceConfig.twilio_account_sid || '',
          twilio_auth_token: voiceConfig.twilio_auth_token || '',
        },
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

  const handleSaveInstance = async () => {
    if (!instance) return
    setSavingInstance(true)
    try {
      // @ts-ignore
      const { templatesApi } = await import('@/lib/api')
      await templatesApi.updateInstance(instance.id, { variable_values: variables })
      qc.invalidateQueries({ queryKey: ['agent-instance', id] })
      qc.invalidateQueries({ queryKey: ['agent', id] }) // refetch agent to get updated prompt
      toast.success('Template variables updated!')
    } catch {
      toast.error('Failed to update variables')
    } finally {
      setSavingInstance(false)
    }
  }
  
  const handleVariableChange = (key: string, value: any) => {
    setVariables(prev => ({ ...prev, [key]: value }))
  }

  const handleSendMessage = async () => {
    if (!chatInput.trim() || chatLoading || sessionStatus === 'closed') return
    const userMsg = chatInput.trim()
    setChatInput('')
    setMessages((prev) => [...prev, { role: 'user', content: userMsg }])
    setChatLoading(true)
    setStreaming(false)

    // Cancel any in-flight TTS playback
    if (ttsCancelRef.current) {
      ttsCancelRef.current()
      ttsCancelRef.current = null
    }

    let assistantText = ''
    let streamed = false
    let firstChunk = true
    try {
      await chatApi.stream(
        {
          agent_id: id,
          message: userMsg,
          session_id: sessionId || undefined,
          channel: selectedChannel || 'chat',
        },
        (chunk, meta) => {
          streamed = true
          setChatLoading(false)
          setStreaming(true)
          assistantText += chunk
          if (meta?.session_status) {
            setSessionStatus(meta.session_status)
          }
          if (meta?.minutes_until_expiry != null) {
            setMinutesUntilExpiry(meta.minutes_until_expiry)
            setShowExpiryWarning(meta.expiry_warning ?? false)
          }
          if (meta?.session_status === 'closed') {
            setMessages((prev) => [
              ...prev,
              { role: 'assistant', content: chunk || 'Your session has expired due to inactivity. Please start a new session to continue.' },
            ])
            firstChunk = false
            return
          }
          setMessages((prev) => {
            const last = prev[prev.length - 1]
            if (last && last.role === 'assistant' && !firstChunk) {
              return [...prev.slice(0, -1), { ...last, content: last.content + chunk }]
            } else {
              firstChunk = false
              return [...prev, { role: 'assistant', content: chunk }]
            }
          })
        },
        (newSessionId) => {
          setSessionId(newSessionId)
        }
      )
    } catch {
      // Streaming failed — fall back to non-streaming endpoint with simulated streaming
      try {
        const data = await chatApi.send({
          agent_id: id,
          message: userMsg,
          session_id: sessionId || undefined,
          channel: selectedChannel || 'chat',
        })
        if (data.session_id) setSessionId(data.session_id)
        if (data.session_status) setSessionStatus(data.session_status)
        if (data.minutes_until_expiry != null) {
          setMinutesUntilExpiry(data.minutes_until_expiry)
          setShowExpiryWarning(data.expiry_warning ?? false)
        }
        if (data.session_status === 'closed') {
          setChatLoading(false)
          setMessages((prev) => [
            ...prev,
            { role: 'assistant', content: 'Your session has expired due to inactivity. Please start a new session to continue.' },
          ])
          return
        }
        setChatLoading(false)
        setStreaming(true)
        const fullText = data.message || data.response || 'No response received.'
        assistantText = fullText
        let displayed = ''
        for (let i = 0; i < fullText.length; i++) {
          displayed += fullText[i]
          const current = displayed
          setMessages((prev) => {
            const last = prev[prev.length - 1]
            if (last && last.role === 'assistant' && i > 0) {
              return [...prev.slice(0, -1), { ...last, content: current }]
            }
            return [...prev, { role: 'assistant', content: current }]
          })
          await new Promise((r) => setTimeout(r, 10))
        }
      } catch {
        setMessages((prev) => [
          ...prev,
          { role: 'assistant', content: 'Error: Failed to get response from agent.' },
        ])
      }
    } finally {
      setStreaming(false)
      setChatLoading(false)
    }

    // Voice mode: play TTS audio as it arrives
    if (selectedChannel === 'voice' && assistantText) {
      try {
        const stream = await voiceApi.streamTts(assistantText)
        if (stream) {
          ttsCancelRef.current = await voiceApi.playStreamedAudio(stream)
        }
      } catch {
        // TTS failed silently — text response is still shown
      }
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

  if (isError) {
    const status = (error as any)?.response?.status
    return (
      <div className="p-8 text-center">
        <p className="text-gray-700 dark:text-gray-300 font-medium mb-1">
          {status === 404 ? 'Agent not found.' : 'Could not load agent.'}
        </p>
        <p className="text-sm text-gray-400 mb-4">
          {status === 404
            ? 'This agent may have been deleted or you may not have access to it.'
            : 'There was a problem connecting to the server. Check that the backend services are running.'}
        </p>
        <div className="flex items-center justify-center gap-3">
          <button
            onClick={() => refetch()}
            className="px-4 py-2 rounded-lg bg-violet-600 text-white text-sm hover:bg-violet-700 transition-colors"
          >
            Retry
          </button>
          <Link href="/dashboard/agents" className="px-4 py-2 rounded-lg border border-gray-200 dark:border-gray-700 text-sm text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors">
            Back to Agents
          </Link>
        </div>
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
    <div className="p-8 w-full">

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
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
        {[
          { href: `/dashboard/agents/${id}/playbooks`, icon: BookOpen, label: 'Playbooks', desc: 'Conversation playbooks' },
          { href: `/dashboard/agents/${id}/tools`, icon: Wrench, label: 'Tools', desc: 'Integrations & actions' },
          { href: `/dashboard/agents/${id}/variables`, icon: Settings, label: 'Variables', desc: 'Dynamic agent variables' },
          { href: `/dashboard/agents/${id}/documents`, icon: FileText, label: 'Documents', desc: 'RAG knowledge base files' },
          { href: `/dashboard/agents/${id}/guardrails`, icon: Shield, label: 'Guardrails', desc: 'Content filters & safety' },
          { href: `/dashboard/agents/${id}/escalation`, icon: PhoneCall, label: 'Escalation', desc: 'Human handoff & connectors' },
          { href: `/dashboard/agents/${id}/greeting`, icon: Mic, label: 'Greeting', desc: 'Voice greeting & language' },
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
                {LANGUAGES.map((l) => (
                  <option key={l.code} value={l.code}>{l.label}</option>
                ))}
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

          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1.5">
              Greeting message
              <span className="ml-2 text-xs font-normal text-gray-400">(shown at start of every conversation)</span>
            </label>
            <textarea
              value={(formData.greeting_message as string) || ''}
              onChange={(e) => setFormData((p) => ({ ...p, greeting_message: e.target.value }))}
              rows={2}
              maxLength={1000}
              placeholder={`Hi! I'm ${agent.name}. How can I help you today?`}
              className="w-full px-3 py-2.5 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm focus:outline-none focus:ring-1 focus:ring-violet-500 resize-none"
            />
            <p className="text-xs text-gray-400 mt-1">
              For voice recording, go to{' '}
              <Link href={`/dashboard/agents/${id}/greeting`} className="text-violet-600 hover:underline">
                Greeting &amp; Language
              </Link>
              .
            </p>
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

          {!!formData.voice_enabled && (
            <div className="space-y-4 p-4 rounded-lg bg-gray-50 dark:bg-gray-800/50 border border-gray-200 dark:border-gray-700">
              <div>
                <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Voice Configuration</h3>
                <p className="text-xs text-gray-400 mb-3">Configure your Twilio phone number for inbound voice calls. Callers dialing this number will reach this agent.</p>
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1.5">
                  Twilio Phone Number
                </label>
                <input
                  value={((formData.voice_config as any)?.twilio_phone_number) || ''}
                  onChange={(e) => setFormData((p) => ({ ...p, voice_config: { ...(p.voice_config as any || {}), twilio_phone_number: e.target.value } }))}
                  placeholder="+18001234567"
                  className="w-full px-3 py-2.5 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm focus:outline-none focus:ring-1 focus:ring-violet-500"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1.5">
                  Twilio Account SID
                </label>
                <input
                  type="password"
                  value={((formData.voice_config as any)?.twilio_account_sid) || ''}
                  onChange={(e) => setFormData((p) => ({ ...p, voice_config: { ...(p.voice_config as any || {}), twilio_account_sid: e.target.value } }))}
                  placeholder="ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
                  className="w-full px-3 py-2.5 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm focus:outline-none focus:ring-1 focus:ring-violet-500"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1.5">
                  Twilio Auth Token
                </label>
                <input
                  type="password"
                  value={((formData.voice_config as any)?.twilio_auth_token) || ''}
                  onChange={(e) => setFormData((p) => ({ ...p, voice_config: { ...(p.voice_config as any || {}), twilio_auth_token: e.target.value } }))}
                  placeholder="Your Twilio Auth Token"
                  className="w-full px-3 py-2.5 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm focus:outline-none focus:ring-1 focus:ring-violet-500"
                />
              </div>
            </div>
          )}

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
          <div className="px-5 py-4 border-b border-gray-200 dark:border-gray-800 flex items-center justify-between">
            <div>
              <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-300">
                Test &quot;{agent.name}&quot;
              </h2>
              <div className="flex items-center gap-3 mt-0.5">
                <p className="text-xs text-gray-500">Select a channel to start testing</p>
                {selectedChannel && sessionStatus && (
                  <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium ${
                    sessionStatus === 'active'
                      ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-900/20 dark:text-emerald-400'
                      : 'bg-red-50 text-red-700 dark:bg-red-900/20 dark:text-red-400'
                  }`}>
                    {sessionStatus === 'active' ? <CheckCircle size={10} /> : <XCircle size={10} />}
                    {sessionStatus === 'active' ? 'Active' : sessionStatus === 'closed' ? 'Expired' : 'Ended'}
                  </span>
                )}
                {minutesUntilExpiry != null && sessionStatus === 'active' && (
                  <span className="inline-flex items-center gap-1 text-xs text-gray-400">
                    <Clock size={10} />
                    {Math.round(minutesUntilExpiry)}m left
                  </span>
                )}
              </div>
            </div>
            <div className="flex items-center gap-2">
              {selectedChannel && (
                <button
                  onClick={handleNewSession}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium text-gray-500 hover:text-violet-700 dark:text-gray-400 dark:hover:text-violet-300 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
                  title="Start new session"
                >
                  <RefreshCw size={13} />
                  New Session
                </button>
              )}
              {selectedChannel && (
                <div className="flex items-center gap-2 bg-gray-100 dark:bg-gray-800 rounded-lg p-1">
                <button
                  onClick={() => handleChannelSwitch('chat')}
                  className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-all ${
                    selectedChannel === 'chat'
                      ? 'bg-white dark:bg-gray-700 text-violet-700 dark:text-violet-300 shadow-sm'
                      : 'text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200'
                  }`}
                >
                  <MessageCircle size={14} />
                  Chat
                </button>
                <button
                  onClick={() => handleChannelSwitch('voice')}
                  className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-all ${
                    selectedChannel === 'voice'
                      ? 'bg-white dark:bg-gray-700 text-violet-700 dark:text-violet-300 shadow-sm'
                      : 'text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200'
                  }`}
                >
                  <Phone size={14} />
                  Voice
                </button>
              </div>
            )}
            </div>
          </div>

          {/* Channel Selector */}
          {!selectedChannel && (
            <div className="flex-1 flex items-center justify-center p-8">
              <div className="text-center space-y-4">
                <p className="text-sm text-gray-500 dark:text-gray-400 mb-4">Choose a channel to test</p>
                <div className="flex gap-4 justify-center">
                  <button
                    onClick={() => handleChannelSelect('voice')}
                    className="flex flex-col items-center gap-2 p-6 rounded-xl border border-gray-200 dark:border-gray-700 hover:border-violet-500 hover:bg-violet-50 dark:hover:bg-violet-900/20 transition-all group"
                  >
                    <div className="w-12 h-12 rounded-full bg-violet-100 dark:bg-violet-900/30 flex items-center justify-center group-hover:scale-110 transition-transform">
                      <Phone size={24} className="text-violet-600 dark:text-violet-400" />
                    </div>
                    <span className="text-sm font-medium text-gray-700 dark:text-gray-300">Voice</span>
                  </button>
                  <button
                    onClick={() => handleChannelSelect('chat')}
                    className="flex flex-col items-center gap-2 p-6 rounded-xl border border-gray-200 dark:border-gray-700 hover:border-violet-500 hover:bg-violet-50 dark:hover:bg-violet-900/20 transition-all group"
                  >
                    <div className="w-12 h-12 rounded-full bg-violet-100 dark:bg-violet-900/30 flex items-center justify-center group-hover:scale-110 transition-transform">
                      <MessageCircle size={24} className="text-violet-600 dark:text-violet-400" />
                    </div>
                    <span className="text-sm font-medium text-gray-700 dark:text-gray-300">Chat</span>
                  </button>
                </div>
              </div>
            </div>
          )}

          {/* Expiry Warning Banner */}
          {showExpiryWarning && sessionStatus === 'active' && (
            <div className="mx-4 mt-3 px-4 py-2.5 rounded-lg bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 flex items-center gap-2">
              <Clock size={14} className="text-amber-600 dark:text-amber-400 flex-shrink-0" />
              <p className="text-xs text-amber-700 dark:text-amber-300">
                Session will expire in {minutesUntilExpiry != null ? Math.round(minutesUntilExpiry) : 'a few'} minutes due to inactivity.
                Send a message to keep it active or{' '}
                <button onClick={handleNewSession} className="underline font-medium hover:text-amber-900 dark:hover:text-amber-100">
                  start a new session
                </button>.
              </p>
            </div>
          )}

          {/* Session Expired Banner */}
          {sessionStatus === 'closed' && (
            <div className="mx-4 mt-3 px-4 py-2.5 rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 flex items-center gap-2">
              <XCircle size={14} className="text-red-600 dark:text-red-400 flex-shrink-0" />
              <p className="text-xs text-red-700 dark:text-red-300">
                Session expired.{' '}
                <button onClick={handleNewSession} className="underline font-medium hover:text-red-900 dark:hover:text-red-100">
                  Start a new session
                </button>
              </p>
            </div>
          )}

          {/* Messages */}
          {selectedChannel && (
            <div className="flex-1 overflow-y-auto p-5 space-y-4">
              {messages.map((msg, i) => (
                <div
                  key={i}
                  className={`flex ${msg.role === 'user' ? 'justify-end' : msg.role === 'system' ? 'justify-center' : 'justify-start'}`}
                >
                  <div className="max-w-[75%] flex flex-col gap-1">
                    <div
                      className={`px-4 py-2.5 rounded-2xl text-sm ${
                        msg.role === 'user'
                          ? 'bg-gradient-to-r from-violet-600 to-blue-600 text-white rounded-tr-sm'
                          : msg.role === 'system'
                          ? 'bg-amber-100 dark:bg-amber-900/30 text-amber-800 dark:text-amber-300 italic'
                          : 'bg-gray-100 dark:bg-gray-800 text-gray-900 dark:text-white rounded-tl-sm'
                      }`}
                    >
                      {msg.content}
                      {streaming && msg.role === 'assistant' && i === messages.length - 1 && (
                        <span className="inline-block w-1.5 h-4 ml-0.5 bg-violet-500 animate-pulse rounded-sm align-middle" />
                      )}
                    </div>
                    {/* Feedback buttons for assistant messages */}
                    {msg.role === 'assistant' && (
                      <div className="flex items-center gap-2 mt-1">
                        {msg.feedback ? (
                          <>
                            <button
                              onClick={() => openFeedbackModal(i, 'rate')}
                              className={`flex items-center gap-1 text-xs px-2 py-0.5 rounded-full transition-opacity hover:opacity-80 ${
                                msg.feedback.rating === 'positive'
                                  ? 'bg-green-100 text-green-600 dark:bg-green-900/30'
                                  : 'bg-red-100 text-red-600 dark:bg-red-900/30'
                              }`}
                            >
                              {msg.feedback.rating === 'positive' ? <ThumbsUp size={11} /> : <ThumbsDown size={11} />}
                              {msg.feedback.rating}
                            </button>
                            <button
                              onClick={() => openFeedbackModal(i, 'correct')}
                              className={`flex items-center gap-1 text-xs px-2 py-0.5 rounded-full transition-colors ${
                                msg.feedback.ideal_response
                                  ? 'bg-violet-100 text-violet-600 dark:bg-violet-900/30 dark:text-violet-300'
                                  : 'text-gray-400 hover:text-violet-500 hover:bg-violet-50 dark:hover:bg-violet-900/20'
                              }`}
                            >
                              <PenLine size={11} />
                              {msg.feedback.ideal_response ? 'Corrected' : 'Add correction'}
                            </button>
                          </>
                        ) : (
                          <>
                            <button
                              onClick={() => openFeedbackModal(i, 'rate')}
                              className="text-xs text-gray-400 hover:text-green-600 transition-colors flex items-center gap-1"
                              title="Rate this response"
                            >
                              <ThumbsUp size={11} />
                              Rate
                            </button>
                            <button
                              onClick={() => openFeedbackModal(i, 'correct')}
                              className="text-xs text-gray-400 hover:text-violet-500 transition-colors flex items-center gap-1"
                              title="Add a correction the bot will learn from"
                            >
                              <PenLine size={11} />
                              Correct
                            </button>
                          </>
                        )}
                      </div>
                    )}
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
          )}

          {/* Input */}
          {selectedChannel && (
            <div className="p-4 border-t border-gray-200 dark:border-gray-800">
              <div className="flex gap-2">
                <input
                  value={chatInput}
                  onChange={(e) => setChatInput(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && !e.shiftKey && handleSendMessage()}
                  placeholder={sessionStatus === 'closed' ? 'Session expired — start a new session to continue' : 'Type a message…'}
                  disabled={sessionStatus === 'closed'}
                  className="flex-1 px-3 py-2.5 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm focus:outline-none focus:ring-1 focus:ring-violet-500 disabled:opacity-50 disabled:cursor-not-allowed"
                />
                <button
                  onClick={handleSendMessage}
                  disabled={!chatInput.trim() || chatLoading || sessionStatus === 'closed'}
                  className="p-2.5 rounded-lg bg-violet-600 text-white hover:bg-violet-700 disabled:opacity-50 transition-colors"
                >
                  <Send size={16} />
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {showFeedbackModal && feedbackMessageIndex !== null && (
        <TestFeedbackModal
          message={messages[feedbackMessageIndex]}
          focusCorrection={feedbackMode === 'correct'}
          onClose={closeFeedbackModal}
          onSubmit={handleFeedbackSubmit}
        />
      )}
    </div>
  )
}

function TestFeedbackModal({
  message,
  focusCorrection = false,
  onClose,
  onSubmit,
}: {
  message: ChatMessage
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
            placeholder="Write the ideal response here — it will be used as a training example for future conversations…"
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
