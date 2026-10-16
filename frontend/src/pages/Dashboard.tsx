import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import OpenClaude from '../components/OpenClaude'
import ReplanBanner from '../components/ReplanBanner'
import { Button, Card, EmptyState, ErrorText, Loading, PageHeader, ProgressBar, ScoreRing, TimelineBadge, cx } from '../components/ui'
import { api } from '../lib/api'
import { addDays, fmtMinutes, prettyDate, todayIso } from '../lib/dates'
import type { Dashboard as DashboardData } from '../lib/types'

export const seriesColor = (i: number) => `var(--series-${(i % 8) + 1})`
const axis = { stroke: 'var(--chart-axis)', fontSize: 11, tickLine: false, axisLine: false }
const tooltipStyle = {
  contentStyle: {
    background: 'var(--chart-surface)',
    border: '1px solid var(--chart-grid)',
    borderRadius: 10,
    fontSize: 12,
    color: 'var(--chart-text)',
  },
  labelStyle: { color: 'var(--chart-text)', fontWeight: 600 },
  itemStyle: { color: 'var(--chart-text)' },
}

function Stat({ label, value, sub }: { label: string; value: React.ReactNode; sub?: React.ReactNode }) {
  return (
    <Card className="!p-4">
      <p className="text-xs font-medium text-zinc-500">{label}</p>
      <p className="mt-1 text-2xl font-bold tabular-nums">{value}</p>
      {sub && <p className="mt-0.5 text-xs text-zinc-500">{sub}</p>}
    </Card>
  )
}

function Heatmap({ data }: { data: { date: string; score: number; rest?: boolean }[] }) {
  const byDate = new Map(data.map((d) => [d.date, d.score]))
  const rest = new Set(data.filter((d) => d.rest).map((d) => d.date))
  const today = todayIso()
  // 18 weeks ending this week, columns = weeks (Mon..Sun rows)
  const end = new Date(`${today}T12:00:00`)
  const offset = (end.getDay() + 6) % 7
  const start = addDays(today, -offset - 17 * 7)
  const weeks = Array.from({ length: 18 }, (_, w) => Array.from({ length: 7 }, (_, d) => addDays(start, w * 7 + d)))
  const level = (s: number | undefined) => (s === undefined ? -1 : s < 25 ? 1 : s < 50 ? 2 : s < 75 ? 3 : 4)
  return (
    <div>
      <div className="flex gap-[3px] overflow-x-auto pb-1">
        {weeks.map((week, wi) => (
          <div key={wi} className="flex flex-col gap-[3px]">
            {week.map((d) => {
              const isRest = rest.has(d)
              const s = isRest ? undefined : byDate.get(d)
              const l = level(s)
              return (
                <div
                  key={d}
                  title={d > today ? '' : `${prettyDate(d, { weekday: 'short' })}: ${isRest ? 'rest day' : s === undefined ? 'not logged' : `score ${Math.round(s)}`}`}
                  className={cx('size-3 rounded-[3px]', d > today && 'opacity-0', isRest && 'ring-1 ring-inset ring-[var(--chart-muted)]')}
                  style={{ background: isRest ? 'transparent' : l < 0 ? 'var(--chart-grid)' : `var(--seq-${l})` }}
                />
              )
            })}
          </div>
        ))}
      </div>
      <div className="mt-2 flex items-center gap-1 text-[10px] text-zinc-500">
        Less
        {[-1, 1, 2, 3, 4].map((l) => (
          <span key={l} className="size-2.5 rounded-[2px]" style={{ background: l < 0 ? 'var(--chart-grid)' : `var(--seq-${l})` }} />
        ))}
        More
      </div>
    </div>
  )
}

