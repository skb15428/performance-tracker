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
    <li className={cx('rounded-xl px-3 py-2.5 ring-1 ring-zinc-100 dark:ring-zinc-800', item.status === 'done' && 'opacity-60')}>
      <button className="w-full text-left" onClick={() => setOpen(!open)}>
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-sm">{item.status === 'done' ? '✅' : item.status === 'skipped' ? '⏭️' : '⬜'}</span>
          <span className={cx('text-sm font-medium', item.status === 'skipped' && 'text-zinc-400 line-through')}>{item.title}</span>
          <Badge tone={typeTone[item.type]}>{item.type}</Badge>
          {item.source === 'trend' && <Badge tone="brand">new trend</Badge>}
          {item.status === 'in_progress' && <Badge tone="amber">in progress</Badge>}
          {overdue && <Badge tone="red">overdue</Badge>}
          {item.status !== 'done' && item.hours_logged >= item.est_hours && <Badge tone="red">over estimate</Badge>}
        </div>
        <div className="mt-1 flex items-center gap-3 pl-6 text-xs text-zinc-500">
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
          {item.description && <p className="text-zinc-600 dark:text-zinc-300">{item.description}</p>}
          {item.resources.length > 0 && (
            <ul className="space-y-1">
              {item.resources.map((r, i) => (
                <li key={i}>
                  {r.url ? (
                    <a className="text-brand-600 hover:underline dark:text-brand-400" href={r.url} target="_blank" rel="noreferrer">
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

function Roadmap({ goalId }: { goalId: number }) {
  const { data, isLoading } = useQuery({ queryKey: ['roadmap', goalId], queryFn: () => api<RoadmapOut>(`/goals/${goalId}/roadmap`) })
  if (isLoading || !data) return <Loading />
  if (!data.phases.length) return <EmptyState title="No roadmap yet" />
  return (
    <div className="space-y-4">
      {data.phases.map((phase, i) => (
        <Card
          key={phase.id}
          title={
            <span>
              <span className="mr-2 text-xs text-zinc-400">PHASE {i + 1}</span>
              {phase.title}
            </span>
          }
          action={
            <span className="text-xs text-zinc-500 tabular-nums">
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
          <li key={step} className={done[i] ? '' : 'text-zinc-500'}>
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
      <Link to="/goals" className="text-sm text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200">
        ← Goals
      </Link>
      <div className="mt-2 mb-4 flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-2xl font-bold tracking-tight">{goal.title}</h1>
          <div className="mt-2 flex flex-wrap items-center gap-2 text-sm text-zinc-500">
            {intakeLabel(goal)}
            {goal.target_date && <span>Target {prettyDate(goal.target_date, { year: 'numeric' })}</span>}
          </div>
        </div>
        <div className="w-40">
          <div className="mb-1 text-right text-xs text-zinc-500 tabular-nums">{Math.round(goal.progress_pct)}% done</div>
          <ProgressBar value={goal.progress_pct} />
        </div>
      </div>

      <ReplanBanner goalId={goal.id} />

      <div className="space-y-4">
        {goal.intake_status !== 'active' && <IntakeProgress goal={goal} />}

        {(goal.statement || goal.routine.length > 0) && (
          <Card>
            {goal.statement && <p className="font-medium">{goal.statement}</p>}
            {goal.success_criteria.length > 0 && (
              <ul className="mt-1 list-disc pl-5 text-sm text-zinc-600 dark:text-zinc-300">
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
                <ul className="mt-1 space-y-0.5 text-xs text-zinc-500">
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
