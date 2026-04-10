'use client'

import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { feedbackApi, agentsApi, sessionsApi, tenantApi } from '@/lib/api'
import Link from 'next/link'
import { CheckCircle, Trash2, ExternalLink, FileText, MessageSquare } from 'lucide-react'

function truncate(s: string, n = 120) {
  return s.length > n ? s.slice(0, n) + '…' : s
}

function timeAgo(iso: string) {
  const d = new Date(iso)
  const diff = (Date.now() - d.getTime()) / 1000
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
  return `${Math.floor(diff / 86400)}d ago`
}

function ConversationContext({ sessionId }: { sessionId: string }) {
  const { data: detail, isLoading } = useQuery({
    queryKey: ['session-detail', sessionId],
    queryFn: () => sessionsApi.get(sessionId, true),
    staleTime: 60_000,
  })

  if (isLoading) {
    return <div className="mt-3 space-y-2">{[1, 2].map(i => <div key={i} className="h-8 rounded-lg bg-gray-100 dark:bg-gray-800 animate-pulse" />)}</div>
  }

  if (!detail?.messages?.length) {
    return <p className="mt-3 text-xs text-gray-400">No conversation messages available.</p>
  }

  return (
    <div className="mt-3 space-y-2 max-h-64 overflow-y-auto rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-950 p-3">
      {detail.messages.map((msg: any, i: number) => (
        <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
          <div className={`max-w-[80%] px-3 py-1.5 rounded-lg text-xs ${
            msg.role === 'user'
              ? 'bg-blue-500 text-white rounded-br-sm'
              : msg.role === 'assistant'
              ? 'bg-white dark:bg-gray-800 text-gray-800 dark:text-gray-200 border border-gray-200 dark:border-gray-700 rounded-bl-sm'
              : 'bg-amber-50 dark:bg-amber-900/20 text-amber-700 dark:text-amber-300 italic text-center'
          }`}>
            {msg.content}
          </div>
        </div>
      ))}
    </div>
  )
}

