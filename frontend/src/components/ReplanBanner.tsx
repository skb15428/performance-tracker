import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../lib/api'
import { prettyDate } from '../lib/dates'
import type { Replan } from '../lib/types'
import { Badge, Button, ErrorText } from './ui'

const STRATEGY: Record<string, string> = {
  shift: 'Reschedule remaining work',
  reduce_scope: 'Cut low-value items',
  increase_hours: 'Add more hours per day',
}

export default function ReplanBanner({ goalId }: { goalId?: number }) {
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const { data } = useQuery({ queryKey: ['replans'], queryFn: () => api<Replan[]>('/replans') })
  const act = useMutation({
    mutationFn: ({ id, action }: { id: number; action: 'accept' | 'reject' }) => api(`/replans/${id}/${action}`, { method: 'POST' }),
    onSuccess: () => qc.invalidateQueries(),
  })
  const proposals = (data ?? []).filter((p) => goalId === undefined || p.goal_id === goalId)
  if (!proposals.length) return null

  return (
    <div className="mb-5 space-y-3">
      {proposals.map((p) => (
        <div key={p.id} className="rounded-2xl bg-amber-50 p-4 ring-1 ring-amber-200 dark:bg-amber-950/40 dark:ring-amber-900">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0 flex-1">
              <p className="font-semibold text-amber-900 dark:text-amber-200">
                {p.diff.status?.state === 'behind' ? "You're falling behind. Proposed fix: " : 'Schedule update: '}
                {STRATEGY[p.diff.strategy] ?? p.diff.strategy}
              </p>
              <p className="mt-1 text-sm text-amber-900/80 dark:text-amber-200/80">{p.reason}</p>
              <p className="mt-2 text-xs text-amber-900/70 dark:text-amber-200/70">
                New finish: <b>{prettyDate(p.diff.new_finish_date, { year: 'numeric' })}</b>
                {p.diff.target_date && <> · target {prettyDate(p.diff.target_date, { year: 'numeric' })}</>} · {p.diff.goal_hours_per_day}h/day
                {p.diff.daily_available_hours && <> · daily budget → {p.diff.daily_available_hours}h</>}
              </p>
            </div>
            <div className="flex gap-2">
              <Button size="sm" variant="secondary" onClick={() => setOpen(!open)}>
                {open ? 'Hide' : 'See'} changes ({p.diff.changes.length})
              </Button>
              <Button size="sm" variant="ghost" loading={act.isPending} onClick={() => act.mutate({ id: p.id, action: 'reject' })}>
                Reject
              </Button>
              <Button size="sm" loading={act.isPending} onClick={() => act.mutate({ id: p.id, action: 'accept' })}>
                Accept
              </Button>
            </div>
          </div>
          {open && (
            <ul className="mt-3 max-h-60 space-y-1 overflow-auto text-sm">
              {p.diff.changes.map((c) => (
                <li key={c.item_id} className="flex flex-wrap items-center gap-2">
                  {c.action === 'skip' ? <Badge tone="red">skip</Badge> : <Badge>move</Badge>}
                  <span className="flex-1">{c.title}</span>
                  <span className="text-xs text-zinc-500 tabular-nums">
                    {prettyDate(c.old_due)} → {c.action === 'skip' ? '—' : prettyDate(c.new_due)}
                  </span>
                </li>
              ))}
            </ul>
          )}
          <ErrorText error={act.error} />
        </div>
      ))}
    </div>
  )
}
