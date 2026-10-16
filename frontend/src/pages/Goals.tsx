import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import OpenClaude from '../components/OpenClaude'
import { Badge, Card, EmptyState, ErrorText, Loading, PageHeader, ProgressBar, TimelineBadge } from '../components/ui'
import { api } from '../lib/api'
import { prettyDate } from '../lib/dates'
import type { Goal } from '../lib/types'


export function intakeLabel(goal: Goal) {
  if (goal.intake_status === 'interviewing') return <Badge tone="amber">Coach interview</Badge>
  if (goal.intake_status === 'roadmap_proposed') return <Badge tone="brand">Roadmap ready to review</Badge>
  if (goal.intake_status === 'commitment_pending') return <Badge tone="amber">Agree daily plan</Badge>
  return <TimelineBadge timeline={goal.timeline} />
}

export default function Goals() {
  const { data: goals, isLoading, error } = useQuery({ queryKey: ['goals'], queryFn: () => api<Goal[]>('/goals') })

  return (
    <>
      <PageHeader
        title="Goals"
        subtitle="Goals are set up with your coach in Claude: the exact goal, a roadmap, and the daily routine."
        action={<OpenClaude message="New goal: ">+ New goal in Claude</OpenClaude>}
      />
      {isLoading && <Loading />}
      <ErrorText error={error} />
      {goals && goals.length === 0 && (
        <EmptyState title="No goals yet">
          Start with what you really want — e.g. “Senior role at an AI company” or “Run my own business”.
          <div className="mt-4">
            <OpenClaude message="New goal: ">Add your first goal in Claude</OpenClaude>
          </div>
        </EmptyState>
      )}
      <div className="grid gap-4 sm:grid-cols-2">
        {goals?.map((g) => (
          <Link key={g.id} to={`/goals/${g.id}`} className="group">
            <Card className="h-full transition group-hover:ring-brand-400">
              <div className="mb-2 flex items-start justify-between gap-2">
                <h3 className="font-semibold leading-snug">{g.title}</h3>
                {intakeLabel(g)}
              </div>
              <div className="mb-4 flex flex-wrap gap-1.5 text-xs text-zinc-500">
                <Badge>{g.category}</Badge>
                <Badge>Priority {g.priority}</Badge>
                {g.status !== 'active' && <Badge tone="amber">{g.status}</Badge>}
                {g.target_date && <Badge>Target {prettyDate(g.target_date, { year: 'numeric' })}</Badge>}
              </div>
              <div className="flex items-center gap-3">
                <ProgressBar value={g.progress_pct} />
                <span className="text-xs tabular-nums text-zinc-500">{Math.round(g.progress_pct)}%</span>
              </div>
            </Card>
          </Link>
        ))}
      </div>
    </>
  )
}
