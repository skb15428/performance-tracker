import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import OpenClaude from '../components/OpenClaude'
import { Badge, Button, Card, EmptyState, ErrorText, Input, Loading, PageHeader, Select } from '../components/ui'
import { api } from '../lib/api'
import { prettyDate } from '../lib/dates'
import type { Goal, TrendSource, TrendSuggestion } from '../lib/types'

function Sources() {
  const qc = useQueryClient()
  const [name, setName] = useState('')
  const [url, setUrl] = useState('')
  const [kind, setKind] = useState<'rss' | 'github'>('rss')
  const { data: sources = [] } = useQuery({ queryKey: ['sources'], queryFn: () => api<TrendSource[]>('/trends/sources') })
  const add = useMutation({
    mutationFn: () => api('/trends/sources', { method: 'POST', json: { name, url, kind } }),
    onSuccess: () => {
      setName('')
      setUrl('')
      qc.invalidateQueries({ queryKey: ['sources'] })
    },
  })
  const remove = useMutation({
    mutationFn: (id: number) => api(`/trends/sources/${id}`, { method: 'DELETE' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['sources'] }),
  })
  return (
    <Card title="Sources" className="mt-8">
      <p className="mb-3 text-xs text-muted">
        Feeds are pulled daily and matched against what you're currently studying. The weekly scan also searches the web for anything the feeds missed.
      </p>
      <ul className="mb-4 space-y-1 text-sm">
        {sources.map((s) => (
          <li key={s.id} className="flex items-center gap-2">
            <Badge>{s.kind}</Badge>
            <span className="flex-1 truncate">{s.name}</span>
            {s.user_id ? (
              <button className="text-xs text-red-500" onClick={() => remove.mutate(s.id)}>
                remove
              </button>
            ) : (
              <span className="text-xs text-muted">default</span>
            )}
          </li>
        ))}
        {!sources.length && <li className="text-muted">Default sources are added on the first daily ingest.</li>}
      </ul>
      <form
        className="grid gap-2 sm:grid-cols-[7rem_1fr_2fr_auto]"
        onSubmit={(e) => {
          e.preventDefault()
          add.mutate()
        }}
      >
        <Select value={kind} onChange={(e) => setKind(e.target.value as 'rss' | 'github')}>
          <option value="rss">RSS/Atom</option>
          <option value="github">GitHub</option>
        </Select>
        <Input required value={name} onChange={(e) => setName(e.target.value)} placeholder="Name" />
        <Input required value={url} onChange={(e) => setUrl(e.target.value)} placeholder={kind === 'rss' ? 'https://blog.example.com/feed.xml' : 'topic:rag'} />
        <Button type="submit" variant="secondary" loading={add.isPending}>
          Add
        </Button>
      </form>
      <ErrorText error={add.error} />
    </Card>
  )
}

export default function Trends() {
  const qc = useQueryClient()
  const { data: goals = [] } = useQuery({ queryKey: ['goals'], queryFn: () => api<Goal[]>('/goals') })
  const { data: items, isLoading } = useQuery({ queryKey: ['trends'], queryFn: () => api<TrendSuggestion[]>('/trends') })
  const act = useMutation({
    mutationFn: ({ id, action }: { id: number; action: 'add' | 'dismiss' }) => api(`/trends/${id}/${action}`, { method: 'POST' }),
    onSuccess: () => qc.invalidateQueries(),
  })
  const goalTitle = (id: number) => goals.find((g) => g.id === id)?.title ?? ''

  return (
    <>
      <PageHeader
        title="What's new"
        subtitle="New techniques, tools and papers relevant to what you're learning right now."
        action={<OpenClaude message="What's new for my goals?">Check what's new in Claude</OpenClaude>}
      />
      <ErrorText error={act.error} />
      {isLoading && <Loading />}
      {items && items.length === 0 && (
        <EmptyState title="Nothing to review">
          Ask Claude what's new for a goal: it checks the feeds and the web, and suggestions show up here.
        </EmptyState>
      )}
      <div className="space-y-3">
        {items?.map((s) => (
          <Card key={s.id}>
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0 flex-1">
                <div className="mb-1 flex flex-wrap items-center gap-2">
                  <h3 className="font-display text-2xl leading-tight">{s.title}</h3>
                  <Badge tone="brand">{goalTitle(s.goal_id)}</Badge>
                  <Badge>~{s.est_hours}h</Badge>
                </div>
                <p className="text-sm text-muted">{s.why_relevant}</p>
                <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-sm">
                  {s.links.map((l, i) => (
                    <a key={i} href={l.url} target="_blank" rel="noreferrer" className="text-accent-ink hover:underline">
                      {l.title || new URL(l.url).hostname} ↗
                    </a>
                  ))}
                </div>
                <p className="mt-2 text-xs text-muted">Found {prettyDate(s.created_at)}</p>
              </div>
              <div className="flex gap-2">
                <Button variant="ghost" size="sm" onClick={() => act.mutate({ id: s.id, action: 'dismiss' })}>
                  Dismiss
                </Button>
                <Button size="sm" loading={act.isPending} onClick={() => act.mutate({ id: s.id, action: 'add' })}>
                  Add to my roadmap
                </Button>
              </div>
            </div>
          </Card>
        ))}
      </div>
      <Sources />
    </>
  )
}
