import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate, useParams } from 'react-router-dom'
import OpenClaude from '../components/OpenClaude'
import { Button, Card, EmptyState, Input, Loading, PageHeader, ScoreRing, cx, scoreTone } from '../components/ui'
import { api } from '../lib/api'
import { addDays, fmtMinutes, prettyDate, todayIso } from '../lib/dates'
import type { Entry, PlanItem } from '../lib/types'

// ---------------- Plan for the day ----------------

function DayPlan({ day }: { day: string }) {
  const qc = useQueryClient()
  const { data: plan = [] } = useQuery({ queryKey: ['plan', day], queryFn: () => api<PlanItem[]>(`/plan?day=${day}`) })
  const patch = useMutation({
    mutationFn: ({ id, status }: { id: number; status: PlanItem['status'] }) => api(`/plan/${id}`, { method: 'PATCH', json: { status } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['plan', day] }),
  })
  if (!plan.length) return null
  const done = plan.filter((p) => p.status === 'done').length
  return (
    <Card title="Plan for this day" action={<span className="text-xs text-zinc-500">{done}/{plan.length} done</span>}>
      <p className="mb-3 text-xs text-zinc-500">Tick blocks as you finish them. Partial blocks can be logged in Claude.</p>
      <ul className="space-y-1.5">
        {plan.map((p) => (
          <li key={p.id} className="flex items-center gap-3">
            <input
              type="checkbox"
              className="size-4 accent-brand-600"
              checked={p.status === 'done'}
              onChange={(e) => patch.mutate({ id: p.id, status: e.target.checked ? 'done' : 'open' })}
              aria-label="Done"
            />
            <span className="w-24 shrink-0 text-xs text-zinc-500 tabular-nums">{p.time_block || fmtMinutes(p.minutes)}</span>
            <span className={cx('flex-1 text-sm', p.status === 'done' && 'text-zinc-400 line-through', p.status === 'skipped' && 'text-zinc-400 italic')}>{p.title}</span>
            {p.status !== 'done' && (
              <button className="text-xs text-zinc-400 hover:text-zinc-700" onClick={() => patch.mutate({ id: p.id, status: p.status === 'skipped' ? 'open' : 'skipped' })}>
                {p.status === 'skipped' ? 'undo skip' : 'skip'}
              </button>
            )}
          </li>
        ))}
      </ul>
    </Card>
  )
}

// ---------------- Result ----------------

