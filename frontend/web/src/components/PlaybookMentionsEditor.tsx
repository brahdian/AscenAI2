'use client'

import React, { useMemo, useCallback, useEffect, useState } from 'react'
import { MentionsInput, Mention, SuggestionDataItem } from 'react-mentions'

export interface ToolItem {
  name: string
  description?: string
  [key: string]: unknown
}

export interface VariableItem {
  name: string
  scope?: string
  data_type?: string
  [key: string]: unknown
}

export interface DocumentItem {
  id: string
  name?: string
  [key: string]: unknown
}

export interface PlaybookMentionsEditorProps {
  value: string
  onChange: (value: string) => void
  tools?: ToolItem[]
  variables?: VariableItem[]
  documents?: DocumentItem[]
  placeholder?: string
  minRows?: number
  minHeight?: string
}

// Custom styles for react-mentions to match Tailwind
const defaultStyle = {
  control: {
    backgroundColor: '#fff',
    fontSize: 14,
    fontWeight: 'normal',
    lineHeight: '1.5',
    minHeight: 120, // corresponding to minRows=5 approximately
  },
  input: {
    padding: '0.75rem',
    outline: 'none',
    border: '1px solid #e5e7eb',
    borderRadius: '0.5rem',
  },
  '&multiLine': {
    control: {
      fontFamily: 'inherit',
      minHeight: 120,
    },
    highlighter: {
      padding: '0.75rem',
    },
    input: {
      padding: '0.75rem',
    },
  },
  suggestions: {
    list: {
      backgroundColor: 'white',
      border: '1px solid #e5e7eb',
      fontSize: 14,
      borderRadius: '0.5rem',
      boxShadow: '0 4px 6px -1px rgb(0 0 0 / 0.1), 0 2px 4px -2px rgb(0 0 0 / 0.1)',
      overflow: 'hidden',
    },
    item: {
      padding: '8px 12px',
      borderBottom: '1px solid #f3f4f6',
      '&focused': {
        backgroundColor: '#f3e8ff', // violet-100
      },
    },
  },
}

const darkStyle = {
  ...defaultStyle,
  control: { ...defaultStyle.control, backgroundColor: '#111827', color: '#fff' },
  input: { ...defaultStyle.input, border: '1px solid #374151', color: '#fff' },
  suggestions: {
    list: { ...defaultStyle.suggestions.list, backgroundColor: '#1f2937', border: '1px solid #374151' },
    item: {
      ...defaultStyle.suggestions.item,
      borderBottom: '1px solid #374151',
      color: '#fff',
      '&focused': { backgroundColor: '#4c1d95' }, // violet-900
    },
  },
}

export function PlaybookMentionsEditor({
  value,
  onChange,
  tools = [],
  variables = [],
  documents = [],
  placeholder = 'Type instructions... Use $tools: to reference tools, $vars: for variables, $rag: for documents.',
  minHeight = '120px',
}: PlaybookMentionsEditorProps) {
  // Convert tools arrays to SuggestionDataItem format requested by react-mentions
  const toolData: SuggestionDataItem[] = useMemo(() => tools.map((t) => ({
    id: t.name,
    display: `$[tools:${t.name}]`,
    description: t.description || 'Tool',
  })), [tools])

  const varData: SuggestionDataItem[] = useMemo(() => variables.map((v) => ({
    id: v.name,
    display: `$[vars:${v.name}]`,
    description: `[${v.scope === 'local' ? 'Playbook' : 'Global'}] ${v.data_type || 'string'}`,
  })), [variables])

  const docData: SuggestionDataItem[] = useMemo(() => documents.map((d) => ({
    id: d.id, // Or d.name if we want to refer to it by name
    display: `$[rag:${d.name || d.id.substring(0, 8)}]`,
    description: 'Knowledge Document',
  })), [documents])

  // Generic render function for suggestions
  const renderSuggestion = useCallback((
    suggestion: SuggestionDataItem,
    search: string,
    highlightedDisplay: React.ReactNode,
    index: number,
    focused: boolean
  ) => {
    return (
      <div className={`flex flex-col gap-0.5 ${focused ? 'text-violet-900 dark:text-violet-100' : 'text-gray-900 dark:text-gray-100'}`}>
        <span className="font-semibold text-sm">{highlightedDisplay}</span>
        {((suggestion as any).description) && (
          <span className="text-xs text-gray-500 dark:text-gray-400 truncate max-w-[300px]">
            {(suggestion as any).description}
          </span>
        )}
      </div>
    )
  }, [])

  const [isDark, setIsDark] = useState(false)
  useEffect(() => {
    setIsDark(document.documentElement.classList.contains('dark'))
    const observer = new MutationObserver(() => {
      setIsDark(document.documentElement.classList.contains('dark'))
    })
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] })
    return () => observer.disconnect()
  }, [])


  return (
    <div className="relative w-full text-base group" style={{ minHeight }}>
      <MentionsInput
        value={value}
        onChange={(e, newValue) => onChange(newValue)}
        style={isDark ? darkStyle : defaultStyle}
        placeholder={placeholder}
        className="w-full"
        a11ySuggestionsListLabel="Suggested items"
        allowSuggestionsAboveCursor
      >
        <Mention
          trigger="$[tools:"
          data={toolData}
          renderSuggestion={renderSuggestion}
          markup="$[tools:__id__]"
          displayTransform={(id, display) => display}
          style={{
            backgroundColor: isDark ? '#4c1d95' : '#ede9fe', // violet-900 / violet-100
            borderRadius: 4,
            padding: '1px 2px',
          }}
        />
        <Mention
          trigger="$[vars:"
          data={varData}
          renderSuggestion={renderSuggestion}
          markup="$[vars:__id__]"
          displayTransform={(id, display) => display}
          style={{
            backgroundColor: isDark ? '#1e3a8a' : '#dbeafe', // blue-900 / blue-100
            borderRadius: 4,
            padding: '1px 2px',
          }}
        />
        <Mention
          trigger="$[rag:"
          data={docData}
          renderSuggestion={renderSuggestion}
          markup="$[rag:__id__]"
          displayTransform={(id, display) => display}
          style={{
            backgroundColor: isDark ? '#064e3b' : '#d1fae5', // emerald-900 / emerald-100
            borderRadius: 4,
            padding: '1px 2px',
          }}
        />
      </MentionsInput>
    </div>
  )
}
