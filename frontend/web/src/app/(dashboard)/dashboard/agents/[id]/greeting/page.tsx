'use client'

import { useState, useEffect, useRef, useCallback } from 'react'
import { useParams } from 'next/navigation'
import Link from 'next/link'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { agentsApi, platformApi, variablesApi, toolsApi, documentsApi } from '@/lib/api'
import toast from 'react-hot-toast'
import {
  ArrowLeft,
  Volume2,
  Globe,
  Info,
  CheckCircle2,
  Loader2,
  PhoneCall,
  Save,
  Mic,
  AlertTriangle,
  Zap,
} from 'lucide-react'
import { PlaybookMentionsEditor } from '@/components/PlaybookMentionsEditor'

export default function GreetingPage() {
  const params = useParams()
  const qc = useQueryClient()
  const id = params.id as string

  // Fetch platform language config
  const { data: langConfig } = useQuery({
    queryKey: ['platform-language-config'],
    queryFn: () => platformApi.getLanguageConfig(),
    staleTime: 1000 * 60 * 60, // 1 hour
  })

  // Aliases for convenience
  const LANGUAGES = langConfig?.languages || []

  // Form state
  const [language, setLanguage] = useState('en')
  const [autoDetectLanguage, setAutoDetectLanguage] = useState(false)
  const [supportedLanguages, setSupportedLanguages] = useState<string[]>([])
  const [greetingText, setGreetingText] = useState('')
  const [ivrLanguagePrompt, setIvrLanguagePrompt] = useState('')
  const [openingPreview, setOpeningPreview] = useState('')
  const [voiceProtocolPresetId, setVoiceProtocolPresetId] = useState('')
  const [voiceSystemPrompt, setVoiceSystemPrompt] = useState('')

  const { data: voiceProtocols = [] } = useQuery({
    queryKey: ['platform-voice-protocols'],
    queryFn: () => platformApi.getVoiceProtocols(),
    staleTime: 1000 * 60 * 60, // 1 hour
  })

  const [isSaving, setIsSaving] = useState(false)
  const [isGeneratingGreeting, setIsGeneratingGreeting] = useState(false)
  const [isGeneratingIvr, setIsGeneratingIvr] = useState(false)

  // Detect session-variable placeholders ($vars:name or $[vars:name]) in text.
  // When present the backend skips pre-generation and uses JIT TTS at call time.
  const hasVariables = (text: string): boolean =>
    /\$\[vars:\w+\]|\$vars:\w+/.test(text)

  const greetingHasVars = hasVariables(greetingText)
  const ivrHasVars = hasVariables(ivrLanguagePrompt)

  const { data: agent, isLoading } = useQuery({
    queryKey: ['agent', id],
    queryFn: () => agentsApi.get(id),
    enabled: !!id,
  })

  const { data: baseVariables = [] } = useQuery({
    queryKey: ['variables', id],
    queryFn: () => variablesApi.list(id),
    enabled: !!id,
  })
  
  const globalVariables = Array.isArray(baseVariables) ? baseVariables.filter((v: any) => v.scope === 'global') : []

  const { data: tools = [] } = useQuery({
    queryKey: ['tools', id],
    queryFn: () => toolsApi.list(id),
    enabled: !!id,
  })

  const { data: documents = [] } = useQuery({
    queryKey: ['documents', id],
    queryFn: () => documentsApi.list(id),
    enabled: !!id,
  })

  // Populate form when agent loads
  useEffect(() => {
    if (agent) {
      const cfg = (agent.agent_config || {}) as Record<string, unknown>
      setLanguage((agent.language as string) || 'en')
      setAutoDetectLanguage((cfg.auto_detect_language as boolean) || (agent.auto_detect_language as boolean) || false)
      setSupportedLanguages((cfg.supported_languages as string[]) || (agent.supported_languages as string[]) || [])
      setGreetingText((cfg.greeting_message as string) || (agent.greeting_message as string) || '')
      setIvrLanguagePrompt((cfg.ivr_language_prompt as string) || (agent.ivr_language_prompt as string) || '')
      setVoiceProtocolPresetId((cfg.voice_protocol_preset_id as string) || (agent.voice_protocol_preset_id as string) || '')
      setVoiceSystemPrompt((cfg.voice_system_prompt as string) || (agent.voice_system_prompt as string) || '')
      
      // Load opening preview text from agent if available
      if (agent.computed_greeting) {
        setOpeningPreview(agent.computed_greeting)
      }
    }
  }, [agent])

  const fetchPreview = useCallback(async () => {
    if (!id) return
    try {
      const { text } = await agentsApi.getOpeningPreview(id, language, supportedLanguages, greetingText)
      setOpeningPreview(text)
    } catch {
      // fallback
    }
  }, [id, language, supportedLanguages, greetingText])

  // Refresh preview on state change
  useEffect(() => {
    const timer = setTimeout(() => {
      fetchPreview()
    }, 300) // debounce 300ms
    return () => clearTimeout(timer)
  }, [language, supportedLanguages, greetingText, fetchPreview])

  const handleGenerateGreetingAudio = async () => {
    try {
      setIsGeneratingGreeting(true)
      await agentsApi.generateGreetingAudio(id)
      qc.invalidateQueries({ queryKey: ['agent', id] })
      toast.success('Greeting audio generated!')
    } catch {
      toast.error('Failed to generate greeting audio.')
    } finally {
      setIsGeneratingGreeting(false)
    }
  }

  const handleGenerateIvrAudio = async () => {
    try {
      setIsGeneratingIvr(true)
      await agentsApi.generateIvrAudio(id)
      qc.invalidateQueries({ queryKey: ['agent', id] })
      toast.success('IVR prompt audio generated!')
    } catch {
      toast.error('Failed to generate IVR audio.')
    } finally {
      setIsGeneratingIvr(false)
    }
  }

  const saveSettings = async () => {
    setIsSaving(true)
    try {
      await agentsApi.update(id, {
        language,
        auto_detect_language: autoDetectLanguage,
        supported_languages: supportedLanguages,
        greeting_message: greetingText || null,
        ivr_language_prompt: ivrLanguagePrompt || null,
        voice_system_prompt: voiceSystemPrompt || null,
        voice_protocol_preset_id: voiceProtocolPresetId || null,
      })
      qc.invalidateQueries({ queryKey: ['agent', id] })
      qc.invalidateQueries({ queryKey: ['agents'] })
      toast.success('Settings saved.')
    } catch {
      toast.error('Save failed. Please try again.')
    } finally {
      setIsSaving(false)
    }
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin w-8 h-8 border-2 border-violet-600 border-t-transparent rounded-full" />
      </div>
    )
  }

  if (!agent) {
    return <div className="text-center py-16 text-gray-500">Agent not found.</div>
  }

  const savedGreetingUrl = agent.voice_greeting_url
  const savedIvrUrl = (agent.agent_config as Record<string, unknown>)?.ivr_language_url as string | undefined

  return (
    <div className="p-8 w-full space-y-6">
      {/* Header */}
      <div className="flex items-center gap-3">
        <Link
          href={`/dashboard/agents/${id}`}
          className="p-2 hover:bg-gray-100 dark:hover:bg-gray-800 rounded-lg transition-colors"
        >
          <ArrowLeft size={20} className="text-gray-600 dark:text-gray-400" />
        </Link>
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">
            Greeting &amp; Language
          </h1>
          <p className="text-sm text-gray-500">{agent.name}</p>
        </div>
      </div>

      {/* Language */}
      <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 p-6 space-y-4">
        <div className="flex items-center gap-2 mb-1">
          <Globe size={18} className="text-violet-600 dark:text-violet-400" />
          <h2 className="text-base font-semibold text-gray-900 dark:text-white">Language</h2>
        </div>
        <p className="text-sm text-gray-500">
          Sets the default language for STT recognition and TTS voice synthesis.
        </p>
        <select
          value={language}
          onChange={(e) => setLanguage(e.target.value)}
          className="w-full px-3 py-2 bg-gray-50 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg text-sm text-gray-900 dark:text-white focus:ring-2 focus:ring-violet-500 focus:border-transparent"
        >
          {LANGUAGES.map((l) => (
            <option key={l.code} value={l.code}>
              {l.label}
            </option>
          ))}
        </select>

        <div className="pt-4 border-t border-gray-100 dark:border-gray-800">
          <label className="flex items-center gap-3 cursor-pointer">
            <input
              type="checkbox"
              checked={autoDetectLanguage}
              onChange={(e) => setAutoDetectLanguage(e.target.checked)}
              className="w-4 h-4 text-violet-600 rounded focus:ring-violet-500 border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700"
            />
            <span className="text-sm font-medium text-gray-900 dark:text-white">Enable Auto-Detect Language</span>
          </label>
          <p className="text-xs text-gray-500 mt-1 ml-7">
            Automatically detect the user's language based on browser/session headers or initial user message.
          </p>
        </div>

        {autoDetectLanguage && (
          <div className="pl-7 space-y-2">
            <label className="text-sm font-medium text-gray-700 dark:text-gray-300">Supported Languages</label>
            <p className="text-xs text-gray-500 mb-2">Select the languages your agent is allowed to speak.</p>
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 max-h-48 overflow-y-auto p-2 bg-gray-50 dark:bg-gray-800 rounded border border-gray-200 dark:border-gray-700">
              {LANGUAGES.map((l) => (
                <label key={l.code} className="flex items-center gap-2 cursor-pointer text-sm">
                  <input
                    type="checkbox"
                    checked={supportedLanguages.includes(l.code)}
                    onChange={(e) => {
                      if (e.target.checked) {
                        setSupportedLanguages([...supportedLanguages, l.code])
                      } else {
                        setSupportedLanguages(supportedLanguages.filter((code) => code !== l.code))
                      }
                    }}
                    className="w-3.5 h-3.5 text-violet-600 rounded focus:ring-violet-500 border-gray-300 dark:border-gray-600"
                  />
                  <span className="truncate text-gray-700 dark:text-gray-300">{l.label}</span>
                </label>
              ))}
            </div>
          </div>
        )}

        {/* Dynamic Opening Preview */}
        <div className="mt-4 p-4 bg-violet-50 dark:bg-violet-900/10 border border-violet-100 dark:border-violet-800/50 rounded-xl">
          <div className="flex items-center gap-2 mb-2">
            <Volume2 size={14} className="text-violet-600 dark:text-violet-400" />
            <span className="text-xs font-bold text-violet-700 dark:text-violet-300 uppercase tracking-wider">Audible Opening Preview</span>
          </div>
          <p className="text-sm text-gray-700 dark:text-gray-300 italic font-medium leading-relaxed">
            "{openingPreview || 'Loading preview...'}"
          </p>
          <p className="text-[10px] text-gray-400 mt-2">
            * This is the exact phrase your agent will speak at the start of a voice call.
          </p>
        </div>

        <div className="pt-2">
          <button
            onClick={saveSettings}
            disabled={isSaving}
            className="flex items-center gap-2 px-4 py-2 bg-violet-600 hover:bg-violet-700 disabled:opacity-50 text-white rounded-lg text-sm font-medium transition-colors"
          >
            {isSaving ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
            {isSaving ? 'Saving…' : 'Save Language Settings'}
          </button>
        </div>
      </div>

      {/* Text greeting */}
      <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 p-6 space-y-4">
        <div className="flex items-center gap-2 mb-1">
          <Volume2 size={18} className="text-violet-600 dark:text-violet-400" />
          <h2 className="text-base font-semibold text-gray-900 dark:text-white">Text Greeting</h2>
        </div>
        <p className="text-sm text-gray-500">
          The greeting spoken to callers when a new call connects. Saving this text
          automatically generates a high-quality TTS audio file.
        </p>

        {/* Text Greeting generation status */}
        <div className="flex items-center gap-3">
          {savedGreetingUrl ? (
            <div className="flex items-center gap-2 px-3 py-2 bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800 rounded-lg text-sm flex-1">
              <CheckCircle2 size={14} className="text-green-600 dark:text-green-400 flex-shrink-0" />
              <span className="text-green-700 dark:text-green-300 flex-1 truncate">TTS audio active</span>
              <audio src={savedGreetingUrl} controls className="h-7" preload="none" />
            </div>
          ) : (
            <div className="flex items-center gap-2 px-3 py-2 bg-gray-50 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg text-sm text-gray-500 flex-1">
              <Info size={14} className="flex-shrink-0" />
              No audio generated yet.
            </div>
          )}
          <button
            onClick={handleGenerateGreetingAudio}
            disabled={isGeneratingGreeting || !greetingText || greetingHasVars}
            title={greetingHasVars ? 'Cannot pre-generate audio for a greeting with session variables — it will be synthesized live at call time.' : undefined}
            className="flex items-center gap-2 px-4 py-2 bg-gray-100 dark:bg-gray-800 hover:bg-gray-200 dark:hover:bg-gray-700 disabled:opacity-50 text-gray-700 dark:text-gray-300 rounded-lg text-sm font-medium transition-colors"
          >
            {isGeneratingGreeting
              ? <Loader2 size={14} className="animate-spin" />
              : greetingHasVars
                ? <Zap size={14} className="text-amber-500" />
                : <Volume2 size={14} />}
            {greetingHasVars ? 'JIT (Live)' : savedGreetingUrl ? 'Regenerate' : 'Generate Audio'}
          </button>
        </div>

        <div>
          <PlaybookMentionsEditor
            value={greetingText}
            onChange={(val) => setGreetingText(val)}
            tools={tools}
            variables={globalVariables}
            documents={documents}
            placeholder={`Hi! I me ${agent?.name || 'an agent'}. How can I help you today?`}
          />
          <p className="text-xs text-gray-400 mt-1 text-right">{greetingText.length}/1000</p>
          {greetingHasVars && (
            <div className="mt-2 flex items-start gap-2 rounded-lg border border-amber-200 dark:border-amber-700/50 bg-amber-50 dark:bg-amber-900/20 px-3 py-2.5">
              <Zap size={14} className="text-amber-500 mt-0.5 flex-shrink-0" />
              <p className="text-xs text-amber-700 dark:text-amber-300 leading-relaxed">
                <span className="font-semibold">JIT Synthesis Active</span> — This greeting contains dynamic variables and will be spoken verbatim at call-time. No static audio file is generated; the voice engine resolves placeholders live for each caller.
              </p>
            </div>
          )}
        </div>
        <button
          onClick={saveSettings}
          disabled={isSaving}
          className="flex items-center gap-2 px-4 py-2 bg-violet-600 hover:bg-violet-700 disabled:opacity-50 text-white rounded-lg text-sm font-medium transition-colors"
        >
          {isSaving ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
          {isSaving ? 'Saving…' : 'Save Greeting Settings'}
        </button>
      </div>

      {/* IVR Language Prompt */}
      <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 p-6 space-y-4">
        <div className="flex items-center gap-2 mb-1">
          <PhoneCall size={18} className="text-violet-600 dark:text-violet-400" />
          <h2 className="text-base font-semibold text-gray-900 dark:text-white">IVR Language Prompt</h2>
        </div>
        <p className="text-sm text-gray-500">
          Optional prompt played immediately after the greeting to offer callers a language choice.
        </p>

        {/* IVR Prompt generation status */}
        <div className="flex items-center gap-3">
          {savedIvrUrl ? (
            <div className="flex items-center gap-2 px-3 py-2 bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800 rounded-lg text-sm flex-1">
              <CheckCircle2 size={14} className="text-green-600 dark:text-green-400 flex-shrink-0" />
              <span className="text-green-700 dark:text-green-300 flex-1 truncate">IVR audio active</span>
              <audio src={savedIvrUrl} controls className="h-7" preload="none" />
            </div>
          ) : (
            <div className="flex items-center gap-2 px-3 py-2 bg-gray-50 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg text-sm text-gray-500 flex-1">
              <Info size={14} className="flex-shrink-0" />
              No IVR audio generated yet.
            </div>
          )}
          <button
            onClick={handleGenerateIvrAudio}
            disabled={isGeneratingIvr || !ivrLanguagePrompt || ivrHasVars}
            title={ivrHasVars ? 'Cannot pre-generate audio for an IVR prompt with session variables — it will be synthesized live at call time.' : undefined}
            className="flex items-center gap-2 px-4 py-2 bg-gray-100 dark:bg-gray-800 hover:bg-gray-200 dark:hover:bg-gray-700 disabled:opacity-50 text-gray-700 dark:text-gray-300 rounded-lg text-sm font-medium transition-colors"
          >
            {isGeneratingIvr
              ? <Loader2 size={14} className="animate-spin" />
              : ivrHasVars
                ? <Zap size={14} className="text-amber-500" />
                : <Volume2 size={14} />}
            {ivrHasVars ? 'JIT (Live)' : savedIvrUrl ? 'Regenerate' : 'Generate Audio'}
          </button>
        </div>

        <div>
          <PlaybookMentionsEditor
            value={ivrLanguagePrompt}
            onChange={(val) => setIvrLanguagePrompt(val)}
            tools={tools}
            variables={globalVariables}
            documents={documents}
            placeholder="For English, press 1. Pour le français, appuyez sur 2."
          />
          <p className="text-xs text-gray-400 mt-1 text-right">{ivrLanguagePrompt.length}/500</p>
          {ivrHasVars && (
            <div className="mt-2 flex items-start gap-2 rounded-lg border border-amber-200 dark:border-amber-700/50 bg-amber-50 dark:bg-amber-900/20 px-3 py-2.5">
              <Zap size={14} className="text-amber-500 mt-0.5 flex-shrink-0" />
              <p className="text-xs text-amber-700 dark:text-amber-300 leading-relaxed">
                <span className="font-semibold">JIT Synthesis Active</span> — This IVR prompt contains dynamic variables and will be resolved live at call time.
              </p>
            </div>
          )}
        </div>
        <button
          onClick={saveSettings}
          disabled={isSaving}
          className="flex items-center gap-2 px-4 py-2 bg-violet-600 hover:bg-violet-700 disabled:opacity-50 text-white rounded-lg text-sm font-medium transition-colors"
        >
          {isSaving ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
          {isSaving ? 'Saving…' : 'Save IVR Prompt'}
        </button>
      </div>

      {/* Voice Protocol */}
      <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 p-6 space-y-4">
        <div className="flex items-center gap-2 mb-1">
          <Mic size={18} className="text-violet-600 dark:text-violet-400" />
          <h2 className="text-base font-semibold text-gray-900 dark:text-white">Voice Protocol</h2>
        </div>
        <p className="text-sm text-gray-500">
          Advanced instructions for how the agent handles voice-specific logic. Select a platform preset and add any optional custom instructions.
        </p>

        {/* Protocol Presets */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
          {voiceProtocols.map((preset: any) => {
            const isSelected = voiceProtocolPresetId === preset.id
            return (
              <button
                key={preset.id}
                onClick={() => setVoiceProtocolPresetId(preset.id)}
                className={`text-left p-3 border rounded-lg transition-colors group ${
                  isSelected 
                    ? 'bg-violet-50 dark:bg-violet-900/40 border-violet-600 dark:border-violet-500 ring-1 ring-violet-600 dark:ring-violet-500' 
                    : 'bg-gray-50 dark:bg-gray-800 hover:bg-violet-50/50 dark:hover:bg-violet-900/20 border-gray-200 dark:border-gray-700 hover:border-violet-300 dark:hover:border-violet-700'
                }`}
              >
                <div className="flex items-center justify-between mb-0.5">
                  <p className={`text-sm font-medium ${isSelected ? 'text-violet-800 dark:text-violet-200' : 'text-gray-800 dark:text-gray-200 group-hover:text-violet-700 dark:group-hover:text-violet-300'}`}>
                    {preset.label}
                  </p>
                  {isSelected && (
                    <div className="w-2 h-2 rounded-full bg-violet-600 dark:bg-violet-400" />
                  )}
                </div>
              </button>
            )
          })}
        </div>

        <div className="relative mt-2">
          <label className="block text-xs font-semibold text-gray-700 dark:text-gray-300 uppercase tracking-wider mb-2">
            Additional Custom Instructions (Optional)
          </label>
          <PlaybookMentionsEditor
            value={voiceSystemPrompt}
            onChange={(val) => setVoiceSystemPrompt(val)}
            tools={tools}
            variables={globalVariables}
            documents={documents}
            placeholder="Enter any custom voice-specific system instructions to append to the chosen preset..."
          />
        </div>
        <div className="flex justify-start">
          <button
            onClick={saveSettings}
            disabled={isSaving}
            className="flex items-center gap-2 px-4 py-2 bg-violet-600 hover:bg-violet-700 disabled:opacity-50 text-white rounded-lg text-sm font-medium transition-colors"
          >
            {isSaving ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
            {isSaving ? 'Saving…' : 'Save Voice Protocol'}
          </button>
        </div>
      </div>
    </div>
  )
}