function ReviewResult({ entry }: { entry: Entry }) {
  const review = entry.review!
  const { data: tomorrow = [] } = useQuery({ queryKey: ['plan', addDays(entry.date, 1)], queryFn: () => api<PlanItem[]>(`/plan?day=${addDays(entry.date, 1)}`) })
  const goals = Object.entries(review.per_goal).filter(([k]) => !k.startsWith('_'))
  return (
    <div className="space-y-4">
      {review.rest_day ? (
        <Card>
          <p className="font-medium">Rest day 🌿</p>
          <p className="text-sm text-zinc-500">Not scored, and your streak is safe.</p>
        </Card>
      ) : (
      <Card>
        <div className="flex flex-wrap items-center gap-6">
          <ScoreRing score={review.total_score} size={112} />
          <div className="min-w-0 flex-1 space-y-2">
            {goals.map(([id, g]) => (
              <div key={id}>
                <div className="flex items-center justify-between gap-2 text-sm">
                  <span className="font-medium">{g.title}</span>
                  <span className={cx('font-semibold tabular-nums', scoreTone(g.score * 10))}>{g.score.toFixed(1)}/10</span>
                </div>
                <p className="text-xs text-zinc-500">
                  {fmtMinutes(g.minutes)} · {g.timeline.replace('_', ' ')}
                  {g.note && ` · ${g.note}`}
                </p>
              </div>
            ))}
            {review.breakdown?.explanation && <p className="text-xs text-zinc-500 tabular-nums">{review.breakdown.explanation}</p>}
            <p className="text-xs text-zinc-500">
              {review.adherence !== null && `Plan adherence ${Math.round(review.adherence * 100)}% · `}
              {review.drift_minutes > 0 && `${fmtMinutes(review.drift_minutes)} not linked to any goal · `}
              {review.used_llm ? 'AI-reviewed' : 'Rules-only review'}
            </p>
          </div>
        </div>
      </Card>
      )}
      <div className="grid gap-4 sm:grid-cols-2">
        <Card title="👍 Went well">
          <ul className="list-disc space-y-1 pl-5 text-sm">{review.went_well.filter(Boolean).map((t, i) => <li key={i}>{t}</li>)}</ul>
        </Card>
        <Card title="👎 Could be better">
          <ul className="list-disc space-y-1 pl-5 text-sm">{review.went_badly.filter(Boolean).map((t, i) => <li key={i}>{t}</li>)}</ul>
        </Card>
      </div>
      {review.tip && <p className="rounded-xl bg-brand-50 px-4 py-3 text-sm text-brand-800 dark:bg-brand-700/20 dark:text-brand-100">💡 {review.tip}</p>}
      <Card title={`Tomorrow · ${prettyDate(addDays(entry.date, 1), { weekday: 'long' })}`}>
        {tomorrow.length ? (
          <ul className="space-y-1.5 text-sm">
            {tomorrow.map((p) => (
              <li key={p.id} className="flex gap-3">
                <span className="w-24 shrink-0 text-xs text-zinc-500 tabular-nums">{p.time_block || fmtMinutes(p.minutes)}</span>
                <span>{p.title}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-zinc-500">No plan yet.</p>
        )}
      </Card>
      <div className="flex justify-end">
        <OpenClaude variant="secondary" message={`Let's redo my review for ${prettyDate(entry.date, { weekday: 'long' })} (${entry.date}).`}>
          Change this review in Claude
        </OpenClaude>
      </div>
    </div>
  )
}

// ---------------- Page ----------------

export default function DailyLog() {
  const day = useParams().day ?? todayIso()
  const navigate = useNavigate()
  const { data: entry, isLoading } = useQuery({ queryKey: ['entry', day], queryFn: () => api<Entry>(`/entries/${day}`) })
  const isToday = day === todayIso()
  const label = isToday ? 'today' : `${prettyDate(day, { weekday: 'long' })} (${day})`

  return (
    <>
      <PageHeader
        title={isToday ? 'Today' : prettyDate(day, { weekday: 'long', year: 'numeric' })}
        subtitle={isToday ? prettyDate(day, { weekday: 'long', year: 'numeric' }) : <Link to="/log" className="text-brand-600">Jump to today</Link>}
        action={
          <div className="flex gap-1">
            <Button variant="secondary" size="sm" onClick={() => navigate(`/log/${addDays(day, -1)}`)} aria-label="Previous day">
              ←
            </Button>
            <Input type="date" value={day} max={todayIso()} onChange={(e) => e.target.value && navigate(`/log/${e.target.value}`)} className="w-40 py-1 text-xs" />
            <Button variant="secondary" size="sm" disabled={isToday} onClick={() => navigate(`/log/${addDays(day, 1)}`)} aria-label="Next day">
              →
            </Button>
          </div>
        }
      />
      {isLoading && <Loading />}
      {entry && (
        <div className="space-y-4">
          <DayPlan day={day} />
          {entry.review ? (
            <ReviewResult entry={entry} />
          ) : (
            <EmptyState title={isToday ? "Today isn't logged yet" : 'This day was not logged'}>
              Tell Claude how the day went: it scores it, checks your goals and plans tomorrow.
              <div className="mt-4">
                <OpenClaude message={isToday ? 'Log my day' : `Log my day for ${label}`}>Log {isToday ? 'today' : 'this day'} in Claude</OpenClaude>
              </div>
            </EmptyState>
          )}
        </div>
      )}
    </>
  )
}
