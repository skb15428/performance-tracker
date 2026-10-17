import { useEffect, useState } from 'react'
import { fmtMinutes } from '../lib/dates'
import type { PlanDetails } from '../lib/types'
import { Button, cx } from './ui'

type Step = NonNullable<PlanDetails['steps']>[number]

/** Confetti made of a few coloured dots flying outwards; purely decorative. */
export function Celebration() {
  const colors = ['#6d5efc', '#b46cff', '#ff8a5c', '#1baf7a', '#eda100']
  return (
    <div aria-hidden className="pointer-events-none absolute inset-0 flex items-center justify-center">
      {Array.from({ length: 24 }, (_, i) => {
        const angle = (i / 24) * Math.PI * 2
        const dist = 120 + (i % 3) * 50
        return (
          <span
            key={i}
            className="absolute size-2.5 rounded-full"
            style={{
              background: colors[i % colors.length],
              ['--dx' as string]: `${Math.cos(angle) * dist}px`,
              ['--dy' as string]: `${Math.sin(angle) * dist}px`,
              animation: `burst 0.9s cubic-bezier(0.2, 0.7, 0.2, 1) ${(i % 4) * 40}ms both`,
            }}
          />
        )
      })}
    </div>
  )
}

function Countdown({ seconds, total }: { seconds: number; total: number }) {
  const size = 220
  const stroke = 10
  const r = size / 2 - stroke
  const c = 2 * Math.PI * r
  const mm = Math.floor(Math.max(seconds, 0) / 60)
  const ss = Math.max(seconds, 0) % 60
  return (
    <div className="relative" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={r} strokeWidth={stroke} className="fill-none stroke-surface-2" />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={c}
          strokeDashoffset={c * (1 - Math.max(seconds, 0) / Math.max(total, 1))}
          className="fill-none stroke-[var(--accent)] transition-all duration-1000 ease-linear"
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="font-display text-6xl tabular-nums">
          {mm}:{String(ss).padStart(2, '0')}
        </span>
        <span className="text-xs text-muted">{seconds > 0 ? 'left on this step' : 'time is up'}</span>
      </div>
    </div>
  )
}

export default function FocusMode({
  title,
  steps,
  doneWhen,
  onToggleStep,
  onComplete,
  onClose,
}: {
  title: string
  steps: Step[]
  doneWhen?: string
  onToggleStep: (index: number, done: boolean) => void
  onComplete: () => void
  onClose: () => void
}) {
  const firstOpen = steps.findIndex((s) => !s.done)
  const [current, setCurrent] = useState(firstOpen === -1 ? 0 : firstOpen)
  const [remaining, setRemaining] = useState((steps[current]?.minutes ?? 25) * 60)
  const [running, setRunning] = useState(false)
  const [finished, setFinished] = useState(false)

  useEffect(() => {
    if (!running) return
    const t = setInterval(() => setRemaining((s) => s - 1), 1000)
    return () => clearInterval(t)
  }, [running])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const goTo = (i: number) => {
    setCurrent(i)
    setRemaining((steps[i]?.minutes ?? 25) * 60)
    setRunning(false)
  }
  const completeStep = () => {
    onToggleStep(current, true)
    const next = steps.findIndex((s, i) => i > current && !s.done)
    if (next === -1) {
      setFinished(true)
      setRunning(false)
      onComplete()
    } else {
      goTo(next)
      setRunning(true)
    }
  }
  const step = steps[current]

  return (
    <div className="fixed inset-0 z-50 overflow-y-auto bg-canvas" role="dialog" aria-modal="true" aria-label={`Focus: ${title}`}>
      <div className="bg-glow min-h-full">
        <div className="mx-auto flex min-h-dvh max-w-3xl flex-col px-5 py-6 sm:px-8">
          <div className="flex items-center justify-between">
            <p className="text-[11px] font-semibold tracking-[0.16em] text-muted uppercase">Focus · {title}</p>
            <Button variant="secondary" size="sm" onClick={onClose}>
              Close
            </Button>
          </div>

          {finished ? (
            <div className="relative flex flex-1 flex-col items-center justify-center text-center">
              <Celebration />
              <p className="pop font-display text-6xl">Block complete</p>
              <p className="mt-3 text-muted">Nicely done. It's marked as done; tell Claude about it tonight.</p>
              <Button className="mt-8" onClick={onClose}>
                Back to today
              </Button>
            </div>
          ) : (
            <>
              <div className="mt-6 flex gap-1.5">
                {steps.map((s, i) => (
                  <button
                    key={i}
                    onClick={() => goTo(i)}
                    aria-label={`Step ${i + 1}`}
                    className={cx('h-1.5 flex-1 rounded-full transition', s.done ? 'bg-emerald-500' : i === current ? 'bg-ink' : 'bg-surface-2')}
                  />
                ))}
              </div>

              <div className="flex flex-1 flex-col items-center justify-center py-10 text-center">
                <p className="text-sm text-muted">
                  Step {current + 1} of {steps.length} · {fmtMinutes(step?.minutes ?? 0)}
                </p>
                <h2 key={current} className="rise mt-3 max-w-2xl font-display text-4xl leading-tight sm:text-5xl">
                  {step?.text}
                </h2>
                <div className="mt-10">
                  <Countdown seconds={remaining} total={(step?.minutes ?? 25) * 60} />
                </div>
                <div className="mt-8 flex flex-wrap justify-center gap-2">
                  <Button variant="secondary" onClick={() => setRunning((r) => !r)}>
                    {running ? 'Pause' : remaining < (step?.minutes ?? 25) * 60 ? 'Resume' : 'Start timer'}
                  </Button>
                  <Button onClick={completeStep}>{steps.some((s, i) => i !== current && !s.done) ? 'Step done → next' : '✓ Finish block'}</Button>
                </div>
              </div>

              {doneWhen && (
                <div className="mb-4 rounded-2xl bg-emerald-500/10 p-4 text-center">
                  <p className="text-[11px] font-semibold tracking-[0.14em] text-emerald-700 uppercase dark:text-emerald-300">Done when</p>
                  <p className="mt-1 text-[15px]">{doneWhen}</p>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  )
}