export default function Dashboard() {
  const qc = useQueryClient()
  const { data, isLoading, error } = useQuery({ queryKey: ['dashboard'], queryFn: () => api<DashboardData>('/dashboard/summary') })
  const togglePlan = useMutation({
    mutationFn: ({ id, done }: { id: number; done: boolean }) => api(`/plan/${id}`, { method: 'PATCH', json: { status: done ? 'done' : 'open' } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['dashboard'] }),
  })

  if (isLoading) return <Loading />
  if (!data) return <ErrorText error={error} />

  const today = todayIso()
  const loggedToday = data.latest?.date === today
  const goals = data.goals.filter((g) => g.intake_status === 'active')
  const goalIndex = new Map(data.goals.map((g, i) => [String(g.id), i]))
  const weeklyHours = data.weekly_effort.map(({ week, ...rest }) => ({
    week,
    ...Object.fromEntries(Object.entries(rest).map(([k, v]) => [k, Math.round((Number(v) / 60) * 10) / 10])),
  }))

  if (!data.goals.length)
    return (
      <>
        <PageHeader title="Welcome to GoalCoach" />
        <EmptyState title="Start by adding a goal">
          Your coach lives in Claude: tell it what you're aiming for. It agrees the exact goal, a roadmap and a daily routine with you, then scores every day against it. Everything shows up here.
          <div className="mt-4">
            <OpenClaude message="New goal: ">Add a goal in Claude</OpenClaude>
          </div>
        </EmptyState>
      </>
    )

  return (
    <>
      <PageHeader
        title="Today"
        subtitle={prettyDate(today, { weekday: 'long', year: 'numeric' })}
        action={
          loggedToday ? (
            <Link to="/log">
              <Button variant="secondary">View today’s review</Button>
            </Link>
          ) : (
            <OpenClaude message="Log my day">Log today in Claude</OpenClaude>
          )
        }
      />
      <ReplanBanner />

      {data.weekly_focus.length > 0 && (
        <div className="mb-4 rounded-2xl bg-brand-50 px-4 py-3 dark:bg-brand-700/20">
          <p className="mb-1 text-xs font-semibold text-brand-700 uppercase dark:text-brand-100">This week's focus</p>
          <ul className="space-y-0.5 text-sm">
            {data.weekly_focus.map((f, i) => (
              <li key={i}>• {f}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="Latest score" value={data.latest ? Math.round(data.latest.score) : '—'} sub={data.latest ? prettyDate(data.latest.date, { weekday: 'short' }) : 'No days logged'} />
        <Stat label="Streak" value={`${data.streak}d`} sub="consecutive days logged" />
        <Stat label="Plan adherence" value={data.adherence_avg !== null ? `${Math.round(data.adherence_avg * 100)}%` : '—'} sub="last 30 days" />
        <Link to="/trends">
          <Stat label="What's new" value={data.new_trends} sub="suggestions to review" />
        </Link>
      </div>

      <div className="grid gap-4 lg:grid-cols-5">
        <Card title="Today's plan" className="lg:col-span-3">
          {data.today_plan.length ? (
            <ul className="space-y-1.5">
              {data.today_plan.map((p) => (
                <li key={p.id} className="flex items-center gap-3">
                  <input
                    type="checkbox"
                    className="size-4 accent-brand-600"
                    checked={p.status === 'done'}
                    onChange={(e) => togglePlan.mutate({ id: p.id, done: e.target.checked })}
                    aria-label="Done"
                  />
                  <span className="w-24 shrink-0 text-xs text-zinc-500 tabular-nums">{p.time_block || fmtMinutes(p.minutes)}</span>
                  <span className={cx('text-sm', p.status === 'done' && 'text-zinc-400 line-through')}>{p.title}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-zinc-500">No plan for today yet. Log tonight and the coach will plan tomorrow.</p>
          )}
        </Card>
        <Card title="Last review" className="lg:col-span-2">
          {data.latest ? (
            <div className="flex gap-4">
              <ScoreRing score={data.latest.score} size={84} />
              <div className="min-w-0 flex-1 space-y-1.5 text-sm">
                {Object.entries(data.latest.per_goal).map(([id, g]) => (
                  <div key={id} className="flex items-center gap-2">
                    <span className="size-2 shrink-0 rounded-full" style={{ background: seriesColor(goalIndex.get(id) ?? 0) }} />
                    <span className="flex-1 truncate">{g.title}</span>
                    <span className="text-xs text-zinc-500 tabular-nums">{g.score.toFixed(1)}/10</span>
                  </div>
                ))}
                {data.latest.explanation && <p className="pt-1 text-xs text-zinc-500 tabular-nums">{data.latest.explanation}</p>}
                {data.latest.tip && <p className="pt-1 text-xs text-zinc-500">💡 {data.latest.tip}</p>}
              </div>
            </div>
          ) : (
            <p className="text-sm text-zinc-500">Your first review will show here.</p>
          )}
        </Card>
      </div>

      <h2 className="mt-8 mb-3 text-sm font-semibold text-zinc-700 dark:text-zinc-200">Goals: planned vs actual hours</h2>
      <div className="grid gap-4 sm:grid-cols-2">
        {data.goals.map((g, i) => (
          <Link key={g.id} to={`/goals/${g.id}`}>
            <Card className="h-full transition hover:ring-brand-400">
              <div className="mb-2 flex items-start justify-between gap-2">
                <div className="flex min-w-0 items-center gap-2">
                  <span className="size-2.5 shrink-0 rounded-full" style={{ background: seriesColor(i) }} />
                  <h3 className="truncate font-semibold">{g.title}</h3>
                </div>
                <TimelineBadge timeline={g.intake_status === 'active' ? g.timeline : null} />
              </div>
              <div className="mb-3 flex items-center gap-3">
                <ProgressBar value={g.progress_pct} />
                <span className="text-xs text-zinc-500 tabular-nums">{Math.round(g.progress_pct)}%</span>
              </div>
              {g.insight && (
                <p className="mb-2 text-xs text-zinc-500 tabular-nums">
                  {g.insight.actual_hours_per_week}h/week of {g.insight.planned_hours_per_week}h planned
                  {g.insight.forecast_finish_at_actual_pace && (
                    <>
                      {' · at this pace: '}
                      <span className={g.insight.forecast_misses_target ? 'font-medium text-red-600 dark:text-red-400' : ''}>
                        {prettyDate(g.insight.forecast_finish_at_actual_pace, { year: 'numeric' })}
                      </span>
                      {g.insight.target_date && ` (target ${prettyDate(g.insight.target_date, { year: 'numeric' })})`}
                    </>
                  )}
                </p>
              )}
              {g.intake_status === 'active' ? (
                <div className="h-28">
                  <ResponsiveContainer>
                    <LineChart data={g.burnup} margin={{ top: 4, right: 4, bottom: 0, left: -28 }}>
                      <CartesianGrid vertical={false} stroke="var(--chart-grid)" />
                      <XAxis dataKey="date" {...axis} tickFormatter={(d) => prettyDate(d)} minTickGap={40} />
                      <YAxis {...axis} width={50} />
                      <Tooltip {...tooltipStyle} labelFormatter={(d) => prettyDate(String(d), { weekday: 'short' })} formatter={(v, n) => [`${v}h`, n === 'planned' ? 'Planned' : 'Actual']} />
                      <Line type="monotone" dataKey="planned" stroke="var(--chart-muted)" strokeWidth={2} strokeDasharray="4 4" dot={false} />
                      <Line type="monotone" dataKey="actual" stroke={seriesColor(i)} strokeWidth={2} dot={false} activeDot={{ r: 4 }} />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              ) : (
                <p className="text-sm text-zinc-500">Goal setup isn't finished: continue it in Claude →</p>
              )}
            </Card>
          </Link>
        ))}
      </div>

      <div className="mt-6 grid gap-4 lg:grid-cols-2">
        <Card title="Daily score (30 days)">
          {data.scores.length ? (
            <div className="h-48">
              <ResponsiveContainer>
                <LineChart data={data.scores} margin={{ top: 8, right: 8, bottom: 0, left: -24 }}>
                  <CartesianGrid vertical={false} stroke="var(--chart-grid)" />
                  <XAxis dataKey="date" {...axis} tickFormatter={(d) => prettyDate(d)} minTickGap={30} />
                  <YAxis {...axis} domain={[0, 100]} ticks={[0, 50, 100]} />
                  <Tooltip {...tooltipStyle} labelFormatter={(d) => prettyDate(String(d), { weekday: 'short' })} formatter={(v) => [Math.round(Number(v)), 'Score']} />
                  <Line type="monotone" dataKey="score" stroke="var(--series-1)" strokeWidth={2} dot={{ r: 3, strokeWidth: 0, fill: 'var(--series-1)' }} activeDot={{ r: 5 }} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          ) : (
            <p className="text-sm text-zinc-500">Log a few days to see your trend.</p>
          )}
        </Card>
        <Card title="Weekly effort by goal">
          {data.weekly_effort.length ? (
            <div className="h-48">
              <ResponsiveContainer>
                <BarChart data={weeklyHours} margin={{ top: 8, right: 8, bottom: 0, left: -20 }}>
                  <CartesianGrid vertical={false} stroke="var(--chart-grid)" />
                  <XAxis dataKey="week" {...axis} tickFormatter={(d) => prettyDate(d)} />
                  <YAxis {...axis} allowDecimals={false} tickFormatter={(h) => `${h}h`} />
                  <Tooltip {...tooltipStyle} cursor={{ fill: 'var(--chart-grid)', opacity: 0.5 }} labelFormatter={(d) => `Week of ${prettyDate(String(d))}`} formatter={(v, n) => [fmtMinutes(Number(v) * 60), n]} />
                  <Legend iconType="circle" iconSize={8} wrapperStyle={{ fontSize: 11, color: 'var(--chart-text)' }} />
                  {goals.map((g) => (
                    <Bar
                      key={g.id}
                      dataKey={String(g.id)}
                      name={g.title}
                      stackId="effort"
                      fill={seriesColor(goalIndex.get(String(g.id)) ?? 0)}
                      stroke="var(--chart-surface)"
                      strokeWidth={2}
                      maxBarSize={36}
                    />
                  ))}
                </BarChart>
              </ResponsiveContainer>
            </div>
          ) : (
            <p className="text-sm text-zinc-500">Effort per goal appears after your first logged day.</p>
          )}
        </Card>
      </div>

      <Card title="Consistency" className="mt-4">
        <Heatmap data={data.heatmap} />
      </Card>
    </>
  )
}
