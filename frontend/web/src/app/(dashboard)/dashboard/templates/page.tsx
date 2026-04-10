import { redirect } from 'next/navigation'

// Template selection is now part of the new-agent flow.
export default function TemplatesPage() {
  redirect('/dashboard/agents/new')
}
