import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../lib/api'
import { fmtMinutes } from '../lib/dates'
import type { Goal, RoadmapOut, TimeLog } from '../lib/types'
import { Button, ErrorText, Input, Select, cx } from './ui'

const CHOICES = [30, 60, 90, 120]

/** Add time straight from the app. Hours count at once, so a day still counts if you never open Claude. */
export default function QuickLog({ day, goals }: { day: string; goals: Pick<Goal, 'id' | 'title'>[] }) {
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const [minutes, setMinutes] = useState(60)
  const [goalId, setGoalId] = useState<number | null>(null)
  const [itemId, setItemId] = useState('')
  const [note, setNote] = useState('')
  const goal = goalId ?? goals[0]?.id
  const { data: logs = [] } = useQuery({ queryKey: ['time-logs', day], queryFn: () => api<TimeLog[]>(`/time-logs?day=${day}`) })
  const { data: roadmap } = useQuery({
    queryKey: ['roadmap', goal],
    queryFn: () => api<RoadmapOut>(`/goals/${goal}/roadmap`),
    enabled: open && !!goal,
  })
  const steps = (roadmap?.phases ?? []).flatMap((p) => p.items).filter((i) => i.status === 'todo' || i.status === 'in_progress')
  const refresh = () => qc.invalidateQueries()
  const add = useMutation({
    mutationFn: () =>
      api('/time-logs', { method: 'POST', json: { day, goal_id: goal, minutes, roadmap_item_id: itemId ? Number(itemId) : null, note } }),
    onSuccess: () => {
      setNote('')
      setOpen(false)
      refresh()
    },
  })
  const remove = useMutation({ mutationFn: (id: number) => api(`/time-logs/${id}`, { method: 'DELETE' }), onSuccess: refresh })
  if (!goals.length) return null
  const manual = logs.filter((l) => l.source === 'manual')
  return (
    <div className="rounded-3xl border border-line bg-surface p-5">
      <div className="flex items-center justify-between gap-3">
        <p className="text-sm">
          <span className="font-medium">Log time</span>
          {logs.length > 0 && <span className="text-muted"> · {fmtMinutes(logs.reduce((s, l) => s + l.minutes, 0))} added</span>}
        </p>
        <Button size="sm" variant="secondary" onClick={() => setOpen(!open)} aria-expanded={open}>
          {open ? 'Close' : 'Add time'}
        </Button>
      </div>
      {manual.length > 0 && (
        <ul className="mt-3 space-y-1 text-sm">
          {manual.map((l) => (
            <li key={l.id} className="flex items-center justify-between gap-3">
              <span className="min-w-0 truncate text-muted">
                {fmtMinutes(l.minutes)}
                {l.note && ` · ${l.note}`}
              </span>
              <button aria-label="Remove this time" className="px-1 text-muted hover:text-ink" onClick={() => remove.mutate(l.id)}>
                ✕
              </button>
            </li>
          ))}
        </ul>
      )}
      {open && (
        <form
          className="mt-4 space-y-3"
          onSubmit={(e) => {
            e.preventDefault()
            add.mutate()
          }}
        >
          <div className="flex flex-wrap items-center gap-2">
            {CHOICES.map((m) => (
              <button
                key={m}
                type="button"
                aria-pressed={minutes === m}
                onClick={() => setMinutes(m)}
                className={cx('rounded-full border px-3 py-1.5 text-sm transition', minutes === m ? 'border-accent bg-accent-soft text-accent-ink' : 'border-line hover:border-accent/40')}
              >
                {fmtMinutes(m)}
              </button>
            ))}
            <Input aria-label="Minutes" type="number" min={1} max={960} value={minutes} onChange={(e) => setMinutes(Number(e.target.value))} className="w-24" />
          </div>
          {goals.length > 1 && (
            <Select aria-label="Goal" value={goal} onChange={(e) => (setGoalId(Number(e.target.value)), setItemId(''))}>
              {goals.map((g) => (
                <option key={g.id} value={g.id}>
                  {g.title}
                </option>
              ))}
            </Select>
          )}
          <Select aria-label="Roadmap step" value={itemId} onChange={(e) => setItemId(e.target.value)}>
            <option value="">Which step? (optional)</option>
            {steps.map((s) => (
              <option key={s.id} value={s.id}>
                {s.title}
              </option>
            ))}
          </Select>
          <Input aria-label="Note" placeholder="What did you do? (optional)" value={note} onChange={(e) => setNote(e.target.value)} />
          <ErrorText error={add.error} />
          <Button type="submit" loading={add.isPending} disabled={minutes < 1}>
            Add {fmtMinutes(minutes)}
          </Button>
        </form>
      )}
    </div>
  )
}
