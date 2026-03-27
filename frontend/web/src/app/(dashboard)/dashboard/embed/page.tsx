'use client'

import { useEffect, useRef, useState } from 'react'
import { agentsApi, apiKeysApi } from '@/lib/api'
import { Code2, Copy, Check, Globe, Package, Terminal, MessageSquare, Eye, RefreshCw } from 'lucide-react'

interface Agent { id: string; name: string }
interface APIKey { id: string; name: string; key_prefix: string; key?: string }

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

export default function EmbedPage() {
  const [agents, setAgents] = useState<Agent[]>([])
  const [keys, setKeys] = useState<APIKey[]>([])
  const [agentId, setAgentId] = useState('')
  const [keyPrefix, setKeyPrefix] = useState('')
  const [activeTab, setActiveTab] = useState<'widget' | 'sdk' | 'api'>('widget')
  const [copied, setCopied] = useState<string | null>(null)
  const [previewKey, setPreviewKey] = useState(0)
  const iframeRef = useRef<HTMLIFrameElement>(null)

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

            {/* Live preview */}
            <div className="rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden">
              <div className="flex items-center justify-between px-4 py-2.5 bg-gray-50 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">
                <div className="flex items-center gap-2 text-sm font-medium text-gray-700 dark:text-gray-300">
                  <Eye size={14} className="text-violet-500" />
                  Live Preview
                </div>
                <button
                  onClick={() => setPreviewKey(k => k + 1)}
                  className="flex items-center gap-1.5 text-xs text-gray-500 hover:text-gray-700 dark:hover:text-gray-300 transition-colors px-2 py-1 rounded-md hover:bg-gray-200 dark:hover:bg-gray-700"
                >
                  <RefreshCw size={12} />
                  Reset
                </button>
              </div>
              <div className="relative bg-[#f8f9ff] dark:bg-gray-900" style={{ height: '360px' }}>
                {agentId && keyPrefix ? (
                  <iframe
                    key={previewKey}
                    ref={iframeRef}
                    title="Widget Preview"
                    className="w-full h-full border-0"
                    sandbox="allow-scripts allow-same-origin allow-forms"
                    srcDoc={`<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8"/>
  <style>
    body { margin: 0; background: #f8f9ff; font-family: sans-serif; }
    .page-mock {
      padding: 40px;
      color: #6b7280;
      font-size: 14px;
      line-height: 1.6;
    }
    h3 { color: #111827; font-size: 18px; margin-bottom: 8px; }
    p { margin-bottom: 12px; }
  </style>
</head>
<body>
  <div class="page-mock">
    <h3>Your website</h3>
    <p>This is how the chat widget will appear on your customers' site. Click the bubble in the bottom-right corner to try it.</p>
    <p>The widget is fully isolated — it won't conflict with your existing styles.</p>
  </div>
  <script>
    window.AscenAI = {
      agentId: '${agentId}',
      apiKey: '${keyPrefix}',
      apiUrl: '${API_URL}',
      title: '${selectedAgent?.name ?? 'Support'}',
      greeting: 'Hi! How can I help you today?',
      theme: { primaryColor: '#7c3aed' },
    };
  </script>
  <script src="${API_URL}/widget/widget.js" defer></script>
</body>
</html>`}
                  />
                ) : (
                  <div className="flex flex-col items-center justify-center h-full gap-3 text-gray-400">
                    <MessageSquare size={36} className="opacity-30" />
                    <p className="text-sm">Select an agent and API key above to preview the widget</p>
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
    </div>
  )
}
