'use client'

import { useEffect, useState, useCallback } from 'react'
import { useParams } from 'next/navigation'
import Link from 'next/link'
import { documentsApi, agentsApi } from '@/lib/api'
import { FileText, Upload, Trash2, ArrowLeft, CheckCircle, Clock, AlertCircle } from 'lucide-react'

interface Doc {
  id: string
  name: string
  file_type: string
  file_size_bytes: number
  chunk_count: number
  status: 'processing' | 'ready' | 'failed'
  error_message?: string
  created_at: string
}

const fmtSize = (bytes: number) => {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

const StatusBadge = ({ status }: { status: Doc['status'] }) => {
  const map = {
    processing: { icon: Clock, label: 'Processing', cls: 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400' },
    ready: { icon: CheckCircle, label: 'Ready', cls: 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400' },
    failed: { icon: AlertCircle, label: 'Failed', cls: 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400' },
  }
  const { icon: Icon, label, cls } = map[status]
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium ${cls}`}>
      <Icon size={10} />
      {label}
    </span>
  )
}

export default function DocumentsPage() {
  const { id: agentId } = useParams<{ id: string }>()
  const [docs, setDocs] = useState<Doc[]>([])
  const [agentName, setAgentName] = useState('')
  const [loading, setLoading] = useState(true)
  const [uploading, setUploading] = useState(false)
  const [drag, setDrag] = useState(false)
  const [error, setError] = useState('')

  const load = useCallback(() => {
    Promise.all([
      documentsApi.list(agentId),
      agentsApi.get(agentId).catch(() => ({ name: '' })),
    ]).then(([d, a]) => {
      setDocs(d)
      setAgentName((a as any).name || '')
    }).catch(() => setError('Failed to load documents'))
      .finally(() => setLoading(false))
  }, [agentId])

  useEffect(() => { load() }, [load])

  const upload = async (file: File) => {
    const allowed = ['application/pdf', 'text/plain', 'text/markdown', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document']
    if (!allowed.includes(file.type) && !file.name.endsWith('.md') && !file.name.endsWith('.txt')) {
      setError('Only PDF, TXT, Markdown (.md), and Word (.docx) files are supported.')
      return
    }
    if (file.size > 10 * 1024 * 1024) {
      setError('File must be under 10 MB.')
      return
    }
    setUploading(true)
    setError('')
    try {
      await documentsApi.upload(agentId, file)
      load()
    } catch (e: any) {
      setError(e?.response?.data?.detail || 'Upload failed')
    } finally {
      setUploading(false)
    }
  }

  const remove = async (docId: string, name: string) => {
    if (!confirm(`Delete "${name}"? This will remove it from the knowledge base.`)) return
    try {
      await documentsApi.delete(agentId, docId)
      load()
    } catch {
      setError('Failed to delete document')
    }
  }

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault()
    setDrag(false)
    const file = e.dataTransfer.files[0]
    if (file) upload(file)
  }

  return (
    <div className="p-8 max-w-3xl mx-auto">
      <div className="mb-6">
        <Link href={`/dashboard/agents/${agentId}`} className="flex items-center gap-1 text-sm text-gray-500 hover:text-gray-700 dark:hover:text-gray-300 mb-4">
          <ArrowLeft size={14} />
          Back to {agentName || 'Agent'}
        </Link>
        <h1 className="text-2xl font-bold text-gray-900 dark:text-white flex items-center gap-2">
          <FileText size={24} className="text-violet-500" />
          Knowledge Base
        </h1>
        <p className="text-gray-500 mt-1">
          Upload documents your agent references when answering questions. Supports PDF, TXT, Markdown, and Word up to 10 MB.
        </p>
      </div>

      {error && (
        <div className="mb-4 p-3 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg text-sm text-red-700 dark:text-red-400">
          {error}
        </div>
      )}

      {/* Drop zone */}
      <div
        onDragOver={(e) => { e.preventDefault(); setDrag(true) }}
        onDragLeave={() => setDrag(false)}
        onDrop={onDrop}
        className={`border-2 border-dashed rounded-xl p-8 text-center mb-6 transition-colors ${
          drag ? 'border-violet-400 bg-violet-50 dark:bg-violet-900/20' : 'border-gray-200 dark:border-gray-700'
        }`}
      >
        <Upload size={32} className="mx-auto mb-3 text-gray-400" />
        <p className="text-sm text-gray-600 dark:text-gray-400 mb-3">
          Drag and drop a file here, or
        </p>
        <label className={`cursor-pointer inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
          uploading ? 'bg-gray-100 text-gray-400 cursor-not-allowed' : 'bg-violet-600 hover:bg-violet-700 text-white'
        }`}>
          <Upload size={14} />
          {uploading ? 'Uploading…' : 'Select File'}
          <input
            type="file"
            accept=".pdf,.txt,.md,.docx"
            disabled={uploading}
            onChange={(e) => { if (e.target.files?.[0]) upload(e.target.files[0]) }}
            className="hidden"
          />
        </label>
        <p className="text-xs text-gray-400 mt-2">PDF, TXT, MD, DOCX — max 10 MB</p>
      </div>

      {/* Documents list */}
      <div className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800">
        {loading ? (
          <div className="p-8 text-center text-gray-500">Loading documents…</div>
        ) : docs.length === 0 ? (
          <div className="p-8 text-center">
            <FileText size={32} className="mx-auto mb-3 text-gray-300" />
            <p className="text-gray-500 text-sm">No documents uploaded yet.</p>
          </div>
        ) : (
          <table className="w-full">
            <thead>
              <tr className="border-b border-gray-100 dark:border-gray-800">
                <th className="text-left px-6 py-3 text-xs font-medium text-gray-500 uppercase">Document</th>
                <th className="text-left px-6 py-3 text-xs font-medium text-gray-500 uppercase">Status</th>
                <th className="text-right px-6 py-3 text-xs font-medium text-gray-500 uppercase">Size</th>
                <th className="text-right px-6 py-3 text-xs font-medium text-gray-500 uppercase">Chunks</th>
                <th className="px-6 py-3" />
              </tr>
            </thead>
            <tbody>
              {docs.map((d) => (
                <tr key={d.id} className="border-b border-gray-50 dark:border-gray-800 last:border-0 hover:bg-gray-50 dark:hover:bg-gray-800/30">
                  <td className="px-6 py-4">
                    <div className="flex items-center gap-3">
                      <FileText size={16} className="text-gray-400 flex-shrink-0" />
                      <div>
                        <p className="text-sm font-medium text-gray-900 dark:text-white truncate max-w-[200px]">{d.name}</p>
                        <p className="text-xs text-gray-500 uppercase">{d.file_type}</p>
                      </div>
                    </div>
                  </td>
                  <td className="px-6 py-4"><StatusBadge status={d.status} /></td>
                  <td className="px-6 py-4 text-right text-sm text-gray-500">{fmtSize(d.file_size_bytes)}</td>
                  <td className="px-6 py-4 text-right text-sm text-gray-500">{d.chunk_count}</td>
                  <td className="px-6 py-4 text-right">
                    <button onClick={() => remove(d.id, d.name)} className="p-1.5 text-gray-400 hover:text-red-500 transition-colors">
                      <Trash2 size={14} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
