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
  Plus,
  Trash,
  Play,
  StopCircle,
  MessageSquare,
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
  const [isPreviewOverridden, setIsPreviewOverridden] = useState(false)
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
  const [isSavingDtmf, setIsSavingDtmf] = useState(false)
  const [generatingDtmfAudioFor, setGeneratingDtmfAudioFor] = useState<string | null>(null)

  // DTMF Menu State
  const [dtmfTimeout, setDtmfTimeout] = useState(10)
  const [dtmfMaxRetries, setDtmfMaxRetries] = useState(3)
  const [dtmfEntries, setDtmfEntries] = useState<any[]>([])

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

  // Fetch DTMF Menu
  const { data: dtmfMenuData } = useQuery({
    queryKey: ['agent-dtmf-menu', id],
    queryFn: () => agentsApi.getIvrDtmfMenu(id),
    enabled: !!id,
  })

  useEffect(() => {
    if (dtmfMenuData?.ivr_dtmf_menu) {
      setDtmfTimeout(dtmfMenuData.ivr_dtmf_menu.timeout_seconds ?? 10)
      setDtmfMaxRetries(dtmfMenuData.ivr_dtmf_menu.max_retries ?? 3)
      setDtmfEntries(dtmfMenuData.ivr_dtmf_menu.entries || [])
    }
  }, [dtmfMenuData])

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
        // If the saved computed_greeting is in the config, it might be an override
        const cfg = (agent.agent_config || {}) as Record<string, unknown>
        if (cfg._cached_greeting === agent.computed_greeting) {
           setIsPreviewOverridden(true)
        }
      }
    }
  }, [agent])

  const fetchPreview = useCallback(async () => {
    if (!id) return
    try {
      const { text } = await agentsApi.getOpeningPreview(id, language, supportedLanguages, greetingText, ivrLanguagePrompt)
      setOpeningPreview(text)
    } catch {
      // fallback
    }
  }, [id, language, supportedLanguages, greetingText, ivrLanguagePrompt])

  // Refresh preview on state change
  useEffect(() => {
    const timer = setTimeout(() => {
      fetchPreview()
    }, 300) // debounce 300ms
    return () => clearTimeout(timer)
  }, [language, supportedLanguages, greetingText, ivrLanguagePrompt, fetchPreview])

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

  const saveDtmfMenu = async () => {
    setIsSavingDtmf(true)
    try {
      await agentsApi.updateIvrDtmfMenu(id, {
        timeout_seconds: dtmfTimeout,
        max_retries: dtmfMaxRetries,
        entries: dtmfEntries,
      })
      qc.invalidateQueries({ queryKey: ['agent-dtmf-menu', id] })
      toast.success('DTMF menu saved.')
    } catch {
      toast.error('Failed to save DTMF menu.')
    } finally {
      setIsSavingDtmf(false)
    }
  }

  const handleGenerateDtmfAudio = async (digit: string) => {
    try {
      setGeneratingDtmfAudioFor(digit)
      await agentsApi.generateDtmfEntryAudio(id, digit)
      qc.invalidateQueries({ queryKey: ['agent-dtmf-menu', id] })
      toast.success(`Audio generated for digit ${digit}`)
    } catch {
      toast.error(`Failed to generate audio for digit ${digit}`)
    } finally {
      setGeneratingDtmfAudioFor(null)
    }
  }

  const saveSettings = async () => {
    setIsSaving(true)
    try {
      // Auto-populate IVR prompt from preview if empty, as requested (saves a manual copy step)
      let finalIvrPrompt = ivrLanguagePrompt
      if (!finalIvrPrompt && openingPreview) {
        finalIvrPrompt = openingPreview
        setIvrLanguagePrompt(openingPreview)
      }

      await agentsApi.update(id, {
        language,
        auto_detect_language: autoDetectLanguage,
        supported_languages: supportedLanguages,
        greeting_message: greetingText || null,
        ivr_language_prompt: finalIvrPrompt || null,
        voice_system_prompt: voiceSystemPrompt || null,
        voice_protocol_preset_id: voiceProtocolPresetId || null,
        opening_preview: isPreviewOverridden ? openingPreview : null,
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

        {/* Language configuration ends here */}

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

      {/* Audio Preview (Moved here as requested) */}
      <div className="bg-violet-50 dark:bg-violet-900/10 border border-violet-100 dark:border-violet-800/50 p-6 rounded-xl space-y-3">
        <div className="flex justify-between items-center">
          <div className="flex items-center gap-2">
            <Volume2 size={18} className="text-violet-600 dark:text-violet-400" />
            <h3 className="text-base font-semibold text-violet-900 dark:text-violet-100">Generated Voice Greeting Preview</h3>
          </div>
          <button
            onClick={() => {
              if (openingPreview) {
                setIvrLanguagePrompt(openingPreview)
                toast.success('Copied to Voice Greeting')
              }
            }}
            disabled={!openingPreview}
            className="text-xs px-3 py-1.5 bg-violet-600 hover:bg-violet-700 text-white rounded font-medium disabled:opacity-50 transition-colors"
          >
            Copy to Voice Greeting
          </button>
        </div>
        <p className="text-sm text-violet-800 dark:text-violet-200 italic leading-relaxed">
          {openingPreview || "Preview not available."}
        </p>
        <p className="text-xs text-violet-600/70 dark:text-violet-300/70">
          This preview shows how your greeting and language options will sound to callers. Use "Copy to Voice Greeting" to customize the exact script below.
        </p>
      </div>


      {/* Chat greeting */}
      <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 p-6 space-y-4">
        <div className="flex items-center gap-2 mb-1">
          <MessageSquare size={18} className="text-violet-600 dark:text-violet-400" />
          <h2 className="text-base font-semibold text-gray-900 dark:text-white">Greeting message for Text and Chat</h2>
        </div>
        <p className="text-sm text-gray-500">
          The text shown to users when a new web chat or SMS session connects.
        </p>



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

      {/* Voice Greeting & IVR Menu */}
      <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 p-6 space-y-4">
        <div className="flex items-center gap-2 mb-1">
          <PhoneCall size={18} className="text-violet-600 dark:text-violet-400" />
          <h2 className="text-base font-semibold text-gray-900 dark:text-white">Voice Greeting &amp; IVR Menu</h2>
        </div>
        <p className="text-sm text-gray-500">
          The complete script spoken to callers on Voice channels. This should include your welcome message and DTMF options.
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
        </div>
        <div className="flex justify-between items-end mt-2">
          <p className="text-xs text-gray-400 text-right w-full">{ivrLanguagePrompt.length}/500</p>
        </div>
        {ivrHasVars && (
          <div className="mt-2 flex items-start gap-2 rounded-lg border border-amber-200 dark:border-amber-700/50 bg-amber-50 dark:bg-amber-900/20 px-3 py-2.5">
            <Zap size={14} className="text-amber-500 mt-0.5 flex-shrink-0" />
            <p className="text-xs text-amber-700 dark:text-amber-300 leading-relaxed">
              <span className="font-semibold">JIT Synthesis Active</span> — This IVR prompt contains dynamic variables and will be resolved live at call time.
            </p>
          </div>
        )}

        <button
          onClick={saveSettings}
          disabled={isSaving}
          className="flex items-center gap-2 px-4 py-2 bg-violet-600 hover:bg-violet-700 disabled:opacity-50 text-white rounded-lg text-sm font-medium transition-colors mt-4"
        >
          {isSaving ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
          {isSaving ? 'Saving…' : 'Save IVR Prompt'}
        </button>
      </div>

      {/* IVR Menu (DTMF Builder) */}
      <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 p-6 space-y-6">
        <div className="flex flex-col gap-1 mb-1">
          <div className="flex items-center gap-2">
            <PhoneCall size={18} className="text-violet-600 dark:text-violet-400" />
            <h2 className="text-base font-semibold text-gray-900 dark:text-white">IVR Menu (DTMF Builder)</h2>
          </div>
          <p className="text-sm text-gray-500">
            Map keypad presses to instant audio responses. Static audio is played without engaging the AI, saving tokens and latency.
          </p>
        </div>

        {/* Timeout & Retries */}
        <div className="flex items-center gap-6 p-4 bg-gray-50 dark:bg-gray-800/50 rounded-lg border border-gray-200 dark:border-gray-700">
          <div className="flex-1">
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
              Timeout (Seconds)
            </label>
            <input
              type="number"
              min={3}
              max={30}
              value={dtmfTimeout}
              onChange={(e) => setDtmfTimeout(Number(e.target.value))}
              className="w-full px-3 py-2 bg-white dark:bg-gray-800 border border-gray-300 dark:border-gray-600 rounded-md text-sm text-gray-900 dark:text-white focus:ring-2 focus:ring-violet-500"
            />
          </div>
          <div className="flex-1">
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
              Max Retries
            </label>
            <input
              type="number"
              min={0}
              max={5}
              value={dtmfMaxRetries}
              onChange={(e) => setDtmfMaxRetries(Number(e.target.value))}
              className="w-full px-3 py-2 bg-white dark:bg-gray-800 border border-gray-300 dark:border-gray-600 rounded-md text-sm text-gray-900 dark:text-white focus:ring-2 focus:ring-violet-500"
            />
          </div>
          <div className="flex-[2]">
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
              Timeout Action
            </label>
            <p className="text-sm text-gray-600 dark:text-gray-400 py-2">
              Proceed to AI Agent (Auto-fallback)
            </p>
          </div>
        </div>

        {/* Entries Table */}
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-medium text-gray-900 dark:text-white">Menu Entries</h3>
            <button
              onClick={() => setDtmfEntries([...dtmfEntries, { digit: '', label: '', action: 'proceed_to_agent', audio_text: '' }])}
              className="flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium text-violet-600 bg-violet-50 hover:bg-violet-100 dark:text-violet-400 dark:bg-violet-900/20 dark:hover:bg-violet-900/40 rounded-md transition-colors"
            >
              <Plus size={14} /> Add Entry
            </button>
          </div>

          {dtmfEntries.length === 0 ? (
            <div className="text-center py-8 bg-gray-50 dark:bg-gray-800/30 rounded-lg border border-dashed border-gray-300 dark:border-gray-700">
              <p className="text-sm text-gray-500">No DTMF entries configured.</p>
            </div>
          ) : (
            <div className="space-y-4">
              {dtmfEntries.map((entry, idx) => (
                <div key={idx} className="p-4 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl space-y-4">
                  <div className="flex items-start gap-4">
                    <div className="w-24">
                      <label className="block text-xs font-semibold text-gray-700 dark:text-gray-300 uppercase tracking-wider mb-1">
                        Digit
                      </label>
                      <select
                        value={entry.digit}
                        onChange={(e) => {
                          const newEntries = [...dtmfEntries];
                          newEntries[idx].digit = e.target.value;
                          setDtmfEntries(newEntries);
                        }}
                        className="w-full px-3 py-2 bg-gray-50 dark:bg-gray-900 border border-gray-200 dark:border-gray-700 rounded-lg text-sm text-gray-900 dark:text-white focus:ring-2 focus:ring-violet-500 focus:border-transparent"
                      >
                        <option value="">--</option>
                        {['0', '1', '2', '3', '4', '5', '6', '7', '8', '9', '*', '#'].map(d => (
                          <option key={d} value={d} disabled={dtmfEntries.some((e, i) => i !== idx && e.digit === d)}>{d}</option>
                        ))}
                      </select>
                    </div>
                    <div className="flex-1">
                      <label className="block text-xs font-semibold text-gray-700 dark:text-gray-300 uppercase tracking-wider mb-1">
                        Label (Internal)
                      </label>
                      <input
                        type="text"
                        placeholder="e.g. Store Hours"
                        value={entry.label}
                        onChange={(e) => {
                          const newEntries = [...dtmfEntries];
                          newEntries[idx].label = e.target.value;
                          setDtmfEntries(newEntries);
                        }}
                        className="w-full px-3 py-2 bg-gray-50 dark:bg-gray-900 border border-gray-200 dark:border-gray-700 rounded-lg text-sm text-gray-900 dark:text-white focus:ring-2 focus:ring-violet-500 focus:border-transparent"
                      />
                    </div>
                    <div className="flex-1">
                      <label className="block text-xs font-semibold text-gray-700 dark:text-gray-300 uppercase tracking-wider mb-1">
                        Action
                      </label>
                      <select
                        value={entry.action}
                        onChange={(e) => {
                          const newEntries = [...dtmfEntries];
                          newEntries[idx].action = e.target.value;
                          setDtmfEntries(newEntries);
                        }}
                        className="w-full px-3 py-2 bg-gray-50 dark:bg-gray-900 border border-gray-200 dark:border-gray-700 rounded-lg text-sm text-gray-900 dark:text-white focus:ring-2 focus:ring-violet-500 focus:border-transparent"
                      >
                        <option value="play_audio">Play Audio</option>
                        <option value="proceed_to_agent">Proceed to AI Agent</option>
                        <option value="repeat_menu">Repeat Menu</option>
                        <option value="end_call">End Call</option>
                      </select>
                    </div>
                    <button
                      onClick={() => {
                        const newEntries = dtmfEntries.filter((_, i) => i !== idx);
                        setDtmfEntries(newEntries);
                      }}
                      className="mt-6 p-2 text-gray-400 hover:text-red-600 hover:bg-red-50 dark:hover:bg-red-900/20 rounded-lg transition-colors"
                    >
                      <Trash size={16} />
                    </button>
                  </div>

                  {entry.action === 'play_audio' && (
                    <div className="pl-28 space-y-3">
                      <div>
                        <label className="block text-xs font-semibold text-gray-700 dark:text-gray-300 uppercase tracking-wider mb-1">
                          Audio Text
                        </label>
                        <textarea
                          rows={2}
                          value={entry.audio_text || ''}
                          onChange={(e) => {
                            const newEntries = [...dtmfEntries];
                            newEntries[idx].audio_text = e.target.value;
                            setDtmfEntries(newEntries);
                          }}
                          placeholder="Our store is open from 9 AM to 6 PM."
                          className="w-full px-3 py-2 bg-gray-50 dark:bg-gray-900 border border-gray-200 dark:border-gray-700 rounded-lg text-sm text-gray-900 dark:text-white focus:ring-2 focus:ring-violet-500 focus:border-transparent resize-none"
                        />
                      </div>
                      <div className="flex items-center gap-3">
                        <button
                          onClick={() => handleGenerateDtmfAudio(entry.digit)}
                          disabled={!entry.digit || !entry.audio_text || generatingDtmfAudioFor === entry.digit}
                          className="flex items-center gap-2 px-3 py-1.5 bg-gray-100 hover:bg-gray-200 dark:bg-gray-800 dark:hover:bg-gray-700 text-gray-700 dark:text-gray-300 rounded-md text-sm font-medium transition-colors disabled:opacity-50"
                        >
                          {generatingDtmfAudioFor === entry.digit ? <Loader2 size={14} className="animate-spin" /> : <Volume2 size={14} />}
                          Generate Audio
                        </button>
                        {entry.audio_url && (
                          <audio src={entry.audio_url} controls className="h-8 flex-1 max-w-sm" preload="none" />
                        )}
                      </div>
                      
                      <div className="pt-2 border-t border-gray-100 dark:border-gray-700/50">
                        <label className="block text-xs font-semibold text-gray-700 dark:text-gray-300 uppercase tracking-wider mb-1">
                          After Playback
                        </label>
                        <select
                          value={entry.after_playback || 'proceed_to_agent'}
                          onChange={(e) => {
                            const newEntries = [...dtmfEntries];
                            newEntries[idx].after_playback = e.target.value;
                            setDtmfEntries(newEntries);
                          }}
                          className="w-48 px-3 py-1.5 bg-gray-50 dark:bg-gray-900 border border-gray-200 dark:border-gray-700 rounded-lg text-sm text-gray-900 dark:text-white focus:ring-2 focus:ring-violet-500 focus:border-transparent"
                        >
                          <option value="proceed_to_agent">Proceed to AI Agent</option>
                          <option value="end_call">End Call</option>
                        </select>
                      </div>
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>

        <button
          onClick={saveDtmfMenu}
          disabled={isSavingDtmf}
          className="flex items-center gap-2 px-4 py-2 bg-violet-600 hover:bg-violet-700 disabled:opacity-50 text-white rounded-lg text-sm font-medium transition-colors mt-4"
        >
          {isSavingDtmf ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
          {isSavingDtmf ? 'Saving…' : 'Save DTMF Menu'}
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

        {/* Voice Protocol is now dynamically injected based on channel */}
        <div className="bg-violet-50 dark:bg-violet-900/20 border border-violet-200 dark:border-violet-800 rounded-lg p-3 flex items-start gap-2 mb-2">
          <Zap size={16} className="text-violet-600 dark:text-violet-400 mt-0.5 flex-shrink-0" />
          <p className="text-xs text-violet-800 dark:text-violet-300">
            <strong>Auto-Injected Protocol:</strong> Core telephony rules (conciseness, DTMF support, auto-language routing) are now globally injected into all Voice Agents automatically.
          </p>
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
