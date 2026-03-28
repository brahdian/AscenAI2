'use client'

import { useState, useEffect } from 'react'
import { useParams } from 'next/navigation'
import Link from 'next/link'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { agentsApi } from '@/lib/api'
import toast from 'react-hot-toast'
import {
  ChevronRight, PhoneCall, MessageSquare, Webhook, Save,
  Info, ExternalLink, AlertCircle, CheckCircle2, XCircle, Loader2,
} from 'lucide-react'

// ─────────────────────────────────────────────────────────────────────────────
// Connector catalogue — display metadata for the UI
// ─────────────────────────────────────────────────────────────────────────────
const CONNECTORS = [
  { id: '',          label: 'None — no live-agent platform',            fields: [] },
  { id: 'webhook',   label: 'Custom Webhook',                           logo: '🔗',
    fields: [
      { key: 'url',    label: 'HTTPS Webhook URL', required: true, placeholder: 'https://your-server.com/escalation' },
      { key: 'secret', label: 'Signing Secret (HMAC-SHA256)', required: false, placeholder: 'optional — verify payload authenticity' },
    ],
  },
  { id: 'hubspot',   label: 'HubSpot',                                  logo: '🟠',
    docs: 'https://developers.hubspot.com/docs/api/crm/tickets',
    fields: [
      { key: 'access_token', label: 'Private App Access Token', required: true, placeholder: 'pat-na1-...' },
      { key: 'pipeline_id',  label: 'Pipeline ID', required: false, placeholder: '0' },
      { key: 'stage_id',     label: 'Stage ID', required: false, placeholder: '1' },
      { key: 'owner_id',     label: 'Owner ID', required: false, placeholder: '' },
    ],
  },
  { id: 'intercom',  label: 'Intercom',                                 logo: '💙',
    docs: 'https://developers.intercom.com/docs/references/rest-api/api.intercom.io/Conversations/',
    fields: [
      { key: 'access_token', label: 'Access Token', required: true, placeholder: 'dG9rO...' },
      { key: 'inbox_id',     label: 'Inbox ID', required: false, placeholder: '' },
      { key: 'admin_id',     label: 'Assign to Admin ID', required: false, placeholder: '' },
    ],
  },
  { id: 'zendesk',   label: 'Zendesk',                                  logo: '🟢',
    docs: 'https://developer.zendesk.com/api-reference/ticketing/tickets/tickets/',
    fields: [
      { key: 'subdomain',  label: 'Subdomain', required: true, placeholder: 'acme (for acme.zendesk.com)' },
      { key: 'email',      label: 'Agent Email', required: true, placeholder: 'agent@company.com' },
      { key: 'api_token',  label: 'API Token', required: true, placeholder: '' },
      { key: 'group_id',   label: 'Group ID', required: false, placeholder: '' },
    ],
  },
  { id: 'freshdesk', label: 'Freshdesk',                                logo: '🩵',
    docs: 'https://developers.freshdesk.com/api/#create_ticket',
    fields: [
      { key: 'subdomain', label: 'Subdomain', required: true, placeholder: 'acme (for acme.freshdesk.com)' },
      { key: 'api_key',   label: 'API Key', required: true, placeholder: '' },
      { key: 'group_id',  label: 'Group ID', required: false, placeholder: '' },
    ],
  },
  { id: 'freshchat', label: 'Freshchat',                                logo: '🔵',
    docs: 'https://developers.freshchat.com/api/#conversations',
    fields: [
      { key: 'api_key',    label: 'API Key', required: true, placeholder: '' },
      { key: 'domain',     label: 'Domain', required: true, placeholder: 'acme.freshchat.com' },
      { key: 'channel_id', label: 'Channel ID', required: false, placeholder: '' },
    ],
  },
  { id: 'livechat',  label: 'LiveChat',                                 logo: '🟡',
    docs: 'https://platform.text.com/docs/messaging/agent-chat-api',
    fields: [
      { key: 'login',   label: 'Agent Login (email)', required: true, placeholder: 'agent@company.com' },
      { key: 'api_key', label: 'API Key', required: true, placeholder: '' },
    ],
  },
  { id: 'zoho_desk', label: 'Zoho Desk',                                logo: '🔴',
    docs: 'https://desk.zoho.com/DeskAPIDocument#Tickets#Tickets_Createaticket',
    fields: [
      { key: 'access_token',  label: 'OAuth Access Token', required: true, placeholder: '' },
      { key: 'org_id',        label: 'Organization ID', required: true, placeholder: '' },
      { key: 'department_id', label: 'Department ID', required: false, placeholder: '' },
      { key: 'tld',           label: 'TLD', required: false, placeholder: 'com (or eu, com.au, in)' },
    ],
  },
  { id: 'helpscout', label: 'Help Scout',                               logo: '🟤',
    docs: 'https://developer.helpscout.com/mailbox-api/endpoints/conversations/create/',
    fields: [
      { key: 'app_id',     label: 'App ID (Client ID)', required: true, placeholder: '' },
      { key: 'app_secret', label: 'App Secret', required: true, placeholder: '' },
      { key: 'mailbox_id', label: 'Mailbox ID', required: true, placeholder: '' },
    ],
  },
  { id: 'crisp',     label: 'Crisp',                                    logo: '🟣',
    docs: 'https://docs.crisp.chat/references/rest-api/v1/#create-a-new-conversation',
    fields: [
      { key: 'website_id',  label: 'Website ID', required: true, placeholder: '' },
      { key: 'identifier',  label: 'Plugin Identifier', required: true, placeholder: '' },
      { key: 'key',         label: 'Plugin Key', required: true, placeholder: '' },
    ],
  },
  { id: 'gorgias',   label: 'Gorgias',                                  logo: '🛍️',
    docs: 'https://developers.gorgias.com/reference/post_api-tickets',
    fields: [
      { key: 'domain',  label: 'Domain', required: true, placeholder: 'acme (for acme.gorgias.com)' },
      { key: 'email',   label: 'Agent Email', required: true, placeholder: '' },
      { key: 'api_key', label: 'API Key', required: true, placeholder: '' },
    ],
  },
  { id: 'reamaze',   label: 'Re:amaze',                                 logo: '🔆',
    docs: 'https://www.reamaze.com/api/post_conversations',
    fields: [
      { key: 'brand',     label: 'Brand (subdomain)', required: true, placeholder: 'acme (for acme.reamaze.com)' },
      { key: 'email',     label: 'Agent Email', required: true, placeholder: '' },
      { key: 'api_token', label: 'API Token', required: true, placeholder: '' },
    ],
  },
  { id: 'liveagent', label: 'LiveAgent',                                logo: '🎧',
    docs: 'https://www.liveagent.com/app/page/api-reference',
    fields: [
      { key: 'account', label: 'Account (subdomain)', required: true, placeholder: 'acme (for acme.ladesk.com)' },
      { key: 'api_key', label: 'API Key', required: true, placeholder: '' },
    ],
  },
  { id: 'front',     label: 'Front',                                    logo: '📨',
    docs: 'https://dev.frontapp.com/reference/import-inbox-message',
    fields: [
      { key: 'api_token', label: 'API Token', required: true, placeholder: '' },
      { key: 'inbox_id',  label: 'Inbox ID', required: true, placeholder: 'inb_xxxxxxxx' },
    ],
  },
  { id: 'tidio',     label: 'Tidio',                                    logo: '💬',
    docs: 'https://developers.tidio.com/',
    fields: [
      { key: 'public_key',  label: 'Public API Key', required: false, placeholder: '' },
      { key: 'private_key', label: 'Private API Key', required: false, placeholder: '' },
      { key: 'webhook_url', label: 'Webhook URL (Tidio Automation bridge)', required: false, placeholder: 'https://...' },
    ],
  },
  { id: 'tawkto',    label: 'tawk.to',                                  logo: '🗨️',
    docs: 'https://www.tawk.to/api/',
    fields: [
      { key: 'webhook_url',  label: 'Webhook/Bridge URL', required: true, placeholder: 'https://your-bridge.com/tawkto' },
      { key: 'property_id',  label: 'Property ID (optional, for reference)', required: false, placeholder: '' },
    ],
  },
  { id: 'comm100',   label: 'Comm100 (Canadian 🍁)',                    logo: '🏢',
    docs: 'https://www.comm100.com/platform/api/',
    fields: [
      { key: 'access_token',  label: 'JWT Access Token', required: true, placeholder: '' },
      { key: 'site_id',       label: 'Site ID', required: true, placeholder: '' },
      { key: 'department_id', label: 'Department ID', required: false, placeholder: '' },
    ],
  },
]

