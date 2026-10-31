import { useQuery } from '@tanstack/react-query'
import { Link, useNavigate, useParams } from 'react-router-dom'
import OpenClaude from '../components/OpenClaude'
import QuickLog from '../components/QuickLog'
import TaskCard from '../components/TaskCard'
import { Button, Card, EmptyState, Input, Loading, PageHeader, cx, scoreTone } from '../components/ui'
import { api } from '../lib/api'
import { addDays, fmtMinutes, prettyDate, todayIso } from '../lib/dates'
import type { Entry, Goal, PlanItem, StudyToday } from '../lib/types'

// ---------------- Plan for the day ----------------

function DayPlan({ day }: { day: string }) {
  const { data: plan = [] } = useQuery({ queryKey: ['plan', day], queryFn: () => api<PlanItem[]>(`/plan?day=${day}`) })
  if (!plan.length) return null
  const done = plan.filter((p) => p.status === 'done').length
  return (
    <section className="space-y-4">
      <div className="flex items-end justify-between">
        <p className="text-[11px] font-semibold tracking-[0.14em] text-muted uppercase">Plan for this day</p>
        <span className="text-xs text-muted tabular-nums">
          {done}/{plan.length} done
        </span>
      </div>
      {plan.map((p) => (
        <TaskCard key={p.id} block={p} />
      ))}
    </section>
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
          {review.breakdown?.bonus_minutes ? (
            <>
              <p className="font-medium">Bonus day · {fmtMinutes(review.breakdown.bonus_minutes)} extra</p>
              <p className="text-sm text-muted">You worked on a rest day. The hours count toward this week.</p>
            </>
          ) : (
            <>
              <p className="font-medium">Rest day 🌿</p>
              <p className="text-sm text-muted">Your streak is safe.</p>
            </>
          )}
        </Card>
      ) : (
      <Card>
        <div className="space-y-2">
          {goals.map(([id, g]) => (
            <div key={id}>
              <div className="flex items-center justify-between gap-2 text-sm">
                <span className="font-medium">{g.title}</span>
                {g.extra ? (
                  <span className="font-semibold text-emerald-700 dark:text-emerald-300">Extra</span>
                ) : g.llm !== null ? (
                  <span className={cx('font-semibold tabular-nums', scoreTone(g.llm * 10))}>{g.llm}/10</span>
                ) : null}
              </div>
              <p className="text-xs text-muted">
                {fmtMinutes(g.minutes)} · {g.timeline.replace('_', ' ')}
                {g.note && ` · ${g.note}`}
              </p>
            </div>
          ))}
          <p className="text-xs text-muted">
            {review.adherence !== null && `Plan adherence ${Math.round(review.adherence * 100)}% · `}
            {review.drift_minutes > 0 && `${fmtMinutes(review.drift_minutes)} not linked to any goal · `}
            {review.used_llm ? "Claude's rating of the work" : 'Rules-only review'}. Your score is worked out weekly.
          </p>
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
      {review.tip && <p className="rounded-xl bg-accent-soft px-4 py-3 text-sm">💡 {review.tip}</p>}
      <Card title={`Tomorrow · ${prettyDate(addDays(entry.date, 1), { weekday: 'long' })}`}>
        {tomorrow.length ? (
          <ul className="space-y-1.5 text-sm">
            {tomorrow.map((p) => (
              <li key={p.id} className="flex gap-3">
                <span className="w-24 shrink-0 text-xs text-muted tabular-nums">{p.time_block || fmtMinutes(p.minutes)}</span>
                <span>{p.title}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-muted">No plan yet.</p>
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

function DayInterviews({ day }: { day: string }) {
  const { data } = useQuery({ queryKey: ['study', day], queryFn: () => api<StudyToday>(`/study/today?day=${day}`) })
  if (!data?.interviews.length) return null
  return (
    <Card eyebrow="Interviews" title="What you proved this day">
      <ul className="space-y-3">
        {data.interviews.map((s) => (
          <li key={s.id}>
            <Link to={`/study/${s.topic_id}`} className="flex items-center justify-between gap-3">
              <span className="min-w-0">
                <span className="block truncate text-sm font-medium">{s.topic}</span>
                <span className="block text-xs text-muted">
                  {s.kind === 'retest' ? 'Re-test' : 'Interview'} · {s.passed ? 'Passed' : `Weak: ${s.weak_concepts.join(', ')}`}
                </span>
              </span>
              <span className={cx('font-display text-2xl tabular-nums', scoreTone(s.overall_pct))}>{Math.round(s.overall_pct)}%</span>
            </Link>
          </li>
        ))}
      </ul>
    </Card>
  )
}

// ---------------- Page ----------------

export default function DailyLog() {
  const day = useParams().day ?? todayIso()
  const navigate = useNavigate()
  const { data: entry, isLoading } = useQuery({ queryKey: ['entry', day], queryFn: () => api<Entry>(`/entries/${day}`) })
  const { data: goals = [] } = useQuery({ queryKey: ['goals'], queryFn: () => api<Goal[]>('/goals') })
  const isToday = day === todayIso()
  const label = isToday ? 'today' : `${prettyDate(day, { weekday: 'long' })} (${day})`

  return (
    <>
      <PageHeader
        title={isToday ? 'Today' : prettyDate(day, { weekday: 'long', year: 'numeric' })}
        subtitle={isToday ? prettyDate(day, { weekday: 'long', year: 'numeric' }) : <Link to="/log" className="text-accent-ink">Jump to today</Link>}
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
          <QuickLog day={day} goals={goals.filter((g) => g.status === 'active' && g.intake_status === 'active')} />
          <DayInterviews day={day} />
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
