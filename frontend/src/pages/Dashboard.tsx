import { useQuery } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import OpenClaude from '../components/OpenClaude'
import ReplanBanner from '../components/ReplanBanner'
import TaskCard from '../components/TaskCard'
import { Button, Card, EmptyState, ErrorText, Loading, PageHeader, ProgressBar, ScoreRing, TimelineBadge, cx } from '../components/ui'
import { api } from '../lib/api'
import { addDays, fmtMinutes, prettyDate, todayIso } from '../lib/dates'
import type { Dashboard as DashboardData, Settings, WeekDay } from '../lib/types'

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

const WEEK_STYLE: Record<WeekDay['state'], { ring: string; label: string }> = {
  done: { ring: 'bg-emerald-500 text-white', label: 'Logged' },
  rest: { ring: 'bg-surface-2 text-muted', label: 'Rest' },
  missed: { ring: 'bg-red-500/15 text-red-600 dark:text-red-300', label: 'Missed' },
  today: { ring: 'bg-ink text-canvas', label: 'Today' },
  upcoming: { ring: 'border border-dashed border-line text-muted', label: 'Planned' },
}

function WeekStrip({ week }: { week: WeekDay[] }) {
  return (
    <div className="rise grid grid-cols-7 gap-1.5 rounded-3xl border border-line bg-surface p-2 sm:gap-3 sm:p-3">
      {week.map((d) => {
        const style = WEEK_STYLE[d.state]
        const date = new Date(`${d.date}T12:00:00`)
        return (
          <div
            key={d.date}
            title={`${prettyDate(d.date, { weekday: 'long' })}: ${style.label}${d.score !== null ? ` · score ${Math.round(d.score)}` : ''}${d.planned_minutes ? ` · ${fmtMinutes(d.planned_minutes)} planned` : ''}`}
            className={cx('flex flex-col items-center gap-1.5 rounded-2xl py-2 sm:py-3', d.is_today && 'bg-accent-soft')}
          >
            <span className="text-[10px] font-semibold tracking-wider text-muted uppercase">
              {date.toLocaleDateString(undefined, { weekday: 'short' }).slice(0, 2)}
            </span>
            <span className={cx('flex size-9 items-center justify-center rounded-full text-sm font-semibold tabular-nums sm:size-10', style.ring)}>
              {date.getDate()}
            </span>
            <span className="text-[10px] text-muted tabular-nums">
              {d.score !== null ? Math.round(d.score) : <span className="hidden sm:inline">{style.label}</span>}
              {d.score === null && <span className="sm:hidden">&nbsp;</span>}
            </span>
          </div>
        )
      })}
    </div>
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

function Heatmap({ data }: { data: { date: string; score: number; rest?: boolean }[] }) {
  const byDate = new Map(data.map((d) => [d.date, d.score]))
  const rest = new Set(data.filter((d) => d.rest).map((d) => d.date))
  const today = todayIso()
  const offset = (new Date(`${today}T12:00:00`).getDay() + 6) % 7
  const start = addDays(today, -offset - 17 * 7)
  const weeks = Array.from({ length: 18 }, (_, w) => Array.from({ length: 7 }, (_, d) => addDays(start, w * 7 + d)))
  const level = (s: number | undefined) => (s === undefined ? -1 : s < 25 ? 1 : s < 50 ? 2 : s < 75 ? 3 : 4)
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
                  title={d > today ? '' : `${prettyDate(d, { weekday: 'short' })}: ${isRest ? 'rest day' : s === undefined ? 'not logged' : `score ${Math.round(s)}`}`}
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

  if (isLoading) return <Loading />
  if (!data) return <ErrorText error={error} />

  const today = data.today ?? todayIso()
  const loggedToday = data.latest?.date === today
  const goals = data.goals.filter((g) => g.intake_status === 'active')
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

  return (
    <>
      <PageHeader
        eyebrow={prettyDate(today, { weekday: 'long', month: 'long', day: 'numeric' })}
        title={
          <>
            {greeting()}
            {firstName ? (
              <>
                , <span className="gradient-text italic">{firstName}</span>
              </>
            ) : null}
          </>
        }
        subtitle={data.today_plan.length ? `${data.today_plan.length} block${data.today_plan.length > 1 ? 's' : ''} planned today.` : undefined}
        action={
          loggedToday ? (
            <Link to="/log">
              <Button variant="secondary">View today's review</Button>
            </Link>
          ) : (
            <OpenClaude message="Log my day">Log today in Claude</OpenClaude>
          )
        }
      />
      <ReplanBanner />

      <div className="mb-4 grid grid-cols-1 gap-4 lg:grid-cols-5">
        <div className="lg:col-span-3">
          <WeekStrip week={data.week} />
        </div>
        <div className="lg:col-span-2">{data.today_plan.length > 0 && <DayProgress plan={data.today_plan} />}</div>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        {/* Today's plan: the hero */}
        <div className="min-w-0 space-y-4 lg:col-span-2">
          {data.today_plan.length ? (
            data.today_plan.map((p) => <TaskCard key={p.id} block={p} goalTitle={goalTitle(p.goal_id)} />)
          ) : (
            <div className="flex h-full flex-col justify-between rounded-3xl border border-line bg-surface p-7">
              <div>
                <p className="text-[11px] font-semibold tracking-[0.14em] text-muted uppercase">Today's plan</p>
                <p className="mt-3 font-display text-3xl leading-tight">Nothing planned yet.</p>
                <p className="mt-2 text-sm text-muted">Ask Claude and it builds today's blocks from your routine and roadmap.</p>
              </div>
              <div className="mt-6">
                <OpenClaude message="What's my plan today?">Get today's plan in Claude</OpenClaude>
              </div>
            </div>
          )}
        </div>

        {/* Score */}
        <Card eyebrow="Last review" title={data.latest ? prettyDate(data.latest.date, { weekday: 'long' }) : undefined}>
          {data.latest ? (
            <>
              <div className="flex items-center gap-5">
                <ScoreRing score={data.latest.score} size={112} />
                <div className="min-w-0 space-y-2 text-sm">
                  {Object.entries(data.latest.per_goal).map(([id, g]) => (
                    <div key={id}>
                      <div className="flex items-center gap-2">
                        <span className="size-2 shrink-0 rounded-full" style={{ background: seriesColor(goalIndex.get(id) ?? 0) }} />
                        <span className="truncate">{g.title}</span>
                      </div>
                      <p className="pl-4 text-xs text-muted tabular-nums">{g.score.toFixed(1)} / 10</p>
                    </div>
                  ))}
                </div>
              </div>
              {data.latest.explanation && <p className="mt-4 rounded-2xl bg-surface-2 px-3 py-2 text-xs text-muted tabular-nums">{data.latest.explanation}</p>}
              {data.latest.tip && <p className="mt-3 text-sm">💡 {data.latest.tip}</p>}
            </>
          ) : (
            <p className="text-sm text-muted">Your first score appears after you log a day in Claude.</p>
          )}
        </Card>
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
        <Card eyebrow="Trend" title="Daily score · 30 days">
          {data.scores.length ? (
            <div className="h-52">
              <ResponsiveContainer>
                <LineChart data={data.scores} margin={{ top: 8, right: 8, bottom: 0, left: -24 }}>
                  <CartesianGrid vertical={false} stroke="var(--chart-grid)" />
                  <XAxis dataKey="date" {...axis} tickFormatter={(d) => prettyDate(d)} minTickGap={30} />
                  <YAxis {...axis} domain={[0, 100]} ticks={[0, 50, 100]} />
                  <Tooltip {...tooltipStyle} labelFormatter={(d) => prettyDate(String(d), { weekday: 'short' })} formatter={(v) => [Math.round(Number(v)), 'Score']} />
                  <Line type="monotone" dataKey="score" stroke="var(--series-1)" strokeWidth={2.5} dot={{ r: 3, strokeWidth: 0, fill: 'var(--series-1)' }} activeDot={{ r: 5 }} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          ) : (
            <p className="text-sm text-muted">Log a few days to see your trend.</p>
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
