'use client'

import { useState, useEffect, useRef, useCallback } from 'react'
import { useParams } from 'next/navigation'
import Link from 'next/link'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { agentsApi } from '@/lib/api'
import toast from 'react-hot-toast'
import {
  ArrowLeft,
  Mic,
  MicOff,
  Play,
  Trash2,
  Save,
  Upload,
  Volume2,
  Globe,
  Info,
} from 'lucide-react'

// Languages supported by the voice pipeline (Gemini STT + Cartesia TTS)
const LANGUAGES = [
  { code: 'en', label: 'English (Global)' },
  { code: 'en-CA', label: 'English (Canada)' },
  { code: 'fr', label: 'French (France)' },
  { code: 'fr-CA', label: 'French (Canada / Québec)' },
  { code: 'es', label: 'Spanish' },
  { code: 'es-MX', label: 'Spanish (Mexico)' },
  { code: 'de', label: 'German' },
  { code: 'it', label: 'Italian' },
  { code: 'pt', label: 'Portuguese' },
  { code: 'pt-BR', label: 'Portuguese (Brazil)' },
  { code: 'nl', label: 'Dutch' },
  { code: 'pl', label: 'Polish' },
  { code: 'ru', label: 'Russian' },
  { code: 'zh', label: 'Chinese (Mandarin)' },
  { code: 'ja', label: 'Japanese' },
  { code: 'ko', label: 'Korean' },
  { code: 'hi', label: 'Hindi' },
  { code: 'pa', label: 'Punjabi' },
  { code: 'ar', label: 'Arabic' },
  { code: 'tr', label: 'Turkish' },
  { code: 'uk', label: 'Ukrainian' },
  { code: 'vi', label: 'Vietnamese' },
  { code: 'id', label: 'Indonesian' },
  { code: 'tl', label: 'Tagalog / Filipino' },
]

type RecordingState = 'idle' | 'recording' | 'recorded'

