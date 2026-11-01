import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import OpenClaude from '../components/OpenClaude'
import QuickLog from '../components/QuickLog'
import ReplanBanner from '../components/ReplanBanner'
import TaskCard from '../components/TaskCard'
import { Button, Card, EmptyState, ErrorText, Loading, PageHeader, ProgressBar, ScoreRing, TimelineBadge, cx } from '../components/ui'
import { api } from '../lib/api'
import { addDays, fmtMinutes, prettyDate, todayIso } from '../lib/dates'
import type { Dashboard as DashboardData, ScorecardRow, Settings, StudyToday, StudyUpcoming, WeekDay, WeekScore } from '../lib/types'

const seriesColor = (i: number) => `var(--series-${(i % 8) + 1})`
const axis = { stroke: 'var(--chart-axis)', fontSize: 11, tickLine: false, axisLine: false }
const tooltipStyle = {
  contentStyle: {
    background: 'var(--chart-surface)',
    border: '1px solid var(--chart-grid)',
    borderRadius: 14,
    fontSize: 12,
    color: 'var(--chart-text)',
  },
  labelStyle: { color: 'var(--chart-text)', fontWeight: 600 },
  itemStyle: { color: 'var(--chart-text)' },
}

function greeting(): string {
  const h = new Date().getHours()
  return h < 5 ? 'Good night' : h < 12 ? 'Good morning' : h < 17 ? 'Good afternoon' : 'Good evening'
}

function Stat({ label, value, sub, to, className }: { label: string; value: ReactNode; sub?: ReactNode; to?: string; className?: string }) {
  const body = (
    <div className="h-full rounded-3xl border border-line bg-surface p-5 transition hover:border-accent/40">
      <p className="text-[11px] font-semibold tracking-[0.14em] text-muted uppercase">{label}</p>
      <p className="mt-2 font-display text-5xl leading-none tabular-nums">{value}</p>
      {sub && <p className="mt-2 text-xs text-muted">{sub}</p>}
    </div>
  )
  return to ? (
    <Link to={to} className={className}>
      {body}
    </Link>
  ) : (
    <div className={className}>{body}</div>
  )
}

// `short` is the label shown under the date, so a day's state never depends on colour alone.
const WEEK_STYLE: Record<WeekDay['state'], { ring: string; label: string; short: string }> = {
  done: { ring: 'bg-emerald-500 text-white', label: 'Logged', short: 'Done' },
  rest: { ring: 'bg-surface-2 text-muted', label: 'Rest', short: 'Rest' },
  bonus: { ring: 'bg-emerald-500/20 text-emerald-700 dark:text-emerald-300', label: 'Extra', short: 'Extra' },
  before: { ring: 'text-muted', label: 'Not started', short: '—' },
  covered: { ring: 'border border-emerald-500/50 text-emerald-700 dark:text-emerald-300', label: 'Covered', short: 'Fine' },
  missed: { ring: 'bg-red-500/15 text-red-600 dark:text-red-300', label: 'Missed', short: 'Missed' },
  today: { ring: 'bg-ink text-canvas', label: 'Today', short: 'Today' },
  upcoming: { ring: 'border border-dashed border-line text-muted', label: 'Planned', short: 'Plan' },
}

type DayChange = { day_type: 'rest' | 'work' | null; goal_id?: number }
type GoalName = { id: number; title: string }

function useDayType(date: string, onDone?: () => void) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (json: DayChange) => api(`/entries/${date}/type`, { method: 'PUT', json }),
    onSuccess: () => {
      qc.invalidateQueries()
      onDone?.()
    },
  })
}

