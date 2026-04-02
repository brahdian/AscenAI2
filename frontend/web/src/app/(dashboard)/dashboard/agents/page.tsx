'use client'

import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { agentsApi } from '@/lib/api'
import Link from 'next/link'
import toast from 'react-hot-toast'
import { Bot, Plus, Trash2, Edit2, Mic, MicOff, TestTube, BookOpen, Shield } from 'lucide-react'

export default function AgentsPage() {
  const qc = useQueryClient()
  const [testingId, setTestingId] = useState<string | null>(null)
  const [testMsg, setTestMsg] = useState('')
  const [testResult, setTestResult] = useState<string | null>(null)

  const { data: agents, isLoading } = useQuery({
    queryKey: ['agents'],
    queryFn: agentsApi.list,
    staleTime: 30000, // 30s stability
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) => agentsApi.delete(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['agents'] })
      toast.success('Agent removed')
    },
    onError: () => toast.error('Failed to remove agent'),
  })

  const handleDelete = (agent: any) => {
    toast((t) => (
      <div className="flex items-center gap-3">
        <span className="text-sm">Delete <b>{agent.name}</b>?</span>
        <button
          onClick={() => {
            deleteMutation.mutate(agent.id)
            toast.dismiss(t.id)
          }}
          className="px-3 py-1 bg-red-600 text-white text-xs font-bold rounded hover:bg-red-700 transition-colors"
        >
          CONFIRM
        </button>
        <button
          onClick={() => toast.dismiss(t.id)}
          className="px-3 py-1 bg-gray-200 dark:bg-gray-800 text-gray-600 dark:text-gray-400 text-xs font-bold rounded hover:bg-gray-300 dark:hover:bg-gray-700 transition-colors"
        >
          CANCEL
        </button>
      </div>
    ), { duration: 5000, position: 'top-center' })
  }

  const testMutation = useMutation({
    mutationFn: ({ id, message }: { id: string; message: string }) =>
      agentsApi.test(id, message),
    onSuccess: (data) => {
      setTestResult(data.message)
    },
    onError: (err: any) =>
      toast.error(err?.response?.data?.detail || 'Test failed'),
  })

  return (
    <div className="p-8">
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Agents</h1>
          <p className="text-gray-500 dark:text-gray-400 mt-1">
            Manage your AI agents and their configurations.
          </p>
        </div>
        <Link
          href="/dashboard/agents/new"
          className="inline-flex items-center gap-2 px-4 py-2.5 rounded-lg bg-gradient-to-r from-violet-600 to-blue-600 text-white text-sm font-medium hover:opacity-90 transition-opacity"
        >
          <Plus size={16} />
          New agent
        </Link>
      </div>

      {isLoading ? (
        <div className="space-y-3">
          {[1, 2, 3].map((i) => (
            <div
              key={i}
              className="h-24 rounded-xl bg-gray-100 dark:bg-gray-800 animate-pulse"
            />
          ))}
        </div>
      ) : agents?.length === 0 ? (
        <div className="text-center py-16 bg-white dark:bg-gray-900 rounded-xl border border-dashed border-gray-200 dark:border-gray-700">
          <Bot size={40} className="mx-auto text-gray-300 dark:text-gray-600 mb-3" />
          <h3 className="text-gray-900 dark:text-white font-medium">No agents yet</h3>
          <p className="text-gray-500 text-sm mt-1 mb-6">Create your first AI agent to get started.</p>
          <Link
            href="/dashboard/agents/new"
            className="inline-flex items-center gap-2 px-4 py-2.5 rounded-lg bg-violet-600 text-white text-sm font-medium hover:bg-violet-700 transition-colors"
          >
            <Plus size={16} /> Create agent
          </Link>
        </div>
      ) : (
        <div className="space-y-3">
          {agents?.map((agent: any) => (
            <div
              key={agent.id}
              className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 p-5"
            >
              <div className="flex items-start justify-between">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-violet-500/20 to-blue-500/20 flex items-center justify-center">
                    <Bot size={20} className="text-violet-600 dark:text-violet-400" />
                  </div>
                  <div>
                    <h3 className="font-semibold text-gray-900 dark:text-white">
                      {agent.name}
                    </h3>
                    <p className="text-xs text-gray-500 mt-0.5">
                      {agent.business_type} • {agent.language}
                      {agent.voice_enabled ? (
                        <span className="ml-2 inline-flex items-center gap-1 text-green-600">
                          <Mic size={10} /> Voice
                        </span>
                      ) : (
                        <span className="ml-2 inline-flex items-center gap-1 text-gray-400">
                          <MicOff size={10} /> Text only
                        </span>
                      )}
                    </p>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => {
                      setTestingId(testingId === agent.id ? null : agent.id)
                      setTestResult(null)
                      setTestMsg('')
                    }}
                    className="p-2 text-gray-400 hover:text-violet-600 transition-colors"
                    title="Test agent"
                  >
                    <TestTube size={16} />
                  </button>
                  <Link
                    href={`/dashboard/agents/${agent.id}/playbooks`}
                    className="p-2 text-gray-400 hover:text-violet-600 transition-colors"
                    title="Edit Playbook"
                  >
                    <BookOpen size={16} />
                  </Link>
                  <Link
                    href={`/dashboard/agents/${agent.id}/guardrails`}
                    className="p-2 text-gray-400 hover:text-orange-500 transition-colors"
                    title="Edit Guardrails"
                  >
                    <Shield size={16} />
                  </Link>
                  <Link
                    href={`/dashboard/agents/${agent.id}`}
                    className="p-2 text-gray-400 hover:text-blue-600 transition-colors"
                    title="Edit agent"
                  >
                    <Edit2 size={16} />
                  </Link>
                  <div className="flex items-center gap-1">
                    <button
                      onClick={() => handleDelete(agent)}
                      className="p-2 text-gray-400 hover:text-red-500 transition-colors"
                      title="Delete agent"
                    >
                      <Trash2 size={16} />
                    </button>
                  </div>
                </div>
              </div>

              {/* Test panel */}
              {testingId === agent.id && (
                <div className="mt-4 pt-4 border-t border-gray-100 dark:border-gray-800">
                  <div className="flex gap-2">
                    <input
                      value={testMsg}
                      onChange={(e) => setTestMsg(e.target.value)}
                      placeholder="Send a test message…"
                      className="flex-1 px-3 py-2 rounded-lg text-sm bg-gray-50 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 text-gray-900 dark:text-white focus:outline-none focus:ring-1 focus:ring-violet-500"
                      onKeyDown={(e) => {
                        if (e.key === 'Enter' && testMsg.trim()) {
                          testMutation.mutate({ id: agent.id, message: testMsg })
                        }
                      }}
                    />
                    <button
                      onClick={() =>
                        testMsg.trim() &&
                        testMutation.mutate({ id: agent.id, message: testMsg })
                      }
                      disabled={testMutation.isPending}
                      className="px-3 py-2 rounded-lg bg-violet-600 text-white text-sm font-medium hover:bg-violet-700 disabled:opacity-50"
                    >
                      {testMutation.isPending ? '…' : 'Send'}
                    </button>
                  </div>
                  {testResult && (
                    <div className="mt-3 p-3 rounded-lg bg-gray-50 dark:bg-gray-800 text-sm text-gray-700 dark:text-gray-300">
                      <strong className="text-violet-600 dark:text-violet-400">Agent:</strong>{' '}
                      {testResult}
                    </div>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
