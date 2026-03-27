'use client'

import { useEffect, useState } from 'react'
import { agentsApi, apiKeysApi } from '@/lib/api'
import { Code2, Copy, Check, Globe, Package, Terminal } from 'lucide-react'

interface Agent { id: string; name: string }
interface APIKey { id: string; name: string; key_prefix: string }

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

export default function EmbedPage() {
  const [agents, setAgents] = useState<Agent[]>([])
  const [keys, setKeys] = useState<APIKey[]>([])
  const [agentId, setAgentId] = useState('')
  const [keyPrefix, setKeyPrefix] = useState('')
  const [activeTab, setActiveTab] = useState<'widget' | 'sdk' | 'api'>('widget')
  const [copied, setCopied] = useState<string | null>(null)

  useEffect(() => {
    agentsApi.list().then(setAgents).catch(() => {})
    apiKeysApi.list().then(setKeys).catch(() => {})
  }, [])

  const selectedAgent = agents.find((a) => a.id === agentId)
  const selectedKey = keys.find((k) => k.key_prefix === keyPrefix)

  const widgetSnippet = `<!-- AscenAI Chat Widget -->
<script>
  window.AscenAI = {
    agentId: '${agentId || 'YOUR_AGENT_ID'}',
    apiKey: '${keyPrefix || 'YOUR_API_KEY'}',
    apiUrl: '${API_URL}',
    theme: { primaryColor: '#7c3aed' },
  };
</script>
<script src="${API_URL}/widget/widget.js" defer></script>`

  const sdkUsage = `// AscenAI JavaScript client — copy this into your project
// (npm package @ascenai/sdk coming soon)

const ASCENAI_API = '${API_URL}';
const API_KEY     = '${keyPrefix || 'YOUR_API_KEY'}';
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

  return (
    <div className="p-8 max-w-4xl mx-auto">
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
              value={keyPrefix}
              onChange={(e) => setKeyPrefix(e.target.value)}
              className="w-full px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-sm text-gray-900 dark:text-white"
            >
              <option value="">Select an API key…</option>
              {keys.map((k) => (
                <option key={k.id} value={k.key_prefix}>{k.name} ({k.key_prefix}…)</option>
              ))}
            </select>
          </div>
        </div>
        {(!agentId || !keyPrefix) && (
          <p className="text-xs text-amber-600 dark:text-amber-400 mt-3">
            Select an agent and API key to generate your integration code.
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
            <div className="mt-4 p-4 bg-violet-50 dark:bg-violet-900/20 rounded-lg border border-violet-100 dark:border-violet-800">
              <p className="text-xs text-violet-700 dark:text-violet-300 font-medium mb-1">Widget Preview</p>
              <p className="text-xs text-violet-600 dark:text-violet-400">
                A chat bubble will appear in the bottom-right corner. Visitors can click it to start chatting with <strong>{selectedAgent?.name || 'your agent'}</strong>.
              </p>
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
    </div>
  )
}