function DayPanel({ day, goals, onDone }: { day: WeekDay; goals: GoalName[]; onDone: () => void }) {
  const change = useDayType(day.date, onDone)
  const state = day.day_type === 'rest' ? "Marked as a rest day, so its hours are off the week's target."
    : day.day_type === 'work' ? 'Marked as a work day.'
    : day.usual ? `${fmtMinutes(day.planned_minutes)} planned.` : 'A rest day in your routine.'
  const next = day.day_type ? null : day.usual ? 'rest' : 'work'
  return (
    <div className="mt-2 rounded-2xl bg-surface-2 p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="min-w-0 text-sm">
          <span className="font-medium">{prettyDate(day.date, { weekday: 'long' })}</span>
          <span className="text-muted"> · {state}</span>
        </p>
        <Button size="sm" variant="secondary" loading={change.isPending} onClick={() => change.mutate({ day_type: next })}>
          {next === 'rest' ? 'Make it a rest day' : next === 'work' ? 'Make it a work day' : 'Back to normal'}
        </Button>
      </div>
      {goals.length > 1 && day.usual && !day.day_type && (
        <ul className="mt-3 space-y-1 border-t border-line pt-3">
          {goals.map((g) => {
            const resting = day.goal_day_types[String(g.id)] === 'rest'
            return (
              <li key={g.id}>
                <button className="w-full text-left text-sm text-muted hover:text-ink" onClick={() => change.mutate({ day_type: resting ? null : 'rest', goal_id: g.id })}>
                  {resting ? `${g.title}: back to normal` : `Rest ${g.title} only`}
                </button>
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}

export function WeekStrip({ week, nextWeek, goals }: { week: WeekDay[]; nextWeek: WeekDay[]; goals: GoalName[] }) {
  const [picked, setPicked] = useState<string | null>(null)
  const [ahead, setAhead] = useState(false)
  const days = ahead ? nextWeek : week
  const day = days.find((d) => d.date === picked)
  return (
    <div className="rise rounded-3xl border border-line bg-surface p-2 sm:p-3">
      <div className="mb-2 flex justify-center gap-1">
        {[false, true].map((later) => (
          <button
            key={String(later)}
            aria-pressed={ahead === later}
            onClick={() => {
              setAhead(later)
              setPicked(null)
            }}
            className={cx('rounded-full px-3 py-1 text-xs font-medium transition', ahead === later ? 'bg-ink text-canvas' : 'text-muted hover:text-ink')}
          >
            {later ? 'Next week' : 'This week'}
          </button>
        ))}
      </div>
      <div className="grid grid-cols-7 gap-1.5 sm:gap-3">
        {days.map((d) => {
          const style = WEEK_STYLE[d.state]
          const date = new Date(`${d.date}T12:00:00`)
          return (
            <button
              key={d.date}
              disabled={d.state === 'before'}
              aria-expanded={picked === d.date}
              aria-label={`${prettyDate(d.date, { weekday: 'long' })}: ${style.label}${d.minutes ? `, ${fmtMinutes(d.minutes)} worked` : ''}`}
              onClick={() => setPicked(picked === d.date ? null : d.date)}
              title={`${prettyDate(d.date, { weekday: 'long' })}: ${style.label}${d.minutes ? ` · ${fmtMinutes(d.minutes)} worked` : ''}${d.planned_minutes ? ` · ${fmtMinutes(d.planned_minutes)} planned` : ''}`}
              className={cx('flex min-w-0 flex-col items-center gap-1.5 rounded-2xl py-2 transition sm:py-3', d.is_today && 'bg-accent-soft', picked === d.date && 'ring-1 ring-accent/50')}
            >
              <span className="text-[10px] font-semibold tracking-wider text-muted uppercase">
                {date.toLocaleDateString(undefined, { weekday: 'short' }).slice(0, 2)}
              </span>
              <span className={cx('flex size-9 items-center justify-center rounded-full text-sm font-semibold tabular-nums sm:size-10', style.ring)}>
                {date.getDate()}
              </span>
              <span className="text-[10px] whitespace-nowrap text-muted tabular-nums">
                {d.minutes ? fmtMinutes(d.minutes).replace(' ', '') : style.short}
              </span>
            </button>
          )
        })}
      </div>
      {day ? (
        <DayPanel day={day} goals={goals} onDone={() => setPicked(null)} />
      ) : (
        <p className="mt-2 text-center text-[11px] text-muted">{ahead ? 'Plan ahead: tap a day to rest it or work it.' : 'Tap a day to make it a rest day or a work day.'}</p>
      )}
    </div>
  )
}

function Scorecard({ rows }: { rows: ScorecardRow[] }) {
  const qc = useQueryClient()
  const add = useMutation({ mutationFn: (id: number) => api(`/study/metrics/${id}/log`, { method: 'POST', json: {} }), onSuccess: () => qc.invalidateQueries() })
  return (
    <Card eyebrow="Your scorecard" title="What the goal is made of">
      <ul className="space-y-4">
        {rows.map((r) => (
          <li key={r.id}>
            <div className="mb-1.5 flex items-baseline justify-between gap-3 text-sm">
              <span className="min-w-0">{r.name}</span>
              <span className="flex shrink-0 items-center gap-2 tabular-nums">
                <span>
                  {r.latest_value ?? r.start_value} <span className="text-muted">of {r.target_value}{r.unit && ` ${r.unit}`}</span>
                </span>
                {!r.source && (
                  <button aria-label={`Add 1 to ${r.name}`} disabled={add.isPending} onClick={() => add.mutate(r.id)} className="rounded-full border border-line px-2 text-xs hover:border-accent">
                    +1
                  </button>
                )}
              </span>
            </div>
            <ProgressBar value={r.progress_pct} />
          </li>
        ))}
      </ul>
    </Card>
  )
}

function ThisWeek({ week, tip, forecast }: { week: WeekScore; tip?: string; forecast?: { finish: string; target: string | null; late: boolean } }) {
  const pace = week.score === null ? 'Your score starts after your first logged day.'
    : week.ahead_hours > 0 ? `${week.ahead_hours}h ahead of pace, so a rest day is fine`
    : week.ahead_hours < 0 ? `${-week.ahead_hours}h behind pace` : 'Right on pace'
  return (
    <Card eyebrow="This week" title="Your score">
      <div className="flex items-center gap-5">
        {week.score !== null ? (
          <ScoreRing score={week.score} size={112} />
        ) : (
          <span className="flex size-28 shrink-0 items-center justify-center rounded-full border-8 border-surface-2 font-display text-3xl text-muted">—</span>
        )}
        <div className="min-w-0 flex-1">
          <p className="font-display text-4xl leading-none tabular-nums">
            {week.hours_done}h <span className="font-sans text-sm text-muted">of {week.hours_target}h</span>
          </p>
          <ProgressBar value={week.hours_target ? (week.hours_done / week.hours_target) * 100 : 0} className="mt-3 h-2" />
          <p className="mt-2 text-xs text-muted">
            {pace}
            {week.rest_days_marked > 0 && ` · ${week.rest_days_marked} rest day${week.rest_days_marked > 1 ? 's' : ''} marked`}
          </p>
          {week.average_hours != null && (
            <p className="mt-1 text-xs text-muted tabular-nums">
              {week.average_hours}h a day on average · planned {week.planned_hours_per_day}h
            </p>
          )}
        </div>
      </div>
      {week.goals.length > 1 && (
        <ul className="mt-4 space-y-1 text-sm">
          {week.goals.map((g) => (
            <li key={g.goal_id} className="flex justify-between gap-3">
              <span className="min-w-0 truncate">{g.title}</span>
              <span className="shrink-0 text-xs text-muted tabular-nums">
                {g.sessions_target ? `${g.sessions_done} of ${g.sessions_target} sessions` : `${g.hours_done}h of ${g.hours_target}h`}
              </span>
            </li>
          ))}
        </ul>
      )}
      {week.explanation && <p className="mt-4 rounded-2xl bg-surface-2 px-3 py-2 text-xs text-muted tabular-nums">{week.explanation}</p>}
      {forecast && (
        <p className="mt-3 text-sm">
          At your current pace you finish{' '}
          <span className={forecast.late ? 'font-semibold text-red-600 dark:text-red-400' : 'font-semibold'}>{prettyDate(forecast.finish, { year: 'numeric' })}</span>
          {forecast.target && <span className="text-muted"> · target {prettyDate(forecast.target, { year: 'numeric' })}</span>}
        </p>
      )}
      {tip && <p className="mt-3 text-sm">💡 {tip}</p>}
    </Card>
  )
}

function DayProgress({ plan }: { plan: DashboardData['today_plan'] }) {
  const total = plan.reduce((s, p) => s + p.minutes, 0)
  const done = plan.reduce((s, p) => {
    if (p.status === 'done') return s + p.minutes
    if (p.status === 'partial') return s + (p.done_minutes ?? 0)
    if (p.status === 'open') return s + (p.details?.steps ?? []).filter((st) => st.done).reduce((a, st) => a + st.minutes, 0)
    return s
  }, 0)
  const next = plan.find((p) => p.status === 'open')
  const pct = total ? Math.round((done / total) * 100) : 0
  return (
    <div className="rise flex flex-wrap items-center gap-x-6 gap-y-3 rounded-3xl border border-line bg-surface p-5">
      <div className="min-w-48 flex-1">
        <div className="mb-2 flex items-baseline justify-between">
          <span className="text-[11px] font-semibold tracking-[0.14em] text-muted uppercase">Today's progress</span>
          <span className="text-xs text-muted tabular-nums">
            {fmtMinutes(done)} of {fmtMinutes(total)}
          </span>
        </div>
        <ProgressBar value={pct} className="h-2" />
      </div>
      <div className="flex items-baseline gap-2">
        <span className="font-display text-4xl tabular-nums">{pct}%</span>
      </div>
      {next ? (
        <p className="w-full text-sm sm:w-auto">
          <span className="text-muted">Next up · </span>
          <span className="font-medium tabular-nums">{next.time_block ? `${next.time_block.split('-')[0]} ` : ''}</span>
          {next.title.split(/\s+[-—–]\s+done when/i)[0]}
        </p>
      ) : (
        <p className="w-full text-sm text-emerald-700 sm:w-auto dark:text-emerald-300">All blocks done today 🎉</p>
      )}
    </div>
  )
}

function StudySummary({ study }: { study: StudyToday }) {
  const queue = study.topics.filter((t) => t.mode !== 'done')
  const retests = queue.filter((t) => t.mode === 'retest').length
  const passed = study.interviews.filter((s) => s.passed).length
  return (
    <Link to="/study" className="rise mt-4 flex items-center justify-between gap-4 rounded-3xl border border-line bg-surface p-5 transition hover:border-accent/40">
      <div className="min-w-0">
        <p className="text-[11px] font-semibold tracking-[0.14em] text-muted uppercase">Today's study</p>
        <p className="mt-1 truncate font-display text-2xl leading-tight">
          {queue.length ? queue.slice(0, 3).map((t) => t.title).join(' · ') : 'All topics covered'}
        </p>
        <p className="mt-1 text-xs text-muted">
          {queue.length} to cover{retests ? ` · ${retests} re-test${retests > 1 ? 's' : ''}` : ''}
          {study.interviews.length ? ` · ${passed}/${study.interviews.length} interviews passed` : ''}
        </p>
      </div>
      <span aria-hidden className="text-xl text-muted">
        →
      </span>
    </Link>
  )
}

function RestDayCard({ day, ahead }: { day: WeekDay; ahead?: StudyUpcoming }) {
  const change = useDayType(day.date)
  const next = ahead?.days[0]
  const step = ahead?.steps[0]
  const title = next?.topics[0]?.title ?? step?.title
  const when = next?.date ?? step?.planned_start
  return (
    <div className="rise rounded-3xl border border-accent/40 bg-surface p-7 ring-1 ring-accent/20">
      <p className="text-[11px] font-semibold tracking-[0.14em] text-accent-ink uppercase">Rest day</p>
      <p className="mt-3 font-display text-3xl leading-tight">{day.minutes ? `${fmtMinutes(day.minutes)} of extra work` : 'Nothing is due today.'}</p>
      <p className="mt-2 text-sm text-muted">
        {day.minutes ? "It counts toward this week's hours, and your streak is safe." : "Enjoy the break. If you change your mind, anything you do counts toward this week's hours."}
      </p>
      {title && (
        <p className="mt-4 text-sm">
          <span className="text-muted">Next up{when ? ` · ${prettyDate(when, { weekday: 'short', month: 'short', day: 'numeric' })}` : ''} · </span>
          <span className="font-medium">{title}</span>
        </p>
      )}
      <div className="mt-6 flex flex-wrap gap-2">
        <Button loading={change.isPending} onClick={() => change.mutate({ day_type: day.day_type ? null : 'work' })}>
          Work today
        </Button>
        <Link to="/study">
          <Button variant="secondary">See what's coming up</Button>
        </Link>
      </div>
    </div>
  )
}

function DayOff({ day }: { day: WeekDay }) {
  const change = useDayType(day.date)
  return (
    <button disabled={change.isPending} onClick={() => change.mutate({ day_type: day.day_type ? null : 'rest' })} className="block w-full py-1 text-center text-sm text-muted transition hover:text-ink disabled:opacity-50">
      {day.day_type ? 'Changed your mind? Back to a rest day' : 'Not today? Make it a rest day'}
    </button>
  )
}

function Heatmap({ data }: { data: { date: string; minutes: number; rest?: boolean }[] }) {
  const byDate = new Map(data.map((d) => [d.date, d.minutes]))
  const rest = new Set(data.filter((d) => d.rest).map((d) => d.date))
  const today = todayIso()
  const offset = (new Date(`${today}T12:00:00`).getDay() + 6) % 7
  const start = addDays(today, -offset - 17 * 7)
  const weeks = Array.from({ length: 18 }, (_, w) => Array.from({ length: 7 }, (_, d) => addDays(start, w * 7 + d)))
  const level = (m: number | undefined) => (!m ? -1 : m < 30 ? 1 : m < 60 ? 2 : m < 120 ? 3 : 4)
  return (
    <div>
      <div className="flex gap-1 overflow-x-auto pb-1">
        {weeks.map((week, wi) => (
          <div key={wi} className="flex flex-col gap-1">
            {week.map((d) => {
              const isRest = rest.has(d)
              const s = isRest ? undefined : byDate.get(d)
              const l = level(s)
              return (
                <div
                  key={d}
                  title={d > today ? '' : `${prettyDate(d, { weekday: 'short' })}: ${isRest ? 'rest day' : s ? fmtMinutes(s) : 'nothing logged'}`}
                  className={cx('size-3.5 rounded-[4px]', d > today && 'opacity-0', isRest && 'ring-1 ring-inset ring-[var(--chart-muted)]')}
                  style={{ background: isRest ? 'transparent' : l < 0 ? 'var(--chart-grid)' : `var(--seq-${l})` }}
                />
              )
            })}
          </div>
        ))}
      </div>
      <div className="mt-3 flex items-center gap-1.5 text-[11px] text-muted">
        Less
        {[-1, 1, 2, 3, 4].map((l) => (
          <span key={l} className="size-3 rounded-[3px]" style={{ background: l < 0 ? 'var(--chart-grid)' : `var(--seq-${l})` }} />
        ))}
        More
        <span className="ml-3 size-3 rounded-[3px] ring-1 ring-inset ring-[var(--chart-muted)]" /> Rest day
      </div>
    </div>
  )
}

export default function Dashboard() {
  const { data, isLoading, error } = useQuery({ queryKey: ['dashboard'], queryFn: () => api<DashboardData>('/dashboard/summary') })
  const { data: settings } = useQuery({ queryKey: ['settings'], queryFn: () => api<Settings>('/me/settings') })
  const { data: study } = useQuery({ queryKey: ['study', 'today'], queryFn: () => api<StudyToday>('/study/today') })
  const { data: ahead } = useQuery({ queryKey: ['study', 'upcoming'], queryFn: () => api<StudyUpcoming>('/study/upcoming'), enabled: !!study?.rest_day })

  if (isLoading) return <Loading />
  if (!data) return <ErrorText error={error} />

  const today = data.today ?? todayIso()
  const loggedToday = data.reviewed_today
  const todayCell = data.week.find((d) => d.is_today)
  const activePlan = data.today_plan.some((p) => p.status !== 'skipped')
  const goals = data.goals.filter((g) => g.intake_status === 'active')
  const insight = goals.map((g) => g.insight).find((i) => i?.forecast_finish_at_actual_pace)
  const forecast = insight?.forecast_finish_at_actual_pace
    ? { finish: insight.forecast_finish_at_actual_pace, target: insight.target_date, late: insight.forecast_misses_target }
    : undefined
  const goalIndex = new Map(data.goals.map((g, i) => [String(g.id), i]))
  const goalTitle = (id: number | null) => data.goals.find((g) => g.id === id)?.title
  const firstName = settings?.name?.split(' ')[0]
  const weeklyHours = data.weekly_effort.map(({ week, ...rest }) => ({
    week,
    ...Object.fromEntries(Object.entries(rest).map(([k, v]) => [k, Math.round((Number(v) / 60) * 10) / 10])),
  }))

  if (!data.goals.length)
    return (
      <>
        <PageHeader eyebrow="Welcome" title={<>Let's set your <span className="gradient-text italic">first goal</span></>} />
        <EmptyState title="Your coach lives in Claude">
          Tell Claude what you're aiming for. It agrees the exact goal, a roadmap and a daily routine with you, then plans and scores
          every day against it. Everything shows up here.
          <div className="mt-5">
            <OpenClaude message="New goal: ">Add a goal in Claude</OpenClaude>
          </div>
        </EmptyState>
      </>
    )

  const firstOpen = data.today_plan.find((p) => p.status === 'open')
  return (
    <>
      <header className="rise mb-5 flex items-center justify-between gap-3">
        <div className="min-w-0">
          <p className="text-[11px] font-semibold tracking-[0.16em] text-muted uppercase">
            {prettyDate(today, { weekday: 'long', month: 'long', day: 'numeric' })}
          </p>
          <h1 className="mt-1 font-display text-[1.75rem] leading-tight sm:text-4xl">
            {greeting()}
            {firstName ? (
              <>
                , <span className="gradient-text italic">{firstName}</span>
              </>
            ) : null}
          </h1>
        </div>
        {loggedToday ? (
          <Link to="/log" className="shrink-0">
            <Button variant="secondary" size="sm">
              Today's review
            </Button>
          </Link>
        ) : (
          <OpenClaude message="Log my day" variant="secondary" className="shrink-0 !px-3 !py-1.5 !text-xs">
            Log day
          </OpenClaude>
        )}
      </header>
      <ReplanBanner />
      {data.attention.map((line) => (
        <p key={line} className="rise mb-4 rounded-2xl bg-amber-500/14 px-4 py-3 text-sm text-amber-900 dark:text-amber-200">
          {line}
        </p>
      ))}

      {/* What to do now: the first thing on the page */}
      <section aria-label="Today's tasks" className="space-y-4">
        {study?.rest_day && !activePlan && todayCell ? (
          <RestDayCard day={todayCell} ahead={ahead} />
        ) : data.today_plan.length ? (
          data.today_plan.map((p) => <TaskCard key={p.id} block={p} goalTitle={goalTitle(p.goal_id)} highlight={p.id === firstOpen?.id} />)
        ) : (
          <div className="rise flex flex-col justify-between rounded-3xl border border-accent/40 bg-surface p-7 ring-1 ring-accent/20">
            <p className="text-[11px] font-semibold tracking-[0.14em] text-accent-ink uppercase">Today's task</p>
            <p className="mt-3 font-display text-3xl leading-tight">Nothing planned yet.</p>
            <p className="mt-2 text-sm text-muted">Ask Claude and it builds today's blocks from your routine and roadmap.</p>
            <div className="mt-6">
              <OpenClaude message="What's my plan today?">Get today's plan in Claude</OpenClaude>
            </div>
          </div>
        )}
        {todayCell && !loggedToday && !study?.rest_day && (todayCell.usual || todayCell.day_type === 'work') && <DayOff day={todayCell} />}
        <QuickLog day={today} goals={goals} />
      </section>
      {study && study.topics.length > 0 && <StudySummary study={study} />}

      <div className="mt-10 mb-4 flex items-baseline justify-between gap-3">
        <h2 className="font-display text-3xl">Your day &amp; week</h2>
        <Link to="/log" className="text-sm text-accent-ink">
          Day details →
        </Link>
      </div>
      <div className="mb-4 grid grid-cols-1 gap-4 lg:grid-cols-5">
        <div className="lg:col-span-3">
          <WeekStrip week={data.week} nextWeek={data.next_week} goals={goals} />
        </div>
        <div className="lg:col-span-2">{activePlan && <DayProgress plan={data.today_plan} />}</div>
      </div>

      {/* Score */}
      <div className="grid grid-cols-1 gap-4">
        <ThisWeek week={data.this_week} tip={data.latest?.tip} forecast={forecast} />
        {data.scorecard.length > 0 && <Scorecard rows={data.scorecard} />}
      </div>

      <div className="mt-4 grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Stat label="Streak" value={`${data.streak}`} sub={data.streak === 1 ? 'day logged in a row' : 'days logged in a row'} />
        <Stat label="Plan done" value={data.adherence_avg !== null ? `${Math.round(data.adherence_avg * 100)}%` : '—'} sub="last 30 days" />
        <Stat label="What's new" value={data.new_trends} sub="suggestions to review" to="/trends" className="col-span-2 lg:col-span-1" />
        <div className="col-span-2 rounded-3xl border border-line bg-surface p-5 lg:col-span-1">
          <p className="text-[11px] font-semibold tracking-[0.14em] text-muted uppercase">This week's focus</p>
          {data.weekly_focus.length ? (
            <ul className="mt-3 space-y-2 text-sm">
              {data.weekly_focus.map((f, i) => (
                <li key={i} className="flex gap-2">
                  <span className="text-accent-ink">●</span>
                  {f}
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-3 text-sm text-muted">Set during your weekly review in Claude.</p>
          )}
        </div>
      </div>

      <h2 className="mt-12 mb-4 font-display text-3xl">Your goals</h2>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {data.goals.map((g, i) => (
          <Link key={g.id} to={`/goals/${g.id}`} className="group">
            <article className="h-full rounded-3xl border border-line bg-surface p-6 transition group-hover:border-accent/40">
              <div className="mb-4 flex items-start justify-between gap-3">
                <h3 className="font-display text-2xl leading-tight">{g.title}</h3>
                <TimelineBadge timeline={g.intake_status === 'active' ? g.timeline : null} />
              </div>
              <div className="mb-1 flex items-end justify-between">
                <span className="font-display text-4xl tabular-nums">{Math.round(g.progress_pct)}%</span>
                {g.target_date && <span className="text-xs text-muted">target {prettyDate(g.target_date, { year: 'numeric' })}</span>}
              </div>
              <ProgressBar value={g.progress_pct} />
              {g.insight && (
                <p className="mt-3 text-xs text-muted tabular-nums">
                  {g.insight.actual_hours_per_week}h/week of {g.insight.planned_hours_per_week}h planned
                  {g.insight.forecast_finish_at_actual_pace && (
                    <>
                      {' · at this pace '}
                      <span className={g.insight.forecast_misses_target ? 'font-semibold text-red-600 dark:text-red-400' : 'text-ink'}>
                        {prettyDate(g.insight.forecast_finish_at_actual_pace, { year: 'numeric' })}
                      </span>
                    </>
                  )}
                </p>
              )}
              {g.intake_status === 'active' ? (
                <div className="mt-4 h-28">
                  <ResponsiveContainer>
                    <LineChart data={g.burnup} margin={{ top: 4, right: 4, bottom: 0, left: -28 }}>
                      <CartesianGrid vertical={false} stroke="var(--chart-grid)" />
                      <XAxis dataKey="date" {...axis} tickFormatter={(d) => prettyDate(d)} minTickGap={40} />
                      <YAxis {...axis} width={50} />
                      <Tooltip {...tooltipStyle} labelFormatter={(d) => prettyDate(String(d), { weekday: 'short' })} formatter={(v, n) => [`${v}h`, n === 'planned' ? 'Planned' : 'Done']} />
                      <Line type="monotone" dataKey="planned" stroke="var(--chart-muted)" strokeWidth={2} strokeDasharray="4 4" dot={false} />
                      <Line type="monotone" dataKey="actual" stroke={seriesColor(i)} strokeWidth={2.5} dot={false} activeDot={{ r: 4 }} />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              ) : (
                <p className="mt-4 text-sm text-muted">Setup isn't finished — continue it in Claude →</p>
              )}
            </article>
          </Link>
        ))}
      </div>

      <div className="mt-12 grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card eyebrow="Trend" title="Weekly score">
          {data.week_scores.length ? (
            <div className="h-52">
              <ResponsiveContainer>
                <LineChart data={data.week_scores} margin={{ top: 8, right: 8, bottom: 0, left: -24 }}>
                  <CartesianGrid vertical={false} stroke="var(--chart-grid)" />
                  <XAxis dataKey="week" {...axis} tickFormatter={(d) => prettyDate(d)} minTickGap={30} />
                  <YAxis {...axis} domain={[0, 100]} ticks={[0, 50, 100]} />
                  <Tooltip {...tooltipStyle} labelFormatter={(d) => `Week of ${prettyDate(String(d))}`} formatter={(v) => [Math.round(Number(v)), 'Score']} />
                  <Line type="monotone" dataKey="score" stroke="var(--series-1)" strokeWidth={2.5} dot={{ r: 3, strokeWidth: 0, fill: 'var(--series-1)' }} activeDot={{ r: 5 }} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          ) : (
            <p className="text-sm text-muted">Your weekly scores appear here once you've logged some days.</p>
          )}
        </Card>
        <Card eyebrow="Effort" title="Hours per goal, by week">
          {weeklyHours.length ? (
            <div className="h-52">
              <ResponsiveContainer>
                <BarChart data={weeklyHours} margin={{ top: 8, right: 8, bottom: 0, left: -20 }}>
                  <CartesianGrid vertical={false} stroke="var(--chart-grid)" />
                  <XAxis dataKey="week" {...axis} tickFormatter={(d) => prettyDate(d)} />
                  <YAxis {...axis} allowDecimals={false} tickFormatter={(h) => `${h}h`} />
                  <Tooltip {...tooltipStyle} cursor={{ fill: 'var(--chart-grid)', opacity: 0.5 }} labelFormatter={(d) => `Week of ${prettyDate(String(d))}`} formatter={(v, n) => [fmtMinutes(Number(v) * 60), n]} />
                  <Legend iconType="circle" iconSize={8} wrapperStyle={{ fontSize: 11, color: 'var(--chart-text)' }} />
                  {goals.map((g) => (
                    <Bar key={g.id} dataKey={String(g.id)} name={g.title} stackId="effort" fill={seriesColor(goalIndex.get(String(g.id)) ?? 0)} stroke="var(--chart-surface)" strokeWidth={2} radius={[6, 6, 0, 0]} maxBarSize={36} />
                  ))}
                </BarChart>
              </ResponsiveContainer>
            </div>
          ) : (
            <p className="text-sm text-muted">Hours per goal appear after your first logged day.</p>
          )}
        </Card>
      </div>

      <Card eyebrow="Consistency" title="Last 18 weeks" className="mt-4">
        <Heatmap data={data.heatmap} />
      </Card>
    </>
  )
}
