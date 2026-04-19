import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { feedbackApi, agentsApi, sessionsApi, learningApi, tenantApi } from '@/lib/api'
import Link from 'next/link'
import { CheckCircle, Trash2, ExternalLink, FileText, MessageSquare, Lightbulb, AlertTriangle, XCircle, Sparkles } from 'lucide-react'
import { FeedbackModal } from '@/components/FeedbackModal'

function truncate(s: string, n = 120) {
  return s?.length > n ? s.slice(0, n) + '…' : s
}

function timeAgo(iso: string) {
  try {
    const d = new Date(iso)
    const diff = (Date.now() - d.getTime()) / 1000
    if (diff < 3600) return `${Math.floor(Math.max(0, diff) / 60)}m ago`
    if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
    return `${Math.floor(diff / 86400)}d ago`
  } catch (e) {
    return 'unknown'
  }
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

export default function LearningDashboard() {
  const [selectedAgent, setSelectedAgent] = useState<string>('')
  const [activeTab, setActiveTab] = useState<'corrections' | 'insights'>('corrections')
  const [expandedContext, setExpandedContext] = useState<string | null>(null)
  
  // Promotion / Feedback Modal State
  const [promotingMessage, setPromotingMessage] = useState<any>(null)
  const [promotingSessionId, setPromotingSessionId] = useState<string>('')
  
  const queryClient = useQueryClient()

  const { data: agents } = useQuery({
    queryKey: ['agents'],
    queryFn: agentsApi.list,
  })

  const agentId = selectedAgent || ''

  const { data: corrections, isLoading: isLoadingCorrections } = useQuery({
    queryKey: ['corrections', agentId],
    queryFn: () => feedbackApi.list({
      has_correction: true,
      include_messages: true,
      agent_id: agentId || undefined,
      limit: 100,
    }),
  })

  const { data: insights, isLoading: isLoadingInsights } = useQuery({
    queryKey: ['learning-insights', agentId],
    queryFn: () => learningApi.getInsights(agentId),
    enabled: !!agentId,
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) => feedbackApi.delete(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['corrections', agentId] })
    },
  })

  const openPromotion = (item: any) => {
    setPromotingMessage({
      id: item.message_id,
      content: item.agent_response || item.user_message || '...',
      feedback: item.feedback_id ? { id: item.feedback_id } : null
    })
    setPromotingSessionId(item.session_id)
  }

  return (
    <div className="p-8 max-w-7xl mx-auto">
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 mb-8">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white flex items-center gap-2">
            <Lightbulb size={26} className="text-amber-500" />
            Learning Center
          </h1>
          <p className="text-gray-500 dark:text-gray-400 mt-1">
            Review corrections and discover knowledge gaps to improve your agent.
          </p>
        </div>

        <div className="flex items-center gap-3">
          <select
            value={selectedAgent}
            onChange={(e) => setSelectedAgent(e.target.value)}
            className="px-4 py-2.5 rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 text-sm text-gray-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-violet-500 shadow-sm transition-all"
          >
            <option value="">Select an agent to see insights</option>
            {agents?.map((a: any) => (
              <option key={a.id} value={a.id}>{a.name}</option>
            ))}
          </select>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 p-1 bg-gray-100 dark:bg-gray-800/50 rounded-2xl w-fit mb-6">
        <button
          onClick={() => setActiveTab('corrections')}
          className={`px-6 py-2 rounded-xl text-sm font-medium transition-all ${
            activeTab === 'corrections'
              ? 'bg-white dark:bg-gray-700 text-violet-600 dark:text-violet-400 shadow-sm'
              : 'text-gray-500 hover:text-gray-700 dark:hover:text-gray-300'
          }`}
        >
          Active Corrections ({corrections?.length ?? 0})
        </button>
        <button
          onClick={() => setActiveTab('insights')}
          className={`px-6 py-2 rounded-xl text-sm font-medium transition-all ${
            activeTab === 'insights'
              ? 'bg-white dark:bg-gray-700 text-violet-600 dark:text-violet-400 shadow-sm'
              : 'text-gray-500 hover:text-gray-700 dark:hover:text-gray-300'
          }`}
        >
          Learning Insights
        </button>
      </div>

      {activeTab === 'corrections' ? (
        <div className="grid gap-4">
          {isLoadingCorrections ? (
            <div className="space-y-4">
              {[1, 2, 3].map((i) => (
                <div key={i} className="h-32 rounded-2xl bg-white dark:bg-gray-800 animate-pulse border border-gray-100 dark:border-gray-700" />
              ))}
            </div>
          ) : !corrections?.length ? (
            <div className="py-20 text-center bg-white dark:bg-gray-900 rounded-3xl border border-dashed border-gray-200 dark:border-gray-800">
              <Sparkles size={40} className="mx-auto text-gray-300 mb-4" />
              <p className="text-gray-500 dark:text-gray-400">No corrections yet. Operators can add corrections from the Chat History page.</p>
            </div>
          ) : (
            corrections.map((fb: any) => (
              <div key={fb.id} className="bg-white dark:bg-gray-900 p-6 rounded-2xl border border-gray-100 dark:border-gray-800 shadow-sm hover:shadow-md transition-all group">
                <div className="flex items-start justify-between gap-6">
                  <div className="flex-1 space-y-4">
                    <div className="flex items-center gap-3">
                      <span className="text-[10px] font-bold uppercase tracking-widest px-2 py-0.5 rounded-md bg-violet-100 dark:bg-violet-900/30 text-violet-700 dark:text-violet-300">
                        Correction
                      </span>
                      <span className="text-xs text-gray-400 font-medium">{timeAgo(fb.created_at)}</span>
                    </div>

                    <div className="grid md:grid-cols-2 gap-6">
                      <div className="space-y-2">
                        <p className="text-[10px] font-bold text-gray-400 uppercase tracking-wider">User Question</p>
                        <p className="text-sm text-gray-700 dark:text-gray-300 italic">"{fb.user_message}"</p>
                      </div>
                      <div className="space-y-2">
                        <p className="text-[10px] font-bold text-green-500 uppercase tracking-wider">Ideal Response</p>
                        <p className="text-sm text-gray-900 dark:text-white font-medium leading-relaxed">{fb.ideal_response}</p>
                      </div>
                    </div>

                    {expandedContext === fb.id && fb.session_id && (
                      <ConversationContext sessionId={fb.session_id} />
                    )}
                  </div>

                  <div className="flex flex-col gap-3 shrink-0 opacity-0 group-hover:opacity-100 transition-opacity">
                    <button
                      onClick={() => setExpandedContext(expandedContext === fb.id ? null : fb.id)}
                      className="p-2 text-gray-400 hover:text-violet-500 hover:bg-violet-50 dark:hover:bg-violet-900/20 rounded-lg transition-all"
                      title="View Conversation Context"
                    >
                      <MessageSquare size={18} />
                    </button>
                    <Link
                      href={`/dashboard/sessions?highlight=${fb.session_id}`}
                      className="p-2 text-gray-400 hover:text-blue-500 hover:bg-blue-50 dark:hover:bg-blue-900/20 rounded-lg transition-all"
                      title="Open in Chat History"
                    >
                      <ExternalLink size={18} />
                    </Link>
                    <button
                      onClick={() => confirm('Delete this correction?') && deleteMutation.mutate(fb.id)}
                      className="p-2 text-gray-400 hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-900/20 rounded-lg transition-all"
                      title="Delete Correction"
                    >
                      <Trash2 size={18} />
                    </button>
                  </div>
                </div>
              </div>
            ))
          )}
        </div>
      ) : (
        <div className="space-y-8">
          {!agentId ? (
            <div className="py-20 text-center bg-white dark:bg-gray-900 rounded-3xl border border-dashed border-gray-200 dark:border-gray-800">
              <AlertTriangle size={40} className="mx-auto text-amber-300 mb-4" />
              <p className="text-gray-500 dark:text-gray-400">Select an agent above to see detailed learning insights.</p>
            </div>
          ) : isLoadingInsights ? (
            <div className="grid md:grid-cols-2 gap-6">
               {[1, 2, 3, 4].map(i => <div key={i} className="h-40 rounded-3xl bg-white dark:bg-gray-800 animate-pulse border border-gray-100 dark:border-gray-700" />)}
            </div>
          ) : (
            <div className="space-y-10">
              {/* Knowledge Gaps */}
              <section>
                <div className="flex items-center gap-2 mb-4">
                  <XCircle size={20} className="text-red-500" />
                  <h2 className="text-lg font-bold text-gray-900 dark:text-white">Knowledge Gaps ({insights?.total_gaps ?? 0})</h2>
                </div>
                {!insights?.knowledge_gaps?.length ? (
                  <p className="text-sm text-gray-500 py-6 text-center bg-gray-50 dark:bg-gray-800/30 rounded-2xl">No gaps detected. Your agent is handling common queries well!</p>
                ) : (
                  <div className="grid md:grid-cols-2 gap-4">
                    {insights.knowledge_gaps.map((item: any) => (
                      <div key={item.message_id} className="bg-white dark:bg-gray-900 p-5 rounded-2xl border border-gray-100 dark:border-gray-800 shadow-sm">
                         <div className="flex justify-between items-start mb-3">
                           <span className="text-[10px] font-bold text-gray-400 uppercase tracking-widest">{timeAgo(item.created_at)}</span>
                           <button 
                             onClick={() => openPromotion(item)}
                             className="text-xs font-bold text-violet-600 dark:text-violet-400 hover:underline"
                           >
                             Fix this
                           </button>
                         </div>
                         <p className="text-sm text-gray-600 dark:text-gray-400 mb-2 italic">"{truncate(item.user_message)}"</p>
                         <p className="text-xs text-red-500 bg-red-50 dark:bg-red-900/20 px-3 py-2 rounded-lg line-clamp-2">
                           {item.agent_response}
                         </p>
                      </div>
                    ))}
                  </div>
                )}
              </section>

              {/* Guardrail Triggers */}
              <section>
                <div className="flex items-center gap-2 mb-4">
                  <AlertTriangle size={20} className="text-amber-500" />
                  <h2 className="text-lg font-bold text-gray-900 dark:text-white">Guardrail Triggers ({insights?.total_triggers ?? 0})</h2>
                </div>
                {!insights?.guardrail_triggers?.length ? (
                  <p className="text-sm text-gray-500 py-6 text-center bg-gray-50 dark:bg-gray-800/30 rounded-2xl">No recent guardrail violations.</p>
                ) : (
                  <div className="grid md:grid-cols-2 gap-4">
                    {insights.guardrail_triggers.map((item: any) => (
                      <div key={item.message_id} className="bg-white dark:bg-gray-900 p-5 rounded-2xl border border-gray-100 dark:border-gray-800 shadow-sm">
                         <div className="flex justify-between items-start mb-3">
                           <span className="text-[10px] font-bold text-amber-500 uppercase tracking-widest">{item.trigger_reason}</span>
                           <span className="text-[10px] text-gray-400 uppercase tracking-widest">{timeAgo(item.created_at)}</span>
                         </div>
                         <p className="text-sm text-gray-600 dark:text-gray-400 italic">"{item.user_message}"</p>
                      </div>
                    ))}
                  </div>
                )}
              </section>

              {/* Suggested Training */}
              <section>
                <div className="flex items-center gap-2 mb-4">
                  <Sparkles size={20} className="text-green-500" />
                  <h2 className="text-lg font-bold text-gray-900 dark:text-white">Suggested Training</h2>
                </div>
                {!insights?.suggested_training_pairs?.length ? (
                  <p className="text-sm text-gray-500 py-6 text-center bg-gray-50 dark:bg-gray-800/30 rounded-2xl">No strong suggestions yet. Keep rating interactions!</p>
                ) : (
                  <div className="grid md:grid-cols-2 gap-4">
                    {insights.suggested_training_pairs.map((item: any) => (
                      <div key={item.message_id} className="bg-white dark:bg-gray-900 p-5 rounded-2xl border border-gray-100 dark:border-gray-800 shadow-sm border-l-4 border-l-green-400">
                         <div className="flex justify-between items-start mb-3">
                           <div className="flex gap-2">
                             {item.labels.map((l: string) => (
                               <span key={l} className="text-[10px] bg-green-50 dark:bg-green-900/20 text-green-600 dark:text-green-400 px-1.5 py-0.5 rounded uppercase font-bold">{l}</span>
                             ))}
                           </div>
                           <button 
                             onClick={() => openPromotion(item)}
                             className="text-xs font-bold text-violet-600 dark:text-violet-400 hover:underline"
                           >
                             Promote
                           </button>
                         </div>
                         <p className="text-sm text-gray-600 dark:text-gray-400 mb-2 font-medium">Q: "{truncate(item.user_message, 80)}"</p>
                         <p className="text-sm text-gray-900 dark:text-white leading-relaxed">A: {truncate(item.agent_response, 150)}</p>
                      </div>
                    ))}
                  </div>
                )}
              </section>
            </div>
          )}
        </div>
      )}

      {/* Promotion Modal */}
      {promotingMessage && (
        <FeedbackModal
          message={promotingMessage}
          agentId={agentId}
          sessionId={promotingSessionId}
          focusCorrection={true}
          onClose={() => setPromotingMessage(null)}
          onSubmitted={() => {
            queryClient.invalidateQueries({ queryKey: ['corrections', agentId] })
            queryClient.invalidateQueries({ queryKey: ['learning-insights', agentId] })
          }}
        />
      )}
    </div>
  )
}
