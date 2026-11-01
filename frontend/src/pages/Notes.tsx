import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { isValidElement, useDeferredValue, useEffect, useId, useState, type ReactNode } from 'react'
import Markdown from 'react-markdown'
import { Link, useParams } from 'react-router-dom'
import remarkGfm from 'remark-gfm'
import { Badge, Button, Card, EmptyState, ErrorText, Input, Loading, PageHeader } from '../components/ui'
import { api } from '../lib/api'
import { prettyDate } from '../lib/dates'
import type { Note, NoteSummary } from '../lib/types'

function download(note: Note) {
  const url = URL.createObjectURL(new Blob([`# ${note.title}\n\n${note.content}`], { type: 'text/markdown' }))
  const link = document.createElement('a')
  link.href = url
  link.download = `${note.title.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'notes'}.md`
  link.click()
  URL.revokeObjectURL(url)
}

function Diagram({ source }: { source: string }) {
  const id = `diagram-${useId().replace(/[^a-zA-Z0-9]/g, '')}`
  const [svg, setSvg] = useState<string | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    let current = true
    import('mermaid')
      .then(async ({ default: mermaid }) => {
        const dark = window.matchMedia('(prefers-color-scheme: dark)').matches
        mermaid.initialize({ startOnLoad: false, securityLevel: 'strict', theme: dark ? 'dark' : 'default' })
        await mermaid.parse(source)
        const drawn = await mermaid.render(id, source)
        if (current) setSvg(drawn.svg)
      })
      .catch(() => current && setFailed(true))
    return () => {
      current = false
    }
  }, [id, source])

  if (failed) return <pre><code>{source}</code></pre>
  if (!svg) return <p className="text-sm text-muted">Drawing diagram…</p>
  // securityLevel 'strict' has Mermaid clean the SVG before it reaches here
  return <div className="note-diagram" role="img" aria-label="Diagram" dangerouslySetInnerHTML={{ __html: svg }} />
}

function CodeBlock({ children }: { children?: ReactNode }) {
  const code = isValidElement<{ className?: string; children?: ReactNode }>(children) ? children.props : null
  if (code?.className === 'language-mermaid') return <Diagram source={String(code.children).trim()} />
  return <pre>{children}</pre>
}

export function NoteDetail() {
  const id = Number(useParams().id)
  const { data: note, isLoading, error } = useQuery({ queryKey: ['notes', 'one', id], queryFn: () => api<Note>(`/notes/${id}`) })

  if (isLoading) return <Loading />
  if (!note) return <ErrorText error={error ?? 'Note not found'} />

  return (
    <>
      <Link to="/notes" className="text-sm text-muted hover:text-ink">
        ← Notes
      </Link>
      <h1 className="mt-3 font-display text-4xl leading-[1.05] tracking-tight sm:text-5xl">{note.title}</h1>
      <div className="mt-3 mb-6 flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-muted">Updated {prettyDate(note.updated_at.slice(0, 10), { year: 'numeric' })}</p>
        <div className="flex gap-2">
          {note.topic_id && (
            <Link to={`/study/${note.topic_id}`} className="rounded-full bg-surface px-3 py-1.5 text-xs font-medium ring-1 ring-line hover:bg-surface-2">
              Open topic
            </Link>
          )}
          <Button variant="secondary" size="sm" onClick={() => download(note)}>
            Download .md
          </Button>
        </div>
      </div>
      <Card>
        <div className="note-body">
          <Markdown
            remarkPlugins={[remarkGfm]}
            components={{ a: ({ node: _node, ...props }) => <a {...props} target="_blank" rel="noreferrer" />, pre: ({ children }) => <CodeBlock>{children}</CodeBlock> }}
          >
            {note.content}
          </Markdown>
        </div>
      </Card>
    </>
  )
}

export default function Notes() {
  const [search, setSearch] = useState('')
  const q = useDeferredValue(search.trim())
  const { data, isLoading, error } = useQuery({
    queryKey: ['notes', 'search', q],
    queryFn: () => api<NoteSummary[]>(`/notes?q=${encodeURIComponent(q)}`),
    placeholderData: keepPreviousData,
  })

  return (
    <>
      <PageHeader title="Notes" subtitle="Your study notes, one for each topic. Claude writes them after each interview." />
      <Input type="search" aria-label="Search notes" placeholder="Search topics and notes" value={search} onChange={(e) => setSearch(e.target.value)} className="mb-4" />
      {isLoading && <Loading />}
      {error && <ErrorText error={error} />}
      {data?.length === 0 &&
        (q ? (
          <EmptyState title="Nothing found">No note mentions “{q}”.</EmptyState>
        ) : (
          <EmptyState title="No notes yet">Finish an interview on a topic and Claude will write its notes here.</EmptyState>
        ))}
      <ul className="space-y-2">
        {data?.map((n) => (
          <li key={n.id}>
            <Link to={`/notes/${n.id}`} className="block rounded-3xl border border-line bg-surface p-4 transition hover:bg-surface-2">
              <p className="font-medium">{n.title.replace(/^Big picture: /, '')}</p>
              {n.big_picture && <Badge tone="brand" className="mt-1">Big picture</Badge>}
              <p className="mt-1 line-clamp-2 text-sm text-muted">{n.snippet}</p>
            </Link>
          </li>
        ))}
      </ul>
    </>
  )
}
