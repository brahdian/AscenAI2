'use client'

import { useEffect, useState, useCallback } from 'react'
import { useParams } from 'next/navigation'
import Link from 'next/link'
import { documentsApi, agentsApi } from '@/lib/api'
import { FileText, Upload, Trash2, CheckCircle, Clock, AlertCircle, ChevronRight, Edit2, Plus, X, RefreshCw } from 'lucide-react'
import toast from 'react-hot-toast'

interface Doc {
  id: string
  name: string
  file_type: string
  file_size_bytes: number
  chunk_count: number
  status: 'draft' | 'published' | 'processing' | 'ready' | 'failed'
  content?: string
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
    draft: { icon: FileText, label: 'Draft', cls: 'bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300' },
    published: { icon: CheckCircle, label: 'Published', cls: 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400' },
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
  const [showEditor, setShowEditor] = useState(false)
  const [editingDoc, setEditingDoc] = useState<Doc | null>(null)

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
    if (file.size > 5 * 1024 * 1024) {
      setError('File must be under 5 MB.')
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

  const saveTextDoc = async (data: { name: string; content: string; status: 'draft' | 'published' }) => {
    try {
      if (editingDoc) {
        await documentsApi.updateText(agentId, editingDoc.id, data)
        toast.success("Document updated")
      } else {
        await documentsApi.createText(agentId, data)
        toast.success("Document created")
      }
      setShowEditor(false)
      setEditingDoc(null)
      load()
    } catch (e: any) {
      toast.error(e?.response?.data?.detail || "Failed to save document")
    }
  }

  const retry = async (doc: Doc) => {
    try {
      setLoading(true)
      await documentsApi.retryIndexing(agentId, doc.id)
      toast.success("Re-indexing started")
      load()
    } catch (e: any) {
      toast.error(e?.response?.data?.detail || "Failed to retry")
    } finally {
      setLoading(false)
    }
  }

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault()
    setDrag(false)
    const file = e.dataTransfer.files[0]
    if (file) upload(file)
  }

  return (
    <div className="p-8 w-full">
      <div className="mb-6">

        <h1 className="text-2xl font-bold text-gray-900 dark:text-white flex items-center gap-2">
          <FileText size={24} className="text-violet-500" />
          Knowledge Base
        </h1>
        <p className="text-gray-500 mt-1">
          Upload documents or author text rules for this agent's knowledge base.
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
        
        <div className="mt-4 flex items-center justify-center gap-3">
          <div className="h-px bg-gray-200 dark:bg-gray-700 w-16"></div>
          <span className="text-xs text-gray-400">OR</span>
          <div className="h-px bg-gray-200 dark:bg-gray-700 w-16"></div>
        </div>
        
        <button
          onClick={() => {
            setEditingDoc(null)
            setShowEditor(true)
          }}
          className="mt-4 cursor-pointer inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700"
        >
          <Plus size={14} />
          Author Text Document
        </button>

        <p className="text-xs text-gray-400 mt-3">PDF, TXT, MD, DOCX — max 5 MB</p>
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
                        <p className="text-xs text-gray-500 uppercase flex items-center gap-1">
                          {d.file_type}
                          {d.status === 'failed' && d.error_message && (
                            <span className="text-[10px] text-red-500 lowercase bg-red-50 px-1 rounded truncate max-w-[150px]" title={d.error_message}>
                              : {d.error_message}
                            </span>
                          )}
                        </p>
                      </div>
                    </div>
                  </td>
                  <td className="px-6 py-4"><StatusBadge status={d.status} /></td>
                  <td className="px-6 py-4 text-right text-sm text-gray-500">{fmtSize(d.file_size_bytes)}</td>
                  <td className="px-6 py-4 text-right text-sm text-gray-500">{d.chunk_count}</td>
                  <td className="px-6 py-4 text-right">
                    <div className="flex items-center justify-end gap-2">
                       {/* Allow editing of txt documents created directly (you can determine by content field or extension, here assuming file_type=txt and status allows it) */}
                      {d.file_type === 'txt' && (d.status === 'draft' || d.status === 'published' || d.status === 'ready') && (
                        <button
                          onClick={() => {
                            setEditingDoc(d)
                            setShowEditor(true)
                          }}
                          className="p-1.5 text-gray-400 hover:text-violet-500 transition-colors"
                          title="Edit Document"
                        >
                          <Edit2 size={14} />
                        </button>
                      )}
                       {d.status === 'failed' && (
                         <button
                           onClick={() => retry(d)}
                           className="p-1.5 text-gray-400 hover:text-green-500 transition-colors"
                           title="Retry Indexing"
                         >
                           <RefreshCw size={14} />
                         </button>
                       )}
                      <button onClick={() => remove(d.id, d.name)} className="p-1.5 text-gray-400 hover:text-red-500 transition-colors">
                        <Trash2 size={14} />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {showEditor && (
        <TextDocumentEditor 
          doc={editingDoc}
          onSave={saveTextDoc}
          onClose={() => {
            setShowEditor(false)
            setEditingDoc(null)
          }}
        />
      )}
    </div>
  )
}

function TextDocumentEditor({ 
  doc, 
  onSave, 
  onClose 
}: { 
  doc: Doc | null, 
  onSave: (d: any) => Promise<void>, 
  onClose: () => void 
}) {
  const [name, setName] = useState(doc?.name || '')
  const [content, setContent] = useState(doc?.content || '')
  const [status, setStatus] = useState<'draft'|'published'>(doc?.status === 'ready' ? 'published' : ((doc?.status as string) || 'draft') as any)

  const [saving, setSaving] = useState(false)

  const handleSave = async () => {
    if (!name.trim() || !content.trim()) return
    setSaving(true)
    await onSave({ name, content, status })
    setSaving(false)
  }

  return (
    <div className="fixed inset-0 z-50 flex">
      <div className="flex-1 bg-black/40 backdrop-blur-sm" onClick={onClose} />
      <div className="w-full max-w-xl bg-white dark:bg-gray-900 shadow-2xl flex flex-col h-full right-0 absolute animation-slide-in">
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200 dark:border-gray-800">
          <h2 className="text-base font-semibold text-gray-900 dark:text-white">
            {doc ? 'Edit Knowledge String' : 'New Knowledge String'}
          </h2>
          <button onClick={onClose} className="p-1.5 text-gray-400 hover:text-gray-600 transition-colors">
            <X size={18} />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-6 space-y-4">
          <div>
            <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
              Document Name
            </label>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Return Policy Fall 2026"
              className="w-full px-3 py-2.5 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm focus:outline-none focus:ring-1 focus:ring-violet-500"
            />
          </div>

          <div className="flex-1 flex flex-col min-h-[300px]">
            <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
              Content (Text)
            </label>
            <textarea
              value={content}
              onChange={(e) => setContent(e.target.value)}
              className="flex-1 w-full px-3 py-2.5 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm focus:outline-none focus:ring-1 focus:ring-violet-500 resize-none font-mono"
              placeholder="Enter the textual knowledge facts here. Variables like {company_name} can be used if they exist in global state."
            />
          </div>
          
          <div>
            <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
              Lifecycle Status
            </label>
            <select
              value={status}
              onChange={(e) => setStatus(e.target.value as any)}
              className="w-full px-3 py-2.5 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-white text-sm focus:outline-none focus:ring-1 focus:ring-violet-500"
            >
              <option value="draft">Draft (Excluded from knowledge base)</option>
              <option value="published">Published (Vectorized and queryable)</option>
            </select>
          </div>
        </div>

        <div className="px-6 py-4 border-t border-gray-200 dark:border-gray-800 flex items-center justify-end gap-3 bg-gray-50 dark:bg-gray-800/50">
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-2 rounded-lg border border-gray-200 dark:border-gray-700 text-sm text-gray-600 dark:text-gray-400 hover:bg-white transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={handleSave}
            disabled={saving || !name.trim() || !content.trim()}
            className="px-5 py-2 rounded-lg bg-gradient-to-r from-violet-600 to-blue-600 text-white text-sm font-medium hover:opacity-90 disabled:opacity-50 transition-opacity"
          >
            {saving ? 'Saving...' : 'Save Document'}
          </button>
        </div>
      </div>
    </div>
  )
}