export default function GreetingPage() {
  const params = useParams()
  const qc = useQueryClient()
  const id = params.id as string

  // Form state
  const [language, setLanguage] = useState('en')
  const [autoDetectLanguage, setAutoDetectLanguage] = useState(false)
  const [supportedLanguages, setSupportedLanguages] = useState<string[]>([])
  const [greetingText, setGreetingText] = useState('')
  const [voiceSystemPrompt, setVoiceSystemPrompt] = useState('')

  // Voice recording state
  const [recordingState, setRecordingState] = useState<RecordingState>('idle')
  const [audioBlob, setAudioBlob] = useState<Blob | null>(null)
  const [audioUrl, setAudioUrl] = useState<string | null>(null)
  const [recordingSeconds, setRecordingSeconds] = useState(0)
  const [isUploading, setIsUploading] = useState(false)
  const [isSaving, setIsSaving] = useState(false)

  const mediaRecorderRef = useRef<MediaRecorder | null>(null)
  const chunksRef = useRef<BlobPart[]>([])
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const audioRef = useRef<HTMLAudioElement | null>(null)

  const { data: agent, isLoading } = useQuery({
    queryKey: ['agent', id],
    queryFn: () => agentsApi.get(id),
    enabled: !!id,
  })

  // Populate form when agent loads
  useEffect(() => {
    if (agent) {
      setLanguage(agent.language || 'en')
      setAutoDetectLanguage(agent.auto_detect_language || false)
      setSupportedLanguages(agent.supported_languages || [])
      setGreetingText(agent.greeting_message || '')
      setVoiceSystemPrompt(agent.voice_system_prompt || '')
      if (agent.voice_greeting_url) {
        setAudioUrl(agent.voice_greeting_url)
        setRecordingState('recorded')
      }
    }
  }, [agent])

  // Cleanup object URL on unmount
  useEffect(() => {
    return () => {
      if (audioUrl && audioUrl.startsWith('blob:')) {
        URL.revokeObjectURL(audioUrl)
      }
      if (timerRef.current) clearInterval(timerRef.current)
    }
  }, [audioUrl])

  // ── Recording ────────────────────────────────────────────────────────────

  const startRecording = useCallback(async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const mimeType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
        ? 'audio/webm;codecs=opus'
        : MediaRecorder.isTypeSupported('audio/mp4')
        ? 'audio/mp4'
        : 'audio/webm'

      const mr = new MediaRecorder(stream, { mimeType })
      chunksRef.current = []

      mr.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data)
      }

      mr.onstop = () => {
        stream.getTracks().forEach((t) => t.stop())
        const blob = new Blob(chunksRef.current, { type: mimeType })
        setAudioBlob(blob)
        const url = URL.createObjectURL(blob)
        setAudioUrl(url)
        setRecordingState('recorded')
      }

      mr.start(250) // collect chunks every 250 ms
      mediaRecorderRef.current = mr
      setRecordingState('recording')
      setRecordingSeconds(0)

      timerRef.current = setInterval(() => {
        setRecordingSeconds((s) => {
          if (s >= 60) {
            stopRecording()
            return s
          }
          return s + 1
        })
      }, 1000)
    } catch {
      toast.error('Microphone access denied. Please allow microphone access in your browser.')
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const stopRecording = useCallback(() => {
    if (timerRef.current) {
      clearInterval(timerRef.current)
      timerRef.current = null
    }
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
      mediaRecorderRef.current.stop()
    }
  }, [])

  const discardRecording = useCallback(() => {
    if (audioUrl && audioUrl.startsWith('blob:')) {
      URL.revokeObjectURL(audioUrl)
    }
    setAudioBlob(null)
    setAudioUrl(agent?.voice_greeting_url || null)
    setRecordingState(agent?.voice_greeting_url ? 'recorded' : 'idle')
    setRecordingSeconds(0)
  }, [audioUrl, agent])

  // ── Upload new recording ─────────────────────────────────────────────────

  const uploadRecording = async () => {
    if (!audioBlob) return
    setIsUploading(true)
    try {
      const mimeType = audioBlob.type
      const ext = mimeType.includes('mp4') ? 'm4a' : mimeType.includes('ogg') ? 'ogg' : 'webm'
      const result = await agentsApi.uploadVoiceGreeting(id, audioBlob, ext)
      setAudioUrl(result.url)
      setAudioBlob(null) // already uploaded; keep URL as saved URL
      qc.invalidateQueries({ queryKey: ['agent', id] })
      toast.success('Voice greeting saved — plays on every new call at no TTS cost.')
    } catch {
      toast.error('Upload failed. Please try again.')
    } finally {
      setIsUploading(false)
    }
  }

  // ── Delete saved recording ────────────────────────────────────────────────

  const deleteRecording = async () => {
    if (!confirm('Remove the saved voice greeting?')) return
    try {
      await agentsApi.deleteVoiceGreeting(id)
      if (audioUrl && audioUrl.startsWith('blob:')) URL.revokeObjectURL(audioUrl)
      setAudioUrl(null)
      setAudioBlob(null)
      setRecordingState('idle')
      qc.invalidateQueries({ queryKey: ['agent', id] })
      toast.success('Voice greeting removed.')
    } catch {
      toast.error('Failed to remove greeting.')
    }
  }

  // ── Save text greeting + language ─────────────────────────────────────────

  const saveSettings = async () => {
    setIsSaving(true)
    try {
      await agentsApi.update(id, {
        language,
        auto_detect_language: autoDetectLanguage,
        supported_languages: supportedLanguages,
        greeting_message: greetingText || null,
        voice_system_prompt: voiceSystemPrompt || null,
      })
      qc.invalidateQueries({ queryKey: ['agent', id] })
      toast.success('Greeting settings saved.')
    } catch {
      toast.error('Save failed. Please try again.')
    } finally {
      setIsSaving(false)
    }
  }

  // ── Opening Preview ────────────────────────────────────────────────────────

  const generateOpeningPreview = () => {
    const langs = supportedLanguages.length > 0 ? supportedLanguages : [language]

    // Map codes to human names (covers all in LANGUAGES constant)
    const getLangName = (code: string) => {
      const match = LANGUAGES.find(l => l.code === code)
      if (match) return match.label.split(' (')[0] // 'French (Canada)' -> 'French'
      
      // Fallback: strip region (fr-CA -> fr) and try again
      const baseCode = code.split('-')[0]
      const baseMatch = LANGUAGES.find(l => l.code === baseCode)
      if (baseMatch) return baseMatch.label.split(' (')[0]
      
      return code // Last resort
    }

    const phrases: Record<string, string> = {
      en: 'For English, please continue.',
      fr: 'Pour le français, parlez français s\'il vous plaît.',
      zh: '对于中文请直接用中文交流。',
      es: 'Para español, por favor hable en español.',
      de: 'Für Deutsch sprechen Sie bitte Deutsch.',
      it: 'Per l\'italiano, per favore parla in italiano.',
      pt: 'Para português, por favor fale em português.',
      ja: '日本語での対応をご希望の場合は、そのまま日本語でお話しください。',
      ko: '한국어로 말씀하시려면 한국어로 계속해 주세요.',
    }

    const getPhrase = (code: string) => {
      if (phrases[code]) return phrases[code]
      const baseCode = code.split('-')[0]
      return phrases[baseCode] || ''
    }

    const names = langs.map(l => getLangName(l))
    let assistStr = ''
    if (names.length === 1) assistStr = `I can assist you in ${names[0]}.`
    else if (names.length === 2) assistStr = `I can assist you in ${names[0]} or ${names[1]}.`
    else assistStr = `I can assist you in ${names.slice(0, -1).join(', ')}, and ${names[names.length - 1]}.`

    const audibleLangs = langs.slice(0, 3)
    const audiblePhrases = audibleLangs.map(l => getPhrase(l)).filter(Boolean)

    return `Thank you for calling. ${assistStr} ${audiblePhrases.join(' ')}`
  }

  // ── Recording timer label ─────────────────────────────────────────────────

  const timerLabel = `${Math.floor(recordingSeconds / 60)
    .toString()
    .padStart(2, '0')}:${(recordingSeconds % 60).toString().padStart(2, '0')}`

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin w-8 h-8 border-2 border-violet-600 border-t-transparent rounded-full" />
      </div>
    )
  }

  if (!agent) {
    return (
      <div className="text-center py-16 text-gray-500">Agent not found.</div>
    )
  }

  const savedGreetingUrl = agent.voice_greeting_url
  const hasPendingUpload = !!audioBlob

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

      {/* Cost-saving notice */}
      <div className="flex gap-3 p-4 bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded-xl text-sm text-blue-800 dark:text-blue-300">
        <Info size={16} className="flex-shrink-0 mt-0.5" />
        <span>
          Pre-recorded greetings are played as a static audio file on every new call —
          no TTS synthesis is triggered, which saves cost. Recording storage is billed to your account.
        </span>
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
            "{generateOpeningPreview()}"
          </p>
          <p className="text-[10px] text-gray-400 mt-2">
            * This is the exact phrase your agent will speak at the start of a voice call.
          </p>
        </div>
      </div>

      {/* Text greeting */}
      <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 p-6 space-y-4">
        <div className="flex items-center gap-2 mb-1">
          <Volume2 size={18} className="text-violet-600 dark:text-violet-400" />
          <h2 className="text-base font-semibold text-gray-900 dark:text-white">Text Greeting</h2>
        </div>
        <p className="text-sm text-gray-500">
          Used as a fallback when no voice recording is saved, or in chat/text channels.
        </p>
        <div>
          <textarea
            value={greetingText}
            onChange={(e) => setGreetingText(e.target.value)}
            maxLength={1000}
            rows={3}
            placeholder={`Hi! I'm ${agent.name}. How can I help you today?`}
            className="w-full px-3 py-2 bg-gray-50 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg text-sm text-gray-900 dark:text-white placeholder-gray-400 focus:ring-2 focus:ring-violet-500 focus:border-transparent resize-none"
          />
          <p className="text-xs text-gray-400 mt-1 text-right">{greetingText.length}/1000</p>
        </div>
        <button
          onClick={saveSettings}
          disabled={isSaving}
          className="flex items-center gap-2 px-4 py-2 bg-violet-600 hover:bg-violet-700 disabled:opacity-50 text-white rounded-lg text-sm font-medium transition-colors"
        >
          <Save size={14} />
          {isSaving ? 'Saving…' : 'Save Greeting Settings'}
        </button>
      </div>

      {/* Voice Protocol (System Prompt Extension) */}
      <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 p-6 space-y-4">
        <div className="flex items-center gap-2 mb-1">
          <Mic size={18} className="text-violet-600 dark:text-violet-400" />
          <h2 className="text-base font-semibold text-gray-900 dark:text-white">Voice Protocol</h2>
        </div>
        <p className="text-sm text-gray-500">
          Advanced instructions for how the agent handles voice-specific logic, like language switching and IVR behavior.
        </p>
        <div className="relative">
          <textarea
            value={voiceSystemPrompt}
            onChange={(e) => setVoiceSystemPrompt(e.target.value)}
            rows={8}
            placeholder="Enter voice-specific system instructions..."
            className="w-full px-3 py-2 bg-gray-50 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg text-sm text-gray-900 dark:text-white placeholder-gray-400 focus:ring-2 focus:ring-violet-500 focus:border-transparent font-mono"
          />
          {!voiceSystemPrompt && (
            <button
              onClick={() => setVoiceSystemPrompt(`## Multi-lingual & IVR Operational Protocol
- **INITIAL GREETING (MANDATORY)**: You MUST begin every new voice session with the following opening:
  "${generateOpeningPreview()}"
- **DYNAMIC LANGUAGE ADAPTATION**: You are globally configured to handle multiple languages.
- **PROTOCOL**: Upon detecting ANY supported language, pivot your response language immediately to match the user without requesting procedural confirmation (e.g., avoid "Would you like to speak French?").
- **CONTEXTUAL METADATA**: Ensure your response metadata accurately identifies the current communication language.`)}
              className="mt-2 text-xs text-violet-600 hover:underline flex items-center gap-1"
            >
              <Info size={12} />
              Load Professional IVR Default
            </button>
          )}
        </div>
        <div className="flex justify-end">
          <button
            onClick={saveSettings}
            disabled={isSaving}
            className="flex items-center gap-2 px-4 py-2 bg-violet-600 hover:bg-violet-700 disabled:opacity-50 text-white rounded-lg text-sm font-medium transition-colors"
          >
            <Save size={14} />
            {isSaving ? 'Saving…' : 'Save Voice Protocol'}
          </button>
        </div>
      </div>

      {/* Voice recording */}
      <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 p-6 space-y-5">
        <div className="flex items-center gap-2 mb-1">
          <Mic size={18} className="text-violet-600 dark:text-violet-400" />
          <h2 className="text-base font-semibold text-gray-900 dark:text-white">Voice Recording</h2>
        </div>
        <p className="text-sm text-gray-500">
          Record a greeting that plays automatically when every new call starts.
          Max 60 seconds. Supported formats: WebM, MP3, WAV (max 5 MB).
        </p>

        {/* Existing saved greeting */}
        {savedGreetingUrl && !hasPendingUpload && (
          <div className="flex items-center gap-3 p-3 bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800 rounded-lg">
            <Volume2 size={16} className="text-green-600 flex-shrink-0" />
            <span className="text-sm text-green-700 dark:text-green-400 flex-1 truncate">
              Saved recording active
            </span>
            <audio
              ref={audioRef}
              src={savedGreetingUrl}
              className="h-8 flex-shrink-0"
              controls
              preload="none"
            />
            <button
              onClick={deleteRecording}
              className="p-1.5 hover:bg-red-100 dark:hover:bg-red-900/30 rounded-lg transition-colors group"
              title="Delete recording"
            >
              <Trash2 size={15} className="text-red-500 group-hover:text-red-600" />
            </button>
          </div>
        )}

        {/* Recording controls */}
        <div className="flex flex-col gap-4">
          {recordingState === 'idle' && (
            <button
              onClick={startRecording}
              className="flex items-center justify-center gap-2 w-full py-10 border-2 border-dashed border-gray-300 dark:border-gray-700 rounded-xl hover:border-violet-400 dark:hover:border-violet-600 hover:bg-violet-50/30 dark:hover:bg-violet-900/10 transition-colors text-gray-500 dark:text-gray-400 hover:text-violet-600 dark:hover:text-violet-400"
            >
              <Mic size={20} />
              <span className="text-sm font-medium">Click to record a greeting</span>
            </button>
          )}

          {recordingState === 'recording' && (
            <div className="flex flex-col items-center gap-4 py-6 border-2 border-red-400 rounded-xl bg-red-50/30 dark:bg-red-900/10">
              <div className="flex items-center gap-2">
                <span className="w-3 h-3 rounded-full bg-red-500 animate-pulse" />
                <span className="text-sm font-medium text-red-600 dark:text-red-400">
                  Recording… {timerLabel}
                </span>
              </div>
              <p className="text-xs text-gray-500">Max 60 seconds</p>
              <button
                onClick={stopRecording}
                className="flex items-center gap-2 px-5 py-2 bg-red-600 hover:bg-red-700 text-white rounded-lg text-sm font-medium transition-colors"
              >
                <MicOff size={15} />
                Stop Recording
              </button>
            </div>
          )}

          {recordingState === 'recorded' && audioUrl && hasPendingUpload && (
            <div className="space-y-4">
              <div className="flex items-center gap-3 p-3 bg-gray-50 dark:bg-gray-800 rounded-lg">
                <Play size={15} className="text-violet-600 flex-shrink-0" />
                <span className="text-sm text-gray-700 dark:text-gray-300 flex-1">
                  New recording — {timerLabel}
                </span>
                <audio src={audioUrl} controls className="h-8" preload="auto" />
              </div>

              <div className="flex gap-2">
                <button
                  onClick={uploadRecording}
                  disabled={isUploading}
                  className="flex items-center gap-2 px-4 py-2 bg-violet-600 hover:bg-violet-700 disabled:opacity-50 text-white rounded-lg text-sm font-medium transition-colors"
                >
                  <Upload size={14} />
                  {isUploading ? 'Uploading…' : 'Save Recording'}
                </button>
                <button
                  onClick={() => {
                    // Re-record
                    discardRecording()
                    setRecordingState('idle')
                  }}
                  disabled={isUploading}
                  className="flex items-center gap-2 px-4 py-2 border border-gray-300 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-800 disabled:opacity-50 text-gray-700 dark:text-gray-300 rounded-lg text-sm font-medium transition-colors"
                >
                  <Mic size={14} />
                  Re-record
                </button>
                <button
                  onClick={discardRecording}
                  disabled={isUploading}
                  className="flex items-center gap-2 px-4 py-2 text-red-600 hover:bg-red-50 dark:hover:bg-red-900/20 disabled:opacity-50 rounded-lg text-sm font-medium transition-colors"
                >
                  <Trash2 size={14} />
                  Discard
                </button>
              </div>
            </div>
          )}
        </div>

        {/* Re-record option when saved greeting exists */}
        {savedGreetingUrl && !hasPendingUpload && recordingState !== 'recording' && (
          <button
            onClick={() => {
              discardRecording()
              setRecordingState('idle')
              setTimeout(startRecording, 100)
            }}
            className="flex items-center gap-2 text-sm text-violet-600 dark:text-violet-400 hover:underline"
          >
            <Mic size={14} />
            Record a new greeting (replaces current)
          </button>
        )}
      </div>
    </div>
  )
}