export default function CorrectionsPage() {
  const [selectedAgent, setSelectedAgent] = useState<string>('')
  const [expandedContext, setExpandedContext] = useState<string | null>(null)
  const queryClient = useQueryClient()

  const { data: agents } = useQuery({
    queryKey: ['agents'],
    queryFn: agentsApi.list,
  })

  useQuery({
    queryKey: ['current-user'],
    queryFn: async () => {
      try {
        const user = await tenantApi.getMe()
        console.log('Current tenant for corrections:', user)
        return user
      } catch (e) {
        console.log('Current tenant query failed:', e)
        return null
      }
    },
  })

  const agentId = selectedAgent || ''

  const { data: corrections, isLoading, error } = useQuery({
    queryKey: ['corrections', agentId],
    queryFn: async () => {
      const params: Record<string, unknown> = {
        has_correction: true,
        include_messages: true,
        limit: 500,
      }
      if (agentId) {
        params.agent_id = agentId
      }
      console.log('Fetching corrections with params:', params)
      const result = await feedbackApi.list(params)
      console.log('Corrections API response:', result)
      return result
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) => feedbackApi.delete(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['corrections', agentId] })
    },
  })

  return (
    <div className="p-8">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white flex items-center gap-2">
            <CheckCircle size={24} className="text-violet-500" />
            Corrections
          </h1>
          <p className="text-gray-500 dark:text-gray-400 mt-1">
            All corrections added via chat history feedback
          </p>
        </div>

        <select
          value={selectedAgent}
          onChange={(e) => setSelectedAgent(e.target.value)}
          className="px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 text-sm text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-violet-500"
        >
          <option value="">All agents</option>
          {agents?.map((a: any) => (
            <option key={a.id} value={a.id}>
              {a.name}
            </option>
          ))}
        </select>
      </div>

      <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800">
        {isLoading ? (
          <div className="space-y-3 p-6">
            {[1, 2, 3].map((i) => (
              <div key={i} className="h-28 rounded-lg bg-gray-100 dark:bg-gray-800 animate-pulse" />
            ))}
          </div>
        ) : error ? (
          <div className="py-10 text-center text-red-500 text-sm">
            Failed to load corrections: {error instanceof Error ? error.message : 'Unknown error'}
          </div>
        ) : !corrections?.length ? (
          <div className="py-10 text-center text-gray-400 text-sm">
            No corrections yet — add corrections from the Chat History page
          </div>
        ) : (
          <div className="divide-y divide-gray-100 dark:divide-gray-800">
            {corrections.map((fb: any) => {
              const agent = agents?.find((a: any) => a.id === fb.agent_id)
              return (
                <div key={fb.id} className="p-5 hover:bg-gray-50 dark:hover:bg-gray-800/50 transition-colors">
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex-1 min-w-0 space-y-3">
                      <div className="flex items-center gap-2">
                        <span className="text-xs font-medium px-2 py-0.5 rounded-full bg-violet-100 dark:bg-violet-900/30 text-violet-700 dark:text-violet-300">
                          Correction
                        </span>
                        {agent && (
                          <span className="text-xs px-2 py-0.5 rounded-full bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-400">
                            {agent.name}
                          </span>
                        )}
                        <span className="text-xs text-gray-400">{timeAgo(fb.created_at)}</span>
                      </div>

                      {fb.user_message && (
                        <div>
                          <p className="text-xs font-medium text-gray-500 mb-0.5">Original question</p>
                          <p className="text-sm text-gray-700 dark:text-gray-300">
                            {truncate(fb.user_message)}
                          </p>
                        </div>
                      )}

                      {fb.agent_response && (
                        <div>
                          <p className="text-xs font-medium text-red-500 mb-0.5">Original response</p>
                          <p className="text-sm text-gray-500 dark:text-gray-400 line-through opacity-70">
                            {truncate(fb.agent_response)}
                          </p>
                        </div>
                      )}

                      <div>
                        <p className="text-xs font-medium text-green-600 dark:text-green-400 mb-0.5">
                          Corrected response
                        </p>
                        <p className="text-sm text-gray-900 dark:text-white font-medium">
                          {truncate(fb.ideal_response)}
                        </p>
                      </div>

                      {fb.rag_documents?.length > 0 && (
                        <div>
                          <p className="text-xs font-medium text-gray-500 mb-1 flex items-center gap-1">
                            <FileText size={12} />
                            RAG Documents
                          </p>
                          <div className="flex flex-wrap gap-1">
                            {fb.rag_documents.map((doc: string, i: number) => (
                              <span key={i} className="text-xs px-2 py-0.5 rounded-full bg-blue-50 dark:bg-blue-900/20 text-blue-600 dark:text-blue-400 border border-blue-200 dark:border-blue-800">
                                {doc}
                              </span>
                            ))}
                          </div>
                        </div>
                      )}

                      {fb.session_id && expandedContext === fb.id && (
                        <ConversationContext sessionId={fb.session_id} />
                      )}
                    </div>

                    <div className="flex flex-col gap-2 shrink-0">
                      {fb.session_id && (
                        <button
                          onClick={() => setExpandedContext(expandedContext === fb.id ? null : fb.id)}
                          className="flex items-center gap-1 text-xs text-violet-600 dark:text-violet-400 hover:underline"
                        >
                          <MessageSquare size={12} />
                          {expandedContext === fb.id ? 'Hide context' : 'View context'}
                        </button>
                      )}
                      <Link
                        href={`/dashboard/sessions?highlight=${fb.session_id}`}
                        className="flex items-center gap-1 text-xs text-violet-600 dark:text-violet-400 hover:underline"
                      >
                        <ExternalLink size={12} />
                        View in History
                      </Link>
                      <button
                        onClick={() => {
                          if (confirm('Delete this correction?')) {
                            deleteMutation.mutate(fb.id)
                          }
                        }}
                        disabled={deleteMutation.isPending}
                        className="flex items-center gap-1 text-xs text-red-600 dark:text-red-400 hover:underline disabled:opacity-50"
                      >
                        <Trash2 size={12} />
                        Delete
                      </button>
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}