// ─────────────────────────────────────────────────────────────────────────────
// Component
// ─────────────────────────────────────────────────────────────────────────────
export default function EscalationPage() {
  const params = useParams()
  const id = params.id as string
  const qc = useQueryClient()

  const { data: agent, isLoading } = useQuery({
    queryKey: ['agent', id],
    queryFn: () => agentsApi.get(id),
    enabled: !!id,
  })

  // Flatten escalation config into form state
  const [escalateEnabled, setEscalateEnabled] = useState(false)
  const [phone, setPhone] = useState('')
  const [chatEnabled, setChatEnabled] = useState(false)
  const [chatAgentName, setChatAgentName] = useState('')
  const [connectorType, setConnectorType] = useState('')
  const [connectorConfig, setConnectorConfig] = useState<Record<string, string>>({})
  const [saved, setSaved] = useState(false)
  const [testStatus, setTestStatus] = useState<'idle' | 'testing' | 'success' | 'error'>('idle')
  const [testMessage, setTestMessage] = useState('')

  useEffect(() => {
    if (!agent) return
    const ec = agent.escalation_config || {}
    setEscalateEnabled(!!ec.escalate_to_human)
    setPhone(ec.escalation_number || '')
    setChatEnabled(!!ec.chat_enabled)
    setChatAgentName(ec.chat_agent_name || '')
    setConnectorType(ec.connector_type || '')
    setConnectorConfig(ec.connector_config || {})
  }, [agent])

  const selectedConnector = CONNECTORS.find(c => c.id === connectorType) ?? CONNECTORS[0]

  const mutation = useMutation({
    mutationFn: (data: Record<string, unknown>) => agentsApi.update(id, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['agent', id] })
      setSaved(true)
      setTimeout(() => setSaved(false), 2500)
      toast.success('Escalation settings saved')
    },
    onError: () => toast.error('Failed to save'),
  })

  const handleSave = () => {
    const escalation_config: Record<string, unknown> = {
      escalate_to_human: escalateEnabled,
      escalation_number: phone,
      chat_enabled: chatEnabled,
      chat_agent_name: chatAgentName,
      connector_type: connectorType || null,
      connector_config: connectorType ? connectorConfig : {},
    }
    mutation.mutate({ escalation_config })
  }

  const setField = (key: string, value: string) => {
    setTestStatus('idle')
    setTestMessage('')
    setConnectorConfig(prev => ({ ...prev, [key]: value }))
  }

  const handleTestConnection = async () => {
    setTestStatus('testing')
    setTestMessage('')
    try {
      const result = await agentsApi.testEscalationConnector(id)
      if (result.success) {
        setTestStatus('success')
        setTestMessage(result.message || 'Connected successfully')
      } else {
        setTestStatus('error')
        setTestMessage(result.message || 'Connection failed')
      }
    } catch (err: unknown) {
      setTestStatus('error')
      const axiosErr = err as { response?: { data?: { detail?: string } } }
      setTestMessage(axiosErr?.response?.data?.detail || 'Connection test failed')
    }
  }

  // Show the test button only when a connector is selected and at least one required field is filled
  const showTestButton = !!connectorType && selectedConnector.fields &&
    selectedConnector.fields.some(f => f.required && !!connectorConfig[f.key])

  if (isLoading) return <div className="p-8 text-gray-500">Loading…</div>

  return (
    <div className="p-8 max-w-3xl mx-auto">
      {/* Breadcrumb */}
      <nav className="flex items-center gap-1 text-sm text-gray-500 dark:text-gray-400 mb-6">
        <Link href="/dashboard" className="hover:text-gray-700 dark:hover:text-gray-200">Dashboard</Link>
        <ChevronRight size={14} />
        <Link href="/dashboard/agents" className="hover:text-gray-700 dark:hover:text-gray-200">Agents</Link>
        <ChevronRight size={14} />
        <Link href={`/dashboard/agents/${id}`} className="hover:text-gray-700 dark:hover:text-gray-200">{agent?.name}</Link>
        <ChevronRight size={14} />
        <span className="text-gray-900 dark:text-white font-medium">Escalation</span>
      </nav>

      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900 dark:text-white flex items-center gap-2">
          <PhoneCall size={22} className="text-violet-500" />
          Escalation to Human Agent
        </h1>
        <p className="text-gray-500 mt-1 text-sm">
          Configure when and how this agent hands off to a live person.
        </p>
      </div>

      <div className="space-y-5">

        {/* Enable toggle */}
        <section className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 p-5">
          <label className="flex items-center justify-between cursor-pointer">
            <div>
              <p className="font-medium text-gray-900 dark:text-white">Enable human escalation</p>
              <p className="text-xs text-gray-500 mt-0.5">
                When triggered (by keywords, frustration signals, or explicit request) the bot will route to a live agent.
              </p>
            </div>
            <button
              onClick={() => setEscalateEnabled(v => !v)}
              className={`relative w-11 h-6 rounded-full transition-colors ${escalateEnabled ? 'bg-violet-600' : 'bg-gray-300 dark:bg-gray-600'}`}
            >
              <span className={`absolute top-0.5 left-0.5 w-5 h-5 bg-white rounded-full shadow transition-transform ${escalateEnabled ? 'translate-x-5' : ''}`} />
            </button>
          </label>
        </section>

        {escalateEnabled && (
          <>
            {/* Voice / phone */}
            <section className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 p-5 space-y-4">
              <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-300 flex items-center gap-2">
                <PhoneCall size={15} className="text-violet-500" />
                Voice / Phone Transfer
              </h2>
              <div>
                <label className="block text-xs text-gray-500 mb-1">Escalation Phone Number</label>
                <input
                  type="text"
                  value={phone}
                  onChange={e => setPhone(e.target.value)}
                  placeholder="+1 555 123 4567"
                  className="w-full px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-sm text-gray-900 dark:text-white"
                />
                <p className="text-xs text-gray-400 mt-1">
                  Voice calls will transfer to this number. Text/web channels without chat will offer a callback here.
                </p>
              </div>
            </section>

            {/* Chat queue */}
            <section className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 p-5 space-y-4">
              <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-300 flex items-center gap-2">
                <MessageSquare size={15} className="text-violet-500" />
                Live Chat Queue
              </h2>
              <label className="flex items-center gap-3 cursor-pointer">
                <input
                  type="checkbox"
                  checked={chatEnabled}
                  onChange={e => setChatEnabled(e.target.checked)}
                  className="w-4 h-4 accent-violet-600"
                />
                <span className="text-sm text-gray-700 dark:text-gray-300">Route to live chat agent queue</span>
              </label>
              {chatEnabled && (
                <div>
                  <label className="block text-xs text-gray-500 mb-1">Agent Display Name</label>
                  <input
                    type="text"
                    value={chatAgentName}
                    onChange={e => setChatAgentName(e.target.value)}
                    placeholder="Support Team"
                    className="w-full px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-sm text-gray-900 dark:text-white"
                  />
                </div>
              )}
            </section>

            {/* Platform connector */}
            <section className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 p-5 space-y-4">
              <div className="flex items-center justify-between">
                <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-300 flex items-center gap-2">
                  <Webhook size={15} className="text-violet-500" />
                  Live-Agent Platform Connector
                </h2>
                {selectedConnector.docs && (
                  <a
                    href={selectedConnector.docs}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-center gap-1 text-xs text-violet-600 hover:underline"
                  >
                    API docs <ExternalLink size={11} />
                  </a>
                )}
              </div>

              <p className="text-xs text-gray-500">
                When escalation fires, AscenAI will push the conversation transcript to this platform so a live agent sees it immediately.
              </p>

              {/* Platform picker */}
              <div>
                <label className="block text-xs text-gray-500 mb-1">Platform</label>
                <select
                  value={connectorType}
                  onChange={e => {
                    setConnectorType(e.target.value)
                    setConnectorConfig({})
                    setTestStatus('idle')
                    setTestMessage('')
                  }}
                  className="w-full px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-sm text-gray-900 dark:text-white"
                >
                  {CONNECTORS.map(c => (
                    <option key={c.id} value={c.id}>
                      {c.logo ? `${c.logo}  ` : ''}{c.label}
                    </option>
                  ))}
                </select>
              </div>

              {/* Dynamic connector fields */}
              {selectedConnector.fields && selectedConnector.fields.length > 0 && (
                <div className="space-y-3 pt-1">
                  {selectedConnector.fields.map(f => (
                    <div key={f.key}>
                      <label className="block text-xs text-gray-500 mb-1">
                        {f.label}
                        {f.required && <span className="text-red-400 ml-1">*</span>}
                      </label>
                      <input
                        type={f.key.includes('secret') || f.key.includes('token') || f.key.includes('key') ? 'password' : 'text'}
                        value={connectorConfig[f.key] || ''}
                        onChange={e => setField(f.key, e.target.value)}
                        placeholder={f.placeholder || ''}
                        autoComplete="off"
                        className="w-full px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-sm text-gray-900 dark:text-white font-mono"
                      />
                    </div>
                  ))}
                </div>
              )}

              {/* Test Connection */}
              {showTestButton && (
                <div className="flex flex-col gap-2 pt-1">
                  <div className="flex items-center gap-3">
                    <button
                      onClick={handleTestConnection}
                      disabled={testStatus === 'testing'}
                      className="flex items-center gap-2 px-4 py-2 rounded-lg border border-violet-500 text-violet-600 dark:text-violet-400 text-sm font-medium hover:bg-violet-50 dark:hover:bg-violet-900/20 transition-colors disabled:opacity-60"
                    >
                      {testStatus === 'testing'
                        ? <><Loader2 size={14} className="animate-spin" /> Testing…</>
                        : 'Test Connection'
                      }
                    </button>
                    {testStatus === 'success' && (
                      <span className="flex items-center gap-1.5 text-sm text-green-600 dark:text-green-400">
                        <CheckCircle2 size={15} />
                        {testMessage}
                      </span>
                    )}
                    {testStatus === 'error' && (
                      <span className="flex items-center gap-1.5 text-sm text-red-600 dark:text-red-400">
                        <XCircle size={15} />
                        {testMessage}
                      </span>
                    )}
                  </div>
                </div>
              )}

              {connectorType === 'tawkto' && (
                <div className="flex gap-2 p-3 rounded-lg bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800">
                  <AlertCircle size={14} className="text-amber-600 shrink-0 mt-0.5" />
                  <p className="text-xs text-amber-700 dark:text-amber-300">
                    tawk.to does not have a conversation-creation API. Set a webhook URL that your team monitors,
                    or use a Zapier/Make.com bridge that triggers a tawk.to Automation on receipt.
                  </p>
                </div>
              )}

              {connectorType === 'tidio' && (
                <div className="flex gap-2 p-3 rounded-lg bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800">
                  <Info size={14} className="text-blue-600 shrink-0 mt-0.5" />
                  <p className="text-xs text-blue-700 dark:text-blue-300">
                    For best results, set a Webhook URL and create a Tidio Automation that fires when
                    the webhook is received. The connector will also attempt a direct API call if keys are provided.
                  </p>
                </div>
              )}
            </section>
          </>
        )}

        {/* Save */}
        <div className="flex justify-end">
          <button
            onClick={handleSave}
            disabled={mutation.isPending}
            className="flex items-center gap-2 px-5 py-2.5 rounded-lg bg-violet-600 hover:bg-violet-700 text-white text-sm font-medium transition-colors disabled:opacity-60"
          >
            {saved
              ? <><CheckCircle2 size={16} /> Saved</>
              : <><Save size={16} /> {mutation.isPending ? 'Saving…' : 'Save Settings'}</>
            }
          </button>
        </div>
      </div>
    </div>
  )
}
