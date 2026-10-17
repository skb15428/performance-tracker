import { useQuery } from '@tanstack/react-query'
import OpenClaude from '../components/OpenClaude'
import { Badge, Card, EmptyState, Loading, PageHeader } from '../components/ui'
import { api } from '../lib/api'
import { fmtMinutes, prettyDate } from '../lib/dates'
import type { WeeklyReview } from '../lib/types'

function Review({ r }: { r: WeeklyReview }) {
  const total = r.stats.goals.reduce((s, g) => s + g.minutes, 0) || 1
  return (
    <Card title={`Week of ${prettyDate(r.week_start, { year: 'numeric' })}`} action={<Badge>{r.stats.days_logged}/7 days logged</Badge>}>
      <div className="mb-4 grid grid-cols-3 gap-3 text-center">
        <div>
          <p className="text-xs text-muted">Avg score</p>
          <p className="text-xl font-bold tabular-nums">{r.stats.avg_score ?? '—'}</p>
        </div>
        <div>
          <p className="text-xs text-muted">Plan done</p>
          <p className="text-xl font-bold tabular-nums">
            {r.stats.plan_done}/{r.stats.plan_items}
          </p>
        </div>
        <div>
          <p className="text-xs text-muted">Off-goal time</p>
          <p className="text-xl font-bold tabular-nums">{fmtMinutes(r.stats.drift_minutes)}</p>
        </div>
      </div>
      <div className="mb-4 space-y-2">
        {r.stats.goals.map((g, i) => (
          <div key={g.goal_id} className="text-sm">
            <div className="flex justify-between gap-2">
              <span className="flex items-center gap-2">
                <span className="size-2 rounded-full" style={{ background: `var(--series-${(i % 8) + 1})` }} />
                {g.title}
              </span>
              <span className="text-xs text-muted tabular-nums">
                {fmtMinutes(g.minutes)}
                {g.committed_hours ? ` of ${g.committed_hours}h planned (${Math.round((g.pct_of_commitment ?? 0) * 100)}%)` : ` · ${Math.round((100 * g.minutes) / total)}%`} · {g.timeline.replace('_', ' ')}
              </span>
            </div>
            <div className="mt-1 h-1.5 rounded-full bg-surface-2">
              <div className="h-full rounded-full" style={{ width: `${(100 * g.minutes) / total}%`, background: `var(--series-${(i % 8) + 1})` }} />
            </div>
          </div>
        ))}
      </div>
      <p className="mb-4 text-sm leading-relaxed">{r.summary}</p>
      {r.focus?.length > 0 && (
        <div className="mb-4 rounded-xl bg-accent-soft px-4 py-3 text-sm">
          <p className="mb-1 text-xs font-semibold text-accent-ink uppercase">Focus for next week</p>
          <ul className="space-y-0.5">
            {r.focus.map((f, i) => (
              <li key={i}>
                {f.kept === true ? '✅ ' : f.kept === false ? '❌ ' : '• '}
                {f.text}
              </li>
            ))}
          </ul>
        </div>
      )}
      <div className="grid gap-4 sm:grid-cols-3">
        {(
          [
            ['Wins', r.wins],
            ['Gaps', r.gaps],
            ['Next week', r.recommendations],
          ] as const
        ).map(([title, list]) => (
          <div key={title}>
            <p className="mb-1 text-xs font-semibold text-muted uppercase">{title}</p>
            <ul className="list-disc space-y-1 pl-4 text-sm">
              {list.map((t, i) => (
                <li key={i}>{t}</li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </Card>
  )
}

export default function Weekly() {
  const { data, isLoading } = useQuery({ queryKey: ['weekly'], queryFn: () => api<WeeklyReview[]>('/reviews/weekly') })
  return (
    <>
      <PageHeader
        title="Weekly review"
        subtitle="Written with your coach in Claude; you'll be reminded each Monday."
        action={<OpenClaude message="Do my weekly review">Do my weekly review in Claude</OpenClaude>}
      />
      {isLoading && <Loading />}
      {data && data.length === 0 && <EmptyState title="No reviews yet">Log a few days, then ask Claude for your weekly review.</EmptyState>}
      <div className="space-y-4">{data?.map((r) => <Review key={r.id} r={r} />)}</div>
    </>
  )
}
