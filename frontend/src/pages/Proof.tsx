import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { Badge, Card, EmptyState, Loading, PageHeader } from '../components/ui'
import { api } from '../lib/api'
import { prettyDate } from '../lib/dates'
import type { ProofItem } from '../lib/types'

export default function Proof() {
  const { data, isLoading } = useQuery({ queryKey: ['proof'], queryFn: () => api<{ items: ProofItem[] }>('/study/proof') })
  return (
    <>
      <Link to="/goals" className="text-sm text-muted hover:text-ink">
        ← Goals
      </Link>
      <div className="mt-2">
        <PageHeader title="Proof" subtitle="What you can show for your work. Add links from any roadmap step." />
      </div>
      {isLoading && <Loading />}
      {data && data.items.length === 0 && (
        <EmptyState title="Nothing here yet">Finished steps, the topics you've passed and links to your work will collect here.</EmptyState>
      )}
      <div className="space-y-3">
        {data?.items.map((item) => (
          <Card key={item.id} title={item.title} action={item.completed_at ? <Badge tone="green">Done {prettyDate(item.completed_at)}</Badge> : undefined}>
            {item.links.length > 0 && (
              <ul className="space-y-1 text-sm">
                {item.links.map((l, i) => (
                  <li key={i}>
                    <a className="text-accent-ink hover:underline" href={l.url} target="_blank" rel="noreferrer">
                      {l.title || l.url} ↗
                    </a>
                  </li>
                ))}
              </ul>
            )}
            {item.passed_topics.length > 0 && (
              <p className={item.links.length ? 'mt-3 text-sm text-muted' : 'text-sm text-muted'}>
                Passed: {item.passed_topics.join(' · ')}
              </p>
            )}
          </Card>
        ))}
      </div>
    </>
  )
}
