import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import OpenClaude from '../components/OpenClaude'
import ReplanBanner from '../components/ReplanBanner'
import { Badge, Card, EmptyState, ErrorText, Loading, ProgressBar, cx } from '../components/ui'
import { api } from '../lib/api'
import { prettyDate, todayIso } from '../lib/dates'
import type { Goal, RoadmapItem, RoadmapOut } from '../lib/types'
import { intakeLabel } from './Goals'

const typeTone = { topic: 'brand', skill: 'green', task: 'amber', milestone: 'red' } as const
const INTAKE_STEPS = ['Exact goal', 'Roadmap', 'Timeline + daily routine'] as const

function ItemRow({ item }: { item: RoadmapItem }) {
  const [open, setOpen] = useState(false)
  const overdue = item.planned_due && item.planned_due < todayIso() && !['done', 'skipped'].includes(item.status)
  const pct = Math.min((item.hours_logged / item.est_hours) * 100, 100)
  return (
    <li className={cx('rounded-2xl px-4 py-3 ring-1 ring-line', item.status === 'done' && 'opacity-60')}>
      <button className="w-full text-left" onClick={() => setOpen(!open)}>
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-sm">{item.status === 'done' ? '✅' : item.status === 'skipped' ? '⏭️' : '⬜'}</span>
          <span className={cx('text-sm font-medium', item.status === 'skipped' && 'text-muted line-through')}>{item.title}</span>
          <Badge tone={typeTone[item.type]}>{item.type}</Badge>
          {item.source === 'trend' && <Badge tone="brand">new trend</Badge>}
          {item.status === 'in_progress' && <Badge tone="amber">in progress</Badge>}
          {overdue && <Badge tone="red">overdue</Badge>}
          {item.status !== 'done' && item.hours_logged >= item.est_hours && <Badge tone="red">over estimate</Badge>}
        </div>
        <div className="mt-1 flex items-center gap-3 pl-6 text-xs text-muted">
          <span className="tabular-nums">
            {item.hours_logged.toFixed(1)} / {item.est_hours}h
          </span>
          <ProgressBar value={pct} className="max-w-24" />
          <span className="tabular-nums">
            {prettyDate(item.planned_start)} – {prettyDate(item.planned_due)}
          </span>
        </div>
      </button>
      {open && (item.description || item.resources.length > 0) && (
        <div className="mt-2 space-y-2 pl-6 text-sm">
          {item.description && <p className="text-muted">{item.description}</p>}
          {item.resources.length > 0 && (
            <ul className="space-y-1">
              {item.resources.map((r, i) => (
                <li key={i}>
                  {r.url ? (
                    <a className="text-accent-ink hover:underline" href={r.url} target="_blank" rel="noreferrer">
                      {r.title || r.url} ↗
                    </a>
                  ) : (
                    r.title
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </li>
  )
}

function phaseProgress(items: RoadmapItem[]) {
  const live = items.filter((i) => i.status !== 'skipped')
  const total = live.reduce((s, i) => s + i.est_hours, 0)
  const done = live.reduce((s, i) => s + (i.status === 'done' ? i.est_hours : Math.min(i.hours_logged, i.est_hours)), 0)
  return { total, done, pct: total ? Math.round((done / total) * 100) : 0 }
}

function Journey({ phases }: { phases: RoadmapOut['phases'] }) {
  const progress = phases.map((p) => phaseProgress(p.items))
  const current = progress.findIndex((p) => p.pct < 100)
  return (
    <div className="rise overflow-x-auto rounded-3xl border border-line bg-surface p-5 sm:p-6">
      <p className="mb-5 text-[11px] font-semibold tracking-[0.14em] text-muted uppercase">Your journey</p>
      <ol className="flex min-w-max gap-0">
        {phases.map((phase, i) => {
          const pr = progress[i]
          const state = pr.pct >= 100 ? 'done' : i === current ? 'current' : 'later'
          const milestones = phase.items.filter((it) => it.type === 'milestone')
          return (
            <li key={phase.id} className="relative w-56 shrink-0 pr-4 sm:w-64">
              <div className="mb-4 flex items-center">
                <span
                  className={cx(
                    'relative z-10 flex size-9 shrink-0 items-center justify-center rounded-full text-sm font-semibold',
                    state === 'done' && 'bg-emerald-500 text-white',
                    state === 'current' && 'bg-ink text-canvas ring-4 ring-accent-soft',
                    state === 'later' && 'border border-line bg-surface text-muted',
                  )}
                >
                  {state === 'done' ? '✓' : i + 1}
                </span>
                {i < phases.length - 1 && (
                  <span className={cx('h-0.5 flex-1', state === 'done' ? 'bg-emerald-500' : 'bg-line')} />
                )}
              </div>
              {state === 'current' && <span className="mb-2 inline-block rounded-full bg-accent-soft px-2.5 py-0.5 text-[11px] font-semibold text-accent-ink">You are here</span>}
              <p className={cx('font-display text-xl leading-tight', state === 'later' && 'text-muted')}>{phase.title.replace(/^Phase \d+\s*[—–-]\s*/, '')}</p>
              <p className="mt-1 text-xs text-muted tabular-nums">
                {prettyDate(phase.start_date)} – {prettyDate(phase.due_date, { year: '2-digit' })}
              </p>
              <div className="mt-3 flex items-center gap-2">
                <ProgressBar value={pr.pct} className="h-1" />
                <span className="text-[11px] text-muted tabular-nums">{pr.pct}%</span>
              </div>
              <p className="mt-2 text-xs text-muted">
                {phase.items.length} items · {Math.round(pr.total)}h
              </p>
              {milestones.map((m) => (
                <p key={m.id} className="mt-1.5 flex gap-1.5 text-xs">
                  <span className={m.status === 'done' ? 'text-emerald-500' : 'text-[#ff8a5c]'}>◆</span>
                  <span className={cx(m.status === 'done' && 'text-muted line-through')}>{m.title}</span>
                </p>
              ))}
            </li>
          )
        })}
      </ol>
    </div>
  )
}

function Roadmap({ goalId }: { goalId: number }) {
  const { data, isLoading } = useQuery({ queryKey: ['roadmap', goalId], queryFn: () => api<RoadmapOut>(`/goals/${goalId}/roadmap`) })
  if (isLoading || !data) return <Loading />
  if (!data.phases.length) return <EmptyState title="No roadmap yet" />
  return (
    <div className="space-y-4">
      <Journey phases={data.phases} />
      {data.phases.map((phase, i) => (
        <Card
          key={phase.id}
          title={
            <span>
              <span className="mr-2 text-xs text-muted">PHASE {i + 1}</span>
              {phase.title}
            </span>
          }
          action={
            <span className="text-xs text-muted tabular-nums">
              {phase.items.filter((it) => it.status === 'done').length}/{phase.items.length} · {prettyDate(phase.start_date)} –{' '}
              {prettyDate(phase.due_date)}
            </span>
          }
        >
          <ul className="space-y-2">
            {phase.items.map((item) => (
              <ItemRow key={item.id} item={item} />
            ))}
          </ul>
        </Card>
      ))}
    </div>
  )
}

function IntakeProgress({ goal }: { goal: Goal }) {
  const done = [!!goal.statement, goal.intake_status === 'commitment_pending' || goal.intake_status === 'active', goal.intake_status === 'active']
  return (
    <Card title="Goal setup">
      <ol className="mb-4 space-y-1 text-sm">
        {INTAKE_STEPS.map((step, i) => (
          <li key={step} className={done[i] ? '' : 'text-muted'}>
            {done[i] ? '✅' : '⬜'} {i + 1}. {step}
          </li>
        ))}
      </ol>
      <OpenClaude message={`Let's continue setting up my goal "${goal.title}".`}>Continue in Claude</OpenClaude>
    </Card>
  )
}

export default function GoalDetail() {
  const id = Number(useParams().id)
  const { data: goal, isLoading, error } = useQuery({ queryKey: ['goal', id], queryFn: () => api<Goal>(`/goals/${id}`) })

  if (isLoading) return <Loading />
  if (!goal) return <ErrorText error={error ?? 'Goal not found'} />
  const hasRoadmap = goal.intake_status === 'active' || goal.intake_status === 'commitment_pending' || goal.intake_status === 'roadmap_proposed'

  return (
    <>
      <Link to="/goals" className="text-sm text-muted hover:text-ink">
        ← Goals
      </Link>
      <div className="mt-2 mb-4 flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="font-display text-4xl leading-[1.05] tracking-tight sm:text-5xl">{goal.title}</h1>
          <div className="mt-2 flex flex-wrap items-center gap-2 text-sm text-muted">
            {intakeLabel(goal)}
            {goal.target_date && <span>Target {prettyDate(goal.target_date, { year: 'numeric' })}</span>}
          </div>
        </div>
        <div className="w-40">
          <div className="mb-1 text-right text-xs text-muted tabular-nums">{Math.round(goal.progress_pct)}% done</div>
          <ProgressBar value={goal.progress_pct} />
        </div>
      </div>

      <ReplanBanner goalId={goal.id} />

      <div className="space-y-4">
        {goal.intake_status !== 'active' && <IntakeProgress goal={goal} />}

        {(goal.statement || goal.routine.length > 0) && (
          <Card>
            {goal.statement && <p className="font-display text-2xl leading-snug">{goal.statement}</p>}
            {goal.success_criteria.length > 0 && (
              <ul className="mt-1 list-disc pl-5 text-sm text-muted">
                {goal.success_criteria.map((c, i) => (
                  <li key={i}>{c}</li>
                ))}
              </ul>
            )}
            {goal.hours_per_day && (
              <div className="mt-3 text-sm">
                <span className="font-medium">
                  Routine: {goal.hours_per_day}h × {goal.days_per_week} days/week
                </span>
                <ul className="mt-1 space-y-0.5 text-xs text-muted">
                  {goal.routine.map((b, i) => (
                    <li key={i} className="tabular-nums">
                      {b.days.map((d) => d[0].toUpperCase() + d.slice(1)).join(', ')} · {b.start}–{b.end} · {b.activity}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            <div className="mt-4">
              <OpenClaude variant="secondary" message={`I want to change something about my goal "${goal.title}".`}>
                Change goal, roadmap or routine in Claude
              </OpenClaude>
            </div>
          </Card>
        )}

        {hasRoadmap && <Roadmap goalId={goal.id} />}
      </div>
    </>
  )
}
