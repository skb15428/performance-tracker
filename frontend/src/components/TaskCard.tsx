import { useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../lib/api'
import { fmtMinutes } from '../lib/dates'
import type { PlanDetails } from '../lib/types'
import { Button, cx } from './ui'

export type TaskBlock = {
  id: number
  title: string
  time_block: string
  minutes: number
  status: 'open' | 'done' | 'partial' | 'skipped'
  done_minutes: number | null
  details?: PlanDetails
}

const DONE_WHEN = /\s+[-—–]\s+done when\s+/i

/** Older blocks put everything in the title ("X - done when Y"): split that into a title and a finish line. */
function normalise(block: TaskBlock): { title: string; details: PlanDetails } {
  const details = block.details ?? {}
  if (details.done_when || !DONE_WHEN.test(block.title)) return { title: block.title, details }
  const [title, doneWhen] = block.title.split(DONE_WHEN)
  return { title, details: { ...details, done_when: doneWhen } }
}

function addMinutes(hhmm: string, minutes: number): string {
  const [h, m] = hhmm.split(':').map(Number)
  if (Number.isNaN(h) || Number.isNaN(m)) return ''
  const total = (h * 60 + m + minutes) % (24 * 60)
  return `${String(Math.floor(total / 60)).padStart(2, '0')}:${String(total % 60).padStart(2, '0')}`
}

function hostname(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, '')
  } catch {
    return url
  }
}

export default function TaskCard({ block, goalTitle, compact = false }: { block: TaskBlock; goalTitle?: string; compact?: boolean }) {
  const qc = useQueryClient()
  const setStatus = useMutation({
    mutationFn: (status: TaskBlock['status']) => api(`/plan/${block.id}`, { method: 'PATCH', json: { status } }),
    onSuccess: () => qc.invalidateQueries(),
  })
  const { title, details } = normalise(block)
  const steps = details.steps ?? []
  const resources = (details.resources ?? []).filter((r) => r.url || r.title)
  const start = block.time_block.split('-')[0]?.trim()
  let clock = start
  const done = block.status === 'done'
  const skipped = block.status === 'skipped'

  return (
    <article
      className={cx(
        'relative overflow-hidden rounded-3xl border border-line bg-surface transition',
        (done || skipped) && 'opacity-80',
      )}
    >
      <div className="h-1 w-full bg-gradient-to-r from-brand-500 via-[#b46cff] to-[#ff8a5c]" />
      <div className={cx('p-5 sm:p-7', compact && 'sm:p-6')}>
        <div className="mb-3 flex flex-wrap items-center gap-2 text-xs">
          {block.time_block && (
            <span className="rounded-full bg-ink px-3 py-1 font-semibold text-canvas tabular-nums">{block.time_block.replace('-', ' – ')}</span>
          )}
          <span className="rounded-full bg-surface-2 px-3 py-1 font-medium text-muted">{fmtMinutes(block.minutes)}</span>
          {goalTitle && <span className="rounded-full bg-accent-soft px-3 py-1 font-medium text-accent-ink">{goalTitle}</span>}
          {done && <span className="rounded-full bg-emerald-500/15 px-3 py-1 font-semibold text-emerald-700 dark:text-emerald-300">✓ Done</span>}
          {block.status === 'partial' && (
            <span className="rounded-full bg-amber-500/15 px-3 py-1 font-semibold text-amber-800 dark:text-amber-300">
              Partly · {fmtMinutes(block.done_minutes ?? 0)}
            </span>
          )}
          {skipped && <span className="rounded-full bg-surface-2 px-3 py-1 font-semibold text-muted">Skipped</span>}
        </div>

        <h3 className={cx('font-display leading-[1.1] tracking-tight', compact ? 'text-2xl' : 'text-3xl sm:text-[2.6rem]', done && 'line-through decoration-1')}>
          {title}
        </h3>
        {details.why && <p className="mt-2 max-w-2xl text-[15px] leading-relaxed text-muted">{details.why}</p>}

        {(steps.length > 0 || details.done_when || resources.length > 0) && (
          <div className="mt-6 grid gap-6 lg:grid-cols-[1.35fr_1fr]">
            {steps.length > 0 && (
              <ol className="relative space-y-4">
                <span aria-hidden className="absolute top-3 bottom-3 left-[15px] w-px bg-line" />
                {steps.map((step, i) => {
                  const from = clock
                  clock = from ? addMinutes(from, step.minutes) : ''
                  return (
                    <li key={i} className="relative flex gap-4">
                      <span className="relative z-10 flex size-8 shrink-0 items-center justify-center rounded-full border border-line bg-surface text-sm font-semibold tabular-nums">
                        {i + 1}
                      </span>
                      <div className="min-w-0 pt-1">
                        <p className="text-[15px] leading-snug">{step.text}</p>
                        <p className="mt-1 text-xs text-muted tabular-nums">
                          {from && clock ? `${from} – ${clock} · ` : ''}
                          {fmtMinutes(step.minutes)}
                        </p>
                      </div>
                    </li>
                  )
                })}
              </ol>
            )}

            <div className="space-y-4">
              {details.done_when && (
                <div className="rounded-2xl bg-emerald-500/10 p-4">
                  <p className="mb-1 text-[11px] font-semibold tracking-[0.14em] text-emerald-700 uppercase dark:text-emerald-300">Done when</p>
                  <p className="text-[15px] leading-snug">{details.done_when}</p>
                </div>
              )}
              {resources.length > 0 && (
                <div>
                  <p className="mb-2 text-[11px] font-semibold tracking-[0.14em] text-muted uppercase">Resources</p>
                  <ul className="space-y-2">
                    {resources.map((r, i) => (
                      <li key={i}>
                        <a
                          href={r.url || undefined}
                          target="_blank"
                          rel="noreferrer"
                          className="group flex items-center justify-between gap-3 rounded-2xl border border-line px-4 py-3 transition hover:border-accent hover:bg-accent-soft"
                        >
                          <span className="min-w-0">
                            <span className="block truncate text-sm font-medium">{r.title || hostname(r.url)}</span>
                            {r.url && <span className="block truncate text-xs text-muted">{hostname(r.url)}</span>}
                          </span>
                          <span className="text-muted transition group-hover:translate-x-0.5 group-hover:text-accent-ink">↗</span>
                        </a>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          </div>
        )}

        <div className="mt-6 flex flex-wrap items-center gap-2 border-t border-line pt-5">
          {block.status === 'open' || block.status === 'partial' ? (
            <>
              <Button loading={setStatus.isPending && setStatus.variables === 'done'} onClick={() => setStatus.mutate('done')}>
                ✓ Mark done
              </Button>
              <Button variant="ghost" loading={setStatus.isPending && setStatus.variables === 'skipped'} onClick={() => setStatus.mutate('skipped')}>
                Skip today
              </Button>
              <span className="ml-auto text-xs text-muted">Did part of it? Tell Claude tonight.</span>
            </>
          ) : (
            <Button variant="secondary" size="sm" loading={setStatus.isPending} onClick={() => setStatus.mutate('open')}>
              Undo
            </Button>
          )}
        </div>
      </div>
    </article>
  )
}
